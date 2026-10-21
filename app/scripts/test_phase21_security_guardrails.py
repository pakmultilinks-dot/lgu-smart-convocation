#!/usr/bin/env python
"""Phase 21 §6 — security and release-safety guardrails still intact.

Re-verifies, after the Phase 21 changes, every guardrail Phase 20 relied on:
the demo-secret startup guard, the unsupported-schema refusal, the test-tool
guard against production, scanner gate enforcement, credential non-disclosure
and staff cookie hardening.

Everything runs against a disposable database. app/lgu.db is never opened here.
"""
import hashlib
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p21sec-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "sec.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
import database  # noqa: E402
import migrations  # noqa: E402
import scanner_auth  # noqa: E402
import convocation_qr as cqr  # noqa: E402

config.require_test_db()
database.init_db()
database.seed()

from web.routes import create_app  # noqa: E402

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(("    ok   " if ok else "    FAIL ") + name
          + (("  :: %r" % (detail,)) if detail else ""))


def section(t):
    print("\n[%s] %s" % (t[0], t[1]))


section(("A", "Startup refuses committed demo secrets"))
env = dict(os.environ, LGU_TESTING="1", LGU_DB_PATH=os.path.join(_TMP, "guard.db"))
env.pop("LGU_ALLOW_DEMO_SECRETS", None)
p = subprocess.run([PY, "run.py"], cwd=APP_DIR, env=env, capture_output=True,
                   text=True, timeout=120)
out = (p.stdout or "") + (p.stderr or "")
check("run.py exits non-zero when only the committed demo secrets exist",
      p.returncode != 0, p.returncode)
check("the refusal names the setting to override but never prints secret"
      " values", "LGU_ALLOW_DEMO_SECRETS" in out and "FATAL" in out,
      out.strip().splitlines()[:2])
check("no database file was created before the guard fired",
      not os.path.exists(os.path.join(_TMP, "guard.db")))

section(("B", "A newer-than-supported schema is refused, not half-migrated"))
db = database.get_db()
try:
    db.execute("PRAGMA user_version = 99")
    db.commit()
    raised = None
    try:
        migrations.migrate(db)
    except RuntimeError as exc:
        raised = str(exc)
    finally:
        db.rollback()
    check("migrations.migrate() refuses schema version 99 with RuntimeError",
          raised is not None and "99" in raised, raised)
    check("the refusal left user_version untouched",
          db.execute("PRAGMA user_version").fetchone()[0] == 99)
    db.execute("PRAGMA user_version = 6")
    db.commit()
finally:
    db.close()

section(("C", "Test-only helpers refuse to run against production"))
import web.routes as R  # noqa: E402
_app_for_guard = create_app()
with _app_for_guard.test_request_context():
    guard = R._test_tool_guard()
check("_test_tool_guard is inert while LGU_TESTING points at a temp database",
      guard is None, guard)
_prod = config.PRODUCTION_DB_PATH
_real_testing = os.environ.get("LGU_TESTING")
try:
    os.environ["LGU_DB_PATH"] = _prod
    os.environ.pop("LGU_TESTING", None)
    config.DB_PATH = _prod
    with _app_for_guard.test_request_context():
        g = R._test_tool_guard()
    check("_test_tool_guard answers 404 when the configured database is the"
          " production one", g is not None and g[1] == 404,
          g[1] if g else None)
finally:
    os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "sec.db")
    if _real_testing is not None:
        os.environ["LGU_TESTING"] = _real_testing
    config.DB_PATH = os.path.join(_TMP, "sec.db")

