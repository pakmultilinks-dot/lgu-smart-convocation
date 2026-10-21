"""Phase 27 — C2/C3 guest directory and guest-pass credential authorisation.

Both guest surfaces were reachable by ANY anonymous LAN caller:

  C2  GET /guests rendered models.all_guests() into the public page — every
      guest's name, phone, host and a print link straight out of the source.
  C3  GET /guests/<gid>/pass and GET /api/guest-pass/<id> minted
      ids.make_payload(g["qr_id"]) — the signed ADMISSION credential — for an
      enumerable integer alone, so anyone could walk gid 1, 2, 3 … and
      download every guest's pass.

Corrected contract, pinned on ONE disposable temp database:

  C2 (5 scenarios, direct HTTP)
   1. anonymous registration works (HTML + JSON)
   2. anonymous directory retrieval is denied (HTML + JSON)
   3. unauthenticated protected guest details are denied
   4. an authorised operator gets only the minimum fields
   5. direct-URL access cannot bypass authorisation

  C3 (8 regressions)
   1. BOTH protected pass routes refuse an anonymous caller — if either is
      ever exposed again this suite fails
   2. print authorisation cannot be fabricated by changing the guest id
   3. the print capability grants no directory access and the directory
      exposes no pass payloads
   4. expiry and permitted repeat-print behaviour are covered
   5. public registration reads its own pass only via the approved process
   6. a revoked/invalid pass, and the print token itself, cannot gain
      admission
   7. authorised staff printing keeps working
   8. single-use admission is unchanged by any of the above

app/lgu.db is never opened — stat-stamped before and after to prove it.

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase27_guest_pass_authorization.py
"""

import os
import re
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

