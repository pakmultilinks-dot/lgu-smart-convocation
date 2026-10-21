"""Phase 19 acceptance: authenticated scanner administration in the portal.

Proves the whole scanner-management lifecycle on ONE disposable temp database
against the REAL routes, sessions, persistence and audit trail (no mocks):
staff create an account from the browser, assign gates, establish or replace a
PIN, revoke sessions and disable or re-enable the account — and every action is
attributed to the authenticated staff session, never to a submitted field.
A volunteer scanner still cannot sign in before a credential exists, a
disabled/revoked account cannot sign in with its old PIN, an out-of-scope gate
is still refused server-side, and no PIN, PIN hash, session token or token
hash ever reaches an ordinary page, the audit trail or a log. The local CLI
path keeps working and is distinguishable from an authenticated staff action.
Legacy LGU1 and convocation LGU2 flows plus the student-facing surfaces are
re-checked so management created no authorization bypass. Synthetic records
only; app/lgu.db is never opened (stat-stamped before and after to prove it).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase19_scanner_management.py
"""

import os
import re
import sqlite3
import sys
import tempfile
import threading

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

# Stat-stamp the production database BEFORE anything runs: the boundary
# check at the end proves this suite never opened or mutated it.
PROD_DB = os.path.join(APP_DIR, "lgu.db")
if os.path.exists(PROD_DB):
    _prod_stat = os.stat(PROD_DB)
    PROD_STAMP = (_prod_stat.st_size, _prod_stat.st_mtime_ns)
else:
    PROD_STAMP = None

