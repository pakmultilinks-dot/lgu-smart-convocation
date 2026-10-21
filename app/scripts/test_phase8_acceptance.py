"""Phase 8 acceptance: full-platform integration journeys across Phases 2-7.

Runs every Examination / Student / Volunteer workflow end-to-end against one
disposable temp database, plus the security, privacy, email-readiness and
dashboard-acceptance batteries. Synthetic records only; app/lgu.db is never
opened (stat-stamped at the end to prove it).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase8_acceptance.py
"""

import io
import os
import re
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

# Stat-stamp the production database BEFORE anything runs: the boundary
# check at the end proves this suite never opened or mutated it. The stamp
# records size + mtime_ns (no content read — opening the file for hashing
# would violate the never-open rule).
PROD_DB = os.path.join(APP_DIR, "lgu.db")
if os.path.exists(PROD_DB):
    _prod_stat = os.stat(PROD_DB)
    PROD_STAMP = (_prod_stat.st_size, _prod_stat.st_mtime_ns)
else:
    PROD_STAMP = None

TMP = tempfile.mkdtemp(prefix="lgu-p8-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "acceptance.db")
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
import exam_import  # noqa: E402
import exam_registrations as reg  # noqa: E402
import ids  # noqa: E402
import migrations  # noqa: E402
import student_auth as sa  # noqa: E402
import web.exam_routes as exr  # noqa: E402
import web.student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402
from _scanner_fixture import scanner_headers  # noqa: E402

failures = 0
checks = 0
STAFF_USER, STAFF_PW = "p8officer", "acceptance-pass-9"
AV = ("ava.shah@uni.edu.pk", "REG-8001", "08001", "Ava Shah")
BI = ("bilal.aslam@uni.edu.pk", "REG-8002", "08002", "Bilal Aslam")


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


def signup(email, reg_no, roll, name, password="acceptance-pass-9"):
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


def reset_limits():
    for bucket in sr._HITS.values():
        bucket.clear()
    exr._EXAM_FAILS.clear()


def reg_count(status=None):
    sql = "SELECT COUNT(*) FROM convocation_registrations"
    args = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    return raw(sql, args)[0]["COUNT(*)"]


# --------------------------------------------------------------- A. boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
# Phase 14: scans require an authenticated scanner session (all gates).
SCANNER_HDRS = scanner_headers(client)

check("boot: schema at the latest migration version",
      sqlite3.connect(config.DB_PATH).execute(
          "PRAGMA user_version").fetchone()[0] == migrations.MIGRATIONS[-1][0])
conv1 = raw("SELECT * FROM convocations WHERE is_active = 1")
check("boot: seeded convocation is active",
      len(conv1) == 1 and conv1[0]["name"].startswith("LGU"), conv1)
CONV = conv1[0]["id"]
check("boot: seven official gates seeded",
      raw("SELECT COUNT(*) FROM gates")[0]["COUNT(*)"] == 7)
check("boot: student roster seeded",
      raw("SELECT COUNT(*) FROM students")[0]["COUNT(*)"] >= 40)
OPS_BEFORE = {t: raw("SELECT * FROM %s ORDER BY rowid" % t)
              for t in ("students", "gates", "broadcasts", "settings")}

# ------------------------------------------- B. Examination: login journey
exam_auth.create_staff(STAFF_USER, "P8 Officer", STAFF_PW)
reset_limits()
page = html(client.get("/exam/login"))
TOK = csrf_of(page)
r = client.post("/exam/login", data={"csrf_token": TOK, "username":
                                     STAFF_USER, "password": "wrong-pw-xx"})
check("exam: wrong password is rejected 401",
      r.status_code == 401 and "Invalid username" in html(r))
r = client.post("/exam/login", data={"csrf_token": TOK, "username":
                                     STAFF_USER, "password": STAFF_PW},
                follow_redirects=True)
check("exam: staff login lands on the dashboard",
      r.status_code == 200 and "Dashboard" in html(r))
TOK = csrf_of(html(client.get("/exam/event")))
check("exam: session carries a CSRF token for state-changing POSTs", bool(TOK))

# ------------------------------------ C. Examination: login throttling
reset_limits()
for _ in range(5):
    client.post("/exam/login", data={"csrf_token": TOK, "username":
                                     "ghost", "password": "nope-nope-no"})
r = client.post("/exam/login", data={"csrf_token": TOK, "username":
                                     "ghost", "password": "nope-nope-no"})
check("exam: repeated failures are throttled 429",
      r.status_code == 429 and "Too many attempts" in html(r))
reset_limits()

# ------------------------------- D. Examination: create + select event
client.post("/exam/event/create", data={"csrf_token": TOK,
                                        "name": "Convocation 2027",
                                        "year": "2027",
                                        "expected_date": "2027-06-05"})
new_conv = raw("SELECT * FROM convocations WHERE year = '2027'")
check("exam: a second convocation can be created",
      len(new_conv) == 1 and not new_conv[0]["is_active"], new_conv)
client.post("/exam/event/activate",
            data={"csrf_token": TOK,
                  "convocation_id": new_conv[0]["id"]})
check("exam: selecting a convocation switches the active event",
      raw("SELECT COUNT(*) FROM convocations WHERE is_active = 1"
         )[0]["COUNT(*)"] == 1 and
      raw("SELECT is_active FROM convocations WHERE id = ?",
          (new_conv[0]["id"],))[0]["is_active"] == 1)
check("student: the unpublished 2027 event serves no event info",
      sget("/api/student/event")[1] == {"convocation": None, "event": None})
client.post("/exam/event/activate", data={"csrf_token": TOK,
                                           "convocation_id": CONV})
check("exam: the original convocation can be re-selected",
      raw("SELECT is_active FROM convocations WHERE id = ?",
          (CONV,))[0]["is_active"] == 1)
TOK = csrf_of(html(client.get("/exam/event")))

# --------------------------------- E. Examination: Excel import journey
rows = [
    ["REG-8001", AV[0], AV[2], AV[3], "BSCS"],
    ["REG-8002", BI[0], BI[2], BI[3], "BBA"],
    ["REG-8003", "chitra.das@uni.edu.pk", "08003", "Chitra Das", "EE"],
    ["REG-8004", "danish.rao@uni.edu.pk", "08004", "Danish Rao", "ME"],
    ["REG-8005", "not-an-email", "08005", "No Email", "BSCS"],   # invalid
    ["REG-8001", AV[0], AV[2], AV[3], "BSCS"],                   # duplicate
    ["REG-8001", "impostor@uni.edu.pk", "08099", "Impostor", "CS"],
]
r = client.post("/exam/registrations/import",
                data={"csrf_token": TOK,
                      "file": (BytesIO(xlsx(rows)), "roster.xlsx")},
                content_type="multipart/form-data")
m = re.search(r"/import/(\d+)", r.headers.get("Location", ""))
bid = int(m.group(1)) if m else 0
check("import: upload opens a review batch", bid > 0, r.headers)
review = html(client.get("/exam/registrations/import/%d" % bid))
check("import: preview lists the rejected rows for review",
      "university_email" in review and "duplicates row" in review,
      review[-400:])
check("import: preview commits nothing before review",
      reg_count() == 0)
r = client.post("/exam/registrations/import/%d/commit" % bid,
                data={"csrf_token": TOK, "mode": "insert"},
                follow_redirects=True)
check("import: committing adds exactly the valid rows",
      r.status_code == 200 and reg_count() == 4 and
      raw("SELECT result_json FROM import_batches WHERE id = ?",
          (bid,))[0]["result_json"] is not None,
      (reg_count(), r.status_code))
listing = html(client.get("/exam/registrations"))
check("import: committed students appear in the registration list",
      "Ava Shah" in listing and "Danish Rao" in listing)
check("import: invalid and conflicting rows were never applied",
      "No Email" not in listing and "Impostor" not in listing)

# ---------------------------- F. Examination: correct + status actions
reg_danish = raw("SELECT id FROM convocation_registrations"
                 " WHERE registration_number = 'REG-8004'")[0]["id"]
r = client.post("/exam/registrations/%d/correct" % reg_danish,
                data={"csrf_token": TOK, "university_email":
                      "danish.rao@uni.edu.pk", "roll_number": "08004",
                      "student_name": "Danish Rao", "department": "CE"},
                follow_redirects=True)
check("admin: a registration can be corrected with audit",
      r.status_code == 200 and
      raw("SELECT department FROM convocation_registrations WHERE id = ?",
          (reg_danish,))[0]["department"] == "CE")
client.post("/exam/registrations/%d/status" % reg_danish,
            data={"csrf_token": TOK, "action": "cancel"},
            follow_redirects=True)
check("admin: cancel moves the record to cancelled",
      raw("SELECT status FROM convocation_registrations WHERE id = ?",
          (reg_danish,))[0]["status"] == "cancelled")
client.post("/exam/registrations/%d/status" % reg_danish,
            data={"csrf_token": TOK, "action": "reinstate"},
            follow_redirects=True)
check("admin: reinstate returns it to active",
      raw("SELECT status FROM convocation_registrations WHERE id = ?",
          (reg_danish,))[0]["status"] == "active")
client.post("/exam/registrations/%d/status" % reg_danish,
            data={"csrf_token": TOK, "action": "revoke"},
            follow_redirects=True)
check("admin: revoke is terminal",
      raw("SELECT status FROM convocation_registrations WHERE id = ?",
          (reg_danish,))[0]["status"] == "revoked")
trail = raw("SELECT action FROM registration_audit"
            " WHERE registration_id = ? ORDER BY id", (reg_danish,))
check("admin: every status change is audited",
      [t["action"] for t in trail] ==
      ["import_insert", "correct", "cancel", "reinstate", "revoke"], trail)
check("admin: revoked records cannot be reinstated",
      client.post("/exam/registrations/%d/status" % reg_danish,
                  data={"csrf_token": TOK, "action": "reinstate"},
                  follow_redirects=True).status_code == 400)
check("admin: filters and pagination respond",
      client.get("/exam/registrations?status=revoked").status_code == 200 and
      client.get("/exam/registrations?page=2").status_code == 200)

# --------------------------------- G. Examination: dashboard acceptance
import medalists as med  # noqa: E402
import convocation_events as ev  # noqa: E402

db = database.get_db()
with app.test_request_context("/"):
    metrics = exr.dashboard_metrics(db)
db.close()
check("dashboard: totals equal the real record counts",
      metrics["totals"]["total"] == reg_count() and
      metrics["totals"].get("revoked") == reg_count("revoked"), metrics)
texts = [i["text"] for i in metrics["issues"]]
check("dashboard: skipped-import warning counts the 3 rejected rows",
      any("skipped 3 rows" in t for t in texts), texts)
check("dashboard: revoked-holding warning appears only when real",
      not any("no longer active" in t for t in texts), texts)
dash = html(client.get("/exam/dashboard"))
check("dashboard: no placeholder panels remain",
      "Not yet available" not in dash and 'href="#"' not in dash)
bad_links = []
for issue in metrics["issues"]:
    resp = client.get(issue["href"])
    if resp.status_code != 200:
        bad_links.append((issue["href"], resp.status_code))
check("dashboard: every warning link opens a working screen",
      not bad_links, bad_links)

# ------------------------------- H. Examination: medalist admin journey
client.post("/exam/medalists/new",
            data={"csrf_token": TOK, "department": "BSCS",
                  "student_name": "Medal Ava", "award_category": "gold",
                  "position": "1st", "reference_number": "REF-1"},
            follow_redirects=True)
med_gold = raw("SELECT * FROM medalists WHERE student_name = 'Medal Ava'")[0]
client.post("/exam/medalists/%d/publish" % med_gold["id"],
            data={"csrf_token": TOK}, follow_redirects=True)
check("medalists: publishing without a picture is blocked",
      raw("SELECT publication FROM medalists WHERE id = ?",
          (med_gold["id"],))[0]["publication"] == "draft")
client.post("/exam/medalists/%d/photo" % med_gold["id"],
            data={"csrf_token": TOK,
                  "photo": (BytesIO(png_bytes()), "ava.png")},
            content_type="multipart/form-data")
client.post("/exam/medalists/%d/publish" % med_gold["id"],
            data={"csrf_token": TOK}, follow_redirects=True)
check("medalists: publish succeeds once a picture is approved",
      raw("SELECT publication FROM medalists WHERE id = ?",
          (med_gold["id"],))[0]["publication"] == "published")
client.post("/exam/medalists/new",
            data={"csrf_token": TOK, "department": "BBA",
                  "student_name": "Medal Bilal", "award_category": "silver",
                  "position": "1st", "reference_number": "REF-2"},
            follow_redirects=True)
med_silver = raw(
    "SELECT * FROM medalists WHERE student_name = 'Medal Bilal'")[0]
client.post("/exam/medalists/%d/photo" % med_silver["id"],
            data={"csrf_token": TOK,
                  "photo": (BytesIO(png_bytes((60, 90, 200))), "bilal.png")},
            content_type="multipart/form-data")
client.post("/exam/medalists/%d/publish" % med_silver["id"],
            data={"csrf_token": TOK}, follow_redirects=True)
client.post("/exam/medalists/new",
            data={"csrf_token": TOK, "department": "EE",
                  "student_name": "Draft Medal", "award_category": "bronze",
                  "position": "1st", "reference_number": "REF-3"},
            follow_redirects=True)
board = sget("/api/student/medalists")[1]
check("medalists: public board spans departments, drafts excluded",
      board["total"] == 2 and
      {m["department"] for m in board["medalists"]} == {"BSCS", "BBA"},
      board)
keys = set()
for m in board["medalists"]:
    keys |= set(m.keys())
check("medalists: public payload exposes only approved fields",
      keys == {"id", "department", "student_name", "award_category",
               "position", "has_photo"}, keys)
photo = client.get("/api/student/medalists/photo/%d" % med_gold["id"])
check("medalists: approved picture is served",
      photo.status_code == 200 and photo.headers["Content-Type"] ==
      "image/png")
check("medalists: draft picture is never served",
      client.get("/api/student/medalists/photo/%d" % raw(
          "SELECT id FROM medalists WHERE student_name = 'Draft Medal'"
      )[0]["id"]).status_code == 404)

# --------------------- I. Examination: event + announcement publishing
client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-12-10",
                  "confirmed_date": "2026-12-18",
                  "rehearsal_date": "2026-12-11",
                  "rehearsal_time": "10:30", "venue": "Main Ground",
                  "instructions": "Bring your student ID card."},
            follow_redirects=True)
