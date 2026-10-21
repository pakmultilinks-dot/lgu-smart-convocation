#!/usr/bin/env python3
"""Phase 38 — shared analytics & event reliability (backend focused tests).

Covers: rejection logging at every scan-verdict site (live, request-level,
queued sync, mocked LGU2 verdict), dashboard metric math and summary/full
parity, occasion filtering, the student attendance privacy boundary, GET
endpoints performing zero DB writes, concurrent scanner writes with
dashboard reads, poll-interval clamping, the pre-v14 defensive fallback,
and a final read-only production stamp.

Runs ONLY on a disposable database (LGU_TESTING + temp LGU_DB_PATH). The
production file is never opened for write; it is re-stamped at the end.
"""
import hashlib
import os
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("LGU_TESTING", "1")
os.environ.setdefault("LGU_ALLOW_DEMO_SECRETS", "1")
_fd, _PROD = tempfile.mkstemp(prefix="lgu_p38_analytics_", suffix=".db")
os.close(_fd)
os.environ["LGU_DB_PATH"] = _PROD
# Exercise the configurable polling knob from the environment (Phase 38).
os.environ["LGU_DASHBOARD_POLL_MS"] = "2500"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _production_boundary import production_stamp
_PRODUCTION_BEFORE = production_stamp()

import config  # noqa: E402
import database  # noqa: E402
import migrations  # noqa: E402
import models  # noqa: E402
import student_auth as sa  # noqa: E402
from _scanner_fixture import scanner_headers  # noqa: E402
from web import routes  # noqa: E402

FAILURES = []
TOTAL = 0


def ok(cond, label):
    global TOTAL
    TOTAL += 1
    # Console-safe: the Windows console is cp1252; never let a pretty
    # character in a label crash the suite after the assertion itself ran.
    print((("ok   " if cond else "FAIL ") + label)
          .encode("cp1252", "replace").decode("cp1252"))
    if not cond:
        FAILURES.append(label)


def day_counts():
    with database.connection() as db:
        row = db.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(is_duplicate), 0) d"
            " FROM scan_rejections WHERE substr(occurred_at, 1, 10) = ?",
            (models.now_str()[:10],)).fetchone()
    return row["c"], row["d"]


# ---------------------------------------------------------------- setup
database.init_db()
database.seed()
database.update_settings({"expected_attendance": "20"})
app = routes.create_app()
client = app.test_client()
HDRS = scanner_headers(client)
HDRS_G1 = scanner_headers(client, gate_ids=[1])

db = database.get_db()
try:
    ACCOUNT_ID = sa.create_account(db, "p38-analytics@uni.edu.pk",
                                   "Phase38!Analytics#2026")
    TOKEN, _ = sa.issue_session(db, ACCOUNT_ID)
    db.commit()
finally:
    db.close()

print("== [1] process_scan logs every refused verdict ==")
r = routes.process_scan("LGU1:not-a-real-code", 1, "entry", "Tester")
ok(r.get("status") == "error" and r.get("title") == "INVALID CODE",
   "bad code answered INVALID CODE")
ok(day_counts() == (1, 0), "invalid code logged as 1 rejected / 0 dup")

demo = models.first_outside_student()
ok(demo is not None, "seed provides an outside student for the demo flow")
PAYLOAD = routes.ids.make_payload(demo["qr_id"])
r = routes.process_scan(PAYLOAD, 1, "entry", "Tester")
ok(r.get("status") == "ok", "first entry admitted")
r = routes.process_scan(PAYLOAD, 1, "entry", "Tester")
ok(r.get("status") == "error" and r.get("title") == "ALREADY INSIDE",
   "second entry answered ALREADY INSIDE")
ok(day_counts() == (2, 1), "duplicate logged as rejected + duplicate")
r = routes.process_scan(PAYLOAD, 1, "exit", "Tester")
ok(r.get("status") == "ok", "exit admitted")
ok(day_counts() == (2, 1), "success writes no rejection row")