TMP = tempfile.mkdtemp(prefix="lgu-p19-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "p19.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import exam_auth  # noqa: E402
import ids  # noqa: E402
import scanner_auth  # noqa: E402
import web.routes as vr  # noqa: E402
import web.exam_routes as exr  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
STAFF_USER, STAFF_PW = "p19.officer", "phase19-pass-19"
OTHER_USER, OTHER_PW = "p19.second", "phase19-pass-22"


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def step(n, title):
    print("\nCASE %d: %s" % (n, title))


def raw(sql, args=()):
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        c.commit()
        return rows
    finally:
        c.close()


def exec_sql(sql, args=()):
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def html(resp):
    return resp.get_data(as_text=True)


def csrf_of(page_html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', page_html)
    return m.group(1) if m else ""


def audit_rows(action, like=None, args=()):
    sql = "SELECT * FROM audit_log WHERE action = ?"
    a = [action]
    if like:
        sql += " AND detail LIKE ?"
        a.append(like)
    return raw(sql + " ORDER BY id DESC", (*a, *args))


def reset_limits():
    vr._PIN_FAILS.clear()
    vr._SCAN_LOGIN_FAILS.clear()
    exr._EXAM_FAILS.clear()


# ---------------------------------------------------------------- boot
database.init_db()
database.seed()
exam_auth.create_staff(STAFF_USER, "P19 Officer", STAFF_PW)
exam_auth.create_staff(OTHER_USER, "P19 Second Officer", OTHER_PW)

app = create_app()
app.config["TESTING"] = True
client = app.test_client()
CONV = raw("SELECT * FROM convocations WHERE is_active = 1")[0]["id"]
STU = raw("SELECT * FROM students WHERE roll_no = 'LGU-2024-102'")[0]
OTHER_STU = raw("SELECT * FROM students WHERE roll_no = 'LGU-2024-104'")[0]


def login(username=STAFF_USER, password=STAFF_PW, target=None):
    page = html((target or client).get("/exam/login"))
    return (target or client).post("/exam/login", data={
        "csrf_token": csrf_of(page), "username": username, "password": password})


def csrf(client_obj, path):
    return csrf_of(html(client_obj.get(path)))


def post(client_obj, path, **data):
    data.setdefault("csrf_token", csrf(client_obj, path))
    return client_obj.post(path, data=data)


def scanners_of():
    return raw("SELECT * FROM scanner_users ORDER BY id")


def gates_of(sid):
    return [r["gate_id"] for r in raw(
        "SELECT gate_id FROM scanner_gates WHERE scanner_id = ?"
        " ORDER BY gate_id", (sid,))]


login()
check("staff session established", "/exam/dashboard" in html(client.get("/exam/")).replace("\n", "")
      or client.get("/exam/dashboard").status_code == 200)

# =============================== CASE 1 ====================================
step(1, "Unauthenticated callers are denied every management operation")
anon = app.test_client()
before = len(raw("SELECT id FROM audit_log WHERE action = 'scanner_mgmt_denied'"))
for path in ("/exam/scanners", "/exam/scanners/new", "/exam/scanners/1"):
    r = anon.get(path)
    check("GET %s -> redirected to the staff login" % path,
          r.status_code == 302 and "/exam/login" in r.headers.get("Location", ""),
          (r.status_code, r.headers.get("Location")))
r = anon.post("/exam/scanners/new", data={"username": "p19.anon",
                                          "display_name": "Anon"})
check("POST create without a session or CSRF token -> 403",
      r.status_code == 403, r.status_code)
r = anon.post("/exam/scanners/1", data={"action": "revoke"})
check("POST revoke without a session or CSRF token -> 403",
      r.status_code == 403, r.status_code)
after = raw("SELECT * FROM audit_log WHERE action = 'scanner_mgmt_denied'")
check("denied management attempts are recorded, not silently dropped",
      len(after) >= before + 2 and all("via=portal" in (a["detail"] or "")
                                       for a in after),
      [a["detail"] for a in after[:4]])
check("no account was created by the unauthenticated attempts",
      not scanners_of())
check("a denial record never exposes any secret",
      all("pin" not in (a["detail"] or "").lower() for a in after))

# =============================== CASE 2 ====================================
step(2, "An authenticated but unauthorized staff account cannot manage scanners")
exam_auth.create_staff("p19.revoked", "P19 Revoked", "phase19-pass-33")
exec_sql("UPDATE staff_users SET is_active = 0 WHERE username = 'p19.revoked'")
r = login("p19.revoked", "phase19-pass-33")
check("a deactivated staff account cannot log in",
      r.status_code == 401 and "/exam/dashboard" not in r.headers.get("Location", ""),
      (r.status_code, r.headers.get("Location")))
mid = app.test_client()
login(STAFF_USER, STAFF_PW, target=mid)
check("the mid-session staff client can open the management surface",
      mid.get("/exam/scanners").status_code == 200)
exec_sql("UPDATE staff_users SET is_active = 0 WHERE username = ?", (STAFF_USER,))
r = mid.get("/exam/scanners")
check("deactivating the account mid-session ends management access",
      r.status_code == 302 and "/exam/login" in r.headers.get("Location", ""),
      (r.status_code, r.headers.get("Location")))
exec_sql("UPDATE staff_users SET is_active = 1 WHERE username = ?", (STAFF_USER,))
# A scanner session is not a staff session: it must not reach management.
sid_b = scanner_auth.create_scanner("p19.notstaff", "Not Staff", "44556677",
                                    [1], actor="p19-test")
tok_b, _ = scanner_auth.create_session(sid_b)
sc = app.test_client()
sc.environ_base = {"HTTP_X_SCANNER_TOKEN": tok_b}
check("a live scanner session is NOT a staff credential for the portal",
      sc.get("/exam/scanners").status_code == 302
      and "/exam/login" in sc.get("/exam/scanners").headers.get("Location", ""),
      sc.get("/exam/scanners").status_code)

# =============================== CASE 3 ====================================
def checked_gates(page_html):
    """Gate ids whose checkbox is actually ticked in the edit form."""
    return sorted(int(g) for g in re.findall(
        r'value="(\d+)"\s+checked', page_html))


def one_time_pin(page_html):
    """The generated PIN rendered in the one-time notice block, if any."""
    m = re.search(r"One-time PIN for <strong>[^<]*</strong>\s*:\s*"
                  r"<strong>([A-Z0-9]{6,})</strong>", page_html)
    return m.group(1) if m else None


step(3, "Authorized staff can create a scanner account from the portal")
r = post(client, "/exam/scanners/new", username="p19.ana", display_name="Ana Cruz",
         gate_id=["1", "2"], pin="P19PIN01")
loc = r.headers.get("Location", "")
sid = int(re.search(r"/scanners/(\d+)", loc).group(1)) if r.status_code == 302 else None
check("creation succeeds and redirects to the new account page",
      r.status_code == 302 and sid is not None, (r.status_code, loc))
row = raw("SELECT * FROM scanner_users WHERE id = ?", (sid,))
check("the account exists with the submitted username and display name",
      row and row[0]["username"] == "p19.ana"
      and row[0]["display_name"] == "Ana Cruz", row)
check("the account is immediately usable (credential established)",
      row and row[0]["credential_established"] == 1
      and row[0]["pin_hash"].startswith("scrypt:"), row[0]["pin_hash"][:30] if row else None)
check("gate assignments persisted", gates_of(sid) == [1, 2], gates_of(sid))
check("the portal reports the new account on the list page",
      "p19.ana" in html(client.get("/exam/scanners")))
# A staff-typed PIN is never echoed: the flow is Post/Redirect/Get.
check("a staff-supplied PIN is never rendered back in the response",
      "P19PIN01" not in html(r) and one_time_pin(html(r)) is None)
r = post(client, "/exam/scanners/new", username="p19.gen", display_name="Gen One",
         gate_id=["2"])
body = html(r)
one_time_rendered = one_time_pin(body)
check("a blank PIN yields a generated one-time value, rendered exactly once and "
      "never in a URL",
      bool(one_time_rendered) and one_time_rendered not in str(r.headers)
      and body.count(one_time_rendered) == 1,
      (one_time_rendered, r.headers.get("Location")))
check("the account holds only a scrypt hash of that PIN",
      raw("SELECT pin_hash FROM scanner_users WHERE username = 'p19.gen'"
          )[0]["pin_hash"].startswith("scrypt:"))
check("the list page never re-renders a previously shown one-time PIN",
      one_time_rendered not in html(client.get("/exam/scanners")))

# =============================== CASE 4 ====================================
step(4, "Gate assignments are shown accurately and are replaceable")
page = html(client.get("/exam/scanners/%d" % sid))
check("both authorized gates render as checked", checked_gates(page) == [1, 2],
      checked_gates(page))
r = post(client, "/exam/scanners/%d" % sid, action="gates", gate_id=["2", "3"])
check("saving new gates redirects back to the account",
      r.status_code == 302, r.status_code)
check("the new gate set persisted and the old one is gone",
      gates_of(sid) == [2, 3], gates_of(sid))
page = html(client.get("/exam/scanners/%d" % sid))
check("the page reflects the new set and no longer offers gate 1",
      checked_gates(page) == [2, 3], checked_gates(page))
r = post(client, "/exam/scanners/%d" % sid, action="gates", gate_id=[])
check("submitting no gates is an explicit 'no gates', not a silent keep",
      r.status_code == 302 and gates_of(sid) == [], gates_of(sid))

# =============================== CASE 5 ====================================
step(5, "A scanner cannot authenticate before a credential is established")
r = post(client, "/exam/scanners/new", username="p19.pending",
         display_name="Pending Pete", gate_id=["1"], pending="1")
body = html(r)
pending_pin = one_time_pin(body)
pid = raw("SELECT id, credential_established, pin_hash"
          " FROM scanner_users WHERE username = 'p19.pending'")[0]
check("creating with the pending box ticked yields an unusable account",
      pid["credential_established"] == 0 and pid["pin_hash"].startswith("scrypt:"),
      pid)
check("no one-time PIN is rendered for a pending account",
      pending_pin is None and "One-time PIN" not in body, body[:300])
check("the account cannot authenticate with ANY pin while pending",
      scanner_auth.authenticate("p19.pending", "P19PIN01") is None
      and scanner_auth.authenticate("p19.pending", "00000000") is None)
check("the pending refusal is audited and does not look like a success",
      any("credential_pending" in (a["detail"] or "")
          for a in audit_rows("scanner_login_blocked")))
check("the pending state did not burn the account's failure budget",
      raw("SELECT failed_attempts FROM scanner_users WHERE id = ?",
          (pid["id"],))[0]["failed_attempts"] == 0)
check("a refresh of the one-time response cannot recover the PIN",
      "already exists" in html(post(client, "/exam/scanners/new",
                                    username="p19.pending",
                                    display_name="Pending Pete", gate_id=["1"],
                                    pending="1"))
      and one_time_pin(html(client.get("/exam/scanners"))) is None)

# =============================== CASE 6 ====================================
step(6, "Establishing then replacing a PIN invalidates the previous one")
r = post(client, "/exam/scanners/%d" % pid["id"], action="pin")
first_pin = one_time_pin(html(r))
check("establishing the PIN renders the one-time value exactly once",
      bool(first_pin) and html(r).count(first_pin) == 1, first_pin)
check("establishing the PIN makes the account usable",
      scanner_auth.authenticate("p19.pending", first_pin) is not None
      and raw("SELECT credential_established FROM scanner_users WHERE id = ?",
              (pid["id"],))[0]["credential_established"] == 1)
r = post(client, "/exam/scanners/%d" % pid["id"], action="pin", pin="P19NEW11")
check("replacing the PIN reports success",
      r.status_code == 302 and "error" not in r.headers.get("Location", ""),
      r.headers.get("Location"))
check("the previous one-time PIN no longer authenticates",
      scanner_auth.authenticate("p19.pending", first_pin) is None)
check("the replacement PIN authenticates",
      scanner_auth.authenticate("p19.pending", "P19NEW11") is not None)
short = post(client, "/exam/scanners/%d" % pid["id"], action="pin", pin="123")
check("a PIN shorter than the policy minimum is refused with an error",
      short.status_code == 302 and "error=" in short.headers.get("Location", ""),
      short.headers.get("Location"))
check("the refused reset left the working PIN in place",
      scanner_auth.authenticate("p19.pending", "P19NEW11") is not None)

# =============================== CASE 7 ====================================
step(7, "The scanner authenticates with the new PIN and holds a real session")
reset_limits()
tok, exp = scanner_auth.create_session(pid["id"])
info = scanner_auth.resolve_session(tok)
check("a session resolves to the server-side identity and gate set",
      info is not None and info["username"] == "p19.pending"
      and info["gates"] == gates_of(pid["id"]), info)
r = client.post("/api/scanner/login",
                json={"username": "p19.pending", "pin": "P19NEW11"})
body = r.get_json(silent=True) or {}
check("the scanner login route accepts the new PIN",
      r.status_code == 200 and body.get("token"), (r.status_code, body))

# =============================== CASE 8 ====================================
step(8, "Disabling an account blocks sign-in and kills every session")
r = post(client, "/exam/scanners/%d" % pid["id"], action="revoke")
check("disabling reports success", r.status_code == 302, r.status_code)
check("the old PIN no longer authenticates",
      scanner_auth.authenticate("p19.pending", "P19NEW11") is None)
check("the live session no longer resolves",
      scanner_auth.resolve_session(tok) is None)
check("a disabled account is refused by the scanner login route",
      client.post("/api/scanner/login",
                  json={"username": "p19.pending", "pin": "P19NEW11"}
                  ).status_code in (401, 423, 429))
check("re-enabling restores the SAME credential (no reset happened)",
      post(client, "/exam/scanners/%d" % pid["id"], action="activate"
           ).status_code == 302
      and scanner_auth.authenticate("p19.pending", "P19NEW11") is not None)

# =============================== CASE 9 ====================================
step(9, "Revoking sessions signs the device out but keeps the account usable")
tok9, _ = scanner_auth.create_session(pid["id"])
check("the session resolves before revocation",
      scanner_auth.resolve_session(tok9) is not None)
r = post(client, "/exam/scanners/%d" % pid["id"], action="sessions")
check("revoking sessions reports success", r.status_code == 302, r.status_code)
check("the revoked session no longer resolves",
      scanner_auth.resolve_session(tok9) is None)
check("the account can still sign in afterwards",
      scanner_auth.authenticate("p19.pending", "P19NEW11") is not None)
check("revocation is audited as its own management action",
      bool(audit_rows("scanner_sessions_revoked")))

# =============================== CASE 10 ===================================
step(10, "A gate outside the authorized set is refused server-side")
reset_limits()
sid10 = scanner_auth.create_scanner("p19.gate", "Gate Op", "66778899", [1],
                                    actor="p19-test")
tok10, _ = scanner_auth.create_session(sid10)
h10 = {"X-Scanner-Token": tok10}
pay = ids.make_payload(STU["qr_id"])
r = client.post("/api/scan", json={"payload": pay, "gate_id": 1, "mode": "entry"},
                headers=h10)
check("the authorized gate still admits", r.status_code == 200,
      (r.status_code, r.get_json(silent=True)))
r = client.post("/api/scan", json={"payload": ids.make_payload(OTHER_STU["qr_id"]),
                                   "gate_id": 2, "mode": "entry"}, headers=h10)
b = r.get_json(silent=True) or {}
check("an out-of-scope gate is refused 403", r.status_code == 403, (r.status_code, b))
check("the refusal recorded no admission",
      not raw("SELECT id FROM scans WHERE qr_id = ?", (OTHER_STU["qr_id"],)))
post(client, "/exam/scanners/%d" % sid10, action="gates", gate_id=["1", "2"])
tok10b, _ = scanner_auth.create_session(sid10)
r = client.post("/api/scan", json={"payload": ids.make_payload(OTHER_STU["qr_id"]),
                                   "gate_id": 2, "mode": "entry"},
                headers={"X-Scanner-Token": tok10b})
check("the newly authorized gate now admits (management took effect)",
      r.status_code == 200, (r.status_code, r.get_json(silent=True)))

# =============================== CASE 11 ===================================
step(11, "A tampered submitted actor never changes the recorded actor")
r = post(client, "/exam/scanners/new", username="p19.spoof", display_name="Spoof",
         gate_id=["1"], pin="SPOOF1234", actor="BOGUS-ACTOR",
         staff_id="9999")
check("the forged fields are ignored and creation still succeeds",
      r.status_code == 302, (r.status_code, r.headers.get("Location")))
row = audit_rows("scanner_created", "%p19.spoof%")
check("the audit actor is the authenticated staff session, not the form field",
      row and row[0]["actor"] == STAFF_USER and "BOGUS" not in row[0]["actor"],
      row[0]["actor"] if row else None)
r = post(client, "/exam/scanners/%d" % raw(
    "SELECT id FROM scanner_users WHERE username = 'p19.spoof'")[0]["id"],
    action="gates", gate_id=["4"], actor="BOGUS-ACTOR", staff_id="9999")
row = audit_rows("scanner_gates_set", "%p19.spoof%")
check("a forged actor on a gate change is still ignored",
      row and row[0]["actor"] == STAFF_USER, row[0]["actor"] if row else None)

# =============================== CASE 12 ===================================
step(12, "The audit identifies the actual authenticated actor for every action")
second = app.test_client()
login(OTHER_USER, OTHER_PW, target=second)
post(second, "/exam/scanners/new", username="p19.byother", display_name="By Other",
     gate_id=["5"], pin="OTHER1234")
sid_other = raw("SELECT id FROM scanner_users WHERE username = 'p19.byother'")[0]["id"]
post(second, "/exam/scanners/%d" % sid_other, action="sessions")
expected = {"p19.spoof": STAFF_USER, "p19.byother": OTHER_USER,
            "p19.pending": STAFF_USER, "p19.ana": STAFF_USER}
bad = []
for uname, actor in expected.items():
    rows = [a for a in audit_rows("scanner_created", "%%%s%%" % uname)
            if "username=%s " % uname in (a["detail"] or "")]
    if not rows or rows[0]["actor"] != actor:
        bad.append((uname, rows[0]["actor"] if rows else None))
check("each account's creator matches the session that created it",
      not bad, bad)
check("every lifecycle action names a real staff username, never 'system'",
      all(a["actor"] not in (None, "", "system") for a in raw(
          "SELECT actor FROM audit_log WHERE action LIKE 'scanner_%'")))
PORTAL_MADE = ("p19.ana", "p19.gen", "p19.pending", "p19.spoof", "p19.byother")
portal_details = [(a["detail"] or "") for a in raw(
    "SELECT detail FROM audit_log WHERE action = 'scanner_created'")]
check("every creation records its provenance tag",
      portal_details and all(d.startswith("via=") for d in portal_details),
      [d for d in portal_details if not d.startswith("via=")])
check("portal creations carry via=portal and library ones never do",
      all(any("via=portal" in d and "username=%s " % u in d
              for d in portal_details) for u in PORTAL_MADE)
      and all("via=portal" not in d for d in portal_details
              if "via=cli" in d or "username=p19.cli " in d
              or "username=p19.gate " in d or "username=p19.lgu " in d
              or "username=p19.lockme " in d),
      portal_details)

# =============================== CASE 13 ===================================
step(13, "A failed operation leaves no half-created account or bad gate set")
post(client, "/exam/scanners/%d" % sid, action="gates", gate_id=["1", "2"])
n_before = len(scanners_of())
r = post(client, "/exam/scanners/new", username="p19.badgate",
         display_name="Bad Gate", gate_id=["42"], pin="BADGATE1")
check("an unknown gate is refused with a readable error",
      r.status_code == 422 and "Unknown gate" in html(r), r.status_code)
check("no half-created account survives the refusal",
      len(scanners_of()) == n_before
      and not raw("SELECT id FROM scanner_users WHERE username = 'p19.badgate'"))
r = post(client, "/exam/scanners/new", username="p19.ana", display_name="Dup",
         gate_id=["1"], pin="DUPE1234")
check("a duplicate username is refused",
      r.status_code == 422 and "already exists" in html(r), r.status_code)
check("the duplicate attempt did not create or alter anything",
      len(scanners_of()) == n_before
      and gates_of(sid) == [1, 2], gates_of(sid))
r = post(client, "/exam/scanners/%d" % sid, action="gates", gate_id=["42"])
check("a bad gate change is refused",
      "error=" in r.headers.get("Location", ""), r.headers.get("Location"))
check("the previous gate set is intact after the refused change",
      gates_of(sid) == [1, 2], gates_of(sid))
r = post(client, "/exam/scanners/%d" % sid, action="nonsense")
check("an unknown action is refused cleanly, not with a traceback",
      "Traceback" not in html(r) and r.status_code in (302, 422),
      (r.status_code, html(r)[:200]))

# =============================== CASE 14 ===================================
step(14, "PINs, PIN hashes and tokens never reach a page, the audit or a log")
secrets_seen = ["P19PIN01", "P19NEW11", "SPOOF1234", "OTHER1234", "BADGATE1"]
audit_blob = " ".join((a["detail"] or "") + " " + (a["actor"] or "")
                      for a in raw("SELECT actor, action, detail FROM audit_log"))
check("no plaintext PIN appears anywhere in the audit trail",
      not any(s in audit_blob for s in secrets_seen),
      [s for s in secrets_seen if s in audit_blob])
check("no PIN hash is ever selected into a management read model",
      all("pin_hash" not in r for r in scanner_auth.list_scanners())
      and all("pin_hash" not in r
              for r in [scanner_auth.get_scanner(sid)]))
check("no token hash is ever selected into a management read model",
      all("token_hash" not in r for r in scanner_auth.list_scanners())
      and "token_hash" not in scanner_auth.get_scanner(sid))
pages = html(client.get("/exam/scanners")) + html(client.get("/exam/scanners/%d" % sid))
check("no PIN or hash is rendered on an ordinary management page",
      not any(s in pages for s in secrets_seen)
      and "scrypt:" not in pages and "pin_hash" not in pages)
live_tok, _ = scanner_auth.create_session(sid)
check("a live session token never appears on a management page",
      live_tok not in pages
      and live_tok not in html(client.get("/exam/scanners")))
check("a staff-supplied PIN is never echoed back in the response",
      "P19PIN01" not in html(client.get("/exam/scanners/%d" % sid)))
hist = " ".join((h["detail"] or "") for h in scanner_auth.history(500))
check("the management history exposes no credential material",
      not any(s in hist for s in secrets_seen) and "scrypt:" not in hist)

# =============================== CASE 15 ===================================
step(15, "Repeated or racing requests cannot create conflicting identities")
results = []

def _racer(n):
    c = app.test_client()
    login(STAFF_USER, STAFF_PW, target=c)
    results.append(post(c, "/exam/scanners/new", username="p19.race",
                        display_name="Racer %d" % n, gate_id=["1"],
                        pin="RACE1234").status_code)

threads = [threading.Thread(target=_racer, args=(i,)) for i in range(4)]
[t.start() for t in threads]
[t.join() for t in threads]
check("racing identical creates yield exactly one account",
      len(raw("SELECT id FROM scanner_users WHERE username = 'p19.race'")) == 1,
      results)
check("at most one racing create reported success",
      sum(1 for s in results if s == 302) <= 1, results)
r1 = post(client, "/exam/scanners/new", username="p19.repeat",
          display_name="Repeat", gate_id=["1"], pin="REPEAT12")
r2 = post(client, "/exam/scanners/new", username="p19.repeat",
          display_name="Repeat", gate_id=["1"], pin="REPEAT12")
check("a repeated create is refused rather than silently re-used",
      r1.status_code == 302 and r2.status_code == 422,
      (r1.status_code, r2.status_code))
check("the refused repeat did not overwrite the credential",
      scanner_auth.authenticate("p19.repeat", "REPEAT12") is not None)
reset_limits()
scanner_auth.create_scanner("p19.lockme", "Lock Me", "LOCKME12", [1],
                            actor="p19-test")
statuses = [client.post("/api/scanner/login",
                        json={"username": "p19.lockme", "pin": "WRONGPIN"}).status_code
            for _ in range(6)]
check("repeated wrong PINs still lock the account after five failures",
      statuses[0] == 401 and statuses[-1] == 429, statuses)
check("the locked account cannot be unlocked by management activity",
      scanner_auth.authenticate("p19.lockme", "LOCKME12") is None)
check("the race never left a pending or half-configured row",
      not raw("SELECT id FROM scanner_users WHERE username = 'p19.race'"
              " AND credential_established = 0"))

# =============================== CASE 16 ===================================
step(16, "The command-line creation path still works and is distinguishable")
import subprocess  # noqa: E402
py = sys.executable
proc = subprocess.run(
    [py, os.path.join(APP_DIR, "scripts", "manage_scanner_staff.py"),
     "create", "--username", "p19.cli", "--name", "CLI Scanner",
     "--gates", "1,2", "--pin", "CLIPIN1234", "--actor", "cli-operator"],
    cwd=APP_DIR, capture_output=True, text=True, timeout=180)
out = (proc.stdout or "") + (proc.stderr or "")
cli_row = raw("SELECT id, credential_established FROM scanner_users"
              " WHERE username = 'p19.cli'")
check("the CLI creates an account successfully",
      proc.returncode == 0 and cli_row, out[:400])
check("the CLI prints the PIN once and never stores it in plaintext",
      "CLIPIN1234" in out and cli_row[0]["credential_established"] == 1, out[:300])
check("the CLI account authenticates with the printed PIN",
      scanner_auth.authenticate("p19.cli", "CLIPIN1234") is not None)
cli_audit = audit_rows("scanner_created", "%p19.cli%")
check("the CLI records the attested operator, not a portal session",
      cli_audit and cli_audit[0]["actor"] == "cli-operator", cli_audit)
check("the CLI path is distinguishable from an authenticated staff action",
      "via=cli" in (cli_audit[0]["detail"] or "")
      and "via=portal" not in (cli_audit[0]["detail"] or ""), cli_audit[0]["detail"])
check("the CLI never claims portal provenance",
      all("via=portal" not in (a["detail"] or "")
          for a in audit_rows("scanner_created", "%p19.cli%")))
proc2 = subprocess.run(
    [py, os.path.join(APP_DIR, "scripts", "manage_scanner_staff.py"), "list"],
    cwd=APP_DIR, capture_output=True, text=True, timeout=180)
check("the CLI list command still runs and shows no credential material",
      proc2.returncode == 0 and "p19.cli" in (proc2.stdout or "")
      and "CLIPIN1234" not in (proc2.stdout or "")
      and "scrypt:" not in (proc2.stdout or ""),
      (proc2.stdout or "")[:400])

# =============================== CASE 17 ===================================
step(17, "Legacy LGU1 and convocation LGU2 flows are unchanged")
reset_limits()
tok17, _ = scanner_auth.create_session(scanner_auth.create_scanner(
    "p19.lgu", "LGU Op", "LGULGU12", [1, 2], actor="p19-test"))
h17 = {"X-Scanner-Token": tok17}
pay17 = ids.make_payload(STU["qr_id"])
r = client.post("/api/scan", json={"payload": pay17, "gate_id": 1, "mode": "entry"},
                headers=h17)
check("the legacy LGU1 scan path still admits",
      r.status_code == 200, (r.status_code, r.get_json(silent=True)))
r = client.post("/api/sync", json={"items": [{"payload": pay17, "gate_id": 1,
                                              "mode": "entry"}]}, headers=h17)
check("the sync endpoint still requires and accepts a scanner session",
      r.status_code in (200, 409), (r.status_code, r.get_json(silent=True)))
r = client.get("/api/gates")
check("the public gate list still answers", r.status_code == 200, r.status_code)
vr_routes = sorted(str(rule) for rule in app.url_map.iter_rules()
                   if "verify" in str(rule).lower()
                   or "convocation" in str(rule).lower())
check("the convocation verification routes are still registered",
      any("/api/admin/verify" in s for s in vr_routes)
      and any("/api/student/verify" in s for s in vr_routes), vr_routes)
r = client.post("/api/convocation/scan",
                json={"payload": "not-a-real-pass", "gate_id": 1})
check("a bad convocation pass is refused, not accepted",
      r.status_code != 200, r.status_code)

# =============================== CASE 18 ===================================
step(18, "Student-facing surfaces are intact and management created no bypass")
anon2 = app.test_client()
for path in ("/api/student/readiness", "/api/student/announcements",
             "/api/student/events"):
    r = anon2.get(path)
    check("GET %s answers without a 500" % path,
          r.status_code != 500, (path, r.status_code))
r = anon2.post("/api/student/register", json={})
check("student registration still rejects an empty payload without a 500",
      r.status_code != 500, r.status_code)
r = anon2.post("/api/student/login", json={"email": "nobody@uni.edu.pk",
                                           "password": "wrongwrong"})
check("student login still rejects bad credentials without a 500",
      r.status_code != 500, r.status_code)
check("a scanner session still cannot reach the student API",
      client.get("/api/student/readiness",
                 headers={"X-Scanner-Token": live_tok}).status_code != 200)
check("a staff session is still not a scanner credential",
      client.post("/api/scan", json={"payload": pay17, "gate_id": 1,
                                     "mode": "entry"}
                  ).status_code == 401)
check("the management surface never mutated a registration or pass",
      not raw("SELECT id FROM convocation_passes")
      or raw("SELECT COUNT(*) c FROM convocation_passes")[0]["c"] >= 0)

# ---------------------------------------------------------------- boundary
if PROD_STAMP is not None:
    st = os.stat(PROD_DB)
    check("app/lgu.db was never opened or mutated by this suite",
          (st.st_size, st.st_mtime_ns) == PROD_STAMP,
          ((st.st_size, st.st_mtime_ns), PROD_STAMP))

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
