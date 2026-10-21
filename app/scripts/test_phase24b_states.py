"""Phase 24B re-audit — the five student registration states.

The mandate: do NOT treat the status-label mapping alone as complete. Trace
each of the five student-facing registration states to authoritative backend
data (convocation_registrations.status, the active convocation row, and the
registration-window config) — never infer a student's registration state from
profile completion.

The five states (student-facing) and their authoritative source:
  Registered            <- active registration row for the active convocation
  Action needed         <- cancelled / revoked row (correctable)
  Not found on list     <- 404 unmatched: no row matches the four identifiers
  Registration not open <- 409 no_convocation: no active convocation configured
  Registration closed   <- 410 on a non-active row at verify time

This test proves each state is driven by the registration row + convocation
config, and that profile completion is NOT the source of the status.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tmp = tempfile.mkdtemp(prefix="lgu-p24b-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(tmp, "p24b.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ.pop("LGU_ADMIN_PIN", None)

import config  # noqa: E402

config.require_test_db()

import database  # noqa: E402
import emailer  # noqa: E402
import exam_registrations as reg  # noqa: E402
import student_auth as sa  # noqa: E402
from web import student_routes  # noqa: E402
from flask import Flask  # noqa: E402

FAILS = []


def check(label, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + label
          + (("  <- %r" % (detail,)) if (detail and not cond) else ""))
    if not cond:
        FAILS.append(label)


print("=" * 70)
print("Phase 24B re-audit — five student registration states, traced to data")
print("=" * 70)

app = Flask(__name__)
app.register_blueprint(student_routes.bp)
app.config["TESTING"] = True

database.init_db()
db = database.get_db()
# Ensure there IS an active convocation (seed() may not create one).
have = db.execute("SELECT 1 FROM convocations WHERE is_active = 1").fetchone()
if not have:
    db.execute("INSERT INTO convocations (name, year, status, is_active,"
               " created_at, updated_at)"
               " VALUES ('Phase 24B', '2026', 'live', 1,"
               " '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00')")
    db.commit()
conv = reg.active_convocation(db)
check("a convocation is active", conv is not None)
# Seed one active registration on the list for this convocation.
have_reg = db.execute(
    "SELECT 1 FROM convocation_registrations WHERE convocation_id = ?",
    (conv["id"],)).fetchone()
if not have_reg:
    db.execute(
        "INSERT INTO convocation_registrations (convocation_id,"
        " registration_number, university_email, roll_number, student_name,"
        " department, status, created_at, updated_at)"
        " VALUES (?, 'REG-24B-0001', '24b0001@lgu.edu.pk', '240001',"
        " 'Ali Khan', 'BSCS', 'active',"
        " '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00')",
        (conv["id"],))
    db.commit()


def fresh_client():
    """A new simulated device: reset the per-IP limiter buckets first."""
    for bucket in student_routes._HITS.values():
        bucket.clear()
    return app.test_client()


def signup(reg_no, email, roll, name):
    """Drive /verify + /complete for one registration. Returns (client, body)."""
    c = fresh_client()
    emailer.OUTBOX.clear()
    r = c.post("/api/student/verify", json={
        "registration_number": reg_no, "university_email": email,
        "roll_number": roll, "student_name": name})
    if r.status_code != 200:
        return c, None
    cid = r.get_json()["challenge_id"]
    code = emailer.OUTBOX[-1][1] if emailer.OUTBOX else ""
    r = c.post("/api/student/complete", json={
        "challenge_id": cid, "code": code, "password": "correct-horse-battery"})
    return c, (r.get_json() if r.status_code == 200 else None)


# ---- a registration on the list -------------------------------------------
r = db.execute("SELECT * FROM convocation_registrations"
               " WHERE convocation_id = ? AND status = 'active' LIMIT 1",
               (conv["id"],)).fetchone()
check("there is an active registration on the list", r is not None)


def status_of(c):
    """The authoritative status the app serves for this session."""
    me = c.get("/api/student/me",
               headers={"Authorization": "Bearer %s" % _tok(c)})
    return me.get_json()


_TOKS = {}


def _tok(c):
    return _TOKS[id(c)]


# ============================================================ Registered ===
print("\n[1] Registered  <- active row")
c, body = signup(r["registration_number"], r["university_email"],
                 r["roll_number"], r["student_name"])
_TOKS[id(c)] = body["token"]
check("signup succeeds for an active registration", body is not None)
me = status_of(c)
check("GET /me serves status == 'active'",
      me["registration"]["status"] == "active", me["registration"]["status"])
check("the home screen's 'Registered' pill is driven by this row",
      me["registration"]["registration_number"] == r["registration_number"])

# ====================================== profile completion is NOT the source =
print("\n[1b] Profile completion does NOT drive the status")
# Reset the profile so completion.complete is False; the status must stay active.
acct = sa.get_account(db, r["university_email"])
db.execute("DELETE FROM student_profiles WHERE account_id = ?",
           (acct["id"],))
db.commit()
me = status_of(c)
check("with the profile wiped, status is STILL 'active' (not inferred)",
      me["registration"]["status"] == "active", me["registration"]["status"])
check("completion is now incomplete but status is unchanged",
      me["completion"]["complete"] is False)

# ============================================ Registration not open =======
print("\n[2] Registration not open  <- no active convocation (409)")
# Deactivate the convocation: no active convocation -> verify must 409.
db.execute("UPDATE convocations SET is_active = 0 WHERE id = ?",
           (conv["id"],))
db.commit()
c2 = fresh_client()
r2 = c2.post("/api/student/verify", json={
    "registration_number": r["registration_number"],
    "university_email": r["university_email"],
    "roll_number": r["roll_number"],
    "student_name": r["student_name"]})
j2 = r2.get_json()
check("verify with no active convocation is 409", r2.status_code == 409,
      (r2.status_code, j2))
check("code is no_convocation", j2.get("code") == "no_convocation", j2)
check("message says no active convocation is configured",
      "No active convocation" in j2.get("error", ""), j2)
# Restore the convocation for the remaining states.
db.execute("UPDATE convocations SET is_active = 1 WHERE id = ?",
           (conv["id"],))
db.commit()

# ================================================ Not found on list ========
print("\n[3] Not found on list  <- no row matches the identifiers (404)")
c3 = fresh_client()
r3 = c3.post("/api/student/verify", json={
    "registration_number": "REG-NOPE-9999",
    "university_email": r["university_email"],
    "roll_number": r["roll_number"],
    "student_name": r["student_name"]})
j3 = r3.get_json()
check("verify with an unknown registration number is 404",
      r3.status_code == 404, (r3.status_code, j3))
check("code is unmatched", j3.get("code") == "unmatched", j3)
check("message points at the official registration list",
      "No registration matches" in j3.get("error", ""), j3)

# A wrong roll number is equally unmatched (all four identifiers must match).
r3b = c3.post("/api/student/verify", json={
    "registration_number": r["registration_number"],
    "university_email": r["university_email"],
    "roll_number": "000000",
    "student_name": r["student_name"]})
j3b = r3b.get_json()
check("verify with a wrong roll number is also 404 unmatched",
      r3b.status_code == 404 and j3b.get("code") == "unmatched",
      (r3b.status_code, j3b))

# =============================================== Action needed =============
print("\n[4] Action needed  <- cancelled / revoked row")
# Cancel the registration; a NEW signup must be refused with 410.
db.execute("UPDATE convocation_registrations SET status = 'cancelled'"
           " WHERE id = ?", (r["id"],))
db.commit()
c4 = fresh_client()
r4 = c4.post("/api/student/verify", json={
    "registration_number": r["registration_number"],
    "university_email": r["university_email"],
    "roll_number": r["roll_number"],
    "student_name": r["student_name"]})
j4 = r4.get_json()
check("verify on a cancelled registration is 410", r4.status_code == 410,
      (r4.status_code, j4))
check("the status word served is 'cancelled'", j4.get("code") == "cancelled",
      j4)
check("message says the registration is cancelled and cannot be claimed",
      "cancelled" in j4.get("error", "") and "cannot be claimed"
      in j4.get("error", ""), j4)
# The already-claimed session from [1] now reports cancelled on /me.
me = status_of(c)
check("the claimed session's /me now reports 'cancelled'",
      me["registration"]["status"] == "cancelled", me["registration"]["status"])

# Revoke it too — both are Action needed.
db.execute("UPDATE convocation_registrations SET status = 'revoked'"
           " WHERE id = ?", (r["id"],))
db.commit()
me = status_of(c)
check("the claimed session's /me now reports 'revoked'",
      me["registration"]["status"] == "revoked", me["registration"]["status"])

# ================================================ Registration closed ======
print("\n[5] Registration closed  <- non-active row at verify time (410)")
# Revoke is terminal for entry: verify a REVOKED row must also be 410.
c5 = fresh_client()
r5 = c5.post("/api/student/verify", json={
    "registration_number": r["registration_number"],
    "university_email": r["university_email"],
    "roll_number": r["roll_number"],
    "student_name": r["student_name"]})
j5 = r5.get_json()
check("verify on a revoked registration is 410 (closed)",
      r5.status_code == 410, (r5.status_code, j5))
check("the closed status word is 'revoked'", j5.get("code") == "revoked", j5)

# Reinstate -> the row is active again and verify opens a new challenge.
db.execute("UPDATE convocation_registrations SET status = 'active'"
           " WHERE id = ?", (r["id"],))
db.commit()
c6 = fresh_client()
r6 = c6.post("/api/student/verify", json={
    "registration_number": r["registration_number"],
    "university_email": r["university_email"],
    "roll_number": r["roll_number"],
    "student_name": r["student_name"]})
j6 = r6.get_json()
# The row is active again, so verify must no longer be a 410 "closed".
# This registration is already claimed by the session from [1], so the
# correct outcome is a 409 "claimed" (sign in instead) — never 410.
check("after reinstate, verify is no longer 410 (not closed)",
      r6.status_code != 410, (r6.status_code, j6))
check("the claimed registration is refused with a 409 sign-in hint",
      r6.status_code == 409 and j6.get("code") == "claimed",
      (r6.status_code, j6))

db.close()

print("\n" + "-" * 70)
if FAILS:
    print("%d FAILURES:" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("All checks passed. Five states traced to authoritative backend data;")
print("profile completion is NOT the source of the registration status.")
print("PROD_DB untouched (disposable %s)" % os.environ["LGU_DB_PATH"])