print("== [2] api_sync and api_scan refusals are logged once each ==")
TS = "2026-01-01 10:00:00"
queued = {"payload": PAYLOAD, "gate_id": 1, "mode": "entry", "scanned_at": TS}
resp = client.post("/api/sync", json={"items": [None, queued]}, headers=HDRS)
body = resp.get_json()
ok(resp.status_code == 400 and body.get("ok") is False,
   "invalid batch structure is rejected before processing any scan")
ok(day_counts() == (2, 1), "invalid batch structure writes no scan rejection")
# A valid scan object with a missing payload is a per-scan refusal, whereas
# a non-object item above invalidates the entire batch (merged PR #3).
resp = client.post("/api/sync", json={"items": [{"payload": None}, queued]}, headers=HDRS)
body = resp.get_json()
ok(resp.status_code == 200 and body["synced"] == 1,
   "first sync batch: malformed item refused, queued scan synced")
ok(body["results"][0]["result"]["title"] == "INVALID CODE",
   "malformed sync item answered INVALID CODE")
ok(day_counts() == (3, 1), "malformed sync item logged once")
resp = client.post("/api/sync", json={"items": [queued]}, headers=HDRS)
body = resp.get_json()
ok(resp.status_code == 200 and body["synced"] == 0
   and body["results"][0]["result"]["title"] == "ALREADY SYNCED",
   "replayed batch answered ALREADY SYNCED (idempotent)")
ok(day_counts() == (4, 2), "queued replay logged as duplicate")

resp = client.post("/api/scan", json={"mode": "entry", "occasion": "ceremony"},
                   headers=HDRS)
ok(resp.status_code == 400
   and resp.get_json()["title"] == "NO GATE SELECTED", "no-gate refused 400")
ok(day_counts() == (5, 2), "request-level no-gate refusal logged")

resp = client.post("/api/scan",
                   json={"gate_id": 1, "mode": "entry", "occasion": "party"},
                   headers=HDRS)
ok(resp.status_code == 400
   and resp.get_json()["title"] == "UNKNOWN OCCASION",
   "unknown occasion refused 400")
ok(day_counts() == (6, 2), "request-level occasion refusal logged")

resp = client.post("/api/scan",
                   json={"gate_id": 2, "mode": "entry", "occasion": "ceremony"},
                   headers=HDRS_G1)
ok(resp.status_code == 403
   and resp.get_json()["title"] == "GATE NOT AUTHORIZED",
   "unauthorized gate refused 403")
ok(day_counts() == (7, 2), "unauthorized-gate refusal logged")

print("== [3] LGU2 verdicts flow through the same choke point ==")
_orig_verify = routes.convqr.verify_scan
routes.convqr.verify_scan = lambda *a, **k: {
    "status": "error", "level": "red", "title": "ALREADY ADMITTED",
    "detail": "mocked duplicate verdict"}
try:
    r = routes.process_scan("LGU2:mock-token", 1, "entry", "Tester",
                            occasion="rehearsal")
finally:
    routes.convqr.verify_scan = _orig_verify
ok(r.get("title") == "ALREADY ADMITTED", "mocked LGU2 verdict returned")
ok(day_counts() == (8, 3), "LGU2 duplicate logged through process_scan")
with database.connection() as db:
    row = db.execute(
        "SELECT occasion, source FROM scan_rejections"
        " WHERE title = 'ALREADY ADMITTED' ORDER BY id DESC LIMIT 1"
    ).fetchone()
ok(row is not None and row["occasion"] == "rehearsal"
   and row["source"] == "online", "LGU2 row carries occasion + source")

