"""Phase 39 STEP 5 — full application security testing (disposable DB).

Covers the Phase 39 mandate item 5 against a throwaway database:

  01 anonymous authorization matrix (broken auth / IDOR entry points)
  02 admin PIN gates - correct PIN positive controls
  03 admin PIN gates - wrong PIN refusals
  04 input validation and bounds
  05 SQL injection probes (search, guest registration)
  06 stored XSS (announcement + broadcast) and JSON content type
  07 CSRF posture (exam 403, main-blueprint documented gap, cookie backstop)
  08 QR forgery / tamper / replay + print token expiry
  09 guest pass authorization (print token, cross-id, scanner, anonymous)
  10 scanner session lifecycle + scanner login rate limit
  11 admin PIN rate limit -> 429 (JSON + web shared bucket)
  12 secret leakage checks on public payloads
  13 debug/test endpoints vanish when is_production_db() is true
  14 CORS allowlist behaviour on JSON
  15 file upload: binary roster must not 500 (reproduces Q-3 API-level)
  16 production database isolation stamp

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase39_security.py
Exit code 1 if any check fails.
"""

import hashlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p39sec-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "sec.db")
os.environ["LGU_ALLOW_DEMO_SECRETS"] = "1"

import config  # noqa: E402

config.require_test_db()

import database  # noqa: E402
import exam_auth  # noqa: E402
import ids  # noqa: E402
import scanner_auth  # noqa: E402
import web.routes as vr  # noqa: E402
from web.routes import create_app  # noqa: E402

# ------------------------------------------------------------- prod stamp
_PROD = config.PRODUCTION_DB_PATH
_PROD_STAMP = None
_PROD_SHA = None
if os.path.exists(_PROD):
    _s = os.stat(_PROD)
    _PROD_STAMP = (_s.st_size, _s.st_mtime_ns)
    with open(_PROD, "rb") as fh:
        _PROD_SHA = hashlib.sha256(fh.read()).hexdigest()

database.init_db()
database.seed()

OFFICER = "qa-sec-officer"
OFFICER_PW = "QA-sec-Passw0rd-2026!"
SCAN_USER = "qa-sec-gate"
SCAN_PIN = "928374"          # >= 6 chars, never printed
RATE_USER = "qa-sec-rate"
RATE_PIN = "615294"

with database.connection() as db:
    exam_auth.create_staff(OFFICER, "QA Sec Officer", OFFICER_PW)
scanner_auth.create_scanner(username=SCAN_USER, display_name="QA Sec Gate",
                             pin=SCAN_PIN, gate_ids=[1, 2],
                             actor="phase39-fixture")
scanner_auth.create_scanner(username=RATE_USER, display_name="QA Sec Rate",
                             pin=RATE_PIN, gate_ids=[1],
                             actor="phase39-fixture")

app = create_app()
app.config.update(TESTING=True)
client = app.test_client()

RESULTS = []
PIN_MAX = config.PIN_RATE_MAX_FAILS
SCAN_MAX = config.SCANNER_RATE_MAX_FAILS


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    if not cond:
        print("  FAIL %s  %r" % (name, detail))


def step(n, title):
    print("\n[%02d] %s" % (n, title))


def reset_pin():
    with vr._PIN_FAILS_LOCK:
        vr._PIN_FAILS.clear()


def reset_scan_login():
    with vr._SCAN_LOGIN_FAILS_LOCK:
        vr._SCAN_LOGIN_FAILS.clear()


def reset_guest_reg():
    with vr._GUEST_REG_LOCK:
        vr._GUEST_REG_ATTEMPTS.clear()


def txt(r):
    return r.get_data(as_text=True)


def scanner_login(user, pin):
    r = client.post("/api/scanner/login", json={"username": user, "pin": pin})
    return r, (r.get_json() or {}).get("token")


def web_unlock():
    with client.session_transaction() as s:
        s["lgu_admin"] = True


