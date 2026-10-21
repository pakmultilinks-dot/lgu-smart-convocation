"""Phase 37 BE-002 — demo-secret validation at every application entry point.

Phase 36 audit BE-002: the fail-closed demo-secret guard existed only in
run.py (and only for "no opt-in"); create_app() — the way any WSGI server
or script constructs the app — had no check, and neither entry point
refused the committed defaults against the PRODUCTION database.

Contract pinned here:
  1. run.py, demo secrets, no opt-in  -> exit 1 FATAL (names only, no
     values), no database file created (guard precedes init_db)
  2. run.py + LGU_ALLOW_DEMO_SECRETS=1 -> boots, prints the demo warning
  3. run.py + operator secrets        -> boots silently, demo_secrets()==[]
  4. run.py + demo secrets + PRODUCTION database + opt-in
                                       -> exit 1 FATAL BEFORE init_db
     (tested by rebinding config paths to a disposable fake — the real
     app\\lgu.db is never opened by this suite)
  5. create_app() factory:
       demo + no testing + no opt-in  -> RuntimeError (FATAL message)
       demo + LGU_TESTING=1           -> allowed  (35 existing test
                                         scripts depend on this)
       demo + explicit opt-in         -> allowed
       demo + production DB           -> RuntimeError EVEN with testing
                                         or opt-in
       operator secrets               -> allowed everywhere
  6. every refusal message names settings only — never values

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase37_startup_secrets.py
"""

import os
import secrets
import subprocess
import sys
import tempfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

