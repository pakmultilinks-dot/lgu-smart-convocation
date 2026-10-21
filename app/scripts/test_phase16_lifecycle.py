"""Phase 16 — complete student account lifecycle on a disposable database.

Covers the brief's §5 cases 1–17 with synthetic registrations and the
fake (test-only) transport. Temp databases only — app/lgu.db is never
opened, and no production student data is used.

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase16_lifecycle.py
"""

import logging
import os
import secrets
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

TMP = tempfile.mkdtemp(prefix="lgu-p16-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "lifecycle.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "photos")

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import emailer  # noqa: E402
import student_auth as sa  # noqa: E402
from web import student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
CONV = 1
PASSWORD = secrets.token_urlsafe(24)
NEW_PASSWORD = secrets.token_urlsafe(24)
THIRD_PASSWORD = secrets.token_urlsafe(24)


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
    try:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def sql_exec(sql, args=()):
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def reset_limits():
    for bucket in sr._HITS:
        sr._HITS[bucket].clear()


def add_reg(reg_no, email, roll, name, status="active", dept="BSCS"):
    now = "2026-10-01T00:00:00+00:00"
    sql_exec(
        "INSERT INTO convocation_registrations"
        " (convocation_id, registration_number, university_email, roll_number,"
        "  student_name, department, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (CONV, reg_no, email, roll, name, dept, status, now, now))


def post(path, body=None, token=None, raw_body=None):
    headers = {"Authorization": "Bearer %s" % token} if token else {}
    if raw_body is not None:
        r = client.post(path, data=raw_body, content_type="text/plain",
                        headers=headers)
    else:
        r = client.post(path, json=body or {}, headers=headers)
    try:
        return r.status_code, r.get_json(silent=True) or {}
    except Exception:
        return r.status_code, {}


def get(path, token=None):
    headers = {"Authorization": "Bearer %s" % token} if token else {}
    r = client.get(path, headers=headers)
    try:
        return r.status_code, r.get_json(silent=True) or {}
    except Exception:
        return r.status_code, {}


def begin_signup(reg_no, email, roll, name):
    """Case 1–3: verify against the authoritative roster, code to outbox."""
    emailer.OUTBOX.clear()
    st, body = post("/api/student/verify", {"registration_number": reg_no,
                                            "university_email": email,
                                            "roll_number": roll,
                                            "student_name": name})
    code = emailer.OUTBOX[-1][1] if emailer.OUTBOX else ""
    return st, body, code


# --------------------------------------------------------------- log capture
class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


capture = Capture()
logging.getLogger().addHandler(capture)
logging.getLogger().setLevel(logging.DEBUG)

database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()

print("\nPhase 16 — student account lifecycle (disposable DB, fake transport)")

# ------------------------------------------- 1–2. signup + identity matching
reset_limits()
add_reg("REG-P16A", "amina.sha@uni.edu.pk", "160001", "Amina Shaikh")
st, body, code = begin_signup("REG-P16A", "amina.sha@uni.edu.pk", "160001",
                              "Amina Shaikh")
check("1: eligible synthetic student begins signup (200)", st == 200,
      (st, body))
check("2: wrong roll number is rejected as unmatched",
      post("/api/student/verify", {"registration_number": "REG-P16A",
                                   "university_email": "amina.sha@uni.edu.pk",
                                   "roll_number": "999999",
                                   "student_name": "Amina Shaikh"})[0] == 404)
check("2: wrong name is rejected as unmatched",
      post("/api/student/verify", {"registration_number": "REG-P16A",
                                   "university_email": "amina.sha@uni.edu.pk",
                                   "roll_number": "160001",
                                   "student_name": "Someone Else"})[0] == 404)
check("2: altered email cannot borrow another registration",
      post("/api/student/verify", {"registration_number": "REG-P16A",
                                   "university_email": "attacker@uni.edu.pk",
                                   "roll_number": "160001",
                                   "student_name": "Amina Shaikh"})[0] ==
      404)
challenge_id = body.get("challenge_id")

# --------------------------------------------------- 3. test transport output
check("3: verification message generated by the test transport",
      len(emailer.OUTBOX) == 1 and emailer.OUTBOX[0][0] ==
      "amina.sha@uni.edu.pk", emailer.OUTBOX)
check("3: the code is six digits", code.isdigit() and len(code) == 6, code)
check("3: the code never appears in the HTTP response", code not in str(body))

# ------------------------------------------- 5a. no account before the code
check("5: no account exists before the code is verified",
      not raw("SELECT 1 FROM student_accounts WHERE university_email ="
              " 'amina.sha@uni.edu.pk'"))
st, login_body = post("/api/student/login",
                      {"email": "amina.sha@uni.edu.pk",
                       "password": PASSWORD})
check("5: sign-in is impossible before verification", st == 401,
      (st, login_body))

# ------------------------------------------------------ 6. token rejection
reset_limits()
st, b = post("/api/student/complete", {"challenge_id": challenge_id,
                                       "code": "000000" if code != "000000"
                                       else "111111",
                                       "password": PASSWORD})
check("6: invalid code is rejected", st == 400 and b.get("code") == "code",
      (st, b))
st, b = post("/api/student/complete", {"challenge_id": 999999, "code": code,
                                       "password": PASSWORD})
check("6: forged challenge id is rejected", st == 404, (st, b))
sql_exec("UPDATE verification_challenges SET expires_at ="
         " '2000-01-01T00:00:00+00:00' WHERE id = ?", (challenge_id,))
st, b = post("/api/student/complete", {"challenge_id": challenge_id,
                                       "code": code,
                                       "password": PASSWORD})
check("6: expired token is rejected", st == 410 and b.get("code") == "expired",
      (st, b))
sql_exec("DELETE FROM verification_challenges WHERE id = ?",
         (challenge_id,))
# fresh challenge for the happy path (the expired one is spent)
st, body, code = begin_signup("REG-P16A", "amina.sha@uni.edu.pk", "160001",
                              "Amina Shaikh")
challenge_id = body["challenge_id"]

# ------------------------------------------------- 4. token consumed once
reset_limits()
st, b = post("/api/student/complete", {"challenge_id": challenge_id,
                                       "code": code,
                                       "password": PASSWORD})
check("4: valid token is consumed successfully (session issued)",
      st == 200 and b.get("token"), (st, b))
token = b.get("token", "")
check("4: challenge row is marked consumed",
      raw("SELECT consumed_at FROM verification_challenges WHERE id = ?",
          (challenge_id,))[0]["consumed_at"] is not None)
st, b = post("/api/student/complete", {"challenge_id": challenge_id,
                                       "code": code,
                                       "password": PASSWORD})
check("6: reused token is rejected", st == 410, (st, b))

# ------------------------------------------------------ 5b. sign in works
reset_limits()
st, b = post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                    "password": PASSWORD})
check("5: verified account signs in after verification", st == 200, (st, b))
token = b.get("token", token)
st, b = post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                    "password": "wrong-password-xx"})
check("5: wrong password is a uniform 401", st == 401 and
      b.get("error") == "Email or password is incorrect.", (st, b))