def exam_login():
    r = client.get("/exam/login")
    m = re.search(r'name="csrf_token" value="([^"]+)"', txt(r))
    tok = m.group(1) if m else ""
    r = client.post("/exam/login", data={"username": OFFICER,
                                         "password": OFFICER_PW,
                                         "csrf_token": tok})
    return r.status_code in (200, 302)


def csrf_of(path):
    m = re.search(r'name="csrf_token" value="([^"]+)"', txt(client.get(path)))
    return m.group(1) if m else ""


# =========================================================== 01 anon matrix
step(1, "Anonymous authorization matrix")
anon = [
    ("GET", "/api/settings", None, 401),
    ("PUT", "/api/settings", None, 401),
    ("POST", "/api/broadcasts", None, 401),
    ("POST", "/api/gates/1/rename", None, 401),
    ("GET", "/api/search?q=qa", None, 401),
    ("GET", "/api/guests", None, 401),
    ("POST", "/api/guests/1/revoke", None, 401),
    ("POST", "/api/scan", {}, 401),
    ("POST", "/api/sync", {"items": []}, 401),
    ("GET", "/api/guest-pass/1", None, 401),
    ("GET", "/guests/1/pass", None, 401),
    ("GET", "/guests/directory", None, 401),
    ("GET", "/api/student/me", None, 401),
    ("GET", "/admin", None, 401),
    ("GET", "/exam/", None, 302),
    ("GET", "/exam/medalists/", None, 302),
    ("GET", "/exam/scanners", None, 302),
]
for method, path, body, want in anon:
    reset_pin()  # Individual denial checks must not trigger the shared lockout.
    if method == "GET":
        r = client.get(path)
    elif method == "PUT":
        r = client.put(path, json={"expected_attendance": "10"})
    elif body is None:
        r = client.post(path)
    else:
        r = client.post(path, json=body)
    check("anon %s %s -> %d" % (method, path, want),
          r.status_code == want, "%s vs %r" % (r.status_code, path))
reset_pin()
r = client.put("/api/settings", json={"expected_attendance": "10"})
check("anon PUT settings body never processed", r.status_code == 401,
      r.status_code)
# public reads stay public (kiosk design)
for path in ("/api/config", "/api/health", "/api/dashboard", "/api/gates"):
    check("public %s -> 200" % path, client.get(path).status_code == 200,
          path)

# ================================================== 02 correct PIN controls
step(2, "Admin PIN gates - correct PIN positive controls")
reset_pin()
r = client.get("/api/settings", headers={"X-Admin-Pin": str(config.ADMIN_PIN)})
check("GET /api/settings correct pin -> 200", r.status_code == 200,
      r.status_code)
r = client.put("/api/settings",
               json={"university_name": "QA Security Test University"},
               headers={"X-Admin-Pin": str(config.ADMIN_PIN)})
check("PUT /api/settings correct pin -> 200", r.status_code == 200,
      r.status_code)
r = client.post("/api/broadcasts",
                json={"message": "security pass ping", "sent_by": "qa-sec"},
                headers={"X-Admin-Pin": str(config.ADMIN_PIN)})
check("POST /api/broadcasts correct pin -> 200", r.status_code == 200,
      r.status_code)
r = client.post("/api/gates/1/rename", json={"label": "Gate 1"},
                headers={"X-Admin-Pin": str(config.ADMIN_PIN)})
check("POST rename gate correct pin -> 200", r.status_code == 200,
      r.status_code)

# ================================================== 03 wrong PIN refusals
step(3, "Admin PIN gates - wrong PIN refusals")
reset_pin()
wrong = {"X-Admin-Pin": str(config.ADMIN_PIN) + "x"}
r = client.get("/api/settings", headers=wrong)
check("GET /api/settings wrong pin -> 401", r.status_code == 401,
      r.status_code)
r = client.put("/api/settings", json={"expected_attendance": "7"},
               headers=wrong)
check("PUT /api/settings wrong pin -> 401", r.status_code == 401,
      r.status_code)
r = client.post("/api/broadcasts", json={"message": "nope"}, headers=wrong)
check("POST broadcasts wrong pin -> 401", r.status_code == 401,
      r.status_code)