_TMP = tempfile.mkdtemp(prefix="lgu-p37secrets-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "proc.db")
os.environ.pop("LGU_ALLOW_DEMO_SECRETS", None)

import config  # noqa: E402

config.require_test_db()

from web.routes import create_app  # noqa: E402

_PROD = config.PRODUCTION_DB_PATH
_PROD_STAMP = None
if os.path.exists(_PROD):
    _s = os.stat(_PROD)
    _PROD_STAMP = (_s.st_size, _s.st_mtime_ns)

_SECRET_NAMES = ("LGU_SECRET_KEY", "LGU_HMAC_SECRET", "LGU_ADMIN_PIN")
_DEFAULTS = [config._DEMO_SECRETS[n][0] for n in _SECRET_NAMES]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    if not cond:
        print("  FAIL %s  %r" % (name, detail))


def step(n, title):
    print("\n[%02d] %s" % (n, title))


def no_values(text):
    """Refusal output must never carry a committed secret VALUE."""
    return all(v not in text for v in _DEFAULTS)


def run_py(code, env_over=None):
    env = dict(os.environ)
    for k, v in (env_over or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return subprocess.run([sys.executable, "-c", code], cwd=APP, env=env,
                          capture_output=True, text=True, timeout=90)


# ---------------------------------------------------------------- 1
step(1, "run.py refuses demo secrets without opt-in (Phase 20 contract)")
db1 = os.path.join(_TMP, "refusal.db")
r = run_py("import run", {"LGU_DB_PATH": db1})
err = r.stderr or ""
check("exit code 1", r.returncode == 1, r.returncode)
check("stderr starts FATAL", "FATAL" in err, err[:300])
check("names the offending settings",
      "LGU_SECRET_KEY" in err and "LGU_ADMIN_PIN" in err, err[:300])
check("teaches the opt-in escape hatch", "LGU_ALLOW_DEMO_SECRETS=1" in err,
      err[:300])
check("refusal text is values-free", no_values(err), err[:300])
check("no database file created before the guard fired",
      not os.path.exists(db1), "refusal.db exists")

# ---------------------------------------------------------------- 2
step(2, "run.py boots with explicit development opt-in + warning")
r = run_py("import run; print('BOOT-OK')",
           {"LGU_ALLOW_DEMO_SECRETS": "1"})
out = r.stdout or ""
check("exit 0 and BOOT-OK", r.returncode == 0 and "BOOT-OK" in out,
      (r.returncode, out[-200:]))
check("prints the demo-secrets warning", "demo secrets" in out, out[-300:])
check("warning carries names only", no_values(out), out[-300:])

# ---------------------------------------------------------------- 3
step(3, "run.py boots silently with operator-supplied secrets")
r = run_py(
    "import run, config; print('CLEAN' if config.demo_secrets() == []"
    " else 'DIRTY'); print('BOOT-OK')",
    {"LGU_SECRET_KEY": secrets.token_urlsafe(32),
     "LGU_HMAC_SECRET": secrets.token_urlsafe(32),
     "LGU_ADMIN_PIN": "937741"})
out = r.stdout or ""
check("exit 0 and BOOT-OK", r.returncode == 0 and "BOOT-OK" in out,
      (r.returncode, out[-200:]))
check("demo_secrets() reports clean", "CLEAN" in out and "DIRTY" not in out,
      out[-300:])
check("no demo warning printed", "demo secrets" not in out, out[-300:])

# ---------------------------------------------------------------- 4
step(4, "run.py refuses demo secrets against a PRODUCTION database "
         "(even with opt-in) — before init_db")
fake_prod = os.path.join(_TMP, "fake-prod.db")
r = run_py(
    "import os, tempfile\n"
    "os.environ['LGU_ALLOW_DEMO_SECRETS'] = '1'\n"
    "import config\n"
    "fake = r'%s'\n"
    "config.PRODUCTION_DB_PATH = fake\n"
    "config.DB_PATH = fake\n"
    "import run\n" % fake_prod.replace("\\", "\\\\"),
    {"LGU_TESTING": None})          # exercise the demo guard, not require_test_db
err = r.stderr or ""
check("exit code 1", r.returncode == 1, (r.returncode, err[:300]))
check("production-specific refusal text",
      "refusing to run committed demo secrets against the production"
      " database" in err, err[:400])
check("names the offending settings",
      "LGU_SECRET_KEY" in err and "LGU_ADMIN_PIN" in err, err[:400])
check("teaches the non-production DB fix", "LGU_DB_PATH" in err, err[:400])
check("refusal text is values-free", no_values(err), err[:400])
check("guard fired BEFORE init_db (fake production file never created)",
      not os.path.exists(fake_prod), "fake-prod.db exists")

# ---------------------------------------------------------------- 5
step(5, "create_app() refuses demo secrets with no testing flag and no opt-in")
os.environ.pop("LGU_TESTING", None)
os.environ.pop("LGU_ALLOW_DEMO_SECRETS", None)
try:
    create_app()
    check("factory raises", False, "create_app() returned normally")
except RuntimeError as exc:
    m = str(exc)
    check("raises RuntimeError prefixed FATAL", m.startswith("FATAL: "), m[:80])
    check("names the offending settings",
          "LGU_SECRET_KEY" in m and "LGU_ADMIN_PIN" in m, m[:400])
    check("teaches the opt-in escape hatch", "LGU_ALLOW_DEMO_SECRETS=1" in m,
          m[:400])
    check("refusal text is values-free", no_values(m), m[:400])
finally:
    os.environ["LGU_TESTING"] = "1"

# ---------------------------------------------------------------- 6
step(6, "create_app() keeps existing workflows: testing flag / dev opt-in")
os.environ["LGU_TESTING"] = "1"
try:
    app1 = create_app()
    check("LGU_TESTING=1 + disposable DB allowed (test scripts)",
          app1 is not None)
finally:
    pass
os.environ.pop("LGU_TESTING", None)
os.environ["LGU_ALLOW_DEMO_SECRETS"] = "1"
try:
    app2 = create_app()
    check("explicit LGU_ALLOW_DEMO_SECRETS=1 allowed (dev workflows)",
          app2 is not None)
finally:
    os.environ.pop("LGU_ALLOW_DEMO_SECRETS", None)
    os.environ["LGU_TESTING"] = "1"

# ---------------------------------------------------------------- 7
step(7, "create_app() refuses demo secrets on a production DB — even with "
         "testing and opt-in")
_saved_prod, _saved_db = config.PRODUCTION_DB_PATH, config.DB_PATH
fake2 = os.path.join(_TMP, "fake-prod2.db")
config.PRODUCTION_DB_PATH = fake2
config.DB_PATH = fake2
try:
    for label, extra in (("LGU_TESTING=1", {}),
                         ("opt-in", {"LGU_ALLOW_DEMO_SECRETS": "1"})):
        os.environ.pop("LGU_ALLOW_DEMO_SECRETS", None)
        os.environ.update(extra)
        try:
            create_app()
            check("refused with %s" % label, False, "factory returned")
        except RuntimeError as exc:
            m = str(exc)
            check("refused with %s" % label,
                  "production database" in m and no_values(m), m[:300])
        finally:
            os.environ.pop("LGU_ALLOW_DEMO_SECRETS", None)
    check("fake production file never created (no DB work in factory)",
          not os.path.exists(fake2))
finally:
    config.PRODUCTION_DB_PATH, config.DB_PATH = _saved_prod, _saved_db

# ---------------------------------------------------------------- 8
step(8, "operator secrets: policy function reports no violation anywhere")
_orig = {n: config._DEMO_SECRETS[n] for n in _SECRET_NAMES}
try:
    for n in _SECRET_NAMES:
        config._DEMO_SECRETS[n] = (_orig[n][0], "p37-" + n.lower() + "-live",
                                   str)
    check("demo_secrets() empty with operator values",
          config.demo_secrets() == [], config.demo_secrets())
    check("violation(None) with operator values",
          config.demo_secret_violation() is None
          and config.demo_secret_violation(startup=True) is None)
finally:
    for n in _SECRET_NAMES:
        config._DEMO_SECRETS[n] = _orig[n]

# ---------------------------------------------------------------- 9
step(9, "policy matrix: startup vs factory semantics on a disposable DB")
check("factory permits demo + testing", config.demo_secret_violation() is None)
check("startup refuses demo + testing WITHOUT opt-in (run.py contract)",
      isinstance(config.demo_secret_violation(startup=True), str))
os.environ["LGU_ALLOW_DEMO_SECRETS"] = "1"
try:
    check("both modes permit demo + opt-in",
          config.demo_secret_violation() is None
          and config.demo_secret_violation(startup=True) is None)
finally:
    os.environ.pop("LGU_ALLOW_DEMO_SECRETS", None)
check("startup refuses demo without opt-in on a disposable DB",
      isinstance(config.demo_secret_violation(startup=True), str)
      and config.demo_secret_violation() is None)

# ---------------------------------------------------------- integrity
step(10, "Isolation: production database untouched")
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
