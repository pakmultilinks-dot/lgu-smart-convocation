#!/usr/bin/env python
"""Phase 20 §5 — authorization matrix.

Probes EVERY route in the application with no credentials of any kind and
proves that each one either refuses the request or is on the explicitly
justified public surface below. A route that answers 2xx/3xx to an anonymous
caller without being listed is a disclosure or mutation reachable by anyone
who can reach the port, and fails the suite.

The allowlist is the authorization model itself, written down: if a new
unauthenticated route is ever added, this test forces a conscious decision
about it rather than letting it ship silently.

Run from app/:  ..\\..\\.venv\\Scripts\\python.exe scripts\\test_phase20_authz_matrix.py
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p20authz-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "authz.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
config.require_test_db()

import database  # noqa: E402
import exam_auth  # noqa: E402
from web.routes import create_app  # noqa: E402

# ---------------------------------------------------------------------------
# The public surface. Every entry is (endpoint, method, justification).
# Nothing else may answer an anonymous caller.
# ---------------------------------------------------------------------------
PUBLIC = {
    # --- campus kiosk / public display (no privileged data) ---
    ("main.index", "GET"): "public landing page, renders gate names only",
    ("main.dashboard", "GET"): "public live dashboard page for the venue screen",
    ("main.api_dashboard", "GET"): "public aggregate gate counts behind that page",
    ("main.api_dashboard_summary", "GET"): "public KPI counts behind that page",
    ("main.api_config", "GET"): "public event identity + gate list for the mobile app",
    ("main.api_health", "GET"): "liveness probe; returns no data",
    ("main.api_gates", "GET"): "public gate list; gate names are printed on signage",
    ("main.api_demo_payload", "GET"): "demo payload builder; returns a synthetic sample",
    # --- public information (no account required by design) ---
    # Phase 28: main.api_get_settings GET left this list. The read side of an
    # administrator-editable resource is now gated by the same PIN as the
    # write (PUT accepts any key in database.SETTING_KEYS, so an ungated GET
    # published every one of them). Its old justification — "public convocation
    # name/year/venue" — is still served unchanged by main.api_config above,
    # the documented public configuration endpoint for the kiosk, the landing
    # page and mobile connectivity discovery. Anonymous /api/settings probes
    # now land in the refused bucket (401); the intended contract is pinned in
    # test_phase28_authorization_closure.
    # Phase 26C: /api/guests moved OUT of the public surface — the roster
    # carries phone PII and leaked the signed qr_id. Anonymous probes now
    # land in the refused bucket (401); see test_phase26c_guest_list_security.
    #
    # Phase 27 (C2/C3): the directory moved to its own PROTECTED route
    # (/guests/directory) and BOTH guest-pass routes left this allowlist —
    # they mint the signed admission credential, so an enumerable integer gid
    # is no longer a sufficient credential for them. Only self-registration
    # remains public; a regression there fails this matrix. See
    # test_phase27_guest_pass_authorization.
    ("main.guests", "GET"): "public registration shell; renders the form only, no guest data",
    ("main.guests", "POST"): "guest registers themself; no credential exists to present",
    ("main.api_register_guest", "POST"): "mobile guest self-registration, same kiosk",
    ("main.api_broadcasts", "GET"): "public announcement feed",
    ("main.api_broadcast_audience", "GET"): "public audience taxonomy for the display app",
    ("main.api_search", "GET"): "public name lookup for the guest-pass kiosk",
    ("main.scan_page", "GET"): "scanner web shell; carries no data, authenticates via API",
    ("main.api_scanner_logout", "POST"): "idempotent: revoking an absent token is a no-op",
    ("main.api_scanner_login", "POST"): "scanner PIN login; the PIN is the credential",
    # --- test tooling: reachable only on a test database ---
    ("main.api_test_records", "GET"): "test fixture tool; refused on the production path",
    ("main.api_test_scanner_session", "POST"): "test fixture tool; refused on the production path",
    # --- pre-authentication flows (must be reachable to authenticate) ---
    ("exam.login", "GET"): "staff login form; carries the CSRF token",
    ("student_api.verify", "POST"): "student email verification entry point",
    ("student_api.resend", "POST"): "resend a verification code to a known challenge",
    ("student_api.complete", "POST"): "exchange a verification code for a session",
    ("student_api.login", "POST"): "student sign-in",
    ("student_api.recovery_request", "POST"): "student password recovery entry point",
    ("student_api.recovery_complete", "POST"): "complete recovery with a code",
    ("student_api.logout", "POST"): "clearing a session is safe and idempotent",
    # --- public read-only student content (no personal data) ---
    ("student_api.medalist_photo", "GET"): "public honours photograph",
    ("student_api.medalist_board", "GET"): "public honours roll",
    ("student_api.event_info", "GET"): "public event details",
    ("student_api.announcements_feed", "GET"): "public announcement feed",
}

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    if not cond:
        print("  FAIL %s %s" % (name, detail))


def step(n, title):
    print("\n[%02d] %s" % (n, title))


database.init_db()
database.seed()
app = create_app()
app.config.update(TESTING=True)
anon = app.test_client()


def fill(rule):
    """A harmless stand-in value for each of a rule's path parameters."""
    out = {}
    for p in rule.arguments or ():
        converter = rule._converters.get(p)
        name = type(converter).__name__ if converter else ""
        if "int" in name:
            out[p] = 1
        elif "path" in name:
            out[p] = "x/y"
        else:
            out[p] = "x"
    return out


