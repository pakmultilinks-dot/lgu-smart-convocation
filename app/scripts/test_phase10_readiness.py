"""Phase 10 integration: student convocation readiness centre + reminders.

Proves the whole personalized-readiness loop on ONE disposable temp database:
a signed-in student's readiness checklist and reminders are computed
server-side from authoritative records (claimed registration, profile photo,
the published event snapshot, published announcements, own support requests).
Completion reflects backend state — never a screen being opened. Required
items (registration issue, staff awaiting information) are not dismissible,
so a dismissal can never hide an unresolved problem or erase official data;
only informational reminders are. Reminder read/dismiss state is persisted
server-side and validated against the live reminder set, so a client cannot
dismiss an arbitrary key. Students only ever see their own readiness.
Synthetic records only; app/lgu.db is never opened (stat-stamped before and
after to prove it).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase10_readiness.py
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

TMP = tempfile.mkdtemp(prefix="lgu-p10s-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "readiness.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "student-photos")

from io import BytesIO  # noqa: E402

from openpyxl import Workbook  # noqa: E402

import config  # noqa: E402
config.require_test_db()
import announcements as ann  # noqa: E402
import database  # noqa: E402
import emailer  # noqa: E402
import exam_auth  # noqa: E402
import exam_registrations as reg  # noqa: E402
import readiness as rd  # noqa: E402
import web.routes as vr  # noqa: E402
import web.student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
STAFF_USER, STAFF_PW = "p10 officer", "readiness-pass-10"
AVA = ("ava.shah@uni.edu.pk", "REG-9101", "09101", "Ava Shah")
BOB = ("bob.reed@uni.edu.pk", "REG-9102", "09102", "Bob Reed")


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


def signup(email, reg_no, roll, name, password="readiness-pass-10"):
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


def login(email, password="readiness-pass-10"):
    return spost("/api/student/login", {"email": email,
                                        "password": password})


def reset_limits():
    for bucket in sr._HITS.values():
        bucket.clear()
    vr._PIN_FAILS.clear()


def rd_for(token):
    st, body = sget("/api/student/readiness", token)
    return st, (body.get("readiness") or {})


def keys_of(section, data):
    return [i["key"] for i in data.get(section, [])]


def item_of(data, key):
    for i in data.get("items", []):
        if i["key"] == key:
            return i
    return None


def reminder_of(data, key):
    for r in data.get("reminders", []):
        if r["key"] == key:
            return r
    return None


def mark(token, key, action):
    return spost("/api/student/readiness/reminders", {"key": key,
                                                      "action": action}, token)


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

exam_auth.create_staff(STAFF_USER, "P10 Officer", STAFF_PW)
page = html(client.get("/exam/login"))
TOK = csrf_of(page)
r = client.post("/exam/login", data={"csrf_token": TOK, "username":
                                     STAFF_USER, "password": STAFF_PW},
                follow_redirects=True)
check("boot: staff login lands on the dashboard",
      r.status_code == 200 and "Dashboard" in html(r))
# Login rotates the session CSRF token — re-fetch it before any POST.
TOK = csrf_of(html(client.get("/exam/event")))

# A convocation with a CONFIRMED date + rehearsal, then two registrations.
client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-11-01",
                  "confirmed_date": "2026-11-15", "rehearsal_date":
                  "2026-11-10", "rehearsal_time": "10:30",
                  "venue": "Readiness Hall",
                  "instructions": "Bring your student card."})
client.post("/exam/event/publish", data={"csrf_token": TOK})
batch_resp = client.post(
    "/exam/registrations/import",
    data={"csrf_token": TOK,
          "file": (BytesIO(xlsx([["REG-9101", AVA[0], AVA[2], AVA[3],
                                  "Computer Science"],
                                 ["REG-9102", BOB[0], BOB[2], BOB[3],
                                  "Electrical Engineering"]])),
                   "regs.xlsx")},
    content_type="multipart/form-data")
loc = batch_resp.headers.get("Location", "")
BID = int(re.search(r"/import/(\d+)", loc).group(1)) \
    if re.search(r"/import/(\d+)", loc) else 0
check("registrations: the import previews before committing", BID > 0, loc)
client.post("/exam/registrations/import/%d/commit" % BID,
            data={"csrf_token": TOK})

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

# ------------------------------------------- C. readiness needs a session
reset_limits()
check("security: readiness requires a signed-in student",
      sget("/api/student/readiness")[0] == 401)
check("security: reminder write requires a signed-in student",
      spost("/api/student/readiness/reminders",
            {"key": "profile:photo", "action": "read"})[0] == 401)

# --------------------------------- D. active reg + confirmed event + photo
st, body = rd_for(AVA_TOKEN)
check("ready: a signed-in student gets a readiness payload",
      st == 200 and body.get("summary") is not None, (st, body))
reg_item = item_of(body, "registration")
check("ready: an active claimed registration is confirmed (done)",
      reg_item and reg_item["status"] == "done"
      and reg_item["kind"] == "required", reg_item)
ev_item = item_of(body, "event_date")
check("ready: a confirmed published date reads as officially confirmed",
      ev_item and ev_item["status"] == "done" and "confirmed" in ev_item["detail"].lower()
      and "provisional" not in ev_item["detail"].lower(), ev_item)
reh_item = item_of(body, "rehearsal")
check("ready: a published rehearsal appears as its own item",
      reh_item is not None and "2026-11-10" in reh_item["detail"], reh_item)
photo_item = item_of(body, "profile_photo")
check("ready: an incomplete profile photo is an outstanding required item",
      photo_item and photo_item["kind"] == "required"
      and photo_item["status"] == "todo", photo_item)
s = body["summary"]
check("ready: the summary counts required done vs outstanding",
      s["required_total"] >= 3 and s["required_done"] >= 2
      and s["outstanding"] >= 1, s)

# Add a photo -> completion reflects backend state (not a screen opening).
prof = raw("SELECT * FROM student_profiles"
           " WHERE account_id = (SELECT id FROM student_accounts"
           "  WHERE university_email = ?)", (AVA[0],))[0]
raw("UPDATE student_profiles SET photo_file = 'ava.png',"
    " photo_updated_at = '2026-10-01 09:00:00' WHERE account_id = ?",
    (prof["account_id"],))
st, body = rd_for(AVA_TOKEN)
photo_item = item_of(body, "profile_photo")
check("ready: storing a photo flips the photo item to done",
      photo_item and photo_item["status"] == "done", photo_item)
check("ready: the photo reminder is gone once the photo exists",
      reminder_of(body, "profile:photo") is None, body.get("reminders"))

# -------------------------------------- E. expected (provisional) date
# Re-publish with only an expected date -> provisional, never "confirmed".
TOK = csrf_of(html(client.get("/exam/event")))
client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-11-01",
                  "confirmed_date": "", "rehearsal_date": "",
                  "rehearsal_time": "", "venue": "Readiness Hall",
                  "instructions": ""})
client.post("/exam/event/publish", data={"csrf_token": TOK})
st, body = rd_for(AVA_TOKEN)
ev_item = item_of(body, "event_date")
check("dates: an expected-only date is provisional, not confirmed",
      ev_item and "provisional" in ev_item["detail"].lower()
      and ev_item["status"] != "done", ev_item)
check("dates: the expected-date reminder labels itself provisional",
      "not officially confirmed" in
      (reminder_of(body, "event:%s:date" % CONV) or {}).get("reason", "").lower(),
      reminder_of(body, "event:%s:date" % CONV))
# Restore the confirmed publication for the rest of the run.
TOK = csrf_of(html(client.get("/exam/event")))
client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-11-01",
                  "confirmed_date": "2026-11-15", "rehearsal_date":
                  "2026-11-10", "rehearsal_time": "10:30",
                  "venue": "Readiness Hall",
                  "instructions": "Bring your student card."})
client.post("/exam/event/publish", data={"csrf_token": TOK})

# --------------------------------- F. announcements create reminders
with app.test_request_context("/exam"):
    db = database.get_db()
    a = ann.create(db, CONV, ann.clean(
        {"title": "Card collection closes Friday",
         "body": "Collect your card by Friday.",
         "audience": "students", "is_important": "1"}, "p10 officer"))
    ann.publish(db, a, "p10 officer")
    db.commit()
st, body = rd_for(AVA_TOKEN)
a_rem = reminder_of(body, "announcement:%s" % a["id"])
check("announcements: a published important announcement becomes a reminder",
      a_rem is not None and a_rem["dismissible"] is True, a_rem)
ann_item = item_of(body, "announcements")
check("announcements: the checklist links the announcements feed",
      ann_item is not None and ann_item["action"]["route"] ==
      "/(student)/announcements", ann_item)

# ---------------------------- G. support request needing student action
reset_limits()
st, body = spost("/api/student/support",
                 {"category": "correction", "subject": "Wrong department",
                  "message": "Please correct my department."}, AVA_TOKEN)
RID = body.get("request", {}).get("id", 0)
check("support: the student opened a request", st == 200 and RID > 0, (st, body))
raw("UPDATE support_requests SET status = 'info_required',"
    " updated_at = '2026-10-09 12:00:00' WHERE id = ?", (RID,))
st, body = rd_for(AVA_TOKEN)
sup_item = item_of(body, "support:%d" % RID)
check("support: an info_required request is an attention item",
      sup_item and sup_item["status"] == "attention"
      and sup_item["kind"] == "required", sup_item)
sup_rem = reminder_of(body, "support:%d:info_required" % RID)
check("support: the staff information request is a high reminder",
      sup_rem and sup_rem["priority"] == "high", sup_rem)
check("support: the info-required reminder is NOT dismissible",
      sup_rem and sup_rem["dismissible"] is False, sup_rem)

# --------------------------- H. cancelled / revoked registration attention
raw("UPDATE convocation_registrations SET status = 'cancelled'"
    " WHERE registration_number = 'REG-9102'")
st, body = rd_for(BOB_TOKEN)
breg = item_of(body, "registration")
check("reg: a cancelled registration is an attention item",
      breg and breg["status"] == "attention", breg)
brem = reminder_of(body, "registration:%s:cancelled" % CONV)
check("reg: the cancelled-registration reminder is high and not dismissible",
      brem and brem["priority"] == "high" and brem["dismissible"] is False, brem)
raw("UPDATE convocation_registrations SET status = 'revoked'"
    " WHERE registration_number = 'REG-9102'")
st, body = rd_for(BOB_TOKEN)
check("reg: a revoked registration is also an attention item",
      (item_of(body, "registration") or {})["status"] == "attention",
      item_of(body, "registration"))
raw("UPDATE convocation_registrations SET status = 'active'"
    " WHERE registration_number = 'REG-9102'")

# -------------------------------- I. reminder read + dismissal behavior
st, body = rd_for(AVA_TOKEN)
reset_limits()
st, mbody = mark(AVA_TOKEN, "announcement:%s" % a["id"], "read")
check("reminders: an informational reminder can be marked read",
      st == 200 and mbody.get("state") == "read", (st, mbody))
st, body = rd_for(AVA_TOKEN)
check("reminders: a read reminder stays but reports state=read",
      (reminder_of(body, "announcement:%s" % a["id"]) or {}).get("state") == "read",
      reminder_of(body, "announcement:%s" % a["id"]))
st, mbody = mark(AVA_TOKEN, "announcement:%s" % a["id"], "dismiss")
check("reminders: an informational reminder can be dismissed",
      st == 200 and mbody.get("state") == "dismissed", (st, mbody))
st, body = rd_for(AVA_TOKEN)
check("reminders: a dismissed reminder drops off the active list",
      reminder_of(body, "announcement:%s" % a["id"]) is None,
      body.get("reminders"))
check("reminders: the dismissal persisted server-side",
      raw("SELECT * FROM student_reminder_state WHERE account_id = ?"
          " AND reminder_key = ?",
          (prof["account_id"], "announcement:%s" % a["id"]))[0]["state"]
      == "dismissed")

# --- required reminders can never be dismissed (no hiding an issue) ------
st, mbody = mark(AVA_TOKEN, "support:%d:info_required" % RID, "dismiss")
check("reminders: an unresolved support reminder cannot be dismissed",
      st == 400, (st, mbody))
st, body = rd_for(AVA_TOKEN)
check("reminders: the support reminder is still present after a dismiss try",
      reminder_of(body, "support:%d:info_required" % RID) is not None)
st, mbody = mark(BOB_TOKEN, "registration:%s:cancelled" % CONV, "dismiss")
check("reminders: a registration-issue reminder cannot be dismissed",
      st == 400, (st, mbody))

# ---- arbitrary / unknown keys are rejected (no trusting the client) -----
check("reminders: an unknown key is rejected",
      mark(AVA_TOKEN, "not:a:real:key", "dismiss")[0] == 400)
check("reminders: a missing action is rejected",
      spost("/api/student/readiness/reminders",
            {"key": "profile:photo"}, AVA_TOKEN)[0] == 400)

# ---------------------------------- J. dedup + refresh idempotence
st, first = rd_for(AVA_TOKEN)
st, second = rd_for(AVA_TOKEN)
check("dedup: repeated refresh returns a stable required-item set",
      keys_of("items", first) == keys_of("items", second),
      (keys_of("items", first), keys_of("items", second)))
check("dedup: repeated refresh returns a stable reminder set",
      keys_of("reminders", first) == keys_of("reminders", second))
# Marking the same reminder read twice is idempotent (no error, no dup rows).
# The rehearsal reminder is still live (published event), unlike profile:photo
# which correctly vanished once the photo was stored.
reset_limits()
mark(AVA_TOKEN, "event:%s:rehearsal" % CONV, "read")
st, mbody = mark(AVA_TOKEN, "event:%s:rehearsal" % CONV, "read")
check("dedup: marking read twice is idempotent",
      st == 200 and mbody.get("state") == "read", (st, mbody))
check("dedup: only one state row exists per (account, key)",
      len(raw("SELECT * FROM student_reminder_state WHERE account_id = ?"
              " AND reminder_key = ?",
              (prof["account_id"], "event:%s:rehearsal" % CONV))) == 1)

# ------------------------- K. student-to-student data isolation
st, bbody = rd_for(BOB_TOKEN)
check("isolation: Bob's readiness has no trace of Ava's support item",
      "support:%d" % RID not in keys_of("items", bbody)
      and "support:%d:info_required" % RID not in keys_of("reminders", bbody),
      (keys_of("items", bbody), keys_of("reminders", bbody)))
check("isolation: Ava's readiness still shows her own support item",
      "support:%d" % RID in keys_of("items", rd_for(AVA_TOKEN)[1]))
# A student cannot mark a reminder that belongs to another student's set.
st, _ = rd_for(AVA_TOKEN)
reset_limits()
check("isolation: Bob cannot mark Ava's support reminder",
      mark(BOB_TOKEN, "support:%d:info_required" % RID, "read")[0] == 400)

# --------------- L. a server error is not a "missing registration" verdict
real = rd.reg.active_convocation
rd.reg.active_convocation = lambda db: (_ for _ in ()).throw(RuntimeError("boom"))
app.config["PROPAGATE_EXCEPTIONS"] = False
try:
    st, body = sget("/api/student/readiness", AVA_TOKEN)
    check("errors: a server error answers 5xx, never an empty readiness",
          500 <= st < 600 and "readiness" not in body, (st, body))
finally:
    rd.reg.active_convocation = real
    app.config["PROPAGATE_EXCEPTIONS"] = True
st, body = rd_for(AVA_TOKEN)
check("errors: readiness recovers after the fault clears",
      st == 200 and item_of(body, "registration") is not None, (st, body))

# ------------------------------------ M. preservation of prior workflows
st, body = sget("/api/student/event")
check("preserve: the published event feed still works",
      st == 200 and (body.get("event") or {}).get("date_state") in
      ("confirmed", "expected", "not_announced"), (st, body))
st, body = sget("/api/student/announcements")
check("preserve: the announcements feed still works",
      st == 200 and body.get("total", 0) >= 1, (st, body))
st, body = sget("/api/student/support", AVA_TOKEN)
check("preserve: the support list still works",
      st == 200 and body.get("total", 0) >= 1, (st, body))
st, body = sget("/api/student/medalists")
check("preserve: the medalist board still works", st == 200, (st, body))

# ------------------------------------------------- N. database boundary
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