client.post("/exam/event/publish", data={"csrf_token": TOK},
            follow_redirects=True)
event = sget("/api/student/event")[1]["event"]
check("event: published info reaches students with confirmed date",
      event and event["confirmed_date"] == "2026-12-18" and
      event["rehearsal"]["time"] == "10:30" and
      event["date_state"] == "confirmed", event)
client.post("/exam/announcements/create",
            data={"csrf_token": TOK, "title": "Ceremony timing",
                  "body": "Doors open at 8:30 AM.", "audience": "students"},
            follow_redirects=True)
ann_students = raw("SELECT * FROM announcements"
                   " WHERE title = 'Ceremony timing'")[0]
client.post("/exam/announcements/%d/publish" % ann_students["id"],
            data={"csrf_token": TOK}, follow_redirects=True)
client.post("/exam/announcements/create",
            data={"csrf_token": TOK, "title": "Staff briefing",
                  "body": "Report at 7:00 AM.", "audience": "staff"},
            follow_redirects=True)
ann_staff = raw("SELECT * FROM announcements"
                " WHERE title = 'Staff briefing'")[0]
client.post("/exam/announcements/%d/publish" % ann_staff["id"],
            data={"csrf_token": TOK}, follow_redirects=True)
client.post("/exam/announcements/create",
            data={"csrf_token": TOK, "title": "Unpublished note",
                  "body": "Must never leak.", "audience": "students"},
            follow_redirects=True)