# ------------------------------------------------------ 7. resend limiting
reset_limits()
add_reg("REG-P16D", "daniyal.ra@uni.edu.pk", "160004", "Daniyal Raza")
st, body, code = begin_signup("REG-P16D", "daniyal.ra@uni.edu.pk", "160004",
                              "Daniyal Raza")
cid = body["challenge_id"]
sends = []
for _ in range(4):
    sends.append(post("/api/student/resend", {"challenge_id": cid}))
check("7: resend works up to CODE_MAX_SENDS then refuses",
      [s for s, _ in sends].count(200) == config.CODE_MAX_SENDS - 1 and
      sends[-1][0] == 429 and sends[-1][1].get("code") == "send_limit",
      [s for s, _ in sends])
reset_limits()
for _ in range(config.STUDENT_RATE_MAX_VERIFY):
    post("/api/student/verify", {"registration_number": "REG-P16D",
                                 "university_email": "daniyal.ra@uni.edu.pk",
                                 "roll_number": "160004",
                                 "student_name": "Daniyal Raza"})
st, b = post("/api/student/verify", {"registration_number": "REG-P16D",
                                     "university_email":
                                     "daniyal.ra@uni.edu.pk",
                                     "roll_number": "160004",
                                     "student_name": "Daniyal Raza"})
check("7: per-IP send limit refuses the next request", st == 429 and
      b.get("code") == "rate_limited", (st, b))

# ------------------------------------- 8. provider failure is honest + safe
reset_limits()
saved = config.EMAIL_MODE
config.EMAIL_MODE = "disabled"
add_reg("REG-P16B", "bilal.no@uni.edu.pk", "160002", "Bilal Noor")
st, b = post("/api/student/verify", {"registration_number": "REG-P16B",
                                     "university_email": "bilal.no@uni.edu.pk",
                                     "roll_number": "160002",
                                     "student_name": "Bilal Noor"})
check("8: delivery failure answers 503 email_unavailable", st == 503 and
      b.get("code") == "email_unavailable", (st, b))
check("8: failure created no account and no challenge",
      not raw("SELECT 1 FROM student_accounts WHERE university_email ="
              " 'bilal.no@uni.edu.pk'") and
      not raw("SELECT 1 FROM verification_challenges WHERE university_email ="
              " 'bilal.no@uni.edu.pk'"))
st1, b1 = post("/api/student/recovery/request",
               {"email": "bilal.no@uni.edu.pk"})
