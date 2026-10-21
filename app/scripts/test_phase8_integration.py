"""Phase 8 integration: admin portal -> student app round trips.

Proves the authoritative data flow end-to-end on ONE disposable temp
database: every admin publishing workflow (event details, announcements,
registration corrections/status, medalists) reaches the student API ONLY
through the explicit publish step, and every correction/revocation reaches
an open student session through the server (never a stale client cache).
Includes the security/permissions battery and the dashboard-metrics
verification. Synthetic records only; app/lgu.db is never opened
(stat-stamped before and after to prove it).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase8_integration.py
"""

import os
import secrets
import re
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

# Stat-stamp the production database BEFORE anything runs: the boundary
# check at the end proves this suite never opened or mutated it (size +
# mtime_ns; content is never read — opening it would break the rule).
PROD_DB = os.path.join(APP_DIR, "lgu.db")
if os.path.exists(PROD_DB):
    _prod_stat = os.stat(PROD_DB)
    PROD_STAMP = (_prod_stat.st_size, _prod_stat.st_mtime_ns)
else:
    PROD_STAMP = None

TMP = tempfile.mkdtemp(prefix="lgu-p8i-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "integration.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "student-photos")

from io import BytesIO  # noqa: E402

from openpyxl import Workbook  # noqa: E402
from PIL import Image  # noqa: E402

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import emailer  # noqa: E402
import exam_auth  # noqa: E402
import exam_registrations as reg  # noqa: E402
import web.routes as vr  # noqa: E402
import web.exam_routes as exr  # noqa: E402
import web.student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
STAFF_USER, STAFF_PW = "p8i officer", "integration-pass-9"
AV = ("ava.shah@uni.edu.pk", "REG-8001", "08001", "Ava Shah")


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


def png_bytes(color=(201, 76, 76)):
    buf = BytesIO()
    Image.new("RGB", (48, 48), color).save(buf, "PNG")
    return buf.getvalue()


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


TEST_PASSWORD = secrets.token_urlsafe(24)


def signup(email, reg_no, roll, name, password=TEST_PASSWORD):
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


def login(email, password=TEST_PASSWORD):
    return spost("/api/student/login", {"email": email,
                                        "password": password})


def reset_limits():
    for bucket in sr._HITS.values():
        bucket.clear()
    exr._EXAM_FAILS.clear()
    vr._PIN_FAILS.clear()


def metrics():
    """dashboard_metrics uses url_for, so it needs a request context."""
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
check("boot: baseline - no publication exists yet, students see nothing",
      sget("/api/student/event")[1] == {"convocation": None, "event": None})

exam_auth.create_staff(STAFF_USER, "P8I Officer", STAFF_PW)
page = html(client.get("/exam/login"))
TOK = csrf_of(page)
r = client.post("/exam/login", data={"csrf_token": TOK, "username":
                                     STAFF_USER, "password": STAFF_PW},
                follow_redirects=True)
check("boot: staff login lands on the dashboard",
      r.status_code == 200 and "Dashboard" in html(r))
TOK = csrf_of(html(client.get("/exam/event")))

# dashboard on an empty convocation asks for the import first
m = metrics()
check("dashboard: an empty convocation links to the import screen",
      m["totals"]["total"] == 0 and any("Import" in i["label"]
                                        for i in m["issues"]), m)

# ------------------------------------ B. event details -> student app
r = client.post("/exam/event/save",
                data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                      "year": "2026", "expected_date": "2026-11-01",
                      "confirmed_date": "2026-11-15",
                      "rehearsal_date": "2026-11-10",
                      "rehearsal_time": "10:30",
                      "venue": "Integration Hall",
                      "instructions": "Bring your student card."})
check("event: staff can draft-save the working details",
      r.status_code in (200, 302), r.status_code)
st, body = sget("/api/student/event")
check("event: an unpublished draft never reaches the student app",
      body["convocation"] is None, body)

r = client.post("/exam/event/publish", data={"csrf_token": TOK},
                follow_redirects=True)
st, body = sget("/api/student/event")
check("event: publishing pushes the snapshot to the student app",
      body["convocation"] is not None and
      body["event"]["venue"] == "Integration Hall" and
      body["event"]["confirmed_date"] == "2026-11-15" and
      body["event"]["date_state_label"] == "Officially confirmed", body)

client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-11-01",
                  "confirmed_date": "2026-11-15", "rehearsal_date":
                  "2026-11-10", "rehearsal_time": "10:30",
                  "venue": "Main Auditorium (revised)",
                  "instructions": "Bring your student card."})
st, body = sget("/api/student/event")
check("event: a later edit keeps showing the last PUBLISHED venue",
      body["event"]["venue"] == "Integration Hall", body["event"])