feed = sget("/api/student/announcements")[1]
check("announcements: feed shows published student rows only",
      feed["total"] == 1 and
      [a["title"] for a in feed["announcements"]] == ["Ceremony timing"],
      feed)
db = database.get_db()
draft_event = {**ev.details_of(ev.active(db)), "venue": "Secret Hall"}
ev.save_details(db, ev.active(db), draft_event, "p8officer")
db.commit()
db.close()
check("event: an unpublished edit never reaches students",
      sget("/api/student/event")[1]["event"]["venue"] == "Main Ground")
client.post("/exam/announcements/%d/unpublish" % ann_students["id"],
            data={"csrf_token": TOK}, follow_redirects=True)
check("announcements: unpublishing removes it from the feed",
      sget("/api/student/announcements")[1]["total"] == 0)
client.post("/exam/announcements/%d/publish" % ann_students["id"],
            data={"csrf_token": TOK}, follow_redirects=True)
check("announcements: it can be republished",
      sget("/api/student/announcements")[1]["total"] == 1)

# ---------------------------------------- J. Student: full signup journey
reset_limits()
st, body = signup(*AV)
check("student: verify + code + password completes signup",
      st == 200 and body.get("token"), (st, body))
tok_a1 = body.get("token", "")
check("student: signup reports the claimed registration",
      body["registration"]["registration_number"] == "REG-8001" and
      body["registration"]["status"] == "active", body)