r = client.post("/api/gates/1/rename", json={"label": "hax"},
                headers=wrong)
check("POST rename wrong pin -> 401", r.status_code == 401,
      r.status_code)
r = client.post("/api/admin/verify", json={"pin": str(config.ADMIN_PIN) + "x"})
check("admin verify wrong pin -> 401", r.status_code == 401, r.status_code)
check("admin verify refusal text",
      "Incorrect PIN" in txt(r), txt(r)[:80])
reset_pin()

# ================================================ 04 input validation
step(4, "Input validation and bounds")
H = {"X-Admin-Pin": str(config.ADMIN_PIN)}
cases = [
    ("unknown settings key", client.put("/api/settings", json={"nope": 1},
                                        headers=H), 400),
    ("bad year", client.put("/api/settings", json={"convocation_year": "20x9"},
                            headers=H), 400),
    ("attendance over cap", client.put("/api/settings",
                                       json={"expected_attendance": "999999"},
                                       headers=H), 400),
    ("bad datetime", client.put("/api/settings",
                                json={"convocation_datetime": "yesterday"},
                                headers=H), 400),
    ("non-text setting", client.put("/api/settings",
                                    json={"university": 42}, headers=H), 400),
    ("rename gid 0", client.post("/api/gates/0/rename",
                                 json={"label": "x"}, headers=H), 404),
    ("rename empty label", client.post("/api/gates/1/rename",
                                       json={"label": "   "}, headers=H), 400),
    ("rename over cap", client.post("/api/gates/1/rename",
                                    json={"label": "L" * 65}, headers=H), 400),
    ("broadcast empty", client.post("/api/broadcasts", json={"message": ""},
                                    headers=H), 400),
    ("broadcast over limit", client.post(
        "/api/broadcasts",
        json={"message": "X" * (config.MESSAGE_CHAR_LIMIT + 1)},
        headers=H), 400),
]
for name, r, want in cases:
    check("%s -> %d" % (name, want), r.status_code == want, r.status_code)
reset_guest_reg()
r = client.post("/api/guests", json={}, headers=H)
check("guest missing fields -> 400", r.status_code == 400, r.status_code)
r = client.post("/api/guests", json={"name": "N" * 500, "phone": "03001234567",
                                     "host_roll_no": "LGU-2024-102"}, headers=H)
check("guest oversized name -> 400", r.status_code == 400, r.status_code)
reset_guest_reg()
_r, tok = scanner_login(SCAN_USER, SCAN_PIN)
check("fixture scanner login -> 200", _r.status_code == 200, _r.status_code)
check("scanner token issued", bool(tok))
SH = {"X-Scanner-Token": tok or ""}
r = client.get("/api/search?q=a", headers=SH)
check("search q<2 -> 400", r.status_code == 400, r.status_code)
r = client.post("/api/sync", json={"items": "nope"}, headers=SH)
check("sync non-list -> 400", r.status_code == 400, r.status_code)
r = client.post("/api/sync", json={"items": [{"payload": "x"}] * 501},
                headers=SH)
check("sync >500 items -> 400", r.status_code == 400, r.status_code)

# ======================================================= 05 SQL injection
step(5, "SQL injection probes")
payloads = ["' OR '1'='1", "' OR 1=1--", "admin'--",
            "%' OR 1=1--", "1; DROP TABLE students;--"]
for p in payloads:
    r = client.get("/api/search?q=%s" % urllib.parse.quote(p), headers=SH)
    body = r.get_json() or {}
    students = body.get("students") if isinstance(body.get("students"), list) \
        else body.get("results", [])
    ok = r.status_code == 200 and len(students or []) <= 25 \
        and "qr_id" not in txt(r)
    check("search %r bounded, no qr_id, no 500" % p[:14], ok,
          "%s %s" % (r.status_code, txt(r)[:100]))
