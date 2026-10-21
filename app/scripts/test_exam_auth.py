"""Phase 3 regression: exam staff auth on disposable temp databases only.

Run:  python scripts/test_exam_auth.py   (from app/)
"""

import os
import re
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

TMP = tempfile.mkdtemp(prefix="lgu-p3-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "fresh.db")

from werkzeug.security import check_password_hash  # noqa: E402

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import exam_auth  # noqa: E402
import migrations  # noqa: E402
from web import exam_routes  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
PW = "correct-horse-battery"


def check(label, cond, detail=""):
    global failures
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def raw(sql, args=()):
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    out = [dict(r) for r in c.execute(sql, args).fetchall()]
    c.close()
    return out


def csrf_of(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()

# Migration repeatability.
database.init_db()
database.init_db()
check("migration version matches latest", raw("PRAGMA user_version")[0]["user_version"] == max(v for v, _ in migrations.MIGRATIONS))
tables = {r["name"] for r in raw("SELECT name FROM sqlite_master WHERE type='table'")}
check("staff_users and audit_log exist", {"staff_users", "audit_log"} <= tables)

# Account creation: no plaintext stored, hash verifies, policy enforced.
exam_auth.create_staff("examofficer1", "Exam Officer One", PW)
row = raw("SELECT * FROM staff_users WHERE username = ?", ("examofficer1",))[0]
check("password is not stored in plaintext", PW not in row["password_hash"] and row["password_hash"] != PW)
check("stored hash verifies", check_password_hash(row["password_hash"], PW))
try:
    exam_auth.create_staff("shortpw", "Short", "abc")
    check("weak password rejected", False)
except ValueError:
    check("weak password rejected", True)
try:
    exam_auth.create_staff("examofficer1", "Dup", PW)
    check("duplicate username rejected", False)
except ValueError:
    check("duplicate username rejected", True)

# Login: unauthenticated access redirects.
r = client.get("/exam/")
check("unauthenticated dashboard redirects to login", r.status_code == 302 and "/exam/login" in r.headers["Location"])

# Login page renders with CSRF token.
r = client.get("/exam/login")
token = csrf_of(r.get_data(as_text=True))
check("login page renders csrf token", r.status_code == 200 and token != "")

# POST without token is rejected.
r = client.post("/exam/login", data={"username": "examofficer1", "password": PW})
check("login POST without csrf rejected", r.status_code == 403)

# Wrong password fails, correct password succeeds.
r = client.post("/exam/login", data={"username": "examofficer1", "password": "wrong-password-xx", "csrf_token": token})
check("wrong password rejected", r.status_code == 401)
r = client.post("/exam/login", data={"username": "examofficer1", "password": PW, "csrf_token": token})
check("correct password redirects to dashboard", r.status_code == 302 and r.headers["Location"].endswith("/exam/dashboard"))

r = client.get("/exam/dashboard")
check("authenticated dashboard loads", r.status_code == 200 and b"Examination Admin" in r.data)

# Session separation: volunteer PIN session key must not grant exam access.
with client.session_transaction() as s:
    s.pop("exam_staff_id", None)
    s["lgu_admin"] = True
r = client.get("/exam/dashboard")
check("volunteer session does not grant exam access", r.status_code == 302)

# Logout requires CSRF and clears session.
r = client.get("/exam/login")
token = csrf_of(r.get_data(as_text=True))
client.post("/exam/login", data={"username": "examofficer1", "password": PW, "csrf_token": token})
r = client.post("/exam/logout", data={})
check("logout without csrf rejected", r.status_code == 403)
token = csrf_of(client.get("/exam/dashboard").get_data(as_text=True))
r = client.post("/exam/logout", data={"csrf_token": token})
check("logout with csrf redirects", r.status_code == 302)
r = client.get("/exam/dashboard")
check("dashboard inaccessible after logout", r.status_code == 302)

# Lockout after repeated failures.
for _ in range(exam_auth.MAX_FAILED_ATTEMPTS):
    exam_auth.authenticate("examofficer1", "wrong-password-xx")
check("account locked after repeated failures", exam_auth.authenticate("examofficer1", PW) is None)

# Audit trail recorded.
actions = {r["action"] for r in raw("SELECT action FROM audit_log")}
check("audit log records login and failure events", {"login_ok", "login_failed", "logout", "staff_created"} <= actions)


def run(sql, args=()):
    c = sqlite3.connect(config.DB_PATH)
    c.execute(sql, args)
    c.commit()
    c.close()


# --- Phase 3.1: sessionless CSRF bypass (demonstrated gap A) -------------
# A POST with NO session cookie at all must not pass the guard even with
# valid credentials: the empty expected token used to compare equal to an
# empty sent token.
fresh = app.test_client()
r = fresh.post("/exam/login", data={"username": "examofficer1", "password": PW})
check("sessionless login POST without csrf is rejected", r.status_code == 403, r.status_code)

# --- Phase 3.1: bounded input reaches the audit log (demonstrated gap C) -
# Unlock the fixture account so the tests below exercise the password-cap
# and wrong-password branches rather than the lockout branch.
run("UPDATE staff_users SET failed_attempts = 0, locked_until = NULL"
    " WHERE username = ?", ("examofficer1",))
exam_routes._EXAM_FAILS.clear()
token = csrf_of(client.get("/exam/login").get_data(as_text=True))
r = client.post("/exam/login", data={"username": "A" * 200000,
                                     "password": "x" * 300, "csrf_token": token})
check("oversized credentials rejected", r.status_code == 401, r.status_code)
r = client.post("/exam/login", data={"username": "examofficer1",
                                     "password": "x" * 300, "csrf_token": token})
check("over-policy-length password rejected", r.status_code == 401, r.status_code)
r = client.post("/exam/login", data={"username": "   examofficer1" + " " * 5000,
                                     "password": "wrong-password-xx", "csrf_token": token})
check("whitespace-padded username still fails as wrong password", r.status_code == 401, r.status_code)
actor_lens = [x["n"] for x in raw("SELECT length(actor) AS n FROM audit_log")]
check("every audit actor is bounded at 64", actor_lens and max(actor_lens) <= 64, actor_lens and max(actor_lens))

# --- Phase 3.1: per-IP rate limiting on /exam/login (demonstrated gap B) -
run("UPDATE staff_users SET failed_attempts = 0, locked_until = NULL"
    " WHERE username = ?", ("examofficer1",))
exam_routes._EXAM_FAILS.clear()
config.EXAM_RATE_MAX_FAILS = 3

# A successful login must not consume rate budget (3 wrongs below stay 401).
token = csrf_of(client.get("/exam/login").get_data(as_text=True))
r = client.post("/exam/login", data={"username": "examofficer1", "password": PW, "csrf_token": token})
check("successful login is not rate limited", r.status_code == 302, r.status_code)
token = csrf_of(client.get("/exam/dashboard").get_data(as_text=True))
client.post("/exam/logout", data={"csrf_token": token})

token = csrf_of(client.get("/exam/login").get_data(as_text=True))
st = [client.post("/exam/login", data={"username": "examofficer1",
                                       "password": "wrong-password-xx",
                                       "csrf_token": token}).status_code
      for _ in range(config.EXAM_RATE_MAX_FAILS)]
check("failed attempts below threshold return 401", st == [401, 401, 401], st)
r = client.post("/exam/login", data={"username": "examofficer1",
                                     "password": "wrong-password-xx", "csrf_token": token})
check("next failure from same IP returns 429", r.status_code == 429, r.status_code)
r = client.post("/exam/login", data={"username": "examofficer1",
                                     "password": PW, "csrf_token": token})
check("correct password blocked while IP is limited", r.status_code == 429, r.status_code)
r = client.get("/exam/dashboard")
check("no session granted while IP is limited", r.status_code == 302, r.status_code)

# Window expiry releases the limit.
config.EXAM_RATE_WINDOW_SECONDS = 0
r = client.post("/exam/login", data={"username": "examofficer1",
                                     "password": "wrong-password-xx", "csrf_token": token})
check("limit expires after the window", r.status_code == 401, r.status_code)
config.EXAM_RATE_WINDOW_SECONDS = 60

print("\n%s" % ("ALL PASSED" if failures == 0 else "%d FAILED" % failures))
sys.exit(1 if failures else 0)
