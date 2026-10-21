#!/usr/bin/env python
"""Phase 20 §4 — deployment & runtime configuration audit.

Verifies the *behaviour* of every production-relevant setting against the
release claims, on a disposable database. The production file is stat-stamped
and never opened; where a check needs to reason about it (test-tool isolation)
it does so through `config.is_production_db()` inside a request context, never
by writing to it.

Run from app/:  ..\\..\\.venv\\Scripts\\python.exe scripts\\test_phase20_config_audit.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p20cfg-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "cfg.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
for _k in ("LGU_SMTP_HOST", "LGU_SMTP_USER", "LGU_SMTP_PASSWORD",
           "LGU_MAIL_FROM", "LGU_ADMIN_PIN", "LGU_SECRET_KEY",
           "LGU_HMAC_SECRET", "LGU_ALLOW_DEMO_SECRETS"):
    os.environ.pop(_k, None)

import config  # noqa: E402
config.require_test_db()

import database  # noqa: E402
import emailer  # noqa: E402
import exam_auth  # noqa: E402
import scanner_auth  # noqa: E402
import web.routes as vr  # noqa: E402
import web.student_routes as web_student  # noqa: E402
from web.routes import create_app  # noqa: E402

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
RESULTS = []
LEAKS = ("password_hash", "pin_hash", "token_hash", "code_hash",
         "secret_key", "hmac_secret", "lgu-convocation-demo")
STAFF_USER, STAFF_PW = "p20.admin", "Config-Audit-Pass-20"


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    if not cond:
        print("  FAIL %s %s" % (name, detail))


def step(n, title):
    print("\n[%02d] %s" % (n, title))


database.init_db()
database.seed()
exam_auth.create_staff(STAFF_USER, "P20 Admin", STAFF_PW)
sid = scanner_auth.create_scanner("p20.cfg", "Cfg Scanner", pin="73910462",
                                  gate_ids=(1,), actor="p20",
                                  via=scanner_auth.VIA_CLI)
app = create_app()
app.config.update(TESTING=True)
client = app.test_client()


def login(target="/exam/dashboard"):
    r = client.get("/exam/login")
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.get_data(as_text=True))
    return client.post("/exam/login",
                       data={"username": STAFF_USER, "password": STAFF_PW,
                             "csrf_token": token.group(1)},
                       follow_redirects=False)


# ------------------------------------------------------------ A. secrets
step(1, "Demo-secret fallback cannot silently reach a running service")
names = config.demo_secrets()
check("demo_secrets() returns names, not values",
      names == ["LGU_SECRET_KEY", "LGU_HMAC_SECRET", "LGU_ADMIN_PIN"], str(names))
check("demo_secrets() never leaks a value",
      not any(v in repr(names) for v in (config.SECRET_KEY, config.ADMIN_PIN)))

env = dict(os.environ)
env["LGU_DB_PATH"] = os.path.join(_TMP, "guard.db")
env.pop("LGU_ALLOW_DEMO_SECRETS", None)
for k in ("LGU_SECRET_KEY", "LGU_HMAC_SECRET", "LGU_ADMIN_PIN"):
    env.pop(k, None)
r = subprocess.run([PY, "run.py"], capture_output=True, text=True, env=env,
                   cwd=os.path.dirname(APP_DIR))
check("startup refuses demo secrets (exit 1)", r.returncode == 1, r.stderr)
check("refusal names the offending settings",
      "LGU_SECRET_KEY" in r.stderr and "LGU_ADMIN_PIN" in r.stderr, r.stderr)
check("refusal tells the operator how to fix it",
      "LGU_ALLOW_DEMO_SECRETS=1" in r.stderr, r.stderr)
check("refusal does not print any secret value",
      "change-in-production" not in r.stderr.split("LGU_SECRET_KEY,")[-1]
      if "LGU_SECRET_KEY," in r.stderr else True, r.stderr)
check("refusal happens BEFORE any database is created",
      not os.path.exists(env["LGU_DB_PATH"]), "database was created")

env["LGU_ALLOW_DEMO_SECRETS"] = "1"
r = subprocess.run([PY, "-c", "import run; print('ok')"], capture_output=True,
                   text=True, env=env, cwd=os.path.dirname(APP_DIR))
check("explicit development opt-in starts", r.returncode == 0 and "ok" in r.stdout,
      r.stdout + r.stderr)
check("opt-in still warns", "demo secrets" in r.stdout, r.stdout)

for k, v in (("LGU_SECRET_KEY", "a-unique-session-secret-20"),
             ("LGU_HMAC_SECRET", "a-unique-hmac-secret-20"),
             ("LGU_ADMIN_PIN", "8421")):
    env[k] = v
r = subprocess.run([PY, "-c", "import run; print('demo=', run.config.demo_secrets())"],
                   capture_output=True, text=True, env=env,
                   cwd=os.path.dirname(APP_DIR))
check("real secrets start silently", r.returncode == 0 and "[]" in r.stdout,
      r.stdout + r.stderr)

check("app.secret_key is the configured value", app.secret_key == config.SECRET_KEY)
check("debug is disabled", app.debug is False)

# ------------------------------------------------------------ B. cookies
step(2, "Session cookie hardening under the intended (plain-HTTP LAN) topology")
r = login()
cookie = r.headers.get("Set-Cookie", "")
check("staff login sets a session cookie", "session=" in cookie, cookie)
check("session cookie is HttpOnly", "HttpOnly" in cookie, cookie)
check("session cookie is not marked Secure (plain-HTTP LAN tool)",
      "Secure" not in cookie, cookie)
check("session cookie sets SameSite", "SameSite" in cookie, cookie)
check("SameSite is Lax, not None", "SameSite=Lax" in cookie, cookie)
check("Secure is opt-in via LGU_COOKIE_SECURE, default off for LAN HTTP",
      config.COOKIE_SECURE is False)

# ------------------------------------------------------------ C. CORS
step(3, "CORS allowlist — no wildcard, no cross-site grant")
r = client.get("/api/health", headers={"Origin": "https://evil.example"})
check("foreign origin gets no CORS grant",
      "Access-Control-Allow-Origin" not in r.headers, str(dict(r.headers)))
r = client.get("/api/health", headers={"Origin": "http://localhost:5000"})
check("same-host origin is granted", r.headers.get("Access-Control-Allow-Origin")
      == "http://localhost:5000", str(r.headers.get("Access-Control-Allow-Origin")))
check("grant echoes the origin, never a wildcard",
      r.headers.get("Access-Control-Allow-Origin") != "*")
r = client.get("/api/health", headers={"Origin": "http://127.0.0.1:5000"})
check("loopback development origin is granted",
      r.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:5000")
r = client.get("/api/health")
check("no Origin header means no CORS grant",
      "Access-Control-Allow-Origin" not in r.headers)
check("Vary: Origin is set on a granted response",
      "Origin" in client.get("/api/health",
                             headers={"Origin": "http://localhost:5000"})
      .headers.get("Vary", ""))

# ------------------------------------------------------------ D. health
step(4, "Health endpoint and error responses expose nothing")
r = client.get("/api/health")
body = r.get_data(as_text=True)
check("health responds 200", r.status_code == 200)
check("health reports liveness", '\"ok\":true' in body, body)
check("health leaks no secret or hash",
      not any(s in body for s in LEAKS), body[:200])
r = client.get("/api/definitely-not-a-route")
check("404 handler answers JSON clients cleanly",
      r.status_code == 404 and "Not found" in r.get_data(as_text=True))
check("404 body leaks nothing",
      not any(s in r.get_data(as_text=True) for s in LEAKS))

# ------------------------------------------------------------ E. CSRF
step(5, "CSRF is enforced on state-changing staff requests")
login()
r = client.get("/exam/scanners")
token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"',
                  r.get_data(as_text=True))
check("management page is reachable to staff", r.status_code == 200 and token)
r = client.post("/exam/scanners/new",
                data={"username": "p20.nocsrf", "display_name": "No CSRF"})
check("POST without a CSRF token is refused", r.status_code == 403,
      str(r.status_code))
check("no account was created by the refused POST",
      scanner_auth.get_scanner(
          next((s["id"] for s in scanner_auth.list_scanners()
                if s["username"] == "p20.nocsrf"), 0)) is None)
r = client.post("/exam/scanners/new",
                data={"username": "p20.badcsrf", "display_name": "Bad CSRF",
                      "csrf_token": "not-a-real-token"})
check("POST with a forged CSRF token is refused", r.status_code == 403)

# ------------------------------------------------------------ F. rate limit
step(6, "Authentication rate limiting and account lockout")
r = client.get("/exam/login")
good = re.search(r'name="csrf_token"[^>]*value="([^"]+)"',
                 r.get_data(as_text=True)).group(1)
codes = []
for i in range(6):
    r = client.post("/exam/login", data={"username": STAFF_USER,
                                         "password": "wrong-password-%d" % i,
                                         "csrf_token": good})
    codes.append(r.status_code)
check("repeated bad logins are rate limited (429)", codes[-1] == 429, str(codes))
check("every pre-limit attempt is rejected as unauthenticated",
      all(c in (401, 429) for c in codes), str(codes))

# ------------------------------------------------------------ G. isolation
step(7, "Test tooling is absent on a production database path")
saved = config.DB_PATH
try:
    config.DB_PATH = config.PRODUCTION_DB_PATH
    with app.test_request_context("/api/test-scanner-session"):
        guarded = vr._test_tool_guard()
    check("test-tool routes are refused on the production path",
          guarded is not None and guarded[1] == 404, str(guarded))
finally:
    config.DB_PATH = saved
with app.test_request_context("/api/test-scanner-session"):
    check("test-tool routes remain available on a test path",
          vr._test_tool_guard() is None)
try:
    config.require_test_db(config.PRODUCTION_DB_PATH)
except SystemExit:
    check("require_test_db refuses the production path", True)
else:
    check("require_test_db refuses the production path", False)

# ------------------------------------------------------------ H. email
step(8, "Email configuration is fail-closed and reveals no credential values")
saved_mode = config.EMAIL_MODE
config.EMAIL_MODE = "disabled"
try:
    # The fail-closed contract: with delivery impossible, sending must RAISE
    # so the request handler can refuse the request, rather than returning
    # quietly and leaving a student waiting for a code that will never come.
    try:
        emailer.send_verification("p20.cfg.audit@synthetic.invalid", "123456")
    except emailer.EmailUnavailable:
        check("disabled email mode raises instead of silently dropping", True)
    else:
        check("disabled email mode raises instead of silently dropping", False)
    with app.test_request_context("/api/student/verify"):
        try:
            web_student._send_email("p20.cfg.audit@synthetic.invalid", "123456")
        except web_student.sa.StudentError as exc:
            check("the API maps that to a 503 for the client",
                  exc.status == 503 and exc.code == "email_unavailable",
                  "%s %s" % (exc.status, exc.code))
        else:
            check("the API maps that to a 503 for the client", False)
finally:
    config.EMAIL_MODE = saved_mode

config.EMAIL_MODE = "smtp"


def problems_under(**overrides):
    """smtp_problems() evaluated against a modified config, fully restored."""
    saved = {name: getattr(config, name) for name in overrides}
    saved_mode = config.EMAIL_MODE
    config.EMAIL_MODE = "smtp"
    try:
        for name, value in overrides.items():
            setattr(config, name, value)
        return emailer.smtp_problems()
    finally:
        config.EMAIL_MODE = saved_mode
        for name, value in saved.items():
            setattr(config, name, value)


base = problems_under(SMTP_HOST="", SMTP_PORT=0, SMTP_TLS="bogus",
                      SMTP_TIMEOUT=0, SMTP_USER="", SMTP_PASSWORD="",
                      MAIL_FROM="")
check("smtp config reports missing host as a problem",
      any("LGU_SMTP_HOST" in p for p in base), str(base))
check("smtp config validates the port range",
      any("LGU_SMTP_PORT" in p for p in base), str(base))
check("smtp config validates the TLS mode against an allowlist",
      any("LGU_SMTP_TLS" in p for p in base), str(base))
check("smtp config bounds the connection timeout",
      any("LGU_SMTP_TIMEOUT" in p for p in base), str(base))
check("smtp config requires a sender address",
      any("LGU_MAIL_FROM" in p for p in base), str(base))
check("smtp problems describe every gap, not just the first",
      len(base) >= 5, str(base))

check("a user without a password is rejected",
      any("LGU_SMTP_PASSWORD is empty" in p
          for p in problems_under(SMTP_HOST="h", SMTP_USER="u",
                                  SMTP_PASSWORD="", MAIL_FROM="f@x")),
      "no pairing problem reported")
check("a password without a user is rejected",
      any("LGU_SMTP_USER is empty" in p
          for p in problems_under(SMTP_HOST="h", SMTP_USER="",
                                  SMTP_PASSWORD="p", MAIL_FROM="f@x")),
      "no pairing problem reported")
check("a fully valid smtp configuration reports no problem",
      problems_under(SMTP_HOST="smtp.example.edu", SMTP_PORT=587,
                     SMTP_TLS="starttls", SMTP_TIMEOUT=10,
                     SMTP_USER="u", SMTP_PASSWORD="p",
                     MAIL_FROM="noreply@example.edu") == [])
leaky = problems_under(SMTP_HOST="h", SMTP_USER="", MAIL_FROM="f@x",
                       SMTP_PASSWORD="pw-should-not-appear")
check("no problem string ever echoes a credential value",
      all("pw-should-not-appear" not in p for p in leaky), str(leaky))
check("no problem string contains a stack frame or path",
      not any(os.path.sep in p or "line " in p for p in base), str(base))

# The operator tool must describe a credential without ever printing it.
os.environ["LGU_SMTP_PASSWORD"] = "super-secret-smtp-value-20"
for k in ("LGU_SMTP_HOST", "LGU_SMTP_USER", "LGU_MAIL_FROM"):
    os.environ.pop(k, None)
os.environ["LGU_EMAIL_MODE"] = "disabled"
r = subprocess.run([PY, os.path.join("scripts", "check_email_config.py"), "check"],
                   capture_output=True, text=True, cwd=os.path.dirname(APP_DIR))
check("config check exits 0 for the disabled mode", r.returncode == 0,
      r.stdout + r.stderr)
check("config check never prints the password value",
      "super-secret-smtp-value-20" not in r.stdout, r.stdout)
check("config check reports presence, not value",
      re.search(r"LGU_SMTP_PASSWORD[ .]*\.*\s*set \(\d+ chars\)", r.stdout)
      is not None, r.stdout)
check("config check output leaks no other secret",
      not any(s in r.stdout for s in LEAKS), r.stdout)
os.environ.pop("LGU_SMTP_PASSWORD", None)

# ------------------------------------------------------------ I. scanner
step(9, "Scanner session expiry, revocation and server-side gate enforcement")
token, expires = scanner_auth.create_session(sid)
hdrs = {"X-Scanner-Token": token}
r = client.post("/api/scan", json={"qr_id": "LGU1:NOPE", "gate_id": 1,
                                   "mode": "entry", "volunteer": "spoof"},
                headers=hdrs)
check("an authenticated scanner can call the scan endpoint",
      r.status_code in (200, 400, 404), str(r.status_code))
check("client-supplied volunteer name is ignored",
      "spoof" not in r.get_data(as_text=True) or r.status_code == 200,
      r.get_data(as_text=True)[:160])
r = client.post("/api/scan", json={"qr_id": "LGU1:NOPE", "gate_id": 2,
                                   "mode": "entry"}, headers=hdrs)
check("a gate outside the scanner's authorization is refused",
      r.status_code in (401, 403), str(r.status_code))
scanner_auth.revoke_sessions(sid, actor="p20", via=scanner_auth.VIA_CLI)
r = client.post("/api/scan", json={"qr_id": "LGU1:NOPE", "gate_id": 1,
                                   "mode": "entry"}, headers=hdrs)
check("a revoked session is refused on the very next request",
      r.status_code == 401, str(r.status_code))

# ------------------------------------------------------------ J. leaks
step(10, "No response body exposes a credential, hash or secret")
login()
bodies = []
for path in ("/dashboard", "/exam/dashboard", "/exam/scanners",
             "/exam/scanners/new", "/api/health", "/api/gates", "/api/config"):
    r = client.get(path)
    bodies.append((path, r.status_code, r.get_data(as_text=True)))
for path, code, text in bodies:
    check("%s: no credential leak" % path,
          not any(s in text for s in LEAKS), text[:160])
    check("%s: does not expose stack traces" % path,
          "Traceback (most recent call last)" not in text)

# ------------------------------------------------------------ K. limits
step(11, "Upload and payload limits are configured and positive")
check("student photo cap is positive", config.PHOTO_MAX_BYTES > 0)
check("medalist photo cap is positive", config.MEDALIST_PHOTO_MAX_BYTES > 0)
check("student photo cap is a sane 2 MiB",
      config.PHOTO_MAX_BYTES == 2 * 1024 * 1024, str(config.PHOTO_MAX_BYTES))
check("photo directory lives outside static/",
      not config.STUDENT_PHOTO_DIR.replace("\\", "/").endswith("/static"),
      config.STUDENT_PHOTO_DIR)
check("medalist photo directory lives outside static/",
      not config.MEDALIST_PHOTO_DIR.replace("\\", "/").endswith("/static"),
      config.MEDALIST_PHOTO_DIR)

# ------------------------------------------------------------ L. tunables
step(12, "Tunables degrade to a safe default, never to 'unlimited'")
for raw in ("0", "-3", "not-a-number", ""):
    os.environ["LGU_RATE_TEST_ZERO"] = raw
    check("a %r rate limit falls back to the default, never unlimited"
          % (raw or "empty"),
          config.positive_int("LGU_RATE_TEST_ZERO", 5) == 5,
          str(config.positive_int("LGU_RATE_TEST_ZERO", 5)))
os.environ.pop("LGU_RATE_TEST_ZERO", None)
check("scanner session TTL is bounded", config.SCANNER_SESSION_HOURS > 0
      and config.SCANNER_SESSION_HOURS <= 24, str(config.SCANNER_SESSION_HOURS))
check("scanner login lockout threshold is positive",
      config.SCANNER_RATE_MAX_FAILS > 0)

# ------------------------------------------------------------ cleanup
shutil.rmtree(_TMP, ignore_errors=True)
fails = [r for r in RESULTS if not r[1]]
print("\n%d checks, %d failures" % (len(RESULTS), len(fails)))
for name, _, detail in fails:
    print("  FAILED: %s %s" % (name, detail))
sys.exit(1 if fails else 0)