st, body = spost("/api/student/login", {"email": AV[0],
                                        "password": "acceptance-pass-9"})
check("student: sign-in again with the new password works",
      st == 200 and body.get("token"))
tok_a2 = body.get("token", "")
st, body = spost("/api/student/profile", {"phone": "0300 1234567"},
                 token=tok_a2)
check("student: profile completion accepts a phone number",
      st == 200 and body["profile"]["phone"] == "0300 1234567")
st, body = spost("/api/student/profile/photo",
                 {"data": __import__("base64").b64encode(
                     png_bytes((40, 160, 90))).decode()},
                 token=tok_a2)
check("student: a valid profile picture uploads",
      st == 200 and body.get("profile", {}).get("photo") is True, (st, body))
st, me = sget("/api/student/me", token=tok_a2)
check("student: profile is complete end to end",
      me["completion"]["complete"] is True and
      me["registration"]["registration_number"] == "REG-8001", me)
photo = client.get("/api/student/profile/photo",
                   headers={"Authorization": "Bearer %s" % tok_a2})
check("student: own profile picture is served", photo.status_code == 200)

# --------------------------------- K. Student: recovery journey
reset_limits()
emailer.OUTBOX.clear()
st, body = spost("/api/student/recovery/request", {"email": AV[0]})
check("student: recovery request accepts the university email",
      st == 200 and emailer.OUTBOX, (st, body))