# students table still intact after DROP attempt
r = client.get("/api/search?q=QA", headers=SH)
check("students table intact after SQLi probes", r.status_code == 200)
reset_guest_reg()
for p in ("' OR 1=1--", "%' OR 1=1--"):
    r = client.post("/api/guests", json={"name": "Sneaky", "phone": "03001112223",
                                         "host_roll_no": p, "payment_reference": "SQLI-TEST", "payment_verified": True}, headers=H)
    check("guest host %r rejected as unknown roll" % p[:8],
          r.status_code == 400 and "No student found" in txt(r),
          "%s %s" % (r.status_code, txt(r)[:80]))
reset_guest_reg()

# ============================================================ 06 XSS
step(6, "Stored XSS + JSON content type")
check("exam staff login", exam_login())
r = client.post("/exam/announcements/create",
                data={"title": "<script>window.__x=1</script>",
                      "body": "<img src=x onerror=window.__y=1>",
                      "csrf_token": csrf_of("/exam/announcements")})
check("xss announcement created", r.status_code in (200, 302),
      r.status_code)
m = re.search(r"/exam/announcements/(\d+)", r.headers.get("Location", ""))
detail = txt(client.get("/exam/announcements/%s" % m.group(1))) if m else ""
check("announcement title escaped in HTML",
      "<script>window.__x" not in detail and "&lt;script&gt;" in detail,
      detail[:120])
check("announcement body escaped in HTML",
      "<img" not in detail and "&lt;img" in detail, detail[:120])
web_unlock()
r = client.post("/broadcast",
                data={"audience": "Students",
                      "message": "<script>window.__b=1</script>",
                      "sent_by": "qa-sec"})
check("xss broadcast accepted (documented main-bp gap)", r.status_code == 200,
      r.status_code)
page = txt(client.get("/broadcast"))
check("broadcast message escaped in HTML",
      "<script>window.__b" not in page and "&lt;script&gt;" in page,
      page[:120])
r = client.get("/api/student/announcements")
check("student announcements is application/json",
      (r.headers.get("Content-Type") or "").startswith("application/json"),
      r.headers.get("Content-Type"))

# =========================================================== 07 CSRF
step(7, "CSRF posture")
r = client.post("/exam/event/save", data={"venue": "X"})
check("exam POST without csrf -> 403", r.status_code == 403, r.status_code)
r = client.post("/exam/login", data={"username": OFFICER,
                                     "password": OFFICER_PW})
check("exam login without csrf -> 403", r.status_code == 403, r.status_code)
# Main blueprint has no token layer (documented C-csrf); SameSite=Lax +
# PIN header gates are the backstop. This pins the CURRENT posture.
web_unlock()
r = client.post("/broadcast", data={"audience": "Students",
                                    "message": "csrf posture pin",
                                    "sent_by": "qa-sec"})
check("main-bp POST w/o csrf accepted (documented)",
      r.status_code == 200, r.status_code)
# cookie flags must come from a response that CREATES the session
reset_pin()
fresh = app.test_client()
r = fresh.post("/admin", data={"admin_pin": str(config.ADMIN_PIN),
                              "next_url": "/admin"})
check("fresh unlock -> 200 for cookie inspection", r.status_code == 200,
      r.status_code)
sc = r.headers.get("Set-Cookie", "")
check("session cookie SameSite=Lax", "SameSite=Lax" in sc, sc[:80])
check("session cookie HttpOnly", "HttpOnly" in sc, sc[:80])

# ============================================ 08 QR / print token forgery
step(8, "QR forgery, tamper, replay; print token expiry")
valid_id = ids.generate_id()
ok, got = ids.verify_payload(ids.make_payload(valid_id))
check("valid signed payload verifies", ok is True and got == valid_id,
      "%s %s" % (ok, got))
payload = ids.make_payload(valid_id)
tampered = payload[:-1] + ("0" if payload[-1] != "0" else "1")
ok, _ = ids.verify_payload(tampered)
check("tampered payload rejected", ok is False)
ok, _ = ids.verify_payload("LGU2:1:deadbeef:ffffff")
check("garbage payload rejected", ok is False)
forged = ids.make_payload("ZZZZZZZZ")   # signed but unknown id
r = client.post("/api/scan", json={"payload": forged, "gate_id": 1,
                                   "mode": "entry"}, headers=SH)