print("== [4] defensive paths: day scoping and busy are never rejections ==")
yday = (datetime.now(ZoneInfo(config.DISPLAY_TZ))
        - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
with database.connection() as db:
    db.execute(
        "INSERT INTO scan_rejections (occurred_at, gate_id, mode, occasion,"
        " title, is_duplicate, source) VALUES (?, 1, 'entry', NULL,"
        " 'INVALID CODE', 0, 'online')", (yday,))
    db.commit()
ok(day_counts() == (8, 3), "yesterday's rejection excluded from today")
_orig_ps = routes._process_scan


def _busy(*a, **k):
    raise sqlite3.OperationalError("database is locked")


routes._process_scan = _busy
try:
    r = routes.process_scan("LGU1:whatever", 1, "entry", "Tester")
finally:
    routes._process_scan = _orig_ps
ok(r.get("status") == "busy", "busy propagated as a retryable verdict")
ok(day_counts() == (8, 3), "busy writes no rejection row")

print("== [5] dashboard analytics payload ==")
today = models.now_str()[:10]
with database.connection() as db:
    for hh, m, who in (("09", "entry", ("trend-a", "Trend A")),
                       ("10", "entry", ("trend-b", "Trend B")),
                       ("10", "exit", ("trend-b", "Trend B"))):
        db.execute(
            "INSERT INTO scans (qr_id, person_type, person_name, gate_id,"
            " mode, volunteer, scanned_at, source)"
            " VALUES (?, 'student', ?, 1, ?, 'TrendBot', ?, 'online')",
            (who[0], who[1], m, today + " " + hh + ":15:00"))
    db.commit()

summary = client.get("/api/dashboard/summary").get_json()
full = client.get("/api/dashboard").get_json()
ok(summary["rejected_count"] == 8 and summary["duplicate_count"] == 3,
   "rejected/duplicate counts match the recorded log")
ok(summary["duplicate_count"] <= summary["rejected_count"],
   "duplicate is a subset of rejected by construction")
ok(full["rejected_count"] == 8 and full["duplicate_count"] == 3,
   "full dashboard carries the same counts (summary/full parity)")
ok(summary["remaining_attendance"] == 19
   and full["remaining_attendance"] == 19,
   "remaining = expected(20) − inside(1)")
ok(summary["attendance_set"] is True and summary["arrival_pct"] == 5,
   "arrival percentage 5% against the configured target")
ok(isinstance(summary["admissions_by_occasion"], dict)
   and set(summary["admissions_by_occasion"]) == {"ceremony", "rehearsal"},
   "admissions_by_occasion exposes both occasions")
ok(summary["poll_interval_ms"] == 2500,
   "poll_interval_ms comes from LGU_DASHBOARD_POLL_MS")

with database.connection() as db:
    raw = db.execute(
        "SELECT substr(scanned_at, 12, 2) h, mode FROM scans"
        " WHERE substr(scanned_at, 1, 10) = ?", (today,)).fetchall()
buckets, expected, cumulative = {}, [], 0
for row in raw:
    slot = buckets.setdefault(row["h"], [0, 0])
    slot[0 if row["mode"] == "entry" else 1] += 1
for h in sorted(buckets):
    en, ex = buckets[h]
    cumulative += en
    expected.append({"hour": h, "entries": en, "exits": ex,
                     "cumulative_entries": cumulative})
ok(full["trends"] == expected
   and expected[-1]["cumulative_entries"]
   == sum(1 for row in raw if row["mode"] == "entry"),
   "hourly trend matches an independent recount of scans")

shared = [k for k in summary if k != "generated_at"]
ok(all(summary[k] == full[k] for k in shared),
   "every shared key identical between summary and full")

print("== [6] event-specific filtering ==")
r = client.get("/api/dashboard?occasion=ceremony").get_json()
ok(r.get("occasion_filter") == "ceremony"
   and r["occasion_admitted"] == r["admissions_by_occasion"]["ceremony"],
   "?occasion=ceremony adds filter echo + scoped count")
r = client.get("/api/dashboard/summary?occasion=rehearsal").get_json()
ok(r.get("occasion_filter") == "rehearsal"
   and r["occasion_admitted"] == r["admissions_by_occasion"]["rehearsal"],
   "summary endpoint filters too")
resp = client.get("/api/dashboard?occasion=party")
ok(resp.status_code == 400, "invalid occasion is a 400, not a silent pass")
plain = client.get("/api/dashboard").get_json()
ok("occasion_filter" not in plain, "no param -> payload untouched")

print("== [7] student attendance boundary ==")
resp = client.get("/api/student/attendance")
ok(resp.status_code == 401, "anonymous student request is 401")
resp = client.get("/api/student/attendance",
                  headers={"Authorization": "Bearer " + TOKEN})
body = resp.get_json()
ok(resp.status_code == 200 and body.get("ok") is True,
   "valid student token reads attendance")
att = body.get("attendance", {})
ok(set(att) == {"registered", "verified", "remaining", "percentage",
                "expected", "attendance_set", "generated_at"},
   "attendance payload exposes exactly the privacy-safe keys")
ok(att["registered"] == full["student_roster_count"]
   and att["verified"] == full["inside_total"]
   and att["percentage"] == full["arrival_pct"],
   "student view agrees with the dashboard's population semantics")
raw_text = resp.get_data(as_text=True)
for leaked in ("feed", "sync", "busiest_gate", "throughput", "qr_id",
               "rejected_count", "announcement_audience"):
    ok(('"%s"' % leaked) not in raw_text,
       "administrative key %r absent from student payload" % leaked)
database.update_settings({"expected_attendance": "0"})
unset = models.student_attendance()
ok(unset["attendance_set"] is False and unset["remaining"] is None
   and unset["percentage"] == 0,
   "target unset -> explicit not-set state, remaining is null")
database.update_settings({"expected_attendance": "20"})

print("== [8] GET endpoints perform zero DB writes ==")
def snapshot():
    with database.connection() as db:
        counts = {t: db.execute("SELECT COUNT(*) c FROM %s" % t).fetchone()["c"]
                  for t in ("scans", "convocation_admissions", "guests",
                            "scan_rejections", "student_sessions")}
        settings = [tuple(r) for r in db.execute(
            "SELECT key, value, updated_at FROM settings ORDER BY key")]
    return counts, settings

before = snapshot()
for _ in range(5):
    client.get("/api/dashboard")
    client.get("/api/dashboard/summary")
    client.get("/api/student/attendance",
               headers={"Authorization": "Bearer " + TOKEN})
ok(snapshot() == before, "5 poll rounds changed no table")

print("== [9] concurrent scanner writes + dashboard reads ==")
errors = []
def writer(n):
    try:
        for i in range(5):
            routes.process_scan("LGU1:junk-%d-%d" % (n, i), 1, "entry", "Bot")
    except Exception as exc:  # noqa: BLE001
        errors.append("writer%d: %r" % (n, exc))

def reader(n):
    try:
        for _ in range(5):
            d = models.dashboard()
            assert isinstance(d, dict) and "inside_total" in d
    except Exception as exc:  # noqa: BLE001
        errors.append("reader%d: %r" % (n, exc))

threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)] + \
          [threading.Thread(target=reader, args=(n,)) for n in range(4, 8)]
