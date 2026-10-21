#!/usr/bin/env python
"""Phase 28 — remaining authorization closure.

Closes the endpoint-authorization findings carried out of the Phase 27
report, starting with the one the directive prioritised.

  1. GET /api/settings was UNGATED — the read half of an administrator-
     editable resource answered anonymous callers. Reproduced before the
     fix against a disposable database: HTTP 200 carrying all six keys.
     The fix gates the READ with the same `_require_admin_pin()` as the
     write. Being exact about what that does and does not buy: nothing in
     the old payload was UNIQUELY secret — name, year, datetime, venue,
     university and the attendance target are all already published at
     GET /api/config, which stays public for the kiosk, the landing page
     and mobile connectivity discovery. The defect was structural:
     `PUT /api/settings` accepts any key in `database.SETTING_KEYS` while
     `GET /api/settings` served all of them, so an operational key added
     later would have been public the moment it was written. Gating the
     read makes "protected" the default for a key nobody has classified
     yet, and puts the two halves of one resource under one policy.

  2-4 are mobile source contracts, pinned in
     mobile/scripts/phase28-authorization-source-test.mjs (HomeScreen
     confirmation, the venue "Not announced" placeholder, and the
     ClassifiedScan.action review — see that file for why item 4 is a
     reported NO-CHANGE rather than an edit).

Nothing here weakens Phase 27: the guest directory, the guest-pass print
capability and the public self-registration shell are re-probed at the end,
so a regression in either phase fails this suite.

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase28_authorization_closure.py
"""

import os
import re
import shutil
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

PROD_DB = os.path.join(APP_DIR, "lgu.db")
if os.path.exists(PROD_DB):
    _ps = os.stat(PROD_DB)
    PROD_STAMP = (_ps.st_size, _ps.st_mtime_ns)
else:
    PROD_STAMP = None

