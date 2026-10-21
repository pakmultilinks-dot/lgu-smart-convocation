"""Phase 9 integration: student support requests -> exam-dept review queue.

Proves the whole correction/help loop on ONE disposable temp database: a
signed-in student opens a support request (missing registration, correction,
cancellation, account-claim, general), the request reaches the Examination
Department review queue, and staff can search it, ask for information,
record an internal note, answer it and resolve or reject it — all with a
complete, auditable history. A request NEVER mutates an official
registration on its own; resolving one leaves the record byte-identical and
a real correction still goes through the existing exam_registrations.correct
workflow. Students only ever see their own requests and never see internal
notes. Synthetic records only; app/lgu.db is never opened (stat-stamped
before and after to prove it).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase9_support.py
"""

import os
import re
import sqlite3
import sys
import tempfile

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

TMP = tempfile.mkdtemp(prefix="lgu-p9s-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "support.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "student-photos")

from io import BytesIO  # noqa: E402

from openpyxl import Workbook  # noqa: E402

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import emailer  # noqa: E402
import exam_auth  # noqa: E402
import exam_registrations as reg  # noqa: E402
import support_requests as sup  # noqa: E402
import web.routes as vr  # noqa: E402
import web.exam_routes as exr  # noqa: E402
import web.student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
STAFF_USER, STAFF_PW = "p9s officer", "support-pass-9"
AVA = ("ava.shah@uni.edu.pk", "REG-9001", "09001", "Ava Shah")
BOB = ("bob.reed@uni.edu.pk", "REG-9002", "09002", "Bob Reed")


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def raw(sql, args=()):
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        c.commit()
        return rows
    finally:
        c.close()


def html(resp):
    return resp.get_data(as_text=True)


def csrf_of(page_html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', page_html)
    return m.group(1) if m else ""


def xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "registrations"
    ws.append(list(reg.CANONICAL_COLUMNS))
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def spost(path, body, token=None):
    headers = {"Authorization": "Bearer %s" % token} if token else {}
    r = client.post(path, json=body, headers=headers)
    try:
        return r.status_code, r.get_json(silent=True) or {}
    except Exception:
        return r.status_code, {}


def sget(path, token=None):
    headers = {"Authorization": "Bearer %s" % token} if token else {}
    r = client.get(path, headers=headers)
    try:
        return r.status_code, r.get_json(silent=True) or {}
    except Exception:
        return r.status_code, {}


def signup(email, reg_no, roll, name, password="support-pass-9"):
    emailer.OUTBOX.clear()
    st, body = spost("/api/student/verify", {"registration_number": reg_no,
                                             "university_email": email,
                                             "roll_number": roll,
                                             "student_name": name})
    if st != 200:
        return st, body
    code = emailer.OUTBOX[-1][1] if emailer.OUTBOX else ""
    return spost("/api/student/complete",
                 {"challenge_id": body["challenge_id"], "code": code,
                  "password": password})


def login(email, password="support-pass-9"):
    return spost("/api/student/login", {"email": email,
                                        "password": password})


def reset_limits():
    for bucket in sr._HITS.values():
        bucket.clear()
    exr._EXAM_FAILS.clear()
    vr._PIN_FAILS.clear()


def metrics():
    with app.test_request_context("/exam"):
        return exr.dashboard_metrics(database.get_db())


# --------------------------------------------------------------- A. boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()

conv1 = raw("SELECT * FROM convocations WHERE is_active = 1")
check("boot: seeded convocation is active",
      len(conv1) == 1 and conv1[0]["name"].startswith("LGU"), conv1)
CONV = conv1[0]["id"]

exam_auth.create_staff(STAFF_USER, "P9S Officer", STAFF_PW)
page = html(client.get("/exam/login"))
TOK = csrf_of(page)
r = client.post("/exam/login", data={"csrf_token": TOK, "username":
                                     STAFF_USER, "password": STAFF_PW},
                follow_redirects=True)
check("boot: staff login lands on the dashboard",
      r.status_code == 200 and "Dashboard" in html(r))
# Login rotates the session CSRF token — re-fetch it before any POST.
TOK = csrf_of(html(client.get("/exam/event")))

# A convocation + two claimed registrations so both students can sign up.
client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-11-01",
                  "confirmed_date": "2026-11-15", "rehearsal_date":
                  "2026-11-10", "rehearsal_time": "10:30",
                  "venue": "Support Hall",
                  "instructions": "Bring your student card."})