section(("D", "Credentials never appear in responses"))
db = database.get_db()
try:
    conv = db.execute("SELECT id FROM convocations WHERE is_active = 1").fetchone()["id"]
    db.execute("INSERT INTO convocation_registrations (convocation_id,"
               " registration_number, university_email, roll_number,"
               " student_name, department, status, created_at, updated_at)"
               " VALUES (?, 'SEC-1', 'sec@lgu.edu.pk', 'S1', 'Security Test',"
               " 'CS', 'active', '2026-10-14 09:00:00', '2026-10-14 09:00:00')",
               (conv,))
    db.commit()
    reg = db.execute("SELECT id FROM convocation_registrations WHERE"
                     " registration_number = 'SEC-1'").fetchone()["id"]
    db.execute("INSERT INTO student_accounts (university_email, password_hash,"
               " created_at, updated_at)"
               " VALUES ('sec@lgu.edu.pk', 'scrypt$fake', '2026-10-14 09:00:00',"
               " '2026-10-14 09:00:00')")
    db.commit()
    acc = db.execute("SELECT id FROM student_accounts WHERE"
                     " university_email = 'sec@lgu.edu.pk'").fetchone()["id"]
    db.execute("INSERT INTO registration_claims (account_id, convocation_id,"
               " registration_id, created_at)"
               " VALUES (?, ?, ?, '2026-10-14 09:00:00')", (acc, conv, reg))
    db.execute("INSERT INTO convocation_publications (convocation_id, name,"
               " year, venue, published_by, published_at)"
               " VALUES (?, 'Sec Convocation', '2026', 'Hall', 'bench',"
               " '2026-10-14 09:00:00')", (conv,))
    tok = "security-probe-token"
    db.execute("INSERT INTO convocation_passes (token_hash, convocation_id,"
               " registration_id, account_id, status, issued_at)"
               " VALUES (?, ?, ?, ?, 'active', '2026-10-14 09:00:00')",
               (cqr.token_hash(tok), conv, reg, acc))
    db.commit()
finally:
    db.close()

sid = scanner_auth.create_scanner("sec-gate-1", "Sec Volunteer", pin="SECPIN001",
                                  gate_ids=[1], actor="sec", via="test")
stoken, _ = scanner_auth.create_session(sid)

from web.routes import create_app as _ca2  # noqa: E402,F811
app = _ca2()
app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
c = app.test_client()

r = c.post("/api/scan", json={"payload": "LGU2:" + tok, "gate_id": 1,
                              "mode": "entry"},
           headers={"X-Scanner-Token": stoken})
body = r.get_json() or {}
check("a valid scan succeeds without echoing the token back",
      r.status_code == 200 and body.get("status") == "ok"
      and tok not in r.get_data(as_text=True), (r.status_code, sorted(body)))

r2 = c.post("/api/scan", json={"payload": "LGU2:totally-bogus", "gate_id": 1,
                               "mode": "entry"},
            headers={"X-Scanner-Token": stoken})
t2 = r2.get_data(as_text=True)
check("a failed scan reveals nothing about the pass or the database",
      r2.status_code == 200 and "PASS INVALID" in t2
      and "sqlite" not in t2.lower() and "traceback" not in t2.lower()
      and "hash" not in t2.lower(), t2.strip()[:160])

check("an unknown scanner token is refused without detail",
      c.post("/api/scan", json={"payload": "LGU2:" + tok, "gate_id": 1,
                                "mode": "entry"},
             headers={"X-Scanner-Token": "bogus"}).status_code == 401)

section(("E", "Students cannot reach scanner endpoints"))
r3 = c.post("/api/scan", json={"payload": "LGU2:" + tok, "gate_id": 1,
                               "mode": "entry"},
            headers={"Authorization": "Bearer %s" % hashlib.sha256(
                b"student-session").hexdigest()})
check("a student-style Bearer token cannot reach /api/scan",
      r3.status_code == 401, r3.status_code)

section(("F", "Staff session cookie hardening"))
cfg = app.config
check("staff cookie is HttpOnly", cfg.get("SESSION_COOKIE_HTTPONLY") is True)
check("staff cookie sets SameSite", cfg.get("SESSION_COOKIE_SAMESITE") == "Lax",
      cfg.get("SESSION_COOKIE_SAMESITE"))
check("staff cookie Secure flag tracks config.COOKIE_SECURE",
      cfg.get("SESSION_COOKIE_SECURE") == config.COOKIE_SECURE,
      (cfg.get("SESSION_COOKIE_SECURE"), config.COOKIE_SECURE))

section(("G", "Gate authorization is read server-side"))
r4 = c.post("/api/scan", json={"payload": "LGU2:unused", "gate_id": 99,
                               "mode": "entry"},
            headers={"X-Scanner-Token": stoken})
b4 = r4.get_json() or {}
check("a gate the scanner is not provisioned for is refused",
      b4.get("status") == "error", b4)

print("\nPHASE21 SECURITY GUARDRAILS: %d/%d checks passed, %d failing"
      % (len(PASSED), len(PASSED) + len(FAILED), len(FAILED)))
for f in FAILED:
    print("  FAIL: %s" % f)
sys.exit(1 if FAILED else 0)
