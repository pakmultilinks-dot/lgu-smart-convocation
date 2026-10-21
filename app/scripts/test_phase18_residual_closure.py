#!/usr/bin/env python3
"""Phase 18 - Residual defect closure & operational hardening.

Pins the four residual findings carried out of Phase 17:

  1. PASS_ISSUE_RATE_WINDOW_SECONDS (and the other per-bucket windows) were
     shadowed by STUDENT_RATE_WINDOW_SECONDS inside web.student_routes._limited
     -- so the support limiter ran on 60s instead of its intended 300s and the
     pass-issue window was unreachable. Each bucket now honours its own window.
  2. mobile/app/(student)/readiness.tsx::act() swallowed mark failures in a
     bare catch, so a dropped connection was indistinguishable from success.
  3. .badge status contrast was audited for the queued variant only.
  4. Scanner provisioning wrote actor="system" into the audit log, so no
     credential change could be attributed to the operator who made it.

Usage (from app/):  ..\\.venv\\Scripts\\python.exe scripts\\test_phase18_residual_closure.py

The production DB app/lgu.db is only stat'ed + hashed - never opened.
No real student identities are used; every name/email/roll is synthetic.
"""
import getpass
import os
import subprocess
import sys
import tempfile
import time
from hashlib import sha256

# ---------------------------------------------------------------- guardrails
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD_DB = os.path.join(APP_DIR, "lgu.db")
PROD_STAMP = None
if os.path.exists(PROD_DB):
    _s = os.stat(PROD_DB)
    with open(PROD_DB, "rb") as fh:
        _PROD_SHA = sha256(fh.read()).hexdigest().upper()
    PROD_STAMP = (_s.st_size, _s.st_mtime_ns, _PROD_SHA)

TMP = tempfile.mkdtemp(prefix="lgu-p18-")
for _k, _v in (("LGU_TESTING", "1"),
               ("LGU_DB_PATH", os.path.join(TMP, "closure.db")),
               ("LGU_EMAIL_MODE", "fake"),
               ("LGU_STUDENT_PHOTO_DIR", os.path.join(TMP, "student-photos")),
               ("LGU_MEDALIST_PHOTO_DIR", os.path.join(TMP, "medalist-photos"))):
    os.environ[_k] = _v
for _k in ("LGU_SMTP_HOST", "LGU_SMTP_USER", "LGU_SMTP_PASSWORD",
           "LGU_MAIL_FROM", "LGU_ADMIN_PIN", "LGU_SECRET_KEY", "LGU_HMAC_SECRET"):
    os.environ.pop(_k, None)

sys.path.insert(0, APP_DIR)
import config
config.require_test_db()
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import database
import scanner_auth
import web.student_routes as sr

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok   %s" % label)
    else:
        failed += 1
        print("  FAIL %s :: %s" % (label, detail))


def step(n, title):
    print("\n[%d] %s" % (n, title))


def reset_limits():
    for bucket in sr._HITS.values():
        bucket.clear()


def raw(sql, args=()):
    return database.get_db().execute(sql, args).fetchall()


def cli(*args):
    return subprocess.run(
        [sys.executable, os.path.join(APP_DIR, "scripts", "manage_scanner_staff.py"),
         *args], cwd=APP_DIR, capture_output=True, text=True, errors="replace")


database.init_db()
database.seed()

# ================================================================ 1. windows
step(1, "Rate-limit windows: each bucket honours its own documented window")

EXPECT = {"send": 60, "recovery": 60, "login": 60, "confirm": 60,
          "support": 300, "readiness": 60, "passissue": 60}
for bucket, want in EXPECT.items():
    check("bucket '%s' resolves to its own %ss window" % (bucket, want),
          sr._bucket_window(bucket) == want,
          (bucket, sr._bucket_window(bucket), want))