client.post("/exam/event/publish", data={"csrf_token": TOK})
st, body = sget("/api/student/event")
check("event: re-publishing carries the revision to the app",
      body["event"]["venue"] == "Main Auditorium (revised)", body["event"])

client.post("/exam/event/create",
            data={"csrf_token": TOK, "name": "Convocation 2027",
                  "year": "2027", "expected_date": "2027-06-05"})
new_conv = raw("SELECT id FROM convocations WHERE year = '2027'")[0]
client.post("/exam/event/activate",
            data={"csrf_token": TOK, "convocation_id": new_conv["id"]})
check("event: switching the active convocation empties the student feed",
      sget("/api/student/event")[1] == {"convocation": None, "event": None})
client.post("/exam/event/activate",
            data={"csrf_token": TOK, "convocation_id": CONV})
check("event: re-selecting the convocation restores the published feed",
      sget("/api/student/event")[1]["event"]["venue"] ==
      "Main Auditorium (revised)")

# ------------------------------ C. announcements -> student app feed
r = client.post("/exam/announcements/create",
                data={"csrf_token": TOK, "title": "Gates open at 9 AM",
                      "body": "Please be seated before 9:30.",
                      "audience": "students", "is_important": "on"})
loc = r.headers.get("Location", "")
ANN1 = int(re.search(r"/announcements/(\d+)", loc).group(1)) \
    if re.search(r"/announcements/(\d+)", loc) else 0
check("announcements: a new announcement is created as a draft",
      ANN1 > 0, loc)
st, feed = sget("/api/student/announcements")
check("announcements: drafts never reach the student feed",
      all(a["title"] != "Gates open at 9 AM"
          for a in feed.get("announcements", [])), feed)

client.post("/exam/announcements/%d/publish" % ANN1,
            data={"csrf_token": TOK})
st, feed = sget("/api/student/announcements")
hit = next((a for a in feed.get("announcements", [])
            if a["title"] == "Gates open at 9 AM"), None)
check("announcements: publishing pushes it to the student feed",
      hit is not None and hit["is_important"] is True, feed)

r = client.post("/exam/announcements/create",
                data={"csrf_token": TOK, "title": "Staff briefing room",
                      "body": "Volunteers meet in Room 2.",
                      "audience": "staff"})
ANN2 = int(re.search(r"/announcements/(\d+)", r.headers.get(
    "Location", "")).group(1)) if re.search(
        r"/announcements/(\d+)", r.headers.get("Location", "")) else 0
client.post("/exam/announcements/%d/publish" % ANN2,
            data={"csrf_token": TOK})
st, feed = sget("/api/student/announcements")
check("announcements: staff-audience rows never reach the student feed",
      all(a["title"] != "Staff briefing room"
          for a in feed.get("announcements", [])), feed)

client.post("/exam/announcements/%d/save" % ANN1,
            data={"csrf_token": TOK, "title": "Gates open at 8:45 AM",
                  "body": "Please be seated before 9:15.",
                  "audience": "students", "is_important": "on"})
st, feed = sget("/api/student/announcements")
titles = [a["title"] for a in feed.get("announcements", [])]
check("announcements: editing a published row updates the app feed",
      "Gates open at 8:45 AM" in titles and
      "Gates open at 9 AM" not in titles, titles)

client.post("/exam/announcements/%d/archive" % ANN1,
            data={"csrf_token": TOK})
st, feed = sget("/api/student/announcements")
check("announcements: archiving removes it from the student feed",
      all(a["title"] != "Gates open at 8:45 AM"
          for a in feed.get("announcements", [])), feed)
client.post("/exam/announcements/%d/restore" % ANN1,
            data={"csrf_token": TOK})
st, feed = sget("/api/student/announcements")
check("announcements: restoring returns it as a draft (still hidden)",
      all(a["title"] != "Gates open at 8:45 AM"
          for a in feed.get("announcements", [])), feed)
client.post("/exam/announcements/%d/publish" % ANN1,
            data={"csrf_token": TOK})
st, feed = sget("/api/student/announcements")
check("announcements: re-publishing restores the student feed entry",
      any(a["title"] == "Gates open at 8:45 AM"
          for a in feed.get("announcements", [])), feed)

# ---------------------- D. registration lifecycle -> student session
client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-11-01",
                  "confirmed_date": "2026-11-15", "rehearsal_date":
                  "2026-11-10", "rehearsal_time": "10:30",
                  "venue": "Main Auditorium (revised)",
                  "instructions": "Bring your student card."})
batch_resp = client.post(
    "/exam/registrations/import",
    data={"csrf_token": TOK,
          "file": (BytesIO(xlsx([["REG-8001", AV[0], AV[2], AV[3],
                                  "Computer Science"]])),
                   "regs.xlsx")},
    content_type="multipart/form-data")