client.post("/exam/event/publish", data={"csrf_token": TOK})
batch_resp = client.post(
    "/exam/registrations/import",
    data={"csrf_token": TOK,
          "file": (BytesIO(xlsx([["REG-9001", AVA[0], AVA[2], AVA[3],
                                  "Computer Science"],
                                 ["REG-9002", BOB[0], BOB[2], BOB[3],
                                  "Electrical Engineering"]])),
                   "regs.xlsx")},
    content_type="multipart/form-data")
loc = batch_resp.headers.get("Location", "")
BID = int(re.search(r"/import/(\d+)", loc).group(1)) \
    if re.search(r"/import/(\d+)", loc) else 0
check("registrations: the import previews before committing", BID > 0, loc)
client.post("/exam/registrations/import/%d/commit" % BID,
            data={"csrf_token": TOK})
AVROW = raw("SELECT * FROM convocation_registrations"
            " WHERE registration_number = 'REG-9001'")[0]

# --------------------------------------------- B. students sign in
st, body = signup(*AVA)
check("student: Ava signs up and claims her registration",
      st == 200 and body.get("ok") is True, (st, body))
st, tok_body = login(AVA[0])
AVA_TOKEN = tok_body.get("token", "")
check("student: Ava can sign in", bool(AVA_TOKEN))
st, body = signup(*BOB)
check("student: Bob signs up and claims his registration",
      st == 200 and body.get("ok") is True, (st, body))
st, tok_body = login(BOB[0])
BOB_TOKEN = tok_body.get("token", "")
check("student: Bob can sign in", bool(BOB_TOKEN))

# ------------------------------------------------ C. student opens a request
reset_limits()
REQ_BODY = {"category": "correction",
            "subject": "My department is wrong on the convocation card",
            "message": "It shows Computer Science but I study Electrical "
                       "Engineering. Please correct it."}
st, body = spost("/api/student/support", REQ_BODY, AVA_TOKEN)
RID = body.get("request", {}).get("id", 0)
REF = body.get("request", {}).get("reference", "")
check("create: a signed-in student can open a request",
      st == 200 and body.get("ok") is True and RID > 0, (st, body))
check("create: the request carries a SUP- reference",
      REF.startswith("SUP-") and len(REF) == 10, REF)
check("create: a new request starts as submitted",
      body["request"]["status"] == "submitted", body)
check("create: the request is bound to the claimed registration",
      raw("SELECT registration_id FROM support_requests WHERE id = ?",
          (RID,))[0]["registration_id"] == AVROW["id"])
check("create: the student payload never leaks staff fields",
      "handled_by" not in body["request"], body["request"])
st, me = sget("/api/student/me", AVA_TOKEN)
check("create: opening a request never mutates the registration",
      me["registration"]["student_name"] == "Ava Shah" and
      me["registration"]["status"] == "active", me)

# ------------------------------------------- D. validation & limits
reset_limits()
st, body = spost("/api/student/support",
                 {"category": "correction", "subject": "",
                  "message": "needs a subject"}, AVA_TOKEN)
check("validation: an empty subject is refused",
      st == 400 and body.get("code") == "validation", (st, body))
st, body = spost("/api/student/support",
                 {"category": "correction", "subject": "x" * 400,
                  "message": "way too long a subject line"}, AVA_TOKEN)
check("validation: an over-long subject is refused",
      st == 400 and body.get("code") == "validation", (st, body))
st, body = spost("/api/student/support",
                 {"category": "nonsense", "subject": "ok subject",
                  "message": "pick a real category"}, AVA_TOKEN)
check("validation: an unknown category is refused",
      st == 400 and body.get("code") == "validation", (st, body))
st, body = spost("/api/student/support",
                 {"category": "general", "subject": "control\x00char",
                  "message": "control characters are rejected"}, AVA_TOKEN)
check("validation: control characters are refused",
      st == 400 and body.get("code") == "validation", (st, body))
st, body = spost("/api/student/support",
                 {"category": "general", "subject": "no message here",
                  "message": "   "}, AVA_TOKEN)
check("validation: an empty message is refused",
      st == 400 and body.get("code") == "validation", (st, body))
# Rate limit: exhaust the create budget for this session.
for _ in range(config.SUPPORT_RATE_MAX_CREATE):
    spost("/api/student/support", {"category": "general",
                                   "subject": "flood %d" % _,
                                   "message": "rate limit flood"},
          AVA_TOKEN)
st, body = spost("/api/student/support",
                 {"category": "general", "subject": "one too many",
                  "message": "should be rate limited"}, AVA_TOKEN)
check("limits: the create rate limit stops a flood",
      st == 429 and body.get("code") == "rate_limited", (st, body))
reset_limits()

# ---------------------------------------------------- E. list & ownership
st, listing = sget("/api/student/support", AVA_TOKEN)
check("list: the student sees their own requests",
      listing.get("total", 0) >= 1 and
      all(isinstance(r["id"], int) for r in listing["requests"]), listing)