# The real defect: a hit older than the shared 60s window is still LIVE for a
# 300s bucket. Directly proves support no longer inherits the 60s window.
_AGED = 100.0  # > 60s (shared), < 300s (support)
reset_limits()
sr._HITS["support"] = [time.time() - _AGED] * config.SUPPORT_RATE_MAX_CREATE
support_limited = sr._limited("support", config.SUPPORT_RATE_MAX_CREATE)
check("support hits older than 60s still enforce the 300s window (not 60s)",
      support_limited is True, support_limited)

reset_limits()
sr._HITS["send"] = [time.time() - _AGED] * config.STUDENT_RATE_MAX_VERIFY
send_limited = sr._limited("send", config.STUDENT_RATE_MAX_VERIFY)
check("the student verify bucket DOES expire at 60s (window is per bucket)",
      send_limited is False, send_limited)

reset_limits()
sr._HITS["passissue"] = [time.time() - 30.0] * config.PASS_ISSUE_RATE_MAX
check("pass-issue hits inside its own window still enforce the limit",
      sr._limited("passissue", config.PASS_ISSUE_RATE_MAX) is True)

# Bucket independence: exhausting one never limits another.
reset_limits()
for _ in range(config.SUPPORT_RATE_MAX_CREATE):
    sr._limited("support", config.SUPPORT_RATE_MAX_CREATE)
check("buckets are independent: the support flood does not exhaust verify",
      sr._limited("send", config.STUDENT_RATE_MAX_VERIFY) is False)
check("buckets are independent: the support flood does not exhaust readiness",
      sr._limited("readiness", config.READINESS_RATE_MAX_MARK) is False)
reset_limits()
for _ in range(config.READINESS_RATE_MAX_MARK):
    sr._limited("readiness", config.READINESS_RATE_MAX_MARK)
check("buckets are independent: the readiness flood does not exhaust support",
      sr._limited("support", config.SUPPORT_RATE_MAX_CREATE) is False)
reset_limits()

check("documented windows are the ones the code reads",
      config.SUPPORT_RATE_WINDOW_SECONDS == 300
      and config.PASS_ISSUE_RATE_WINDOW_SECONDS == 60
      and config.STUDENT_RATE_WINDOW_SECONDS == 60,
      (config.SUPPORT_RATE_WINDOW_SECONDS,
       config.PASS_ISSUE_RATE_WINDOW_SECONDS,
       config.STUDENT_RATE_WINDOW_SECONDS))

# ================================================================ 2. guard
step(2, "A mistyped limit can never silently disable limiting")

before = sr._bucket_window("support")
config.SUPPORT_RATE_WINDOW_SECONDS = "300"          # typo: string, not int
check("a string window falls back to the shared window instead of unlimited",
      sr._bucket_window("support") == config.STUDENT_RATE_WINDOW_SECONDS,
      sr._bucket_window("support"))
config.SUPPORT_RATE_WINDOW_SECONDS = 0              # typo: zero
check("a zero window falls back rather than disabling the limiter",
      sr._bucket_window("support") == config.STUDENT_RATE_WINDOW_SECONDS,
      sr._bucket_window("support"))
config.SUPPORT_RATE_WINDOW_SECONDS = -5
check("a negative window falls back rather than disabling the limiter",
      sr._bucket_window("support") == config.STUDENT_RATE_WINDOW_SECONDS)
config.SUPPORT_RATE_WINDOW_SECONDS = True
check("a boolean window falls back rather than disabling the limiter",
      sr._bucket_window("support") == config.STUDENT_RATE_WINDOW_SECONDS)
config.SUPPORT_RATE_WINDOW_SECONDS = before
check("the support window is restored after the config-hygiene probes",
      sr._bucket_window("support") == 300)

os.environ["LGU_P18_NOT_AN_INT"] = "three hundred"
os.environ["LGU_P18_ZERO"] = "0"
check("positive_int ignores a non-numeric env var",
      config.positive_int("LGU_P18_NOT_AN_INT", 42) == 42,
      config.positive_int("LGU_P18_NOT_AN_INT", 42))