st2, b2 = post("/api/student/recovery/request",
               {"email": "never.heard@uni.edu.pk"})
check("8: recovery failure is identical for known and unknown email",
      st1 == st2 == 503 and b1 == b2, (st1, b1, st2, b2))
config.EMAIL_MODE = saved

# ------------------------------------------- 9. recovery reveals nothing
reset_limits()
emailer.OUTBOX.clear()
st1, b1 = post("/api/student/recovery/request",
               {"email": "amina.sha@uni.edu.pk"})
st2, b2 = post("/api/student/recovery/request",
               {"email": "ghost.student@uni.edu.pk"})
check("9: known and unknown recovery answers are byte-identical",
      st1 == st2 == 200 and b1 == b2, (st1, b1, st2, b2))
check("9: only one message was generated (the known account)",
      len(emailer.OUTBOX) == 1 and emailer.OUTBOX[0][0] ==
      "amina.sha@uni.edu.pk", emailer.OUTBOX)
rec_code = emailer.OUTBOX[-1][1]
rec_id = raw("SELECT id FROM verification_challenges WHERE purpose ="
             " 'recovery' ORDER BY id DESC LIMIT 1")[0]["id"]

# ------------------------------------------- 10–11. reset + old password
reset_limits()
st, b = post("/api/student/recovery/complete",
             {"challenge_id": rec_id, "code": rec_code,
              "password": NEW_PASSWORD})
check("10: valid recovery resets the password", st == 200, (st, b))
st, b = post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                    "password": PASSWORD})
check("11: the previous password no longer authenticates", st == 401,
      (st, b))
st, b = post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                    "password": NEW_PASSWORD})
check("11: the new password authenticates", st == 200, (st, b))
new_token = b.get("token", "")

# ------------------------------------- 12. expired/consumed reset tokens
reset_limits()
st, b = post("/api/student/recovery/complete",
             {"challenge_id": rec_id, "code": rec_code,
              "password": "another-passphrase-16"})
check("12: a consumed reset token is rejected", st == 410, (st, b))
sql_exec("DELETE FROM verification_challenges WHERE purpose = 'recovery'")
st, b = post("/api/student/recovery/request",
             {"email": "amina.sha@uni.edu.pk"})
exp_id = raw("SELECT id FROM verification_challenges WHERE purpose ="
             " 'recovery' ORDER BY id DESC LIMIT 1")[0]["id"]
sql_exec("UPDATE verification_challenges SET expires_at ="
         " '2000-01-01T00:00:00+00:00' WHERE id = ?", (exp_id,))
st, b = post("/api/student/recovery/complete",
             {"challenge_id": exp_id, "code": "123456",
              "password": "another-passphrase-16"})
check("12: an expired reset token is rejected", st == 410 and
      b.get("code") == "expired", (st, b))

# ------------------------------------------- 13. abuse protections intact
reset_limits()
for _ in range(config.STUDENT_RATE_MAX_LOGIN):
    post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                "password": "nope-not-this-1"})
reset_limits()  # the per-IP login budget is spent too; test the lock itself
st, b = post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                    "password": "nope-not-this-1"})
check("13: per-account lockout engages after the failed attempts", st == 429
      and b.get("code") == "locked", (st, b))
reset_limits()
st, b = post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                    "password": NEW_PASSWORD})
check("13: even the correct password is refused while locked out", st == 429
      and b.get("code") == "locked", (st, b))
sql_exec("UPDATE student_accounts SET locked_until = NULL,"
         " failed_attempts = 0 WHERE university_email ="
         " 'amina.sha@uni.edu.pk'")
for _ in range(config.STUDENT_RATE_MAX_LOGIN):
    post("/api/student/login", {"email": "ghost.user@uni.edu.pk",
                                "password": "nope-not-this-1"})
st, b = post("/api/student/login", {"email": "ghost.user@uni.edu.pk",
                                    "password": "nope-not-this-1"})
check("13: login per-IP limit holds", st == 429 and
      b.get("code") == "rate_limited", (st, b))
reset_limits()
for _ in range(config.STUDENT_RATE_MAX_RECOVERY):
    post("/api/student/recovery/request",
         {"email": "daniyal.ra@uni.edu.pk"})
st, b = post("/api/student/recovery/request",
             {"email": "daniyal.ra@uni.edu.pk"})
check("13: recovery per-IP limit holds", st == 429 and
      b.get("code") == "rate_limited", (st, b))
reset_limits()
for _ in range(config.STUDENT_RATE_MAX_CONFIRM):
    post("/api/student/complete", {"challenge_id": 999999, "code": "000000",
                                   "password": PASSWORD})
st, b = post("/api/student/complete", {"challenge_id": 999999,
                                       "code": "000000",
                                       "password": PASSWORD})