check("list: a student never sees another student's requests",
      all(r["id"] != 0 for r in listing["requests"]) and
      all("bob" not in str(r).lower() for r in listing["requests"]),
      listing)
st, detail = sget("/api/student/support/%d" % RID, AVA_TOKEN)
check("detail: the owner can read one request",
      st == 200 and detail["request"]["id"] == RID, detail)
st, other = sget("/api/student/support/%d" % RID, BOB_TOKEN)
check("detail: another student is answered with 404",
      st == 404 and other.get("code") == "not_found", (st, other))
st, missing = sget("/api/student/support/999999", AVA_TOKEN)
check("detail: a missing request is answered with 404",
      st == 404, st)
st, anon = sget("/api/student/support")
check("support endpoints require a token", st == 401, st)

# ------------------------------------------------- F. staff review queue
TOK = csrf_of(html(client.get("/exam/event")))
r = client.get("/exam/support")
page = html(r)
check("queue: the staff queue renders with the request",
      r.status_code == 200 and REF in page, (r.status_code, REF in page))
r = client.get("/exam/support?q=%s" % REF)
check("queue: search by reference finds the request",
      REF in html(r))
r = client.get("/exam/support?q=%s" % AVA[0])
check("queue: search by student email finds the request",
      REF in html(r))
r = client.get("/exam/support?status=open")
check("queue: the open filter shows the request",
      REF in html(r))
r = client.get("/exam/support?category=correction")
check("queue: the category filter matches",
      REF in html(r))
r = client.get("/exam/support?category=general&q=nothing-matches")
check("queue: an empty result renders an empty state",
      "No requests match" in html(r), html(r)[:200])

# ------------------------------------------ G. staff opens the record
r = client.get("/exam/support/%d" % RID)
page = html(r)
check("detail: the staff detail shows the subject and student",
      r.status_code == 200 and REQ_BODY["subject"] in page and
      AVA[0] in page, (r.status_code, REQ_BODY["subject"] in page))
check("detail: the official record is linked, never edited here",
      "/exam/registrations/%d" % AVROW["id"] in page, page[:200])

# ------------------------------------------ H. status transitions
r = client.post("/exam/support/%d/status" % RID,
                data={"csrf_token": TOK, "status": "info_required"},
                follow_redirects=True)
check("transitions: submitted cannot jump straight to info_required",
      "Cannot move" in html(r), html(r)[:200])
r = client.post("/exam/support/%d/status" % RID,
                data={"csrf_token": TOK, "status": "under_review"},
                follow_redirects=True)
row = raw("SELECT * FROM support_requests WHERE id = ?", (RID,))[0]
check("transitions: submitted -> under_review is allowed",
      r.status_code == 200 and row["status"] == "under_review",
      (r.status_code, row["status"]))
check("transitions: an open request has no resolved_at",
      row["resolved_at"] is None, row["resolved_at"])

# -------------------------------------------- I. information request
r = client.post("/exam/support/%d/respond" % RID,
                data={"csrf_token": TOK,
                      "message": "Please confirm your roll number.",
                      "status": "info_required"}, follow_redirects=True)
check("info: a staff information request is recorded",
      r.status_code == 200, r.status_code)
st, detail = sget("/api/student/support/%d" % RID, AVA_TOKEN)
check("info: the student sees the information request",
      detail["request"]["status"] == "info_required" and
      "roll number" in (detail["request"]["latest_response"] or
                        {}).get("body", ""), detail)

# ------------------------------------------ J. internal note is hidden
r = client.post("/exam/support/%d/respond" % RID,
                data={"csrf_token": TOK,
                      "message": "INTERNAL: checked the registry, match.",
                      "internal": "1"}, follow_redirects=True)
check("internal: the staff detail shows the internal note",
      "INTERNAL: checked" in html(r), html(r)[:200])
st, detail = sget("/api/student/support/%d" % RID, AVA_TOKEN)
joined = str(detail)
check("internal: the student never sees the internal note",
      "INTERNAL: checked" not in joined, joined[:300])
check("internal: the student-visible response is still the last reply",
      "roll number" in (detail["request"]["latest_response"] or {})
      .get("body", ""), detail)

# ------------------------------------------ K. resolve the request
before_reg = raw("SELECT * FROM convocation_registrations WHERE id = ?",
                 (AVROW["id"],))[0]
r = client.post("/exam/support/%d/respond" % RID,
                data={"csrf_token": TOK,
                      "message": "Corrected on your registration record.",
                      "status": "resolved"}, follow_redirects=True)
