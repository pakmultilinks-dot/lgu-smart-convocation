"""Phase 11 integration: digital convocation pass + student history.

Proves the whole invitation-pass and history loop on ONE disposable temp
database. The pass is an INFORMATIONAL, backend-computed invitation derived
from the claimed registration, its status, open support requests and the
PUBLISHED event snapshot — the client never grants eligibility. Critically,
NO QR is ever issued: convocation registrations are not linked to the
operational check-in roster (students/qr_id), so a pass code would not
validate at the gate, and this suite proves (a) the QR prerequisite is
reported as unsatisfied, (b) no QR is ever returned to the student, and
(c) opening a pass never inserts or replaces an operational roster row
(the §2 identity-substitution guard). History is a read-only, per-account
ledger of the convocations a student's verified records touch.
Synthetic records only; app/lgu.db is never opened (stat-stamped before
and after to prove it).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase11_pass_history.py
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
# check at the end proves this suite never opened or mutated it.
PROD_DB = os.path.join(APP_DIR, "lgu.db")
if os.path.exists(PROD_DB):
    _prod_stat = os.stat(PROD_DB)
    PROD_STAMP = (_prod_stat.st_size, _prod_stat.st_mtime_ns)
else:
    PROD_STAMP = None

TMP = tempfile.mkdtemp(prefix="lgu-p11pass-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "pass.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "student-photos")

from io import BytesIO  # noqa: E402

from openpyxl import Workbook  # noqa: E402
from PIL import Image  # noqa: E402

import config  # noqa: E402
config.require_test_db()
import convocation_history as hist  # noqa: E402
import convocation_pass as cp  # noqa: E402
import database  # noqa: E402
import emailer  # noqa: E402
import exam_auth  # noqa: E402
import exam_registrations as reg  # noqa: E402
import ids  # noqa: E402
import medalists as med  # noqa: E402
import web.routes as vr  # noqa: E402
import web.student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402
from _scanner_fixture import scanner_headers  # noqa: E402

failures = 0
checks = 0
STAFF_USER, STAFF_PW = "p11 officer", "pass-history-11"
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


def jpeg_bytes(size=(40, 40), color=(10, 120, 60)):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
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


def signup(email, reg_no, roll, name, password="pass-history-11"):
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


def login(email, password="pass-history-11"):
    return spost("/api/student/login", {"email": email,
                                        "password": password})


def reset_limits():
    for bucket in sr._HITS.values():
        bucket.clear()
    vr._PIN_FAILS.clear()


def pass_of(token):
    st, body = sget("/api/student/pass", token)
    return st, (body.get("pass") or {})


def hist_of(token):
    st, body = sget("/api/student/history", token)
    return st, body


def staff_post(path, data):
    global TOK
    TOK = csrf_of(html(client.get("/exam/event")))
    data = dict(data, csrf_token=TOK)
    return client.post(path, data=data, follow_redirects=True)


def entry_for(body, conv_id):
    for e in body.get("history", []):
        if e["convocation"]["id"] == conv_id:
            return e
    return None


# --------------------------------------------------------------- A. boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
# Phase 14: scans require an authenticated scanner session (all gates).
SCANNER_HDRS = scanner_headers(client)

conv1 = raw("SELECT * FROM convocations WHERE is_active = 1")
check("boot: seeded convocation is active",
      len(conv1) == 1 and conv1[0]["name"].startswith("LGU"), conv1)
CONV = conv1[0]["id"]

exam_auth.create_staff(STAFF_USER, "P11 Officer", STAFF_PW)
page = html(client.get("/exam/login"))
TOK = csrf_of(page)
r = client.post("/exam/login", data={"csrf_token": TOK, "username":
                                     STAFF_USER, "password": STAFF_PW},
                follow_redirects=True)
check("boot: staff login lands on the dashboard",
      r.status_code == 200 and "Dashboard" in html(r))
TOK = csrf_of(html(client.get("/exam/event")))

# A convocation with a CONFIRMED date + rehearsal, then two registrations.
client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-11-01",
                  "confirmed_date": "2026-11-15", "rehearsal_date":
                  "2026-11-10", "rehearsal_time": "10:30",
                  "venue": "Pass Hall",
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

# ------------------------------------------- C. pass + history need session
reset_limits()
check("security: pass requires a signed-in student",
      sget("/api/student/pass")[0] == 401)
check("security: history requires a signed-in student",
      sget("/api/student/history")[0] == 401)

# ------------------------------ D. active reg + confirmed published event
st, p = pass_of(AVA_TOKEN)
check("pass: a signed-in student gets an invitation payload",
      st == 200 and p.get("state") is not None, (st, p))
check("pass: an active registration with a published event is eligible",
      p["state"] == "eligible", p.get("state"))
check("pass: the eligible pass is clearly labelled",
      p["state_label"] == "Invitation available" and bool(p["title"]),
      p.get("state_label"))
check("pass: registration details are surfaced",
      p["registration"]["registration_number"] == AVA[1]
      and p["registration"]["student_name"] == AVA[3]
      and p["registration"]["status"] == "active", p.get("registration"))
check("pass: the convocation is identified",
      p["convocation"]["id"] == CONV, p.get("convocation"))
ev = p.get("event")
check("pass: published event details are attached",
      ev is not None and ev["venue"] == "Pass Hall", ev)
check("pass: a confirmed date reads as officially confirmed",
      ev["date_state"] == "confirmed" and ev["confirmed_date"] == "2026-11-15"
      and "confirmed" in ev["date_state_label"].lower(), ev)

# -------------------------------- E. QR blocker + no operational insert
d = database.get_db()
try:
    prereq = cp.qr_prerequisite(d, reg.active_convocation(d))
finally:
    d.close()
check("qr: the operational-QR prerequisite is reported as NOT satisfied",
      prereq["satisfied"] is False, prereq)
check("qr: a reason explains the roster is not linked",
      "roster" in prereq["reason"].lower(), prereq.get("reason"))
check("qr: GET /pass embeds no QR payload (it is a read-only invitation)",
      p["qr_available"] is False and p["qr"] is None, (p.get("qr_available"),
                                                       p.get("qr")))
check("qr: the invitation explains how a QR is issued and that the roster is unlinked",
      "roster" in p["qr_blocker"].lower() and "qr" in p["qr_blocker"].lower(),
      p.get("qr_blocker"))
students_before = raw("SELECT * FROM students ORDER BY id")
st, _ = pass_of(AVA_TOKEN)  # open the pass again
check("qr: opening a pass never inserts an operational roster row",
      raw("SELECT * FROM students ORDER BY id") == students_before)
check("qr: no operational student row exists for the registration roll",
      raw("SELECT COUNT(*) FROM students WHERE roll_no IN (?, ?)",
          (AVA[2], BOB[2]))[0]["COUNT(*)"] == 0)
check("qr: the scanner still cannot resolve a registration (no qr_id)",
      raw("SELECT COUNT(*) FROM students WHERE roll_no = ?",
          (AVA[2],))[0]["COUNT(*)"] == 0)

# ------------------------------------------------------- F. history basic
st, hb = hist_of(AVA_TOKEN)
check("history: a signed-in student gets a history payload",
      st == 200 and "history" in hb, (st, list(hb)))
ava_entry = entry_for(hb, CONV)
check("history: the claimed convocation appears",
      ava_entry is not None, hb.get("history"))
check("history: the active convocation is flagged active",
      ava_entry["convocation"]["is_active"] is True
      and ava_entry["convocation"]["bucket"] == "active", ava_entry)
check("history: the registration status is shown",
      ava_entry["registration"]["status"] == "active"
      and ava_entry["registration"]["registration_number"] == AVA[1],
      ava_entry.get("registration"))
check("history: published event details are attached",
      ava_entry["event"] is not None
      and ava_entry["event"]["date_state"] == "confirmed", ava_entry.get("event"))
st, hbb = hist_of(BOB_TOKEN)
check("history: Bob's history lists his own convocation",
      entry_for(hbb, CONV) is not None, hbb.get("history"))

# ------------------------------------------------------- G. isolation
joined_bob = str(hbb)
check("history: Bob never sees Ava's registration number",
      AVA[1] not in joined_bob and AVA[3] not in joined_bob, joined_bob[:300])
st, haa = hist_of(AVA_TOKEN)
check("history: Ava never sees Bob's registration number",
      BOB[1] not in str(haa) and BOB[3] not in str(haa), str(haa)[:300])

# ------------------------------------------- H. pending review blocks a pass
reset_limits()
st, body = spost("/api/student/support",
                 {"category": "correction", "subject": "Wrong department",
                  "message": "Please correct my department on the card."},
                 AVA_TOKEN)
CORR_ID = body.get("request", {}).get("id", 0)
check("pending: Ava files a registration-affecting support request",
      st == 200 and CORR_ID > 0, (st, body))
st, p = pass_of(AVA_TOKEN)
check("pending: an open blocking request holds the pass in review",
      p["state"] == "pending_review", p.get("state"))
check("pending: a pass under review shows no event details",
      p["event"] is None, p.get("event"))
check("pending: a pass under review still shows the registration",
      p["registration"]["registration_number"] == AVA[1], p.get("registration"))
check("pending: a pass under review issues no QR",
      p["qr_available"] is False and p["qr"] is None)
# A GENERAL request never blocks a pass.
reset_limits()
st, body = spost("/api/student/support",
                 {"category": "general", "subject": "A general question",
                  "message": "What time do the gates open?"}, BOB_TOKEN)
check("pending: Bob files a general (non-blocking) request",
      st == 200 and body.get("ok") is True, (st, body))
st, p = pass_of(BOB_TOKEN)
check("pending: a general request does NOT block Bob's pass",
      p["state"] == "eligible", p.get("state"))

# ---------------------------------- I. resolving the request frees the pass
r = client.post("/exam/support/%d/status" % CORR_ID,
                data={"csrf_token": TOK, "status": "resolved"},
                follow_redirects=True)
check("pending: staff resolves the blocking request",
      r.status_code == 200, r.status_code)
st, p = pass_of(AVA_TOKEN)
check("pending: once resolved the pass returns to eligible",
      p["state"] == "eligible", p.get("state"))

# ------------------------------------------- J. cancelled registration
ava_row = raw("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (AVA[2],))[0]
bob_row = raw("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (BOB[2],))[0]
staff_post("/exam/registrations/%d/status" % ava_row["id"], {"action": "cancel"})
st, p = pass_of(AVA_TOKEN)
check("cancel: a cancelled registration makes the pass unavailable",
      p["state"] == "registration_cancelled", p.get("state"))
check("cancel: an unavailable pass shows no event details",
      p["event"] is None, p.get("event"))
check("cancel: an unavailable pass issues no QR",
      p["qr_available"] is False and p["qr"] is None)
staff_post("/exam/registrations/%d/status" % ava_row["id"],
           {"action": "reinstate"})
st, p = pass_of(AVA_TOKEN)
check("cancel: reinstate returns Ava's pass to eligible",
      p["state"] == "eligible", p.get("state"))
staff_post("/exam/registrations/%d/status" % bob_row["id"], {"action": "cancel"})
st, p = pass_of(BOB_TOKEN)
check("cancel: Bob's cancelled registration also makes his pass unavailable",
      p["state"] == "registration_cancelled", p.get("state"))
check("cancel: Bob's unavailable pass issues no QR",
      p["qr_available"] is False and p["qr"] is None)

# ------------------------------------------- K. revoked registration
staff_post("/exam/registrations/%d/status" % bob_row["id"], {"action": "revoke"})
st, p = pass_of(BOB_TOKEN)
check("revoke: a revoked registration makes the pass unavailable",
      p["state"] == "registration_revoked", p.get("state"))
check("revoke: an unavailable pass issues no QR",
      p["qr_available"] is False and p["qr"] is None)
st, hbb = hist_of(BOB_TOKEN)
bob_entry = entry_for(hbb, CONV)
check("revoke: history reflects the revoked registration",
      bob_entry and bob_entry["registration"]["status"] == "revoked",
      bob_entry.get("registration") if bob_entry else None)

# ------------------------------------------- L. unpublished event details
raw("DELETE FROM convocation_publications WHERE convocation_id = ?", (CONV,))
st, p = pass_of(AVA_TOKEN)
check("unpublished: an active registration with no published event",
      p["state"] == "event_unpublished", p.get("state"))
check("unpublished: the registration is still recognised",
      p["registration"]["registration_number"] == AVA[1], p.get("registration"))
check("unpublished: no event details leak before publish",
      p["event"] is None, p.get("event"))
check("unpublished: no QR is issued", p["qr_available"] is False and p["qr"] is None)
client.post("/exam/event/publish", data={"csrf_token": TOK})
st, p = pass_of(AVA_TOKEN)
check("unpublished: republishing restores the eligible pass",
      p["state"] == "eligible" and p["event"] is not None, p.get("state"))

# ------------------------------- M. expected (provisional) is never confirmed
c = sqlite3.connect(config.DB_PATH, timeout=30)
c.execute("UPDATE convocation_publications SET confirmed_date = NULL"
          " WHERE convocation_id = ?", (CONV,))
c.commit()
c.close()
st, p = pass_of(AVA_TOKEN)
check("expected: a provisional date is never shown as confirmed",
      p["event"]["date_state"] == "expected"
      and "provisional" in p["event"]["date_state_label"].lower()
      and p["event"]["confirmed_date"] is None, p.get("event"))
c = sqlite3.connect(config.DB_PATH, timeout=30)
c.execute("UPDATE convocation_publications SET confirmed_date = '2026-11-15'"
          " WHERE convocation_id = ?", (CONV,))
c.commit()
c.close()

# ------------------------------------------------- N. history honours
d = database.get_db()
try:
    clean, errs = med.clean_row({"department": "Computer Science",
                                 "student_name": AVA[3],
                                 "award_category": "gold", "position": "1",
                                 "reference_number": AVA[1]})
    assert not errs, errs
    mid = med.insert(d, CONV, clean, STAFF_USER)
    row = med.get(d, mid)
    row = med.store_photo(d, row, jpeg_bytes(), STAFF_USER)
    med.set_publication(d, row, "published", STAFF_USER)
finally:
    d.close()
st, haa = hist_of(AVA_TOKEN)
ava_entry = entry_for(haa, CONV)
check("honours: a published medal matching the registration is surfaced",
      ava_entry and len(ava_entry["honours"]) == 1
      and ava_entry["honours"][0]["award_category"] == "gold",
      ava_entry.get("honours") if ava_entry else None)
st, hbb = hist_of(BOB_TOKEN)
bob_entry = entry_for(hbb, CONV)
check("honours: another student's honours never appear in Bob's history",
      bob_entry and bob_entry["honours"] == [], bob_entry.get("honours")
      if bob_entry else None)

# --------------------------------- O. prior features remain intact
reset_limits()
st, body = sget("/api/student/readiness", AVA_TOKEN)
check("preserve: the readiness centre still works",
      st == 200 and body.get("readiness") is not None, st)
st, body = sget("/api/student/support", AVA_TOKEN)
check("preserve: the support request list still works",
      st == 200 and "requests" in body, st)
st, body = sget("/api/student/event", AVA_TOKEN)
check("preserve: published event info still works",
      st == 200 and "event" in body, st)
st, body = sget("/api/student/medalists", AVA_TOKEN)
check("preserve: the medalist board still works",
      st == 200 and "convocation" in body, st)
r = client.get("/exam/dashboard")
check("preserve: the staff dashboard still renders",
      r.status_code == 200 and "Digital invitation passes" in html(r))
check("preserve: the dashboard reports the legacy roster QR prerequisite as unsatisfied",
      "Legacy operational-QR prerequisite not satisfied" in html(r)
      and "not linked to the check-in roster" in html(r))
check("preserve: the dashboard reports convocation QR entry status (Phase 12)",
      "Convocation QR entry" in html(r)
      and "admitted so far" in html(r))
metrics = raw("SELECT COUNT(*) FROM convocation_registrations"
              " WHERE convocation_id = ? AND status = 'active'", (CONV,))
check("preserve: real registration counts still drive the board",
      metrics[0]["COUNT(*)"] >= 1, metrics)

# ------------------------- P. volunteer operations remain functional
reset_limits()
qr = raw("SELECT qr_id, name, roll_no FROM students"
         " WHERE roll_no NOT IN (SELECT host_roll_no FROM guests)"
         " ORDER BY id LIMIT 1")[0]
payload = ids.make_payload(qr["qr_id"])
res = client.post("/api/scan", json={"payload": payload, "gate_id": 1,
                                     "mode": "entry",
                                     "volunteer": "P11 Volunteer"},
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
# A convocation registration (with no qr_id) can never be scanned at a gate.
check("ops: a registration roll has no scannable QR identity",
      raw("SELECT COUNT(*) FROM students WHERE roll_no = ?",
          (AVA[2],))[0]["COUNT(*)"] == 0)
guest = client.post("/api/guests", json={"name": "P11 Guest",
                                         "phone": "0300 0000011",
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

# ----------------------------------------- Q. read-only guarantees
st, p = pass_of(AVA_TOKEN)
rows_after_pass = raw("SELECT COUNT(*) AS n FROM convocation_registrations")[0]
claims_after = raw("SELECT COUNT(*) AS n FROM registration_claims")[0]
check("readonly: opening a pass changes no registration rows",
      rows_after_pass["n"] == 2, rows_after_pass)
check("readonly: opening a pass creates no new claims",
      claims_after["n"] == 2, claims_after)

# ----------------------------------------------------- R. boundary: prod DB
if PROD_STAMP is not None:
    now = os.stat(PROD_DB)
    check("boundary: app/lgu.db is byte-for-byte untouched",
          (now.st_size, now.st_mtime_ns) == PROD_STAMP,
          (now.st_size, now.st_mtime_ns))
else:
    check("boundary: app/lgu.db absent and never created",
          not os.path.exists(PROD_DB))

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)