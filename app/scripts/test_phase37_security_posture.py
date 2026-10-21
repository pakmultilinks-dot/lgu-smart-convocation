"""Phase 37 STEP 5 — production security posture regression.

Locks the safe corrections and the verified posture from the Phase 36
audit without breaking any existing client:

  A. SEC-002 — no raw ADMIN_PIN comparisons survive in routes.py; every
     gate routes through the constant-time _pin_ok (source-level pin, so
     the plaintext `==` form can never quietly return).
  B. Web-admin form gate: bounded attempts (429), then unlock works.
  C. /api/admin/verify JSON gate: same bounds.
  D. One shared per-IP bucket spans the JSON and form gates.
  E. Session cookie flags: HttpOnly + SameSite=Lax always; Secure tracks
     LGU_COOKIE_SECURE (plain-HTTP LAN default documented, TLS opt-in).
  F. CORS: allowlist echo only (no wildcard), X-Admin-Pin allowed for the
     admin client, foreign origins get NO grant.
  G. Baseline hardening headers on responses.
  H. Scanner authorization boundary: /api/scan refuses unauthenticated
     callers.
  I. Production database untouched (stat + sha256).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase37_security_posture.py
"""

import hashlib
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p37sec-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "sec.db")
os.environ.pop("LGU_ALLOW_DEMO_SECRETS", None)

import config  # noqa: E402

config.require_test_db()

import database  # noqa: E402
import web.routes as vr  # noqa: E402
from web.routes import create_app  # noqa: E402

_PROD = config.PRODUCTION_DB_PATH
_PROD_STAMP = None
if os.path.exists(_PROD):
    _s = os.stat(_PROD)
    _PROD_STAMP = (_s.st_size, _s.st_mtime_ns)
    _sha = hashlib.sha256(open(_PROD, "rb").read()).hexdigest()

database.init_db()
database.seed()

app = create_app()
app.config.update(TESTING=True)
client = app.test_client()

RESULTS = []
MAX = config.PIN_RATE_MAX_FAILS
CORRECT = str(config.ADMIN_PIN)
WRONG = "p37sec-wrong-" + CORRECT


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    if not cond:
        print("  FAIL %s  %r" % (name, detail))


def step(n, title):
    print("\n[%02d] %s" % (n, title))


def reset_limiter():
    with vr._PIN_FAILS_LOCK:
        vr._PIN_FAILS.clear()


# --------------------------------------------------------- A. SEC-002 pin
step(1, "SEC-002: constant-time gate is the ONLY PIN comparison")
src_path = os.path.join(os.path.dirname(vr.__file__), "routes.py")
src = open(src_path, encoding="utf-8").read()
check("routes.py imports hmac", bool(re.search(r"^import hmac$", src, re.M)))
check("_pin_ok uses hmac.compare_digest",
      "hmac.compare_digest" in src)
raw = re.findall(r"\w+\s*(?:==|!=)\s*config\.ADMIN_PIN|"
                 r"config\.ADMIN_PIN\s*(?:==|!=)", src)
check("no raw ==/!= ADMIN_PIN comparisons remain in routes.py",
      len(raw) == 0, raw)
check("all mutation gates call the centralized helper",
      src.count("_require_admin_pin(") >= 5,
      src.count("_require_admin_pin("))

# ------------------------------------------------- B. web admin form gate
step(2, "Browser admin form: anonymous -> unlock, bounded wrong attempts")
reset_limiter()
r = client.get("/admin")
check("anonymous GET /admin -> 401 unlock page", r.status_code == 401,
      r.status_code)
codes = [client.post("/admin", data={"admin_pin": WRONG}).status_code
         for _ in range(MAX)]
check("first %d wrong form PINs stay 401" % MAX, codes == [401] * MAX, codes)
r = client.post("/admin", data={"admin_pin": WRONG})
check("form attempt %d -> 429" % (MAX + 1), r.status_code == 429,
      r.status_code)

reset_limiter()
r = client.post("/admin", data={"admin_pin": CORRECT},
                follow_redirects=False)
check("correct form PIN unlocks (200/302)",
      r.status_code in (200, 302), r.status_code)
set_cookie = r.headers.get("Set-Cookie", "")
check("session cookie issued on unlock", "session=" in set_cookie,
      set_cookie[:120])
r2 = client.get("/admin")
check("authenticated GET /admin succeeds", r2.status_code == 200,
      r2.status_code)

# ------------------------------------------------------- C. JSON verify
step(3, "POST /api/admin/verify: bounded wrong attempts, then success")
reset_limiter()
codes = [client.post("/api/admin/verify", json={"pin": WRONG}).status_code
         for _ in range(MAX)]