body = r.get_json() or {}
check("valid-signed unknown code -> UNKNOWN CODE",
      body.get("title") == "UNKNOWN CODE", body)
r = client.post("/api/scan", json={"payload": tampered, "gate_id": 1,
                                   "mode": "entry"}, headers=SH)
body = r.get_json() or {}
check("tampered code -> INVALID CODE", body.get("title") == "INVALID CODE",
      body)

# live replay: entry once, duplicate refused
r = client.get("/api/demo-payload")
demo = (r.get_json() or {}).get("payload")
r = client.post("/api/scan", json={"payload": demo, "gate_id": 1,
                                   "mode": "entry"}, headers=SH)
body = r.get_json() or {}
check("first entry recorded", body.get("title") == "ENTRY RECORDED", body)
r = client.post("/api/scan", json={"payload": demo, "gate_id": 1,
                                   "mode": "entry"}, headers=SH)
body = r.get_json() or {}
check("replayed entry -> ALREADY INSIDE", body.get("title") == "ALREADY INSIDE",
      body)

# print token: expiry, cross-id, forgery (unit + route level)
reset_guest_reg()
r = client.post("/api/guests", json={"name": "QA Sec Visitor",
                                     "phone": "0300 5556667",
                                     "host_roll_no": "LGU-2024-102", "payment_reference": "SEC-102", "payment_verified": True}, headers=H)
reg = r.get_json() or {}
check("guest fixture registered", r.status_code == 200 and reg.get("gid"),
      "%s %s" % (r.status_code, txt(r)[:80]))
gid_a = reg.get("gid")
reset_guest_reg()
r = client.post("/api/guests", json={"name": "QA Sec Visitor 2",
                                     "phone": "0300 5556668",
                                     "host_roll_no": "LGU-2024-103", "payment_reference": "SEC-103", "payment_verified": True}, headers=H)
reg_b = r.get_json() or {}
gid_b = reg_b.get("gid")
print_tok = reg.get("print_token")
check("print tokens minted", bool(print_tok) and bool(gid_b))
check("expired print token fails verify",
      ids.verify_print_token(ids.make_print_token(gid_a or 1, -5),
                             gid_a or 1) is False)
check("forged print token rejected",
      ids.verify_print_token("%s.9999999999.deadbeef" % gid_a, gid_a) is False)

# =========================================== 09 guest pass authorization
step(9, "Guest pass authorization (print token / cross-id / scanner)")
# fresh client = truly anonymous (main client holds the staff/admin session)
gc = app.test_client()
r = gc.get("/api/guest-pass/%s" % gid_a)
check("anon guest-pass -> 401", r.status_code == 401, r.status_code)
r = gc.get("/api/guest-pass/%s" % gid_a,
           headers={"X-Print-Token": print_tok or ""})
check("own print token -> 200", r.status_code == 200, r.status_code)
r = gc.get("/api/guest-pass/%s" % gid_b,
           headers={"X-Print-Token": print_tok or ""})
check("cross-id print token -> 401", r.status_code == 401, r.status_code)
r = gc.get("/api/guest-pass/%s" % gid_a,
           headers={"X-Print-Token": ids.make_print_token(gid_a or 1, -5)})
check("expired print token route -> 401", r.status_code == 401,
      r.status_code)
r = gc.get("/api/guest-pass/%s" % gid_a, headers=SH)
check("scanner session may read guest pass", r.status_code == 200,
      r.status_code)
r = gc.get("/guests/%s/pass" % gid_a)
check("anon pass page -> 401", r.status_code == 401, r.status_code)
r = gc.get("/guests/%s/pass" % gid_a,
           headers={"X-Print-Token": print_tok or ""})
check("print token pass page -> 200", r.status_code == 200, r.status_code)
# roster projections never leak bearer credentials
r = client.get("/api/guests", headers=SH)
check("guest roster has no qr_id",
      "qr_id" not in txt(r), txt(r)[:120])