code = emailer.OUTBOX[-1][1]
st, body = spost("/api/student/recovery/complete",
                 {"email": AV[0], "code": code,
                  "password": "recovered-pass-8x"})
check("student: recovery completes with the emailed code",
      st == 200 and body.get("ok") is True, (st, body))
st, body = spost("/api/student/login", {"email": AV[0],
                                        "password": "recovered-pass-8x"})
check("student: the new password signs in", st == 200)
tok_a3 = body.get("token", "")
st, _ = spost("/api/student/login", {"email": AV[0],
                                     "password": "acceptance-pass-9"})
check("student: the old password is dead", st == 401)
check("student: recovery revoked earlier sessions",
      sget("/api/student/me", token=tok_a1)[0] == 401 and
      sget("/api/student/me", token=tok_a2)[0] == 401)
raw("UPDATE student_sessions SET expires_at = '2000-01-01T00:00:00+00:00'"
    " WHERE account_id = (SELECT id FROM student_accounts"
    "  WHERE university_email = ?)", (AV[0],))
check("student: expired sessions are rejected",
      sget("/api/student/me", token=tok_a3)[0] == 401)
st, body = spost("/api/student/login", {"email": AV[0],
                                        "password": "recovered-pass-8x"})
tok_a = body.get("token", "")
check("student: fresh sign-in restores access", st == 200 and tok_a)