check("first %d wrong PINs stay 401" % MAX, codes == [401] * MAX, codes)
r = client.post("/api/admin/verify", json={"pin": WRONG})
check("verify attempt %d -> 429" % (MAX + 1), r.status_code == 429,
      r.status_code)
check("429 carries the shared retry message",
      "Too many attempts" in (r.get_json() or {}).get("error", ""),
      r.get_json())
reset_limiter()
r = client.post("/api/admin/verify", json={"pin": CORRECT})
check("correct PIN after window reset -> 200 ok:true",
      r.status_code == 200 and (r.get_json() or {}).get("ok") is True,
      (r.status_code, r.get_json()))

# ------------------------------------------------- D. one shared bucket
step(4, "JSON gate failures throttle the form gate (single per-IP bucket)")
reset_limiter()
for _ in range(MAX):
    client.post("/api/admin/verify", json={"pin": WRONG})
fresh = app.test_client()          # no admin session — gate must engage
r = fresh.post("/admin", data={"admin_pin": CORRECT})
check("form gate also 429 after JSON-gate failures", r.status_code == 429,
      r.status_code)
reset_limiter()

# ----------------------------------------------------------- E. cookies
step(5, "Session cookie hardening tracks the documented posture")
fresh2 = app.test_client()         # clean session: unlock actually issues it
r = fresh2.post("/admin", data={"admin_pin": CORRECT})
sc = r.headers.get("Set-Cookie", "")
check("HttpOnly always", "HttpOnly" in sc, sc[:160])
check("SameSite=Lax always", "SameSite=Lax" in sc, sc[:160])
check("Secure flag == LGU_COOKIE_SECURE (default off for plain-HTTP LAN)",
      ("Secure" in sc) == bool(config.COOKIE_SECURE),
      (config.COOKIE_SECURE, sc[:160]))

# ------------------------------------------------------------ F. CORS
step(6, "CORS allowlist: echo only, admin header allowed, no wildcard")
r = client.options("/api/broadcasts",
                   headers={"Origin": "http://127.0.0.1:19006",
                            "Access-Control-Request-Method": "POST",
                            "Access-Control-Request-Headers":
                                "content-type,x-admin-pin"})
acao = r.headers.get("Access-Control-Allow-Origin", "")
allow = r.headers.get("Access-Control-Allow-Headers", "")
check("loopback dev origin echoed (not * )",
      acao == "http://127.0.0.1:19006" and acao != "*", acao)
check("X-Admin-Pin allowed for the admin client",
      "X-Admin-Pin" in allow, allow)
check("Vary: Origin set", "Origin" in r.headers.get("Vary", ""),
      r.headers.get("Vary"))
r = client.get("/api/health",
               headers={"Origin": "https://evil.example"})
check("foreign origin receives NO CORS grant",
      "Access-Control-Allow-Origin" not in r.headers,
      r.headers.get("Access-Control-Allow-Origin"))

# ------------------------------------------------- G. hardening headers
step(7, "Baseline hardening headers present")
r = client.get("/api/health")
check("X-Content-Type-Options: nosniff",
      r.headers.get("X-Content-Type-Options") == "nosniff",
      r.headers.get("X-Content-Type-Options"))
check("X-Frame-Options: SAMEORIGIN",
      r.headers.get("X-Frame-Options") == "SAMEORIGIN",
      r.headers.get("X-Frame-Options"))
check("Referrer-Policy: no-referrer",
      r.headers.get("Referrer-Policy") == "no-referrer",
      r.headers.get("Referrer-Policy"))

# --------------------------------------------- H. scanner auth boundary
step(8, "Scanner boundary: /api/scan refuses unauthenticated callers")
reset_limiter()
r = client.post("/api/scan", json={"code": "LG1TEST", "gate": "G1"})
check("no scanner token -> 401", r.status_code == 401, r.status_code)
body = r.get_json() or {}
check("refusal reveals nothing about the pass or database",
      "qr" not in str(body).lower() and "hash" not in str(body).lower(),
      body)

# ---------------------------------------------------------- I. isolation
step(9, "Isolation: production database untouched")
if _PROD_STAMP is None:
    check("production database remains absent", not os.path.exists(_PROD))
else:
    _s = os.stat(_PROD)
    check("prod size + mtime unchanged",
          (_s.st_size, _s.st_mtime_ns) == _PROD_STAMP)
    with open(_PROD, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    check("prod sha256 unchanged", digest == _sha, digest)

failed = [n for n, ok in RESULTS if not ok]
print("\n%d checks, %d failures" % (len(RESULTS), len(failed)))
sys.exit(1 if failed else 0)