for t in threads:
    t.start()
for t in threads:
    t.join()
ok(not errors, "20 scans + 20 dashboards with no errors: %s" % (errors or "none"))
ok(day_counts() == (28, 3),
   "final counts 28/3 = 8 before + exactly 20 concurrent rejections")

print("== [10] poll interval clamping ==")
_orig_poll = config.DASHBOARD_POLL_MS
config.DASHBOARD_POLL_MS = 100
ok(models._poll_interval_ms() == 2000, "floor clamp at 2000 ms")
config.DASHBOARD_POLL_MS = 99999
ok(models._poll_interval_ms() == 30000, "ceiling clamp at 30000 ms")
config.DASHBOARD_POLL_MS = _orig_poll

print("== [11] pre-v14 schema degrades honestly (no invented data) ==")
sql14 = [s for v, s in migrations.MIGRATIONS if v == 14][0]
with database.connection() as db:
    db.execute("DROP TABLE scan_rejections")
d = client.get("/api/dashboard/summary").get_json()
ok(d["rejected_count"] == 0 and d["duplicate_count"] == 0,
   "missing log table -> dashboard still answers with zeros")
try:
    models.record_scan_rejection(1, "entry", "ceremony", "INVALID CODE")
    swallowed = True
except sqlite3.OperationalError:
    swallowed = False
ok(swallowed, "log write to a missing table never raises")
with database.connection() as db:
    db.executescript(sql14)

print("== [12] production database untouched (read-only stamp) ==")
PROD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "lgu.db")
ok(production_stamp() == _PRODUCTION_BEFORE,
   "production database unchanged or remains absent")

try:
    os.unlink(_PROD)
except OSError:
    pass
print("")
print("%d checks, %d failures" % (TOTAL, len(FAILURES)))
sys.exit(1 if FAILURES else 0)