TMP = tempfile.mkdtemp(prefix="lgu-p27-guestpass-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "guestpass.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import ids  # noqa: E402
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


def fresh():
    return app.test_client()


anon = fresh()          # never registered anything, holds no capability
web = fresh()           # browser kiosk: registers guest A via the HTML form
apik = fresh()          # API kiosk: registers guest B via JSON

# Signed-in scanner (same trust domain as /api/scan and /api/guests).
sid = scanner_auth.create_scanner("p27.kiosk", "Kiosk Op", "84726153",
                                  [1, 2, 3, 4, 5, 6, 7], actor="p27-test")
_scan_token, _ = scanner_auth.create_session(sid)
KIOSK = {"X-Scanner-Token": _scan_token}


def staff_client():
    """A browser already unlocked at the staff portal (Phase 20 PIN gate)."""
    c = fresh()
    with c.session_transaction() as sess:
        sess["lgu_admin"] = True
    return c


# Seed registers guests against a few rolls; registration is one guest per
# student, so pick two hosts the seed leaves free.
FREE = [r["roll_no"] for r in raw(
    "SELECT s.roll_no FROM students s"
    " WHERE NOT EXISTS (SELECT 1 FROM guests g WHERE g.host_roll_no = s.roll_no)"
    " ORDER BY s.roll_no LIMIT 3")]
if len(FREE) < 2:
    print("FAIL need two free host rolls for the C3 replay test")
    sys.exit(1)

print("Phase 27 guest-pass authorisation (isolated temp DB, production untouched)")

# ----------------------------------------------------------------- C2 #1
step(1, "C2 — anonymous guest self-registration still works")
areg = apik.post("/api/guests", json={"name": "Amna Raza", "phone": "03217778899",
                                      "host_roll_no": FREE[0]})
abody = areg.get_json(silent=True) or {}
GID_B, TOK_B = abody.get("gid"), abody.get("print_token")
check("POST /api/guests answers for an anonymous kiosk", areg.status_code == 200,
      areg.status_code)
check("registration returns the signed pass payload", bool(abody.get("payload")),
      sorted(abody))
check("registration returns a scoped print capability",
      isinstance(TOK_B, str) and TOK_B.count(".") == 2, abody)

hreg = web.post("/guests", data={"name": "Bilal Ahmed", "phone": "03331234567",
                                 "host_roll_no": FREE[1]})
loc = hreg.headers.get("Location", "")
check("HTML registration redirects to that guest's pass page",
      hreg.status_code == 302 and "/pass" in loc, (hreg.status_code, loc))
check("the redirect URL carries NO secret (capability rides the cookie, "
      "so it can never be logged or forwarded)",
      "?" not in loc and "token" not in loc.lower(), loc)
GID_A = int(re.search(r"/guests/(\d+)/pass", loc).group(1)) \
    if re.search(r"/guests/(\d+)/pass", loc) else None
check("redirect targets the registered guest id", isinstance(GID_A, int), loc)

# The just-registered guest reads their own pass through the approved process.
own = web.get(loc)
check("just-registered guest can print their own pass (session capability)",
      own.status_code == 200, own.status_code)
check("their pass page really renders a QR", b"data:image/png;base64" in own.data,
      own.status_code)

# ----------------------------------------------------------------- C2 #2
step(2, "C2 — the public registration shell exposes no guest directory")
shell = anon.get("/guests")
html = shell.get_data(as_text=True)
check("anonymous GET /guests still serves the registration shell",
      shell.status_code == 200, shell.status_code)
check("shell does not list the registered guest name", "Amna Raza" not in html)
check("shell does not leak a guest phone number", "03217778899" not in html)
check("shell leaks no signed credential", "LGU1:" not in html)
check("shell leaks no qr_id column", "qr_id" not in html)

# ----------------------------------------------------------------- C2 #3
step(3, "C2 — anonymous directory retrieval is denied")
d = anon.get("/guests/directory")
djson = anon.get("/api/guests")
djb = djson.get_json(silent=True) or {}
check("anonymous GET /guests/directory -> 401", d.status_code == 401, d.status_code)
check("directory refusal renders no guest rows", "Amna Raza" not in
      d.get_data(as_text=True))
check("anonymous GET /api/guests -> 401", djson.status_code == 401,
      djson.status_code)
check("JSON refusal uses the scanner contract",
      djb.get("code") == "scanner_auth_required", djb)
check("JSON refusal leaked no rows", "guests" not in djb, djb)

# ----------------------------------------------------------------- C2 #4
step(4, "C2 — unauthenticated access to protected guest details is denied")
pg = anon.get("/api/guest-pass/%d" % GID_B)
pgb = pg.get_json(silent=True) or {}
check("anonymous GET /api/guest-pass/<id> -> 401", pg.status_code == 401,
      pg.status_code)
check("refusal is the guest_pass_forbidden contract",
      pgb.get("code") == "guest_pass_forbidden", pgb)
check("refusal carries NO signed payload", "payload" not in pgb, sorted(pgb))
pp = anon.get("/guests/%d/pass" % GID_A)
check("anonymous GET /guests/<id>/pass -> 401", pp.status_code == 401,
      pp.status_code)
check("refusal renders no QR", b"data:image/png;base64" not in pp.data)

# The first id is the one an enumerator tries — pinned explicitly.
first = anon.get("/api/guest-pass/1")
check("gid 1 (first guess) is not an anonymous credential oracle",
      first.status_code == 401 and "payload" not in
      (first.get_json(silent=True) or {}), first.status_code)

# ----------------------------------------------------------------- C2 #5
step(5, "C2 — an authorised operator gets only the minimum fields")
krows = (anon.get("/api/guests", headers=KIOSK).get_json(silent=True) or {}) \
    .get("guests")
check("scanner GET /api/guests -> 200", isinstance(krows, list), krows)
if isinstance(krows, list):
    check("roster keeps the fields the desk renders",
          all(f in krows[0] for f in ("id", "name", "phone", "host_roll_no",
                                      "host_name", "used")), sorted(krows[0]))
    check("roster omits the qr_id credential",
          all("qr_id" not in r for r in krows), krows[:2])
    check("roster omits created_at",
          all("created_at" not in r for r in krows), krows[:2])

staff = staff_client()
dpage = staff.get("/guests/directory")
dhtml = dpage.get_data(as_text=True)
check("staff GET /guests/directory -> 200", dpage.status_code == 200,
      dpage.status_code)
check("staff directory renders the guests it should",
      "Amna Raza" in dhtml and "Bilal Ahmed" in dhtml)
check("staff directory carries no qr_id", "qr_id" not in dhtml)
check("staff directory carries no signed payload", "LGU1:" not in dhtml)

# ----------------------------------------------------------------- C2 #6
step(6, "C2 — direct-URL access cannot bypass authorisation")
tok_client = fresh()
tok_client.set_cookie("guest_print", TOK_B, domain="localhost")
bypass = tok_client.get("/guests/directory")
check("a valid print capability does NOT open the directory (HTML)",
      bypass.status_code == 401, bypass.status_code)
bypass2 = tok_client.get("/api/guests")
check("a valid print capability does NOT open the directory (JSON)",
      bypass2.status_code == 401, bypass2.status_code)
# The capability is bound to its own guest: point it at someone else's id.
wrong = fresh().get("/api/guest-pass/%d" % GID_A,
                    headers={"X-Print-Token": TOK_B})
check("guest B's capability does NOT read guest A's pass",
      wrong.status_code == 401 and "payload" not in
      (wrong.get_json(silent=True) or {}), wrong.status_code)

# ----------------------------------------------------------------- C3 #7
step(7, "C3 — the approved secure process works for each holder")
apipass = apik.get("/api/guest-pass/%d" % GID_B,
                   headers={"X-Print-Token": TOK_B})
apib = apipass.get_json(silent=True) or {}
check("API registrant reads their own pass with the print capability",
      apipass.status_code == 200 and bool(apib.get("payload")), apib)
check("their pass reports not-yet-used", apib.get("used") is False, apib)

scanpass = anon.get("/api/guest-pass/%d" % GID_B, headers=KIOSK)
check("signed-in scanner may print any guest pass",
      scanpass.status_code == 200, scanpass.status_code)
staffpass = staff.get("/api/guest-pass/%d" % GID_A)
check("staff portal may print any guest pass",
      staffpass.status_code == 200, staffpass.status_code)
staffhtml = staff.get("/guests/%d/pass" % GID_A)
check("staff may print the HTML pass page",
      staffhtml.status_code == 200 and b"data:image/png;base64" in staffhtml.data,
      staffhtml.status_code)

# ----------------------------------------------------------------- C3 #8
step(8, "C3 — expiry and permitted repeat printing")
expired = ids.make_print_token(GID_B, -30)
e = apik.get("/api/guest-pass/%d" % GID_B, headers={"X-Print-Token": expired})
check("an expired capability is refused", e.status_code == 401, e.status_code)
check("a malformed capability is refused",
      fresh().get("/api/guest-pass/%d" % GID_B,
                  headers={"X-Print-Token": "not-a-token"}).status_code == 401)
r1 = apik.get("/api/guest-pass/%d" % GID_B, headers={"X-Print-Token": TOK_B})
r2 = apik.get("/api/guest-pass/%d" % GID_B, headers={"X-Print-Token": TOK_B})
check("repeat printing is permitted while the capability is valid",
      r1.status_code == 200 and r2.status_code == 200,
      (r1.status_code, r2.status_code))

# ----------------------------------------------------------------- C3 #9
step(9, "C3 — the print capability grants no admission rights")
as_payload = anon.post("/api/scan", headers=KIOSK, json={
    "payload": TOK_B, "gate_id": 1, "mode": "entry", "volunteer": "Phase27"})
asb = as_payload.get_json(silent=True) or {}
check("the print token is NOT an admission credential",
      "RECORDED" not in str(asb.get("title", "")), asb)

payload = apib.get("payload")
first_scan = anon.post("/api/scan", headers=KIOSK, json={
    "payload": payload, "gate_id": 1, "mode": "entry", "volunteer": "Phase27"})
fsb = first_scan.get_json(silent=True) or {}
check("the signed pass still admits exactly once",
      "RECORDED" in str(fsb.get("title", "")), fsb)
second_scan = anon.post("/api/scan", headers=KIOSK, json={
    "payload": payload, "gate_id": 1, "mode": "entry", "volunteer": "Phase27"})
ssb = second_scan.get_json(silent=True) or {}
check("a used pass is rejected on the next scan (single-use unchanged)",
      ssb.get("title") == "ALREADY USED", ssb)
tampered = payload[:-1] + ("A" if payload[-1] != "A" else "B")
bad = anon.post("/api/scan", headers=KIOSK, json={
    "payload": tampered, "gate_id": 1, "mode": "entry", "volunteer": "Phase27"})
check("a tampered pass is rejected", "RECORDED" not in
      str((bad.get_json(silent=True) or {}).get("title", "")),
      bad.get_json(silent=True))
used_after = apik.get("/api/guest-pass/%d" % GID_B,
                      headers={"X-Print-Token": TOK_B})
check("re-reading after admission reports the pass as used",
      (used_after.get_json(silent=True) or {}).get("used") is True,
      used_after.get_json(silent=True))

# ----------------------------------------------------------------- C3 #10
step(10, "C3 — both protected pass routes stay closed to anonymous callers")
a1 = fresh().get("/api/guest-pass/%d" % GID_A)
a2 = fresh().get("/guests/%d/pass" % GID_A)
check("regression guard: /api/guest-pass/<id> refuses anonymous",
      a1.status_code == 401, a1.status_code)
check("regression guard: /guests/<id>/pass refuses anonymous",
      a2.status_code == 401, a2.status_code)
check("neither refusal yields a credential",
      "payload" not in (a1.get_json(silent=True) or {}) and
      b"data:image/png;base64" not in a2.data)

# ----------------------------------------------------------------- last
step(11, "Production database was never opened")
if PROD_STAMP is None:
    check("no production lgu.db present (nothing to stamp)", True)
else:
    _f = os.stat(PROD_DB)
    check("app/lgu.db size + mtime unchanged",
          (_f.st_size, _f.st_mtime_ns) == PROD_STAMP,
          "before=%s after=%s" % (PROD_STAMP, (_f.st_size, _f.st_mtime_ns)))

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