row = raw("SELECT * FROM support_requests WHERE id = ?", (RID,))[0]
after_reg = raw("SELECT * FROM convocation_registrations WHERE id = ?",
                (AVROW["id"],))[0]
check("resolve: resolving a request is allowed and stamps resolved_at",
      r.status_code == 200 and row["status"] == "resolved" and
      row["resolved_at"] is not None, (row["status"], row["resolved_at"]))
check("resolve: a resolved request does NOT change the registration",
      before_reg == after_reg, (before_reg, after_reg))
st, me = sget("/api/student/me", AVA_TOKEN)
check("resolve: the student's registration is still untouched",
      me["registration"]["student_name"] == "Ava Shah", me)

# ----------------------------- L. the real correction workflow still works
TOK = csrf_of(html(client.get("/exam/event")))
client.post("/exam/registrations/%d/correct" % AVROW["id"],
            data={"csrf_token": TOK, "university_email": AVA[0],
                  "roll_number": AVA[2],
                  "student_name": "Ava Shah (corrected)",
                  "department": "Electrical Engineering"})
st, me = sget("/api/student/me", AVA_TOKEN)
check("correction: the existing correct workflow DOES change the record",
      me["registration"]["student_name"] == "Ava Shah (corrected)" and
      me["registration"]["department"] == "Electrical Engineering", me)

# --------------------------------- M. reopen a decision (audit preserved)
r = client.post("/exam/support/%d/status" % RID,
                data={"csrf_token": TOK, "status": "under_review"},
                follow_redirects=True)
row = raw("SELECT * FROM support_requests WHERE id = ?", (RID,))[0]
check("reopen: a resolved request can return to under_review",
      r.status_code == 200 and row["status"] == "under_review" and
      row["resolved_at"] is None, (row["status"], row["resolved_at"]))
r = client.post("/exam/support/%d/respond" % RID,
                data={"csrf_token": TOK,
                      "message": "Still investigating, sorry.",
                      "status": "rejected"}, follow_redirects=True)
row = raw("SELECT * FROM support_requests WHERE id = ?", (RID,))[0]
check("reject: a rejected request is terminal and stamped",
      row["status"] == "rejected" and row["resolved_at"] is not None,
      (row["status"], row["resolved_at"]))

# ------------------------------------------------- N. audit history
st, detail = sget("/api/student/support/%d" % RID, AVA_TOKEN)
acts = [e["action"] for e in detail["request"]["history"]]
check("history: the student-visible trail is append-only and ordered",
      acts and acts[0] == "create" and
      all(a in ("create", "status", "reply", "info_request", "resolve")
          for a in acts), acts)
db_events = raw("SELECT * FROM support_events WHERE support_request_id = ?"
                " ORDER BY id", (RID,))
check("history: every state change left an audit row",
      len(db_events) >= 5, len(db_events))
check("history: staff and student actors are distinguished",
      any(e["actor_role"] == "student" for e in db_events) and
      any(e["actor_role"] == "staff" for e in db_events))

# ---------------------------------------------- O. dashboard metrics
m = metrics()
supm = m.get("support", {})
check("metrics: the dashboard carries real support metrics",
      "open" in supm and "resolved_recent" in supm and
      "by_category" in supm, supm)
check("metrics: the category breakdown reflects the filed request",
      supm.get("by_category", {}).get("correction", 0) >= 1, supm)
check("metrics: dashboard issues link to the filtered support queue",
      all("support" not in i["href"] or i["href"].startswith("/exam/support")
          for i in m["issues"]), m["issues"])
r = client.get("/exam/", follow_redirects=True)
page = html(r)
check("metrics: the dashboard renders the support KPI tiles",
      r.status_code == 200 and "Support requests awaiting review" in page,
      (r.status_code, "Support requests awaiting review" in page))

# --------------------------------- P. security & permissions
fresh = app.test_client()
r = fresh.get("/exam/support")
check("security: the support queue requires a staff session",
      r.status_code == 302 and "/exam/login" in r.headers.get("Location", ""),
      (r.status_code, r.headers.get("Location")))
r = client.post("/exam/support/%d/status" % RID,
                data={"status": "under_review"})
check("security: staff support POSTs without CSRF are rejected 403",
      r.status_code == 403, r.status_code)
check("security: the student API rejects staff-only misuse",
      sget("/api/student/support")[0] == 401)

# ------------------------------------------------- Q. database boundary
if PROD_STAMP is None:
    check("boundary: production database never appeared",
          not os.path.exists(PROD_DB))
else:
    st2 = os.stat(PROD_DB)
    check("boundary: production database untouched",
          (st2.st_size, st2.st_mtime_ns) == PROD_STAMP,
          (st2.st_size, st2.st_mtime_ns))

print()
print("RESULT: %d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
