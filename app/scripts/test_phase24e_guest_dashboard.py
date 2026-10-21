"""Phase 24E — guest-pass validity and attendance-dashboard honesty.

Audits two things the release gate flagged:

1. Guest-pass validity on the legacy roster path: single-use entry passes
   must refuse a second use (red ALREADY USED with structured identity),
   refuse exit (amber GUEST PASS IS ENTRY ONLY), and record exactly one
   entry scan. There is no expiry/revocation column on `guests`, so these
   are the only validity states that exist — the test pins each one.

2. Dashboard metric honesty: occupancy must be derived from real entry/exit
   scans (a student who exits is no longer inside), guests must be counted
   separately from students, and arrival percentage must be measured ONLY
   against the administrator's expected-attendance target — never silently
   against the roster total. When the target is unset the API must report
   attendance_set=false and arrival_pct=0, not a fabricated ratio.

Everything runs against a disposable database via the real Flask test
client; the production DB is never opened.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p24e-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "p24e.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config                      # noqa: E402
import database                    # noqa: E402
import ids                         # noqa: E402
from web.routes import create_app  # noqa: E402

config.require_test_db()
database.init_db()
database.seed()

PASS = 0
FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok   " + label)
    else:
        FAIL += 1
        print("FAIL " + label + (("  <- " + repr(extra)) if extra else ""))


def scanner_headers(client, gate_ids=(1, 2, 3, 4, 5, 6, 7)):
    r = client.post("/api/test-scanner-session",
                    json={"gate_ids": list(gate_ids)})
    body = r.get_json() or {}
    assert r.status_code == 200 and body.get("token"), \
        "test-scanner-session failed: %s %s" % (r.status_code, body)
    return {"X-Scanner-Token": body["token"]}


app = create_app()
client = app.test_client()
H = scanner_headers(client)


def scan(payload, gate=1, mode="entry"):
    r = client.post("/api/scan", json={
        "payload": payload, "gate_id": gate, "mode": mode,
        "volunteer": "P24E Tester", "scanned_at": "2026-10-15 10:00:00",
    }, headers=H)
    return r.status_code, (r.get_json() or {})


def payload_for(qr_id):
    return ids.make_payload(qr_id)


print("=" * 70)
print("Phase 24E — guest-pass validity + attendance-dashboard honesty")
print("disposable DB:", os.environ["LGU_DB_PATH"])
print("=" * 70)

# ---------------------------------------------------------------- guests
# Seed one guest against a real roster host so the scan path is genuine.
db = database.get_db()
host = db.execute(
    "SELECT roll_no FROM students WHERE qr_id IS NOT NULL"
    " AND roll_no NOT IN (SELECT host_roll_no FROM guests)"
    " ORDER BY roll_no LIMIT 1").fetchone()
check("a roster host without a guest exists", host is not None, host)
HOST_ROLL = host["roll_no"]
db.close()

g_db = database.get_db()
# A guest QR must be a real, well-formed opaque id (correct length +
# alphabet) or verify_payload rejects it as forged — generate one rather
# than hand-writing a slug.
GUEST_QR = ids.generate_id()
g_db.execute(
    "INSERT INTO guests (name, phone, host_roll_no, qr_id, created_at)"
    " VALUES (?, ?, ?, ?, ?)",
    ("P24E Guest", "0300-9999999", HOST_ROLL,
     GUEST_QR, "2026-10-15 09:00:00"))
g_db.commit()
g_db.close()
guest_payload = payload_for(GUEST_QR)

print("\n[A] Guest-pass validity (single-use entry pass)")
# 1. exit is refused before any use — amber, no scan recorded.
code, body = scan(guest_payload, mode="exit")
check("guest exit is refused (GUEST PASS IS ENTRY ONLY)",
      body.get("title") == "GUEST PASS IS ENTRY ONLY" and code == 200,
      (code, body.get("title")))
db = database.get_db()
c = db.execute("SELECT COUNT(*) c FROM scans WHERE qr_id = ?",
               (GUEST_QR,)).fetchone()["c"]
db.close()
check("a refused guest exit records NO scan", c == 0, c)

# 2. first entry is admitted, with guest-specific success and host context.
code, body = scan(guest_payload, mode="entry")
check("guest entry is recorded (GUEST ENTRY RECORDED)",
      body.get("status") == "ok" and body.get("title") == "GUEST ENTRY RECORDED"
      and code == 200, (code, body))
check("guest success carries host context (Guest of <roll>)",
      (body.get("sub") or "").startswith("Guest of %s" % HOST_ROLL),
      body.get("sub"))

# 3. second use is refused red with structured identity for the scanner UI.
code, body = scan(guest_payload, mode="entry")
check("second guest use is refused (ALREADY USED, red)",
      body.get("title") == "ALREADY USED" and body.get("level") == "red",
      (body.get("title"), body.get("level")))
check("ALREADY USED carries structured name + gate + time",
      bool(body.get("name")) and body.get("gate") is not None
      and body.get("time") is not None, body)

db = database.get_db()
c = db.execute("SELECT COUNT(*) c FROM scans WHERE qr_id = ?",
               (GUEST_QR,)).fetchone()["c"]
db.close()
check("exactly ONE guest scan exists (one guest, one entry)", c == 1, c)

# ------------------------------------------------- occupancy from real scans
print("\n[B] Occupancy derives from real entry/exit scans")
db = database.get_db()
stu = db.execute(
    "SELECT qr_id, roll_no FROM students WHERE qr_id IS NOT NULL"
    " ORDER BY roll_no LIMIT 1").fetchone()
STU_QR, STU_ROLL = stu["qr_id"], stu["roll_no"]
db.close()
stu_payload = payload_for(STU_QR)

code, body = scan(stu_payload, mode="entry")
check("student entry is recorded", body.get("status") == "ok", body)
d = client.get("/api/dashboard/summary").get_json()
check("inside_total counts the entered student", d["inside_total"] >= 1, d["inside_total"])
check("guests_inside counts the scanned guest", d["guests_inside"] >= 1, d["guests_inside"])
check("guests are counted SEPARATELY from inside_total (students)",
      d["inside_total"] == d["male"] + d["female"], d)

code, body = scan(stu_payload, mode="exit")
check("student exit is recorded", body.get("status") == "ok", body)
d2 = client.get("/api/dashboard/summary").get_json()
check("a student who EXITS is no longer inside (occupancy from real scans)",
      d2["inside_total"] == d["inside_total"] - 1,
      (d["inside_total"], d2["inside_total"]))

# ------------------------------------------------------- arrival honesty
print("\n[C] Arrival percentage is measured ONLY vs the admin target")
# Target unset: arrival_pct must be 0 and attendance_set false — never a
# silent ratio against the roster total.
d = client.get("/api/dashboard/summary").get_json()
check("unset target reports attendance_set=false",
      d.get("attendance_set") is False, d.get("attendance_set"))
check("unset target reports arrival_pct=0 (no fabricated ratio)",
      d.get("arrival_pct") == 0, d.get("arrival_pct"))
check("expected_attendance is 0 when unset",
      d.get("expected_attendance") == 0, d.get("expected_attendance"))

# Set a target via the real settings endpoint (admin PIN), then confirm the
# percentage is computed against THAT number and only that number.
r = client.put("/api/settings",
               json={"expected_attendance": "10"},
               headers={"X-Admin-Pin": config.ADMIN_PIN})
check("admin can set expected_attendance=10", r.status_code == 200, r.status_code)
d = client.get("/api/dashboard/summary").get_json()
check("target set reports attendance_set=true and expected=10",
      d.get("attendance_set") is True and d.get("expected_attendance") == 10,
      (d.get("attendance_set"), d.get("expected_attendance")))
inside = d["inside_total"]
expected_pct = min(100, round(100 * inside / 10))
check("arrival_pct == inside/expected (not roster)",
      d.get("arrival_pct") == expected_pct, (d.get("arrival_pct"), expected_pct))
check("arrival_pct is clamped to <= 100",
      0 <= d.get("arrival_pct", -1) <= 100, d.get("arrival_pct"))

# A huge target must NOT make occupancy look like 100%; the number is a real
# ratio against the configured target.
r = client.put("/api/settings",
               json={"expected_attendance": "25000"},
               headers={"X-Admin-Pin": config.ADMIN_PIN})
d = client.get("/api/dashboard/summary").get_json()
check("25000 target yields a tiny arrival_pct (real ratio, not 100%)",
      d.get("arrival_pct", 100) < 1, d.get("arrival_pct"))

# Reset the target to unset so the fixture leaves no configured state.
client.put("/api/settings", json={"expected_attendance": "0"},
           headers={"X-Admin-Pin": config.ADMIN_PIN})

# ---------------------------------------------- dashboard honesty labels
print("\n[D] Dashboard reports what it measures")
d = client.get("/api/dashboard").get_json()
check("dashboard carries the same five population values as summary",
      all(k in d for k in ("student_roster_count", "expected_attendance",
                           "announcement_audience_count", "guests_inside",
                           "inside_total")), sorted(d.keys()))
check("busiest_gate is honest when no scans today (label, not a count)",
      isinstance(d.get("busiest_gate"), str), d.get("busiest_gate"))
check("feed carries real scan rows (gate_label joined)",
      all("gate_label" in f for f in d.get("feed", [])[:5])
      or len(d.get("feed", [])) == 0, d.get("feed", [])[:1])

print("\n" + "-" * 70)
print("%d checks, %d failures" % (PASS, FAIL))
print("PROD_DB untouched (this test uses %s)" % os.environ["LGU_DB_PATH"])
sys.exit(1 if FAIL else 0)
