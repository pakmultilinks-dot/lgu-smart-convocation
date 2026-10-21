"""Phase 26C: the guest roster is a scanner surface, not a public one.

GET /api/guests returned models.all_guests() to ANONYMOUS callers: every
guest's phone number plus the signed ``qr_id`` credential that
ids.make_payload signs. This suite pins the corrected contract on ONE
disposable temp database:

  * anonymous GET /api/guests -> 401 (scanner_auth_required), no rows
  * signed-in scanner GET     -> 200, minimum fields only
  * the response omits qr_id (a credential) and created_at
  * the response keeps the fields the kiosk actually renders
  * guest self-registration (POST /api/guests) stays public
  * the single-guest print artefact (/api/guest-pass/<id>) NO LONGER stays
    public — an enumerable gid used to mint the signed admission credential
    for anyone who guessed one (Phase 27 C3). It now needs that guest's
    print capability or a scanner/staff session.

app/lgu.db is never opened — stat-stamped before and after to prove it.

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase26c_guest_list_security.py
"""

import os
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

PROD_DB = os.path.join(APP_DIR, "lgu.db")
if os.path.exists(PROD_DB):
    _s = os.stat(PROD_DB)
    PROD_STAMP = (_s.st_size, _s.st_mtime_ns)
else:
    PROD_STAMP = None

TMP = tempfile.mkdtemp(prefix="lgu-p26c-guestlist-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "guestlist.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import scanner_auth  # noqa: E402
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


def raw(sql, args=()):
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        c.commit()
        return rows
    finally:
        c.close()


database.init_db()
database.seed()
app = create_app()
app.config.update(TESTING=True)
client = app.test_client()

# Mint a signed-in scanner (same trust domain as /api/scan).
sid = scanner_auth.create_scanner("p26c.kiosk", "Kiosk Op", "84726153",
                                  [1, 2, 3, 4, 5, 6, 7], actor="p26c-test")
token, _ = scanner_auth.create_session(sid)
KIOSK = {"X-Scanner-Token": token}

# Pick a roster student who does NOT already have a guest (the seed
# registers guests for a few rolls; registration is one guest per student).
FREE_ROLL = raw(
    "SELECT s.roll_no FROM students s"
    " WHERE NOT EXISTS (SELECT 1 FROM guests g WHERE g.host_roll_no = s.roll_no)"
    " ORDER BY s.roll_no LIMIT 1")[0]["roll_no"]

# Register a guest through the PUBLIC self-registration path, exactly as a
# walk-up kiosk would.
reg = client.post("/api/guests", json={
    "name": "Rafi Khan", "phone": "03214445566",
    "host_roll_no": FREE_ROLL})
rbody = reg.get_json(silent=True) or {}
GID = rbody.get("gid")

print("Phase 26C guest-roster security (isolated temp DB, production untouched)")

step(1, "Guest self-registration stays public (no credential to present)")
check("POST /api/guests answers for an anonymous kiosk",
      reg.status_code == 200, "%s %s" % (reg.status_code, rbody))
check("registration still returns the signed pass payload",
      bool(rbody.get("payload")), rbody)

step(2, "The roster refuses an anonymous caller (no unauthenticated PII dump)")
anon = client.get("/api/guests")
abody = anon.get_json(silent=True) or {}
check("anonymous GET /api/guests -> 401", anon.status_code == 401,
      anon.status_code)
check("refusal uses the scanner_auth_required contract",
      abody.get("code") == "scanner_auth_required", abody)
check("anonymous refusal leaked no guest rows",
      "guests" not in abody, abody)

step(3, "A signed-in scanner gets the roster with MINIMUM fields only")
auth = client.get("/api/guests", headers=KIOSK)
auth_body = auth.get_json(silent=True) or {}
rows = auth_body.get("guests")
check("scanner GET /api/guests -> 200", auth.status_code == 200,
      auth.status_code)
check("roster is a list of rows", isinstance(rows, list), auth_body)

# The credential + metadata the kiosk never renders must be gone.
check("no row exposes the qr_id credential",
      all("qr_id" not in r for r in rows), rows[:3])
check("no row exposes created_at", all("created_at" not in r for r in rows),
      rows[:3])

# The fields the kiosk DOES render must survive (id, name, phone, host roll,
# roster host name, live pass state, latest entry time + gate).
row = next((r for r in rows if r.get("id") == GID), None)
check("the freshly-registered guest appears in the roster", row is not None,
      rows[:3])
if row:
    for field in ("name", "phone", "host_roll_no", "host_name", "used",
                  "used_at", "used_gate"):
        check("roster row keeps the kiosk field '%s'" % field, field in row,
              sorted(row.keys()))
    check("roster row omits qr_id/created_at",
          "qr_id" not in row and "created_at" not in row, sorted(row.keys()))

step(4, "The print artefact needs an approved holder, not just a guessable id")
# `client` registered this guest through the public JSON path and holds the
# print_token that response issued — the approved secure process. It has no
# scanner session, so an ungated route would answer it bare.
gp = client.get("/api/guest-pass/%d" % GID)
gp_body = gp.get_json(silent=True) or {}
check("an enumerable gid alone no longer reaches the pass",
      gp.status_code == 401, gp.status_code)
check("that refusal leaks no signed payload", "payload" not in gp_body,
      sorted(gp_body))
check("refusal uses the guest_pass_forbidden contract",
      gp_body.get("code") == "guest_pass_forbidden", gp_body)

tok = rbody.get("print_token")
gp_ok = client.get("/api/guest-pass/%d" % GID,
                   headers={"X-Print-Token": tok} if tok else {})
ok_body = gp_ok.get_json(silent=True) or {}
check("the registrant reads its own pass with the print capability",
      gp_ok.status_code == 200 and bool(ok_body.get("payload")),
      (gp_ok.status_code, sorted(ok_body)))
gp_kiosk = client.get("/api/guest-pass/%d" % GID, headers=KIOSK)
check("the signed-in kiosk still hands off the same pass",
      gp_kiosk.status_code == 200 and
      bool((gp_kiosk.get_json(silent=True) or {}).get("payload")),
      gp_kiosk.status_code)

step(5, "Production database was never opened")
if PROD_STAMP is None:
    check("no production lgu.db present (nothing to stamp)", True)
else:
    _f = os.stat(PROD_DB)
    check("app/lgu.db size + mtime unchanged",
          (_f.st_size, _f.st_mtime_ns) == PROD_STAMP,
          "before=%s after=%s" % (PROD_STAMP, (_f.st_size, _f.st_mtime_ns)))

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