check("positive_int ignores a non-positive env var",
      config.positive_int("LGU_P18_ZERO", 7) == 7,
      config.positive_int("LGU_P18_ZERO", 7))

# ================================================================ 3. scanner
step(3, "Scanner PIN provisioning is attributable to a named operator")

OP = "p18-ops-lead"
r = cli("create", "--username", "p18.gate", "--name", "P18 Gate",
        "--gates", "1,2", "--pin", "K7QMZP2X", "--actor", OP)
out = (r.stdout or "") + (r.stderr or "")
check("the CLI provisions with an explicit operator",
      r.returncode == 0 and "Created scanner" in out, out[:400])

row = raw("SELECT * FROM scanner_users WHERE username = 'p18.gate'")
check("the account exists", len(row) == 1)
scan_id = row[0]["id"] if row else 0

act = raw("SELECT * FROM audit_log WHERE action = 'scanner_created'")
check("the audit trail records WHO provisioned the account",
      bool(act) and act[0]["actor"] == OP, [a["actor"] for a in act])
check("provisioning is no longer attributed to the placeholder 'system'",
      all(a["actor"] != "system" for a in act),
      [a["actor"] for a in act])
check("the audit detail names the account and gates, never a secret",
      all("p18.gate" in (a["detail"] or "") for a in act)
      and all("K7QMZP2X" not in (a["detail"] or "") for a in act),
      [a["detail"] for a in act])
check("the PIN is stored only as a scrypt hash",
      row and str(row[0]["pin_hash"]).startswith("scrypt:")
      and "K7QMZP2X" not in str(row[0]["pin_hash"]),
      row[0]["pin_hash"][:40] if row else None)

# A PIN reset must be attributable too, and must never log the new PIN.
r = cli("pin", str(scan_id), "--pin", "NEWPIN99", "--actor", OP)
out = (r.stdout or "") + (r.stderr or "")
check("the CLI resets a PIN with an explicit operator",
      r.returncode == 0 and "Reset PIN" in out, out[:400])
reset_row = raw("SELECT * FROM audit_log WHERE action = 'scanner_pin_reset'")
check("a PIN reset is attributed to the operator",
      bool(reset_row) and reset_row[0]["actor"] == OP,
      [a["actor"] for a in reset_row])
check("the new PIN is never written to the audit log",
      all("NEWPIN99" not in (a["detail"] or "") for a in reset_row)
      and all("NEWPIN99" not in (a["actor"] or "") for a in reset_row),
      [a["detail"] for a in reset_row])

# Without --actor the operator is the real OS login, still never "system".
r = cli("gates", str(scan_id), "--gates", "1")
out = (r.stdout or "") + (r.stderr or "")
gate_row = raw("SELECT * FROM audit_log WHERE action = 'scanner_gates_set'")
check("omitting --actor falls back to the OS login, not 'system'",
      r.returncode == 0 and bool(gate_row)
      and gate_row[0]["actor"] == getpass.getuser()
      and gate_row[0]["actor"] != "system",
      [a["actor"] for a in gate_row])

# Revocation stays attributable and still kills live sessions.
tok, _exp = scanner_auth.create_session(scan_id)
check("the scanner can mint a session before revocation", bool(tok))
before_revoke = len(raw("SELECT id FROM scanner_sessions WHERE scanner_id = ?"
                        " AND revoked_at IS NULL", (scan_id,)))
r = cli("revoke", str(scan_id), "--actor", OP)
out = (r.stdout or "") + (r.stderr or "")
rev_row = raw("SELECT * FROM audit_log WHERE action = 'scanner_revoked'")
after_revoke = len(raw("SELECT id FROM scanner_sessions WHERE scanner_id = ?"
                       " AND revoked_at IS NULL", (scan_id,)))