# ============================== 10 scanner session lifecycle + rate limit
step(10, "Scanner session lifecycle and login rate limiting")
r = client.post("/api/scanner/logout", headers=SH)
check("logout -> 200", r.status_code == 200, r.status_code)
r = client.post("/api/scan", json={"payload": demo, "gate_id": 1,
                                   "mode": "entry"}, headers=SH)
check("token dead after logout -> 401", r.status_code == 401, r.status_code)
_r, tok2 = scanner_login(SCAN_USER, SCAN_PIN)
check("re-login after logout works", _r.status_code == 200 and tok2,
      _r.status_code)
SH = {"X-Scanner-Token": tok2 or ""}
# unauthorized gate still refused for this scanner (gates 1,2 only)
r = client.post("/api/scan", json={"payload": demo, "gate_id": 3,
                                   "mode": "entry"}, headers=SH)
body = r.get_json() or {}
check("gate 3 -> 403 GATE NOT AUTHORIZED",
      r.status_code == 403 and body.get("title") == "GATE NOT AUTHORIZED",
      "%s %s" % (r.status_code, body))
reset_scan_login()
for i in range(SCAN_MAX):
    r = client.post("/api/scanner/login",
                    json={"username": RATE_USER, "pin": RATE_PIN + "x"})
    check("scanner wrong pin %d -> 401" % (i + 1), r.status_code == 401,
          r.status_code)
r = client.post("/api/scanner/login",
                json={"username": RATE_USER, "pin": RATE_PIN + "x"})
check("scanner login %d fails -> 429" % (SCAN_MAX + 1),
      r.status_code == 429, r.status_code)
reset_scan_login()

# ============================================ 11 admin PIN rate limiting
step(11, "Admin PIN rate limit -> 429 (JSON and web share one bucket)")
reset_pin()
for i in range(PIN_MAX):
    r = client.post("/api/admin/verify",
                    json={"pin": str(config.ADMIN_PIN) + "x"})
    check("verify wrong pin %d -> 401" % (i + 1), r.status_code == 401,
          r.status_code)
r = client.post("/api/admin/verify", json={"pin": str(config.ADMIN_PIN) + "x"})
check("verify %d fails -> 429" % (PIN_MAX + 1), r.status_code == 429,
      r.status_code)
r = client.post("/api/admin/verify", json={"pin": str(config.ADMIN_PIN)})
check("correct pin also 429 while limited (gate first)",
      r.status_code == 429, r.status_code)
r = client.get("/api/settings", headers=H)
check("settings GET inherits 429 from shared bucket",
      r.status_code == 429, r.status_code)
reset_pin()
wc = app.test_client()          # fresh session: no lgu_admin yet
for i in range(PIN_MAX):
    r = wc.post("/admin", data={"admin_pin": str(config.ADMIN_PIN) + "x",
                                "next_url": "/admin"})
    check("web unlock wrong pin %d -> 401" % (i + 1), r.status_code == 401,
          r.status_code)
r = wc.post("/admin", data={"admin_pin": str(config.ADMIN_PIN) + "x",
                            "next_url": "/admin"})
check("web unlock %d fails -> 429" % (PIN_MAX + 1), r.status_code == 429,
      r.status_code)
reset_pin()
check("web unlock recovers after reset",
      wc.post("/admin", data={"admin_pin": str(config.ADMIN_PIN),
                              "next_url": "/admin"}).status_code == 200)

# ================================================== 12 secret leakage
step(12, "Secret leakage checks on public payloads")
needles = []
# Short PINs (default 4 digits) collide with years/counts in public bodies,
# so the substring scan only runs on LONG secrets (the HMAC key); short
# credentials are covered by the key-name regex below.
for n in (str(config.ADMIN_PIN),):
    if len(n) >= 5:
        needles.append(n)
try:
    h = config.HMAC_SECRET.decode("ascii")
except (UnicodeDecodeError, AttributeError):
    h = config.HMAC_SECRET.hex()
if len(h) >= 5:
    needles.append(h)