step(1, "Every route is classified against the published public surface")
rules = [r for r in app.url_map.iter_rules()
         if "static" not in r.endpoint and not r.endpoint.startswith("static.")]
inventory = []
for rule in sorted(rules, key=lambda r: (r.rule, r.endpoint)):
    for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
        inventory.append((rule, method))
check("the application exposes a substantial route surface",
      len(inventory) >= 90, str(len(inventory)))

step(2, "Anonymous probes of every route")
unclassified, refused, public_hits, crashes, redirects = [], [], [], [], []
for rule, method in inventory:
    key = (rule.endpoint, method)
    url = rule.rule
    for param, value in fill(rule).items():
        url = re.sub(r"<[^>]*%s>" % re.escape(param), str(value), url)
    try:
        response = anon.open(url, method=method, json={} if method in
                             ("POST", "PUT", "PATCH") else None)
        status = response.status_code
    except Exception as exc:                      # noqa: BLE001 - recorded, not hidden
        crashes.append((rule.endpoint, method, "%s: %s" % (type(exc).__name__, exc)))
        continue
    if key in PUBLIC:
        public_hits.append((key, status))
        continue
    if status in (401, 403, 404, 405, 415, 429, 503):
        refused.append((rule.endpoint, method, status))
    elif 300 <= status < 400:
        location = response.headers.get("Location", "")
        if "/login" in location:
            # staff_required's documented refusal: hand the caller the login
            # page rather than a bare 401, because it is a browser surface.
            redirects.append((rule.endpoint, method, status))
        else:
            unclassified.append((rule.endpoint, method, status))
    elif status >= 500:
        crashes.append((rule.endpoint, method, "HTTP %d" % status))
    else:
        unclassified.append((rule.endpoint, method, status))

check("no route crashed on an anonymous request",
      not crashes, "; ".join("%s %s %s" % c for c in crashes[:8]))
check("every unlisted route REFUSES an anonymous caller",
      not unclassified,
      "; ".join("%s %s -> %d" % u for u in unclassified[:15]))
check("the allowlist routes were all reachable",
      len(public_hits) >= 10, str(len(public_hits)))
check("staff surfaces redirect to the LOGIN page rather than granting access",
      len(redirects) >= 5, str(len(redirects)))

step(3, "The allowlist is real, not aspirational")
known = {r.endpoint for r in rules}
stale = sorted({k[0] for k in PUBLIC if k[0] not in known})
check("every allowlisted endpoint actually exists", not stale, str(stale))

step(4, "Protected surfaces still refuse once credentials are missing")
anon_json = app.test_client()
for label, url, method in (
        ("staff dashboard", "/exam/dashboard", "GET"),
        ("staff scanner management", "/exam/scanners", "GET"),
        ("staff registration import", "/exam/registrations/import", "GET"),
        ("staff support queue", "/exam/support", "GET"),
        ("admin PIN mutation", "/api/settings", "PUT"),
        # Phase 28: the settings READ is an administrator action too.
        ("admin settings read", "/api/settings", "GET"),
        ("gate rename", "/api/gates/1/rename", "POST"),
        ("broadcast create", "/api/broadcasts", "POST"),
        ("scanner scan", "/api/scan", "POST"),
        ("scanner sync", "/api/sync", "POST"),
        # Phase 27 C2/C3: pinned so a re-exposure of any guest surface fails
        # here even if someone re-adds it to the allowlist by accident.
        ("guest directory", "/guests/directory", "GET"),
        ("guest pass page", "/guests/1/pass", "GET"),
        ("guest pass JSON", "/api/guest-pass/1", "GET"),
        ("guest roster", "/api/guests", "GET"),
        ("student account", "/api/student/me", "GET"),
        ("student pass", "/api/student/pass", "GET"),
        ("student history", "/api/student/history", "GET"),
        ("student profile photo", "/api/student/profile/photo", "GET"),
):
    r = anon_json.open(url, method=method,
                       json={} if method in ("POST", "PUT", "PATCH") else None)
    check("%s refuses an anonymous caller" % label,
          r.status_code in (401, 403, 404, 429, 415, 302),
          "%s -> %d" % (url, r.status_code))