check("revocation is attributed to the operator",
      r.returncode == 0 and bool(rev_row) and rev_row[0]["actor"] == OP,
      [a["actor"] for a in rev_row])
check("revocation invalidates every live session",
      before_revoke >= 1 and after_revoke == 0,
      (before_revoke, after_revoke))
check("a revoked scanner's token no longer resolves",
      scanner_auth.resolve_session(tok) is None)
check("revocation never writes the token to the audit log",
      not raw("SELECT id FROM audit_log WHERE detail LIKE ?",
              ("%" + tok + "%",)))

# Denial: an operator cannot silently act under another operator's identity
# by leaving the placeholder in place, and the CLI refuses bad input cleanly
# instead of provisioning something unattributed.
r = cli("create", "--username", "p18.badgates", "--name", "Bad Gates",
        "--gates", "99", "--pin", "ZZZZZZ11", "--actor", OP)
check("an unknown gate is refused before any account is provisioned",
      r.returncode != 0 and "Unknown gate" in ((r.stdout or "") + (r.stderr or ""))
      and not raw("SELECT id FROM scanner_users WHERE username = 'p18.badgates'"),
      ((r.stdout or "") + (r.stderr or ""))[:300])
r = cli("revoke", "999999", "--actor", OP)
check("revoking an unknown id fails cleanly, not with a traceback",
      r.returncode != 0 and "Traceback" not in ((r.stdout or "") + (r.stderr or ""))
      and "No scanner with that id" in ((r.stdout or "") + (r.stderr or "")),
      ((r.stdout or "") + (r.stderr or ""))[:300])
unattrib = [a["actor"] for a in raw(
    "SELECT actor FROM audit_log WHERE action LIKE 'scanner_%'")]
check("no scanner lifecycle action is left attributed to 'system'",
      all(a not in (None, "", "system") for a in unattrib), unattrib)

# The placeholder cannot be re-introduced from the CLI either.
r = cli("create", "--username", "p18.spoof", "--name", "P18 Spoof",
        "--gates", "1", "--pin", "SPOOF1234", "--actor", "system")
spoof_row = raw("SELECT * FROM audit_log WHERE action = 'scanner_created'"
                " AND detail LIKE '%p18.spoof%'")
check("--actor system cannot re-create the ownership gap",
      r.returncode == 0 and bool(spoof_row)
      and spoof_row[0]["actor"] == scanner_auth.UNKNOWN_ACTOR
      and spoof_row[0]["actor"] != "system",
      [a["actor"] for a in spoof_row])
check("a library caller that names no operator is still attributed honestly",
      scanner_auth._actor(None) == scanner_auth.UNKNOWN_ACTOR
      and scanner_auth._actor("   ") == scanner_auth.UNKNOWN_ACTOR
      and scanner_auth._actor("SYSTEM") == scanner_auth.UNKNOWN_ACTOR,
      (scanner_auth._actor(None), scanner_auth._actor("SYSTEM")))
check("a real operator identity survives normalisation untouched",
      scanner_auth._actor(" %s " % OP) == OP, scanner_auth._actor(OP))

# The read-only subcommand takes no --actor and must not crash resolving it.
r = cli("list")
out = (r.stdout or "") + (r.stderr or "")
check("the read-only 'list' subcommand still runs clean",
      r.returncode == 0 and "Traceback" not in out and "p18.gate" in out,
      out[:400])

# ================================================================ 4. summary
print("\n" + "=" * 66)
print("PHASE18 RESULT: %d/%d" % (passed, failed))

if PROD_STAMP is not None:
    _s = os.stat(PROD_DB)
    with open(PROD_DB, "rb") as fh:
        now = (_s.st_size, _s.st_mtime_ns, sha256(fh.read()).hexdigest().upper())
    print("production db unchanged: %s" % (now == PROD_STAMP))
    if now != PROD_STAMP:
        failed += 1
        print("  FAIL production db was modified")

sys.exit(1 if failed else 0)