_TMP = tempfile.mkdtemp(prefix="lgu-p28-authz-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "p28.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import scanner_auth  # noqa: E402
import web.routes as vr  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def step(n, title):
    print("\n== CASE %s: %s" % (n, title))


def fresh():
    return app.test_client()


def raw(sql, args=()):
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


database.init_db()
database.seed()
app = create_app()
app.config.update(TESTING=True)

anon = fresh()
PIN = config.ADMIN_PIN

# A real, signed-in scanner — an AUTHENTICATED and privileged role that is
# still not an administrator. This is the wrong-role probe that matters: a
# 401 for a token nobody holds would prove nothing.
_sid = scanner_auth.create_scanner("p28.reader", "P28 Reader", "55914027",
                                   [1, 2, 3, 4, 5, 6, 7], actor="p28-test")
_token, _ = scanner_auth.create_session(_sid)
SCANNER = {"X-Scanner-Token": _token}

staff = fresh()
with staff.session_transaction() as sess:
    sess["lgu_admin"] = True

print("Phase 28 authorization closure (isolated temp DB, production untouched)")

# Guest registration is one guest per student: pick a host the seed leaves
# free rather than assuming a roll number.
FREE = [r["roll_no"] for r in raw(
    "SELECT s.roll_no FROM students s"
    " WHERE NOT EXISTS (SELECT 1 FROM guests g WHERE g.host_roll_no = s.roll_no)"
    " ORDER BY s.roll_no LIMIT 1")]
check("the seed leaves a host roll free for the guest-registration probe",
      len(FREE) == 1, FREE)

# ---------------------------------------------------------------------------
step(1, "GET /api/settings is an administrator action, not a public one")
vr._PIN_FAILS.clear()
r = anon.get("/api/settings")
check("anonymous GET /api/settings is refused 401",
      r.status_code == 401, r.status_code)
body = r.get_json(silent=True) or {}
check("the refusal carries no settings payload",
      not any(k in body for k in database.SETTING_KEYS), body)
check("the refusal is the standard administrator gate contract",
      body.get("error") == "Administrator access required." and
      body.get("ok") is False, body)

wrong = fresh().get("/api/settings", headers={"X-Admin-Pin": "----wrong----"})
check("a wrong PIN is refused 401", wrong.status_code == 401,
      wrong.status_code)
vr._PIN_FAILS.clear()

# Wrong-role probes: other AUTHENTICATED principals must not read it either.
for label, headers in (
        ("a signed-in scanner", SCANNER),
        ("a bearer-style credential", {"Authorization": "Bearer p28.forged"}),
        ("a web staff session", None)):
    c = staff if label == "a web staff session" else anon
    got = c.get("/api/settings", headers=headers or {})
    check("%s cannot read the administrator settings" % label,
          got.status_code == 401, "%s -> %d" % (label, got.status_code))
vr._PIN_FAILS.clear()

ok = fresh().get("/api/settings", headers={"X-Admin-Pin": PIN})
settings = ok.get_json(silent=True) or {}
check("the administrator PIN reads the settings", ok.status_code == 200,
      ok.status_code)
check("the settings read returns EXACTLY the configured keys — nothing extra",
      set(settings) == set(database.SETTING_KEYS),
      sorted(set(settings) ^ set(database.SETTING_KEYS)))
check("the read exposes no secret, PIN or credential field",
      not any(re.search(r"(pin|secret|token|password|hash|salt|key)",
                        k, re.I) for k in settings), sorted(settings))

# ---------------------------------------------------------------------------
step(2, "The write half of the resource is unchanged")
vr._PIN_FAILS.clear()
check("anonymous PUT /api/settings is still refused 401",
      anon.put("/api/settings", json={"venue": "X"}).status_code == 401)
check("a wrong-PIN PUT is still refused 401",
      fresh().put("/api/settings", json={"venue": "X"},
                  headers={"X-Admin-Pin": "----wrong----"}).status_code == 401)
vr._PIN_FAILS.clear()
w = fresh().put("/api/settings", json={"venue": "Phase 28 Hall"},
                headers={"X-Admin-Pin": PIN})
check("the administrator PIN still writes", w.status_code == 200,
      w.status_code)
check("the write is visible to the next authorized read",
      (fresh().get("/api/settings",
                   headers={"X-Admin-Pin": PIN}).get_json() or {}
       ).get("venue") == "Phase 28 Hall")

# ---------------------------------------------------------------------------
step(3, "The settings read inherits the write's rate limit")
vr._PIN_FAILS.clear()
c = fresh()
statuses = [c.get("/api/settings",
                  headers={"X-Admin-Pin": "----wrong----"}).status_code
            for _ in range(config.PIN_RATE_MAX_FAILS + 2)]
check("repeated wrong-PIN reads are throttled 429",
      statuses[-1] == 429, statuses)
vr._PIN_FAILS.clear()

# ---------------------------------------------------------------------------
step(4, "Genuinely public configuration stays public — no workflow broken")
vr._PIN_FAILS.clear()
cfg = anon.get("/api/config")
payload = cfg.get_json(silent=True) or {}
event = payload.get("event") or {}
check("anonymous GET /api/config is still public",
      cfg.status_code == 200, cfg.status_code)
check("the public event identity it carries is intact",
      bool(event.get("name")) and bool(event.get("year")) and
      bool(event.get("datetime")) and bool(event.get("venue")), event)
check("the public config is the SAME data the settings gate protects",
      event.get("venue") and payload.get("university"), payload.get("university"))
check("anonymous GET /api/health is still public",
      anon.get("/api/health").status_code == 200)

# ---------------------------------------------------------------------------
step(5, "Phase 27 guest contracts still hold after this phase")
vr._PIN_FAILS.clear()
shell = anon.get("/guests")
check("the public guest registration shell still renders (no credential)",
      shell.status_code == 200, shell.status_code)
reg = anon.post("/api/guests", json={"name": "P28 Guest",
                                     "phone": "03001112223",
                                     "host_roll_no": FREE[0]})
check("anonymous guest self-registration still works",
      reg.status_code == 200, (reg.status_code, reg.get_json()))
reg_body = reg.get_json(silent=True) or {}
check("the registrant still receives their own print capability",
      bool(reg_body.get("payload")) and bool(reg_body.get("print_token")),
      sorted(reg_body))
gid = reg_body.get("gid")
check("the registration resolved to a real guest id",
      isinstance(gid, int) and gid > 0, gid)
check("anonymous GET /guests/directory is still refused 401",
      anon.get("/guests/directory").status_code == 401)
check("anonymous GET /api/guests is still refused 401",
      anon.get("/api/guests").status_code == 401)
gp = anon.get("/api/guest-pass/%d" % gid)
check("an enumerable gid still cannot mint a guest pass",
      gp.status_code == 401, gp.status_code)
check("that refusal still leaks no signed payload",
      "payload" not in (gp.get_json(silent=True) or {}),
      gp.get_json(silent=True))
gp_page = anon.get("/guests/%d/pass" % gid)
check("the HTML guest-pass route still refuses an anonymous caller",
      gp_page.status_code == 401, gp_page.status_code)
kiosk = anon.get("/api/guests", headers=SCANNER)
check("a signed-in scanner still reads the guest directory",
      kiosk.status_code == 200, kiosk.status_code)
gp_ok = anon.get("/api/guest-pass/%d" % gid, headers=SCANNER)
check("a signed-in scanner still reads a guest pass",
      gp_ok.status_code == 200, gp_ok.status_code)
staff_dir = staff.get("/guests/directory")
check("the protected guest directory still renders for staff",
      staff_dir.status_code == 200, staff_dir.status_code)

# ---------------------------------------------------------------------------
step(6, "Production database integrity")
if PROD_STAMP is None:
    check("production database absent — nothing to protect", True)
else:
    now = os.stat(PROD_DB)
    check("production database untouched (size + mtime)",
          (now.st_size, now.st_mtime_ns) == PROD_STAMP,
          (now.st_size, now.st_mtime_ns))
    c = sqlite3.connect(PROD_DB)
    try:
        check("production settings table still holds no phase-28 rows",
              c.execute("SELECT COUNT(*) FROM settings WHERE key = ? AND "
                        "value = ?", ("venue", "Phase 28 Hall")
                        ).fetchone()[0] == 0)
    finally:
        c.close()

shutil.rmtree(_TMP, ignore_errors=True)
print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