# ------------------------------ L. Student: access + rejection handling
reset_limits()
st, body = signup(*BI)
check("student: a second student signs up", st == 200 and body.get("token"))
tok_b = body.get("token", "")
st, me_a = sget("/api/student/me", token=tok_a)
st, me_b = sget("/api/student/me", token=tok_b)
check("privacy: students only ever see their own records",
      me_a["account"]["email"] == AV[0] and
      me_b["account"]["email"] == BI[0])
check("privacy: a student cannot fetch another student's picture",
      client.get("/api/student/profile/photo",
                 headers={"Authorization": "Bearer %s" % tok_b}
                 ).status_code == 404)
reset_limits()
st, body = spost("/api/student/verify", {"registration_number": "REG-4040",
                                         "university_email":
                                         "ghost@uni.edu.pk",
                                         "roll_number": "04040",
                                         "student_name": "Ghost Person"})
check("student: unregistered records are rejected as unmatched",
      st == 404 and body.get("code") == "unmatched", (st, body))
st, body = spost("/api/student/verify", {"registration_number": AV[1],
                                         "university_email": AV[0],
                                         "roll_number": AV[2],
                                         "student_name": AV[3]})
check("student: duplicate claim of a linked registration is rejected",
      st == 409 and body.get("code") == "claimed", (st, body))
db = database.get_db()
reg_b = db.execute("SELECT * FROM convocation_registrations"
                   " WHERE university_email = ?", (BI[0],)).fetchone()
reg.set_status(db, reg_b, "revoke", "p8officer")
db.commit()
db.close()
reset_limits()
st, body = spost("/api/student/verify", {"registration_number": BI[1],
                                         "university_email": BI[0],
                                         "roll_number": BI[2],
                                         "student_name": BI[3]})
check("student: a revoked registration can never be claimed",
      st == 410 and body.get("code") == "revoked", (st, body))
db = database.get_db()
with app.test_request_context("/"):
    metrics = exr.dashboard_metrics(db)
db.close()
rev_text = [i["text"] for i in metrics["issues"]
            if "no longer active" in i["text"]]
check("dashboard: revoked-but-claimed records raise a real warning",
      len(rev_text) == 1 and "1 student account" in rev_text[0], rev_text)

# ------------------------------------- M. Examination: role separation
# Fresh client: no staff session — a student Bearer token must not unlock
# the session-based Examination portal.
fresh = app.test_client()
check("security: a student session cannot reach exam screens",
      fresh.get("/exam/dashboard",
                headers={"Authorization": "Bearer %s" % tok_a}
                ).status_code == 302)
check("security: state-changing POSTs without CSRF are rejected",
      client.post("/exam/event/publish").status_code == 403 and
      client.post("/exam/announcements/create",
                  data={"title": "x", "body": "y"}).status_code == 403 and
      client.post("/exam/medalists/new",
                  data={"department": "X"}).status_code == 403)
emailer.OUTBOX.clear()
st, body = spost("/api/student/verify", {"registration_number": "REG-8003",
                                         "university_email":
                                         "chitra.das@uni.edu.pk",
                                         "roll_number": "08003",
                                         "student_name": "Chitra Das"})
real_code = emailer.OUTBOX[-1][1] if emailer.OUTBOX else "000000"
wrong_code = str((int(real_code) + 1) % 10 ** len(real_code)).zfill(
    len(real_code))
