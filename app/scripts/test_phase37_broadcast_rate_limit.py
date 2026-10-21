"""Phase 37 BE-001 — admin PIN rate limiting on POST /api/broadcasts.

The Phase 36 audit confirmed this handler inlined the PIN comparison and
never consulted _pin_rate_limited(), so a 4-digit ADMIN_PIN could be
guessed without bound while every other admin mutation returned 429 after
config.PIN_RATE_MAX_FAILS wrong attempts per client IP.

This suite pins the remediation contract:
  A. missing / wrong PIN        -> 401 with the exact legacy denial text
  B. MAX wrong attempts         -> 429 lockout (bounded guessing)
  C. lockout applies uniformly  -> even the CORRECT PIN is refused until
                                   the window clears (shared per-IP bucket)
  D. broadcast failures feed    -> the same limiter as /api/settings
     the centralized bucket
  E. authorized broadcast       -> 200, persisted to the broadcast log
  F. message validation         -> 400 paths unchanged
  G. constant-time comparison   -> _pin_ok semantics (SEC-002)

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase37_broadcast_rate_limit.py
Isolated: LGU_TESTING=1 + disposable LGU_DB_PATH; prod app\\lgu.db is
stat-stamped before/after and must not change.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p37bcast-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "bcast.db")

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

database.init_db()
database.seed()

app = create_app()
app.config.update(TESTING=True)
client = app.test_client()

RESULTS = []
PIN_TEXT = "Administrator access required to send announcements."
MAX = config.PIN_RATE_MAX_FAILS
CORRECT = str(config.ADMIN_PIN)
WRONG = "p37-wrong-" + CORRECT          # never equal to the PIN; never printed


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    if not cond:
        print("  FAIL %s  %r" % (name, detail))


def step(n, title):
    print("\n[%02d] %s" % (n, title))


def reset_limiter():
    with vr._PIN_FAILS_LOCK:
        vr._PIN_FAILS.clear()


def post(pin=None, message="Phase 37 broadcast rate-limit probe"):
    headers = {"X-Admin-Pin": pin} if pin is not None else {}
    return client.post("/api/broadcasts",
                       json={"message": message,
                             "audience": "All students",
                             "sent_by": "P37"},
                       headers=headers)


# ------------------------------------------------ A. authentication paths
step(1, "Authentication: missing and wrong PIN are 401 with pinned text")
reset_limiter()
r = post(pin=None)
check("no PIN header -> 401", r.status_code == 401, r.status_code)
check("401 body carries the exact legacy denial text",
      (r.get_json() or {}).get("error") == PIN_TEXT, r.get_json())
reset_limiter()
r = post(pin=WRONG)
check("wrong PIN -> 401", r.status_code == 401, r.status_code)
check("wrong PIN records exactly one limiter failure",
      sum(len(v) for v in vr._PIN_FAILS.values()) == 1,
      sum(len(v) for v in vr._PIN_FAILS.values()))

# ----------------------------------------------------- B. lockout (429)
step(2, "Lockout: %d wrong attempts exhaust the window -> 429" % MAX)
reset_limiter()
codes = [post(pin=WRONG).status_code for _ in range(MAX)]
check("first %d wrong attempts stay 401 (bounded bucket fills)" % MAX,
      codes == [401] * MAX, codes)
r = post(pin=WRONG)
check("attempt %d -> 429 rate limited" % (MAX + 1), r.status_code == 429,
      r.status_code)
check("429 names the retry window",
      "Too many attempts" in (r.get_json() or {}).get("error", ""),
      r.get_json())

# ------------------------------------ C. lockout is uniform (no bypass)
step(3, "Lockout blocks the CORRECT PIN too (no guessing vs. use window)")
r = post(pin=CORRECT)
check("correct PIN during lockout -> 429 (limiter precedes comparison)",
      r.status_code == 429, r.status_code)

# ------------------------------ D. failures feed the shared PIN bucket
step(4, "Broadcast failures share the centralized limiter with /api/settings")
reset_limiter()
for _ in range(MAX):
    post(pin=WRONG)
r = client.get("/api/settings",
               headers={"X-Admin-Pin": CORRECT})
check("after %d broadcast failures, /api/settings also 429" % MAX,
      r.status_code == 429, r.status_code)
reset_limiter()
r = client.get("/api/settings", headers={"X-Admin-Pin": CORRECT})
check("bucket cleared -> /api/settings serves the correct PIN again",
      r.status_code == 200, r.status_code)

# -------------------------------------- E. authorized broadcast works
step(5, "Authorized broadcast: correct PIN -> 200 and lands in the log")
reset_limiter()
msg = "Phase 37 remediation verification announcement"
r = post(pin=CORRECT, message=msg)
body = r.get_json() or {}
check("correct PIN -> 200 ok", r.status_code == 200 and body.get("ok") is True,
      (r.status_code, body))
check("server never claims delivery it did not perform",
      "note" in body, body)
r = client.get("/api/broadcasts")
log = (r.get_json() or {}).get("log") or []
check("broadcast persisted to the log readable by GET /api/broadcasts",
      any(row.get("message") == msg for row in log),
      [row.get("message") for row in log][:3])

# ------------------------------------------- F. validation paths intact
step(6, "Message validation (400 paths) unchanged after refactor")
reset_limiter()
r = post(pin=CORRECT, message="   ")
check("blank message -> 400", r.status_code == 400, r.status_code)
r = post(pin=CORRECT, message="x" * (config.MESSAGE_CHAR_LIMIT + 1))
check("over-limit message -> 400", r.status_code == 400, r.status_code)
r = post(pin=CORRECT, message="ok")
check("still 200 after the 400s (no limiter pollution)",
      r.status_code == 200, r.status_code)

# ------------------------------------- G. constant-time PIN comparison
step(7, "SEC-002: _pin_ok is a total, strip-tolerant equality")
check("_pin_ok(correct)", vr._pin_ok(CORRECT) is True)
check("_pin_ok(padded correct) keeps strip semantics",
      vr._pin_ok("  " + CORRECT + " ") is True)
check("_pin_ok(wrong) rejects", vr._pin_ok(WRONG) is False)
check("_pin_ok(None/empty) reject", vr._pin_ok(None) is False
      and vr._pin_ok("") is False)

# ----------------------------------------------------------- integrity
step(8, "Isolation: production database untouched")
reset_limiter()
if _PROD_STAMP is None:
    check("production database remains absent", not os.path.exists(_PROD))
else:
    _s = os.stat(_PROD)
    check("prod app/lgu.db size+mtime unchanged",
          (_s.st_size, _s.st_mtime_ns) == _PROD_STAMP,
          (_s.st_size, _s.st_mtime_ns))

failed = [n for n, ok in RESULTS if not ok]
print("\n%d checks, %d failures" % (len(RESULTS), len(failed)))
sys.exit(1 if failed else 0)
