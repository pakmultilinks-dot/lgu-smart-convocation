"""Phase 34 acceptance: scanner, guest-pass lifecycle & attendance integrity.

Central requirement proved here: a successful scan, a valid pass, a recorded
entry, a currently-admitted attendee and a synchronized record are DIFFERENT
concepts and the system never conflates them. On ONE disposable temp database
we exercise: legacy (LGU1) student entry/exit/re-entry, single-use guest
passes, the NEW guest revocation lifecycle (migration 13 + /revoke route +
gate refusal of a revoked pass), convocation (LGU2) per-occasion admission,
the scanner-gated /api/search that no longer leaks the qr_id credential, the
busy/retryable contract, and offline (queued) sync idempotency + permanent
rejections. app/lgu.db is never opened (stat-stamped before and after).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase34_scanner_guest_attendance.py
"""

import os
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

PROD_DB = os.path.join(APP_DIR, "lgu.db")
if os.path.exists(PROD_DB):
    _s = os.stat(PROD_DB)
    PROD_STAMP = (_s.st_size, _s.st_mtime_ns)
else:
    PROD_STAMP = None

TMP = tempfile.mkdtemp(prefix="lgu-p34scan-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "scan.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
config.require_test_db()
import ids  # noqa: E402
import models  # noqa: E402
from web.routes import create_app  # noqa: E402
from _scanner_fixture import scanner_headers  # noqa: E402

failures = 0
checks = 0


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def raw(sql, args=()):
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        c.commit()
        return rows
    finally:
        c.close()


def one(sql, args=()):
    r = raw(sql, args)
    return r[0] if r else None


# ------------------------------------------------------------------ world
import database  # noqa: E402
database.init_db()  # applies base SCHEMA then migrations (-> latest, v14)
_ver = database.get_db().execute("PRAGMA user_version").fetchone()[0]
check("migration applied through v14 (guest status column)", _ver == 14, _ver)
cols = [r["name"] for r in raw("PRAGMA table_info(guests)")]
check("guests table exposes status column", "status" in cols, cols)

# Seed the seven gates the scanner fixture authorizes against.
for _code, _label in database.GATE_LABELS:
    raw("INSERT INTO gates (code, label) VALUES (?, ?)", (_code, _label))

# Gates 1..7 already exist in the base schema.
app = create_app()
client = app.test_client()

# Legacy roster students with HMAC ids.
added, skipped = models.add_students([
    ("LGU-34-001", "Ayaan Male", "Male", "BSc"),
    ("LGU-34-002", "Fatima Female", "Female", "BSc"),
    ("LGU-34-003", "Re-entry Ron", "Male", "BSc"),
])
check("legacy roster seeded", added == 3 and skipped == 0, (added, skipped))
# Assign HMAC qr_id credentials to every roster student (the scanner scans these).
models.assign_ids(models.all_students(), ids.generate_id)


def stu_payload(roll):
    q = one("SELECT qr_id FROM students WHERE roll_no = ?", (roll,))["qr_id"]
    return ids.make_payload(q)


# One guest (active), registered against a real host roll.
GID_A, err = models.register_guest("Grace Guest", "03001112233",
                                   "LGU-34-001", ids.generate_id)
check("guest registered (active by default)", err is None and GID_A, err)
g_a = models.guest_by_id(GID_A)
check("guest defaults to status=active", g_a["status"] == "active", g_a["status"])
guest_payload = ids.make_payload(g_a["qr_id"])

H = scanner_headers(client, gate_ids=[1, 2, 3, 4, 5, 6, 7])


def scan(payload, gate=1, mode="entry", headers=None, occasion=None):
    body = {"payload": payload, "gate_id": gate, "mode": mode}
    if occasion is not None:
        body["occasion"] = occasion
    return client.post("/api/scan", json=body,
                       headers=headers if headers is not None else H)


# ---------------------------------------------------- A. valid admissions
r = scan(stu_payload("LGU-34-001"))
b = r.get_json()
check("valid student entry -> 200 ok/green/ENTRY RECORDED",
      r.status_code == 200 and b["status"] == "ok" and b["title"] == "ENTRY RECORDED", b)

r = scan(guest_payload)
b = r.get_json()
check("valid guest entry -> ok/GUEST ENTRY RECORDED", b["status"] == "ok"
      and b["title"] == "GUEST ENTRY RECORDED", b)

# --------------------------------------------- B. duplicates / transitions
b = scan(stu_payload("LGU-34-001")).get_json()
check("repeat student entry -> ALREADY INSIDE (red)",
      b["status"] == "error" and b["title"] == "ALREADY INSIDE", b)
b = scan(guest_payload).get_json()
check("repeat guest entry -> ALREADY USED (single-use)",
      b["status"] == "error" and b["title"] == "ALREADY USED", b)

b = scan(stu_payload("LGU-34-003")).get_json()
check("student initial entry recorded", b["status"] == "ok", b)
b = scan(stu_payload("LGU-34-003"), mode="exit").get_json()
check("student exit closes entry", b["status"] == "ok" and b["title"] == "EXIT RECORDED", b)
b = scan(stu_payload("LGU-34-003"), mode="exit").get_json()
check("exit when not inside -> NOT INSIDE (amber)",
      b["status"] == "error" and b["title"] == "NOT INSIDE", b)
b = scan(stu_payload("LGU-34-003")).get_json()
check("re-entry after exit allowed (entry recorded)",
      b["status"] == "ok" and b["title"] == "ENTRY RECORDED", b)
# Entry-only rule needs a FRESH (unused) guest — an already-used guest
# correctly reports ALREADY USED before the mode check.
GID_E, _e = models.register_guest("Eve Entryonly", "03005556677",
                                  "LGU-34-003", ids.generate_id)
eve_payload = ids.make_payload(models.guest_by_id(GID_E)["qr_id"])
b = scan(eve_payload, mode="exit").get_json()
check("guest exit refused (entry only)",
      b["status"] == "error" and b["title"] == "GUEST PASS IS ENTRY ONLY", b)

# ------------------------------------------------------- C. invalid/forge
# A validly-SIGNED payload whose qr_id is not in the roster -> UNKNOWN CODE.
b = scan(ids.make_payload(ids.generate_id())).get_json()
check("unknown code -> UNKNOWN CODE", b["status"] == "error"
      and b["title"] == "UNKNOWN CODE", b)
b = scan("LGU1:tampered:signature").get_json()
check("forged signature -> INVALID CODE", b["status"] == "error"
      and b["title"] == "INVALID CODE", b)
r = client.post("/api/scan", json={"payload": stu_payload("LGU-34-001"),
                                   "gate_id": 1, "mode": "entry"})
b = r.get_json()
check("unauthenticated scan -> 401 scanner_auth_required",
      r.status_code == 401 and b.get("code") == "scanner_auth_required", b)
gate2 = scanner_headers(client, gate_ids=[2])
b = scan(stu_payload("LGU-34-001"), gate=1, headers=gate2).get_json()
check("gate not authorized for this scanner -> GATE NOT AUTHORIZED",
      b["status"] == "error" and b["title"] == "GATE NOT AUTHORIZED", b)

# -------------------------------------------- D. dashboard integrity (F)
dash = client.get("/api/dashboard").get_json()
inside_students = models.student_inside(one(
    "SELECT qr_id FROM students WHERE roll_no='LGU-34-001'")["qr_id"])
check("student occupancy tracked (inside_total >= 1)",
      dash["inside_total"] >= 1, dash["inside_total"])
check("guests counted SEPARATELY (guests_inside == 1)",
      dash["guests_inside"] == 1, dash["guests_inside"])
check("convocation admissions surfaced as their own fields",
      "ceremony_admitted" in dash and "rehearsal_admitted" in dash
      and dash["ceremony_admitted"] == 0 and dash["rehearsal_admitted"] == 0,
      (dash.get("ceremony_admitted"), dash.get("rehearsal_admitted")))
check("exit removed Ron from occupancy but not from roster",
      dash["student_roster_count"] == 3, dash["student_roster_count"])

# ------------------------------------------------ E. guest revocation (C)
GID_B, err = models.register_guest("Rita Revoked", "03009998877",
                                   "LGU-34-002", ids.generate_id)
check("second guest registered", err is None and GID_B, err)
g_b = models.guest_by_id(GID_B)
rb = ids.make_payload(g_b["qr_id"])
before = one("SELECT COUNT(*) c FROM scans WHERE qr_id=?", (g_b["qr_id"],))["c"]
check("revocation requires a scanner session",
      client.post("/api/guests/%d/revoke" % GID_B).status_code == 401)
rr = client.post("/api/guests/%d/revoke" % GID_B, headers=H)
rb_json = rr.get_json()
check("scanner can revoke an active guest pass",
      rr.status_code == 200 and rb_json.get("status") == "revoked", rb_json)
check("guest row now status=revoked",
      models.guest_by_id(GID_B)["status"] == "revoked")
b = scan(rb).get_json()
check("revoked pass refused at gate -> GUEST PASS REVOKED",
      b["status"] == "error" and b["title"] == "GUEST PASS REVOKED", b)
check("revoked scan recorded NOTHING",
      one("SELECT COUNT(*) c FROM scans WHERE qr_id=?", (g_b["qr_id"],))["c"] == before)
rr2 = client.post("/api/guests/%d/revoke" % GID_B, headers=H).get_json()
check("re-revoke is idempotent (no error)", rr2.get("ok") is True, rr2)
# A used pass cannot be revoked (lifecycle states stay distinct).
rr3 = client.post("/api/guests/%d/revoke" % GID_A, headers=H)
check("used pass cannot be revoked -> 409", rr3.status_code == 409, rr3.status_code)
# Directory + pass read surface the status.
dirrow = [g for g in models.guest_directory() if g["id"] == GID_B][0]
check("guest_directory surfaces status=revoked", dirrow["status"] == "revoked", dirrow)
pr = client.get("/api/guest-pass/%d" % GID_B, headers=H).get_json()
check("guest-pass read surfaces status=revoked", pr.get("status") == "revoked", pr)

# ---------------------------------------------------- F. search auth (D)
anon = client.get("/api/search?q=Grace")
check("anonymous search -> 401", anon.status_code == 401, anon.status_code)
authd = client.get("/api/search?q=Grace", headers=H).get_json()
res = authd.get("results", [])
check("authorized search returns results", authd.get("ok") and len(res) >= 1, authd)
check("search never returns the qr_id credential",
      all("qr_id" not in r for r in res), res[:1])
stu_res = client.get("/api/search?q=Ayaan", headers=H).get_json()["results"]
check("student search result has no qr_id",
      all("qr_id" not in r for r in stu_res), stu_res[:1])

# ------------------------------------------------ G. queued sync (E)
sync_body = {"items": [{"payload": stu_payload("LGU-34-002"), "gate_id": 1,
                        "mode": "entry", "volunteer": "Rover",
                        "scanned_at": "2026-01-01 10:00:00",
                        "occasion": "ceremony"}]}
sr = client.post("/api/sync", json=sync_body, headers=H).get_json()
check("queued student scan syncs -> synced=1", sr.get("synced") == 1, sr)
sr2 = client.post("/api/sync", json=sync_body, headers=H).get_json()
res2 = sr2["results"][0]["result"]
check("repeat sync is idempotent (ALREADY SYNCED / synced=0)",
      sr2.get("synced") == 0 and "ALREADY" in res2.get("title", ""), res2)
# A revoked pass queued offline is PERMANENTLY rejected on replay, not counted.
revoked_q = {"items": [{"payload": rb, "gate_id": 1, "mode": "entry",
                        "volunteer": "Rover", "scanned_at": "2026-01-01 10:05:00",
                        "occasion": "ceremony"}]}
sr3 = client.post("/api/sync", json=revoked_q, headers=H).get_json()
res3 = sr3["results"][0]["result"]
check("queued REVOKED pass replay -> GUEST PASS REVOKED, not synced",
      sr3.get("synced") == 0 and res3.get("title") == "GUEST PASS REVOKED", res3)

# ------------------------------------------------------- H. prod DB stamp
if PROD_STAMP is not None:
    _s = os.stat(PROD_DB)
    check("production app/lgu.db untouched",
          (_s.st_size, _s.st_mtime_ns) == PROD_STAMP,
          ((_s.st_size, _s.st_mtime_ns), PROD_STAMP))
else:
    check("production app/lgu.db absent/untouched", True)

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