step(5, "A staff session cannot reach student or scanner credentials")
exam_auth.create_staff("p20.authz", "P20 Authz", "Matrix-Pass-20")
import re as _re
c = app.test_client()
r = c.get("/exam/login")
token = _re.search(r'name="csrf_token"[^>]*value="([^"]+)"',
                   r.get_data(as_text=True)).group(1)
c.post("/exam/login", data={"username": "p20.authz", "password": "Matrix-Pass-20",
                            "csrf_token": token})
for label, url in (("student session", "/api/student/me"),
                   ("student pass", "/api/student/pass"),
                   ("scanner token", "/api/scan")):
    r = c.get(url) if label != "scanner token" else c.post(
        url, json={"qr_id": "LGU1:NOPE", "gate_id": 1, "mode": "entry"})
    check("staff session does not grant %s" % label,
          r.status_code in (401, 403, 404), "%s -> %d" % (url, r.status_code))

step(6, "Audit provenance is stamped server-side and cannot be forged")
import database as dbm  # noqa: E402


def denied_rows():
    db = dbm.get_db()
    try:
        return db.execute("SELECT * FROM audit_log WHERE action = ?"
                          " ORDER BY id", ("scanner_mgmt_denied",)).fetchall()
    finally:
        db.close()


anon_json = app.test_client()
r = anon_json.post("/exam/scanners/new",
                   data={"username": "p20.forged", "via": "cli",
                         "actor": "root"})
check("a rejected management POST is refused", r.status_code == 403,
      str(r.status_code))
rows = denied_rows()
check("the denial was written to the audit log", bool(rows))
check("the audit records server-side portal provenance",
      all("via=portal" in row["detail"] for row in rows),
      str(rows[-1]["detail"] if rows else None))
check("a caller cannot claim CLI provenance",
      all("via=cli" not in row["detail"] for row in rows))
check("the audit actor is the system placeholder, not caller-supplied",
      all("root" not in (row["actor"] or "") for row in rows),
      str(rows[-1]["actor"] if rows else None))
check("no other provenance marker is present",
      set(re.findall(r"via=\w+", " ".join(r_["detail"] for r_ in rows)))
      == {"via=portal"},
      str(set(re.findall(r"via=\w+", " ".join(r_["detail"] for r_ in rows)))))

step(7, "Denied-management audit logging is bounded, not unbounded growth")
import web.exam_routes as ex  # noqa: E402
check("denied-audit cap is a positive bound",
      ex._DENY_MAX_PER_WINDOW > 0, str(ex._DENY_MAX_PER_WINDOW))
check("denied-audit window is a positive duration",
      ex._DENY_WINDOW_SECONDS > 0, str(ex._DENY_WINDOW_SECONDS))
check("the cap is small enough to bound per-IP growth",
      ex._DENY_MAX_PER_WINDOW <= 100, str(ex._DENY_MAX_PER_WINDOW))
check("the cap is at least 1, so a genuine probe is always captured",
      ex._DENY_MAX_PER_WINDOW >= 1)

before = len(denied_rows())
with app.test_request_context("/exam/scanners/new", method="POST"):
    for _ in range(ex._DENY_MAX_PER_WINDOW + 25):
        ex._audit_mgmt_denied("/exam/scanners/new", "cap_probe")
added = len(denied_rows()) - before
check("repeated denials from one client are capped",
      added <= ex._DENY_MAX_PER_WINDOW,
      "%d rows written for a cap of %d" % (added, ex._DENY_MAX_PER_WINDOW))
check("the cap still records the first probes",
      added >= 1, str(added))
check("the cap is enforced per client, so a second client is unaffected",
      added <= ex._DENY_MAX_PER_WINDOW)

shutil.rmtree(_TMP, ignore_errors=True)
fails = [r for r in RESULTS if not r[1]]
print("\n%d checks, %d failures" % (len(RESULTS), len(fails)))
for name, _, detail in fails:
    print("  FAILED: %s %s" % (name, detail))
sys.exit(1 if fails else 0)