check("13: code-entry (confirm) per-IP limit holds", st == 429 and
      b.get("code") == "rate_limited", (st, b))
reset_limits()
st, b = post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                    "password": NEW_PASSWORD})
check("13: the lock did not leak into the reset password", st == 200,
      (st, b))
admin_token = b.get("token", "")

# --------------------------------- 14. no cross-registration account claim
reset_limits()
add_reg("REG-P16C", "chitra.das@uni.edu.pk", "160003", "Chitra Das")
st, b = post("/api/student/verify", {"registration_number": "REG-P16A",
                                     "university_email":
                                     "chitra.das@uni.edu.pk",
                                     "roll_number": "160001",
                                     "student_name": "Amina Shaikh"})
check("14: mixing another student's registration fields is unmatched",
      st == 404, (st, b))
st, body, code = begin_signup("REG-P16C", "chitra.das@uni.edu.pk", "160003",
                              "Chitra Das")
st, b = post("/api/student/complete",
             {"challenge_id": body["challenge_id"], "code": code,
              "password": PASSWORD,
              "university_email": "amina.sha@uni.edu.pk",
              "registration_number": "REG-P16A"})
check("14: injected fields cannot redirect the account being created",
      st == 200 and b.get("account", {}).get("email") ==
      "chitra.das@uni.edu.pk" and
      len(raw("SELECT 1 FROM student_accounts WHERE university_email ="
              " 'amina.sha@uni.edu.pk'")) == 1,
      (st, b))
st, b = post("/api/student/verify", {"registration_number": "REG-P16C",
                                     "university_email":
                                     "chitra.das@uni.edu.pk",
                                     "roll_number": "160003",
                                     "student_name": "Chitra Das"})
check("14: a claimed registration cannot be claimed again", st == 409,
      (st, b))

# --------------------------- 15. failures leak no secrets into logs/output
reset_limits()
email_sent_before = len(capture.lines)
config.EMAIL_MODE = "disabled"
post("/api/student/verify", {"registration_number": "REG-P16C",
                             "university_email": "chitra.das@uni.edu.pk",
                             "roll_number": "160003",
                             "student_name": "Chitra Das"})
config.EMAIL_MODE = saved
post("/api/student/complete", {"challenge_id": 999999, "code": "000000",
                               "password": PASSWORD}, raw_body="not-json{")
st, b = post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                    "password": PASSWORD})
logs = "\n".join(capture.lines[email_sent_before:])
check("15: no password, code or token reaches the log stream",
      PASSWORD not in logs and NEW_PASSWORD not in logs and
      code not in logs and token not in logs and admin_token not in logs,
      logs[-400:])
check("15: malformed request answers JSON, never a traceback",
      post("/api/student/complete", raw_body="<html>boom</html>")[0] in
      (400, 404, 415, 429) and "Traceback" not in
      str(post("/api/student/complete", raw_body="<html>boom</html>")[1]))
check("15: the emailer itself never logs or prints",
      "logging" not in open(os.path.join(APP_DIR, "emailer.py")).read() and
      "print(" not in open(os.path.join(APP_DIR, "emailer.py")).read())

# --------------------------------------------- 16. logout + session truth
reset_limits()
st, b = post("/api/student/logout", token=admin_token)
check("16: logout revokes the session", st == 200, (st, b))
st, b = get("/api/student/me", token=admin_token)
check("16: the revoked token no longer reads the account", st == 401,
      (st, b))
st, b = post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                    "password": NEW_PASSWORD})
old_token = b.get("token", "")
st, b = post("/api/student/recovery/request",
             {"email": "amina.sha@uni.edu.pk"})
rec2 = emailer.OUTBOX[-1][1]
rec2_id = raw("SELECT id FROM verification_challenges WHERE purpose ="
              " 'recovery' ORDER BY id DESC LIMIT 1")[0]["id"]
post("/api/student/recovery/complete", {"challenge_id": rec2_id,
                                        "code": rec2,
                                        "password": THIRD_PASSWORD})
st, b = get("/api/student/me", token=old_token)
check("16: a password reset invalidates every earlier session", st == 401,
      (st, b))

# ------------------------- 17. the rest of the student surface still works
reset_limits()
st, b = post("/api/student/login", {"email": "amina.sha@uni.edu.pk",
                                    "password": THIRD_PASSWORD})
tok = b.get("token", "")
for path in ("/api/student/pass", "/api/student/history",
             "/api/student/readiness", "/api/student/support",
             "/api/student/announcements", "/api/student/medalists",
             "/api/student/event"):
    st, b = get(path, token=tok)
    check("17: %s still answers 200" % path, st == 200, (st, b))
st, b = post("/api/student/profile", {"phone": "+923000000000"}, token=tok)
check("17: profile update still answers 200", st == 200, (st, b))

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)