loc = batch_resp.headers.get("Location", "")
BID = int(re.search(r"/import/(\d+)", loc).group(1)) \
    if re.search(r"/import/(\d+)", loc) else 0
check("registrations: the import previews before committing", BID > 0, loc)
client.post("/exam/registrations/import/%d/commit" % BID,
            data={"csrf_token": TOK})
AVROW = raw("SELECT * FROM convocation_registrations"
            " WHERE registration_number = 'REG-8001'")[0]
check("registrations: the committed row is attached to the convocation",
      AVROW["convocation_id"] == CONV and AVROW["status"] == "active", AVROW)

st, body = signup(*AV)
check("student: signing up claims the matching registration",
      st == 200 and body.get("ok") is True, (st, body))
st, tok_body = login(AV[0])
TOKEN = tok_body.get("token", "")
check("student: the account can sign in", bool(TOKEN))
st, me = sget("/api/student/me", TOKEN)
check("app session: /me shows the ACTIVE registration",
      me["registration"]["status"] == "active" and
      me["registration"]["student_name"] == "Ava Shah" and
      me["claimed_at"], me)

client.post("/exam/registrations/%d/correct" % AVROW["id"],
            data={"csrf_token": TOK, "university_email": AV[0],
                  "roll_number": AV[2],
                  "student_name": "Ava Shah (corrected)",
                  "department": "Electrical Engineering"})
st, me = sget("/api/student/me", TOKEN)
check("app session: an admin correction reaches the student immediately",
      me["registration"]["student_name"] == "Ava Shah (corrected)" and
      me["registration"]["department"] == "Electrical Engineering", me)

client.post("/exam/registrations/%d/status" % AVROW["id"],
            data={"csrf_token": TOK, "action": "cancel"})
st, me = sget("/api/student/me", TOKEN)
check("app session: a cancellation is served honestly to the session",
      st == 200 and me["registration"]["status"] == "cancelled", me)
m = metrics()
check("dashboard: the stale claim is surfaced as an issue",
      any("no longer active" in i["text"] for i in m["issues"]), m["issues"])

client.post("/exam/registrations/%d/status" % AVROW["id"],
            data={"csrf_token": TOK, "action": "reinstate"})
st, me = sget("/api/student/me", TOKEN)
check("app session: reinstating returns the registration to active",
      me["registration"]["status"] == "active", me)

client.post("/exam/registrations/%d/status" % AVROW["id"],
            data={"csrf_token": TOK, "action": "revoke"})
st, me = sget("/api/student/me", TOKEN)
check("app session: a revocation is served to the open session",
      me["registration"]["status"] == "revoked", me)
r = client.post("/exam/registrations/%d/status" % AVROW["id"],
                data={"csrf_token": TOK, "action": "reinstate"})
check("registrations: a revoked registration cannot be reinstated",
      "Cannot reinstate" in html(r), html(r)[:200])

# --------------------------------- E. medalists -> public student board
r = client.post("/exam/medalists/new",
                data={"csrf_token": TOK, "department": "Computer Science",
                      "student_name": "Zara Khan", "award_category": "gold",
                      "position": "1st", "reference_number": "REG-8001"})
loc = r.headers.get("Location", "")
MID = int(re.search(r"/medalists/(\d+)", loc).group(1)) \
    if re.search(r"/medalists/(\d+)", loc) else 0
check("medalists: a new record is created as a draft", MID > 0, loc)
r = client.post("/exam/medalists/%d/publish" % MID,
                data={"csrf_token": TOK}, follow_redirects=True)
check("medalists: publishing without a picture is refused",
      "picture" in html(r).lower(), html(r)[:200])
st, board = sget("/api/student/medalists")
check("medalists: the draft never reaches the public board",
      board.get("total") == 0, board)
check("medalists: an unpublished photo answers 404",
      client.get("/api/student/medalists/photo/%d" % MID).status_code == 404)

client.post("/exam/medalists/%d/photo" % MID,
            data={"csrf_token": TOK,
                  "photo": (BytesIO(png_bytes()), "zara.png")},
            content_type="multipart/form-data")
check("medalists: the uploaded picture is stored",
      bool(raw("SELECT photo_file FROM medalists WHERE id = ?",
               (MID,))[0]["photo_file"]))
client.post("/exam/medalists/%d/publish" % MID, data={"csrf_token": TOK})
st, board = sget("/api/student/medalists")
hit = next((x for x in board.get("medalists", [])
            if x["student_name"] == "Zara Khan"), None)
check("medalists: publishing pushes the record to the public board",
      hit is not None and hit["award_category"] == "gold", board)
