"""Phase 24F — announcement delivery honesty + role-gate authorization.

Two mandate questions, answered with direct API calls against a disposable
database (production DB never opened):

1. DELIVERY HONESTY (demo vs real). The volunteer/admin broadcast surface
   must never claim a delivery it did not perform. In the default "demo"
   mode the response note must state the announcement was only recorded,
   not sent by SMS. The stored broadcast is what the log serves back — the
   note is driven by config.BROADCAST_MODE, not by wishful wording.

2. ROLE-GATE AUTHORIZATION. Mutations carry the correct gate:
   - POST /api/broadcasts requires the admin PIN (401 without).
   - PUT /api/settings requires the admin PIN (401 without).
   - The staff announcement lifecycle (create/publish/archive) lives behind
     the staff session + CSRF guard on the exam blueprint; the student feed
     only ever sees published + student-audience rows.

The scenario-driven authz matrix (phase 20) already probes every route
anonymously; this test asserts the specific per-role gates and honesty
contract the release gate asked about, using real authenticated calls.
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p24f-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "p24f.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config                      # noqa: E402
import announcements as ann        # noqa: E402
import database                    # noqa: E402
import exam_auth                   # noqa: E402
from web.routes import create_app  # noqa: E402

config.require_test_db()
database.init_db()
database.seed()

PASS = 0
FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok   " + label)
    else:
        FAIL += 1
        print("FAIL " + label + (("  <- " + repr(extra)) if extra else ""))


app = create_app()
app.config.update(TESTING=True)
client = app.test_client()
PIN = config.ADMIN_PIN
MARKER = "P24F-DELIVERY-MARKER"

print("=" * 70)
print("Phase 24F — announcement delivery honesty + role-gate authorization")
print("BROADCAST_MODE =", config.BROADCAST_MODE)
print("=" * 70)

# ------------------------------------------------- 1. delivery honesty
print("\n[A] Broadcast never claims a delivery it did not perform")
r = client.post("/api/broadcasts", json={"message": MARKER,
                                        "audience": "All students"},
                headers={"X-Admin-Pin": PIN})
body = r.get_json() or {}
check("POST /api/broadcasts with the PIN is accepted",
      r.status_code == 200 and body.get("ok") is True, (r.status_code, body))
note = (body.get("note") or "").lower()
if config.BROADCAST_MODE == "demo":
    check("demo mode note states it was NOT sent by SMS",
          "not sent by sms" in note or "demo" in note, body.get("note"))
else:
    check("real mode note states the gateway is not configured",
          "not configured" in note or "recorded" in note, body.get("note"))
# The honesty contract: a note must never promise an SMS/gateway delivery.
check("note never claims SMS/gateway delivery was performed",
      not re.search(r"\bsent\b(?!.*not)", note) or "not sent" in note,
      body.get("note"))

# The stored row is what the log serves back — the announcement really was
# recorded (not merely acknowledged).
log = client.get("/api/broadcasts").get_json().get("log", [])
check("the broadcast is recorded in the served log",
      any(b.get("message") == MARKER for b in log),
      [b.get("message") for b in log][:3])

# ------------------------------------------------- 2. role-gate authz
print("\n[B] Mutations carry the correct role gate")
r = client.post("/api/broadcasts", json={"message": "no pin attempt"})
check("POST /api/broadcasts WITHOUT the PIN is 401",
      r.status_code == 401, r.status_code)
r = client.put("/api/settings", json={"expected_attendance": "5"})
check("PUT /api/settings WITHOUT the PIN is 401",
      r.status_code == 401, r.status_code)
r = client.put("/api/settings", json={"expected_attendance": "5"},
               headers={"X-Admin-Pin": PIN})
check("PUT /api/settings WITH the PIN is accepted",
      r.status_code == 200, r.status_code)
r = client.post("/api/broadcasts", json={"message": "x" * 9999},
                headers={"X-Admin-Pin": PIN})
check("oversized broadcast is rejected (400, bounded)",
      r.status_code == 400, r.status_code)
r = client.post("/api/broadcasts", json={"message": ""},
                headers={"X-Admin-Pin": PIN})
check("empty broadcast is rejected (400)",
      r.status_code == 400, r.status_code)

# A wrong PIN must not authenticate.
r = client.post("/api/broadcasts", json={"message": "wrong pin"},
                headers={"X-Admin-Pin": "0000"})
check("a wrong PIN is rejected (401)", r.status_code == 401, r.status_code)

# ------------------------------------ 3. staff lifecycle behind session
print("\n[C] Staff announcement lifecycle is session + CSRF gated")
STAFF = "p24fofficer"
PW = "P24F-Passw0rd!"
exam_auth.create_staff(STAFF, "P24F Officer", PW)
# Anonymous staff-page access redirects to login (never leaks). The exam
# blueprint is mounted under /exam, so the staff routes live at /exam/*.
r = client.get("/exam/announcements")
check("anonymous /exam/announcements redirects to the staff login",
      r.status_code in (302, 303) and "/login" in (r.headers.get("Location")
                                                   or ""),
      (r.status_code, r.headers.get("Location")))

# Log in with a real staff session + CSRF token.
with client.session_transaction() as s:
    s.clear()
r = client.get("/exam/login")
ltok = re.search(r'name="csrf_token" value="([^"]+)"',
                 r.get_data(as_text=True)).group(1)
r = client.post("/exam/login", data={"username": STAFF, "password": PW,
                                    "csrf_token": ltok})
check("staff login succeeds", r.status_code == 302, r.status_code)

# A staff POST without the CSRF token is refused (403).
with client.session_transaction() as s:
    s[exam_auth.SESSION_KEY] = 1
r = client.post("/exam/announcements/create",
                data={"title": "No CSRF", "body": "x", "audience": "students"})
check("staff POST without CSRF is refused (403)", r.status_code == 403,
      r.status_code)

# ------------------------------------ 4. student feed scoping via the API
print("\n[D] Student feed only exposes published student-audience rows")
db = database.get_db()
conv = db.execute("SELECT id FROM convocations WHERE is_active = 1"
                  ).fetchone()["id"]
# draft (students) — must NOT appear
ann.create(db, conv, ann.clean(
    {"title": "P24F draft", "body": "draft", "audience": "students"}, STAFF))
# published staff-audience — must NOT appear
staff_row = ann.create(db, conv, ann.clean(
    {"title": "P24F staff only", "body": "staff", "audience": "staff"}, STAFF))
ann.publish(db, staff_row, STAFF)
# published student-audience — MUST appear
pub = ann.create(db, conv, ann.clean(
    {"title": "P24F published", "body": "visible", "audience": "students"},
    STAFF))
ann.publish(db, pub, STAFF)
db.commit()
db.close()

feed = client.get("/api/student/announcements").get_json()
titles = [a["title"] for a in feed.get("announcements", [])]
check("published student row appears in the feed",
      "P24F published" in titles, titles)
check("draft row never appears", "P24F draft" not in titles, titles)
check("published staff-audience row never appears",
      "P24F staff only" not in titles, titles)

print("\n" + "-" * 70)
print("%d checks, %d failures" % (PASS, FAIL))
print("PROD_DB untouched (disposable %s)" % os.environ["LGU_DB_PATH"])
sys.exit(1 if FAIL else 0)