st2, body2 = spost("/api/student/complete",
                    {"challenge_id": body["challenge_id"],
                     "code": wrong_code, "password": "wrong-code-pass-8x"})
check("student: a wrong verification code is refused",
      st2 == 400 and body2.get("code") == "code", (st2, body2))
bad_photo = spost("/api/student/profile/photo",
                  {"data": __import__("base64").b64encode(
                      b"not-an-image-at-all").decode()}, token=tok_a)
check("student: non-image uploads are rejected",
      bad_photo[0] == 400 and bad_photo[1].get("code") == "photo", bad_photo)

# ------------------------------- N. Exam import cannot partially apply
batch_preview = client.post(
    "/exam/registrations/import",
    data={"csrf_token": TOK,
          "file": (BytesIO(xlsx([["REG-7001", "a7@uni.edu.pk", "07001",
                                  "Row Seven", "BSCS"],
                                 ["REG-7002", "b7@uni.edu.pk", "07002",
                                  "Row Eight", "BSCS"]])), "atomic.xlsx")},
    content_type="multipart/form-data")
mbid = int(re.search(r"/import/(\d+)",
                     batch_preview.headers.get("Location", "")).group(1))
before = reg_count()
real_insert = exam_import._insert_row
calls = {"n": 0}


def _boom(db_, conv_id_, clean_, batch_id_, actor_):
    calls["n"] += 1
    if calls["n"] >= 2:
        raise RuntimeError("forced mid-commit failure (Phase 8)")
    return real_insert(db_, conv_id_, clean_, batch_id_, actor_)


exam_import._insert_row = _boom
r = client.post("/exam/registrations/import/%d/commit" % mbid,
                data={"csrf_token": TOK, "mode": "insert"},
                follow_redirects=True)
exam_import._insert_row = real_insert
check("import: a mid-commit failure rolls everything back",
      "fully rolled back" in html(r) and reg_count() == before,
      (reg_count(), before))
check("import: the failed batch is recorded as failed",
      raw("SELECT status FROM import_batches WHERE id = ?",
          (mbid,))[0]["status"] == "failed")

# ----------------------------------------- O. Email delivery readiness
reset_limits()
saved_mode = config.EMAIL_MODE
config.EMAIL_MODE = "disabled"
# Section M left a live pending challenge for this address; expire it so
# verify must actually attempt a (now impossible) send.
raw("UPDATE verification_challenges SET expires_at"
    " = '2000-01-01T00:00:00+00:00'"
    " WHERE university_email = 'chitra.das@uni.edu.pk'"
    " AND consumed_at IS NULL")
emailer.OUTBOX.clear()
st, body = spost("/api/student/verify", {"registration_number": "REG-8003",
                                         "university_email":
                                         "chitra.das@uni.edu.pk",
                                         "roll_number": "08003",
                                         "student_name": "Chitra Das"})
check("email: unconfigured delivery fails closed 503",
      st == 503 and body.get("code") == "email_unavailable", (st, body))
check("email: no verification code is ever issued silently",
      not emailer.OUTBOX)
check("email: signup did not falsely succeed — no account exists",
      raw("SELECT COUNT(*) FROM student_accounts WHERE university_email"
          " = 'chitra.das@uni.edu.pk'")[0]["COUNT(*)"] == 0)
st, body = spost("/api/student/recovery/request",
                 {"email": "chitra.das@uni.edu.pk"})
check("email: recovery also fails closed without leaking existence",
      st == 503 and body.get("code") == "email_unavailable", (st, body))
config.EMAIL_MODE = saved_mode

# ------------------------- P. Volunteer operations remain functional
reset_limits()
qr = raw("SELECT qr_id, name, roll_no FROM students"
         " WHERE roll_no NOT IN (SELECT host_roll_no FROM guests)"
         " ORDER BY id LIMIT 1")[0]