photo = client.get("/api/student/medalists/photo/%d" % MID)
check("medalists: the published picture is served publicly",
      photo.status_code == 200 and photo.mimetype == "image/png")
check("medalists: the public payload carries no reference numbers",
      "reference_number" not in html(client.get("/api/student/medalists")))

client.post("/exam/medalists/%d/unpublish" % MID, data={"csrf_token": TOK})
st, board = sget("/api/student/medalists")
check("medalists: withdrawing removes it from the board again",
      all(x["student_name"] != "Zara Khan"
          for x in board.get("medalists", [])), board)
check("medalists: the withdrawn photo answers 404 again",
      client.get("/api/student/medalists/photo/%d" % MID).status_code == 404)
client.post("/exam/medalists/%d/publish" % MID, data={"csrf_token": TOK})

# ------------------------------------------- F. security & permissions
fresh = app.test_client()
r = fresh.get("/exam/event")
check("security: exam screens require a staff session",
      r.status_code == 302 and "/exam/login" in r.headers.get("Location", ""),
      (r.status_code, r.headers.get("Location")))
r = client.post("/exam/event/save", data={"name": "x", "year": "2026"})
check("security: exam POSTs without CSRF are rejected 403",
      r.status_code == 403, r.status_code)
check("security: student endpoints without a token are rejected 401",
      sget("/api/student/me")[0] == 401 and
      spost("/api/student/profile", {"phone": "0300 0000000"})[0] == 401)
check("security: settings mutations without a PIN are rejected 401",
      client.put("/api/settings", json={"expected_attendance": "5"}
                 ).status_code == 401)
check("security: settings mutations with a wrong PIN are rejected 401",
      client.put("/api/settings", json={"expected_attendance": "5"},
                 headers={"X-Admin-Pin": "----wrong----"}
                 ).status_code == 401)
current = client.get("/api/settings",
                     headers={"X-Admin-Pin": config.ADMIN_PIN}).get_json()
sample_key = next(iter(current))
ok = client.put("/api/settings", json={sample_key: current[sample_key]},
                headers={"X-Admin-Pin": config.ADMIN_PIN})
check("security: the correct PIN passes the administrator gate",
      ok.status_code == 200, ok.status_code)
reset_limits()
st, bad = login(AV[0], "not-the-password")
check("security: a wrong student password is rejected 401", st == 401, st)
reset_limits()

public_text = (html(client.get("/api/student/event")) +
               html(client.get("/api/student/announcements")) +
               html(client.get("/api/student/medalists")))
check("security: public payloads leak no registration or account fields",
      "registration_number" not in public_text and
      "university_email" not in public_text and
      "REG-8001" not in public_text and AV[0] not in public_text)
check("security: PIN attempts are rate limited 429",
      all(client.put("/api/settings", json={},
                     headers={"X-Admin-Pin": "----wrong----"}
                     ).status_code == 401
          for _ in range(config.PIN_RATE_MAX_FAILS)) and
      client.put("/api/settings", json={},
                 headers={"X-Admin-Pin": config.ADMIN_PIN}
                 ).status_code == 429)
vr._PIN_FAILS.clear()

# ------------------------------------------- G. dashboard metrics
m = metrics()
check("dashboard: totals count the real registration rows",
      m["totals"]["total"] == 1 and m["totals"].get("active") == 0 and
      m["totals"].get("revoked") == 1, m["totals"])
check("dashboard: claimed/unclaimed reflect the claim table",
      m["claimed"] == 1 and m["unclaimed"] == 0, m)
check("dashboard: incomplete profiles count real photo gaps",
      m["incomplete_profiles"] == 1, m["incomplete_profiles"])
check("dashboard: the convocation card matches the active event",
      m["conv"]["name"] == "LGU Convocation 2026" and
      m["event"]["published"] is True and m["event"]["dirty"] is False and
      m["event"]["announcements"]["published"] >= 2, m["event"])
check("dashboard: medalist metrics count the real board",
      m["medalists"]["total"] == 1 and m["medalists"]["draft"] == 0,
      m["medalists"])
check("dashboard: every issue links to an authorized screen",
      m["issues"] and all(i.get("href", "").startswith("/")
                          for i in m["issues"]), m["issues"])
resp = client.get("/exam/", follow_redirects=True)
page = html(resp)
# Phase 29 adds the two per-occasion admission tiles (main convocation /
# rehearsal), taking the exam dashboard from 22 to 24 tiles.
check("dashboard: the template renders the 24 KPI tiles",
      resp.status_code == 200 and page.count("kpi-tile") == 24,
      (resp.status_code, page.count("kpi-tile"), page[:160]))

# ------------------------------------------------ H. database boundary
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