print("  (substring scan: %d long secret(s))" % len(needles))
for path in ("/api/config", "/api/health", "/api/dashboard", "/",
             "/api/student/event", "/api/student/announcements"):
    body = txt(client.get(path))
    leaked = [n for n in needles if n and n in body]
    check("no raw secret in %s" % path, not leaked,
          "needle found" if leaked else "")
    check("no secret keys in %s" % path,
          not re.search(r'(?i)"(admin_pin|hmac_secret|secret_key|password"'
                        r'|pin_hash|token_hash)', body), path)
r = txt(client.get("/api/config"))
check("config payload has no session/token fields",
      "session" not in r.lower() and "bearer" not in r.lower(), r[:120])

# ================================== 13 debug endpoints vs production DB
step(13, "Test/debug endpoints vanish on a production database")
orig = config.is_production_db
config.is_production_db = lambda: True      # simulate prod DB selection
try:
    r = client.post("/api/test-scanner-session", json={"gate_ids": [1]})
    check("test-scanner-session -> 404 on prod", r.status_code == 404,
          r.status_code)
    r = client.get("/api/demo-payload")
    check("demo-payload -> 404 on prod", r.status_code == 404,
          r.status_code)
    r = client.post("/api/test-reset", json={})
    check("test-reset -> 404 on prod", r.status_code == 404, r.status_code)
finally:
    config.is_production_db = orig
r = client.post("/api/test-scanner-session", json={"gate_ids": [1]})
check("test-scanner-session works again on test DB",
      r.status_code == 200, r.status_code)
r = client.post("/api/test-reset", json={},
                headers={"X-Admin-Pin": str(config.ADMIN_PIN)})
check("test-reset works again on test DB", r.status_code == 200,
      r.status_code)

# ============================================================ 14 CORS
step(14, "CORS allowlist on JSON")
r = client.get("/api/health", headers={"Origin": "https://evil.example"})
check("foreign origin gets no ACAO grant",
      not r.headers.get("Access-Control-Allow-Origin"),
      r.headers.get("Access-Control-Allow-Origin"))
r = client.get("/api/health", headers={"Origin": "http://localhost"})
check("loopback origin allowed (dev contract)",
      r.headers.get("Access-Control-Allow-Origin") == "http://localhost",
      r.headers.get("Access-Control-Allow-Origin"))
r = client.get("/api/health",
               headers={"Origin": "https://localhost.evil.example"})
check("suffix-spoofed origin refused",
      not r.headers.get("Access-Control-Allow-Origin"),
      r.headers.get("Access-Control-Allow-Origin"))

# ============================================ 15 file upload (Q-3 repro)
step(15, "File upload: binary roster must not crash (Q-3)")
web_unlock()
try:
    r = client.post("/admin", data={
        "action": "upload_roster",
        "roster": (io.BytesIO(b"\x00\x01\xff\xfe\x8f binary \x00 not csv"),
                   "roster.csv")},
        content_type="multipart/form-data")
    up_status, up_body = r.status_code, txt(r)
except Exception as exc:   # noqa: BLE001 - TESTING=True re-raises (Q-3 repro)
    up_status, up_body = 500, repr(exc)
check("binary roster not HTTP 500", up_status in (200, 400),
      "HTTP %s (Q-3 repro)" % up_status)
check("binary roster gives friendly message",
      "could not be read" in up_body or "CSV" in up_body,
      up_body[:100])

# ================================================= 16 prod DB isolation
step(16, "Production database isolation")
if _PROD_STAMP is None:
    check("production database remains absent", not os.path.exists(_PROD))
else:
    _s = os.stat(_PROD)
    check("prod size + mtime unchanged",
          (_s.st_size, _s.st_mtime_ns) == _PROD_STAMP)
    with open(_PROD, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    check("prod sha256 unchanged", digest == _PROD_SHA, digest)

# ================================================================== done
failed = [n for n, ok in RESULTS if not ok]
print("\n%d checks, %d failures" % (len(RESULTS), len(failed)))
for n in failed:
    print("  FAILED: %s" % n)
sys.exit(1 if failed else 0)