payload = ids.make_payload(qr["qr_id"])
res = client.post("/api/scan", json={"payload": payload, "gate_id": 1,
                                     "mode": "entry",
                                     "volunteer": "P8 Volunteer"},
                   headers=SCANNER_HDRS).get_json()
check("ops: a real student QR records an entry",
      res["status"] == "ok" and res["title"] == "ENTRY RECORDED", res)
res = client.post("/api/scan", json={"payload": payload, "gate_id": 2,
                                     "mode": "entry"},
                   headers=SCANNER_HDRS).get_json()
check("ops: a second entry is refused as already inside",
      res["title"] == "ALREADY INSIDE", res)
res = client.post("/api/scan", json={"payload": payload, "gate_id": 2,
                                     "mode": "exit"},
                   headers=SCANNER_HDRS).get_json()
check("ops: exit tracking still closes the entry",
      res["title"] == "EXIT RECORDED", res)
forged = client.post("/api/scan", json={"payload": "garbage-forged-qr",
                                        "gate_id": 1,
                                        "mode": "entry"},
                     headers=SCANNER_HDRS).get_json()
check("ops: forged codes are still rejected",
      forged["title"] == "INVALID CODE", forged)
guest = client.post("/api/guests", json={"name": "P8 Guest",
                                         "phone": "0300 0000008",
                                         "host_roll_no": qr["roll_no"]}
                    ).get_json()
gres = client.post("/api/scan", json={"payload": guest["payload"],
                                      "gate_id": 1, "mode": "entry"},
                   headers=SCANNER_HDRS).get_json()
check("ops: guest passes register and scan at the gate",
      guest["ok"] and gres["title"] == "GUEST ENTRY RECORDED", gres)
gres2 = client.post("/api/scan", json={"payload": guest["payload"],
                                       "gate_id": 3, "mode": "entry"},
                    headers=SCANNER_HDRS).get_json()
check("ops: guest passes stay single-use",
      gres2["title"] == "ALREADY USED", gres2)
check("ops: exam import never touched operational QR identities",
      {t: raw("SELECT * FROM %s ORDER BY rowid" % t)
       for t in ("students", "gates")} ==
      {"students": OPS_BEFORE["students"], "gates": OPS_BEFORE["gates"]})
check("ops: scans contain exactly the deliberate test scans",
      raw("SELECT COUNT(*) FROM scans")[0]["COUNT(*)"] == 3)
check("ops: broadcasts and settings stay untouched by exam/student flows",
      {t: raw("SELECT * FROM %s ORDER BY rowid" % t)
       for t in ("broadcasts", "settings")} ==
      {"broadcasts": OPS_BEFORE["broadcasts"],
       "settings": OPS_BEFORE["settings"]})

# ------------------------------------------------- Q. logout + hygiene
st, body = spost("/api/student/logout", {}, token=tok_a)
check("student: logout revokes the session token",
      st == 200 and sget("/api/student/me", token=tok_a)[0] == 401)
r = client.post("/exam/logout", data={"csrf_token": TOK},
                follow_redirects=False)
check("exam: logout returns to the login page",
      r.status_code == 302 and
      "/exam/login" in r.headers.get("Location", ""), r.headers)
check("exam: logged-out sessions are refused",
      client.get("/exam/dashboard").status_code == 302)

# Boundary: the production database must be byte-for-byte untouched by
# this run. Compare the stat-stamp taken before any test code executed
# (size + mtime_ns) with a fresh stat now — a size-only check would miss
# in-place rewrites, and a hardcoded size breaks whenever the production
# database legitimately grows between releases.
if PROD_STAMP is None:
    check("boundary: production database untouched",
          not os.path.exists(PROD_DB), "lgu.db appeared during the run")
else:
    _after = os.stat(PROD_DB)
    check("boundary: production database untouched",
          (_after.st_size, _after.st_mtime_ns) == PROD_STAMP,
          "size/mtime changed: %s -> %s" % (PROD_STAMP,
                                             (_after.st_size,
                                              _after.st_mtime_ns)))

print("")
print("%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
