"""Phase 29 acceptance: annual convocation lifecycle + complete student dashboard.

Proves the whole two-occasion annual cycle on ONE disposable temp database:
the rehearsal and the main convocation are configured, published and
counted as two distinct occasions of the SAME convocation; a student's
single bearer pass serves both, check-ins land in occasion-scoped ledger
rows ((convocation, registration, occasion) UNIQUE), rehearsal admission
never marks the pass used while ceremony admission does, the countdown
payload is server-computed and honest (a provisional date never counts
down; no published time never yields a fabricated clock), every student
dashboard option works end-to-end over real HTTP, role authorization is
re-verified directly, and migration v11→v12 backfills existing admissions
as ceremony rows without losing the index name. Synthetic records only;
app/lgu.db is never opened (stat-stamped before and after to prove it).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase29_annual_event_and_student.py
"""

import base64
import os
import re
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

PROD_DB = os.path.join(APP_DIR, "lgu.db")
if os.path.exists(PROD_DB):
    _s = os.stat(PROD_DB)
    PROD_STAMP = (_s.st_size, _s.st_mtime_ns)
else:
    PROD_STAMP = None

TMP = tempfile.mkdtemp(prefix="lgu-p29annual-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "annual.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "student-photos")

from io import BytesIO  # noqa: E402

from openpyxl import Workbook  # noqa: E402

import config  # noqa: E402
config.require_test_db()
import convocation_events as ev  # noqa: E402
import convocation_qr as cqr  # noqa: E402
import database  # noqa: E402
import emailer  # noqa: E402
import exam_auth  # noqa: E402
import exam_registrations as reg  # noqa: E402
import migrations  # noqa: E402
import models  # noqa: E402
import web.routes as vr  # noqa: E402
import web.student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402
from _scanner_fixture import scanner_headers  # noqa: E402

failures = 0
checks = 0
STAFF_USER, STAFF_PW = "p29 officer", "annual-event-pass-29"
PW = "annual-event-pass-29"
AVA = ("ava.shah@uni.edu.pk", "REG-9301", "09301", "Ava Shah")
BOB = ("bob.reed@uni.edu.pk", "REG-9302", "09302", "Bob Reed")
CHEN = ("chen.li@uni.edu.pk", "REG-9303", "09303", "Chen Li")

# The 1x1 PNG the photo-upload check posts as base64 (real, decodable image).
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

TODAY = date.today()


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


def signup(email, reg_no, roll, name, password=PW):
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


def login(email, password=PW):
    return spost("/api/student/login", {"email": email, "password": password})


def reset_limits():
    for bucket in sr._HITS.values():
        bucket.clear()
    vr._PIN_FAILS.clear()


def issue(token):
    return spost("/api/student/pass/issue", {}, token)


def scan(payload, gate_id=1, mode="entry", occasion=None):
    body = {"payload": payload, "gate_id": gate_id, "mode": mode,
            "volunteer": "P29 Volunteer"}
    if occasion is not None:
        body["occasion"] = occasion
    r = client.post("/api/scan", json=body, headers=SCANNER_HDRS)
    try:
        return r.status_code, (r.get_json(silent=True) or {})
    except Exception:
        return r.status_code, {}


def sync(items):
    r = client.post("/api/sync", json={"items": items},
                    headers=SCANNER_HDRS)
    return r.status_code, (r.get_json(silent=True) or {})


def staff_post(path, data):
    global TOK
    TOK = csrf_of(html(client.get("/exam/event")))
    data = dict(data, csrf_token=TOK)
    return client.post(path, data=data, follow_redirects=True)


def utc_instant(day_text, time_text):
    dt = datetime.strptime("%s %s" % (day_text, time_text), "%Y-%m-%d %H:%M")
    return (dt.replace(tzinfo=ZoneInfo(config.DISPLAY_TZ))
            .astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")
            .replace("+00:00", "Z"))


# ---------------------------------------------------------------- A. boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
SCANNER_HDRS = scanner_headers(client)

CONV = raw("SELECT * FROM convocations WHERE is_active = 1")[0]["id"]
exam_auth.create_staff(STAFF_USER, "P29 Officer", STAFF_PW)
page = html(client.get("/exam/login"))
TOK = csrf_of(page)
client.post("/exam/login", data={"csrf_token": TOK, "username": STAFF_USER,
                                 "password": STAFF_PW},
            follow_redirects=True)

R_REH = (TODAY + timedelta(days=10)).isoformat()   # rehearsal
R_CER = (TODAY + timedelta(days=15)).isoformat()   # main convocation
REH_TIME, CER_TIME = "09:00", "10:00"

# -------------------------------- B. configure + publish two occasions ---
staff_post("/exam/event/save",
           {"name": "LGU Convocation 2026", "year": "2026",
            "expected_date": (TODAY + timedelta(days=12)).isoformat(),
            "confirmed_date": R_CER, "ceremony_time": CER_TIME,
            "rehearsal_date": R_REH, "rehearsal_time": REH_TIME,
            "rehearsal_venue": "Rehearsal Ground",
            "venue": "Main Hall",
            "instructions": "Bring your student card."})
staff_post("/exam/event/publish", {})

st, payload = sget("/api/student/event")
event = payload.get("event") or {}
occs = {o["key"]: o for o in event.get("occasions", [])}
check("event: publishing records BOTH occasions of the annual cycle",
      st == 200 and set(occs) == {"rehearsal", "ceremony"}, (st, occs.keys()))
check("event: the rehearsal is announced with its own date/time/venue",
      occs["rehearsal"]["state"] == "announced"
      and occs["rehearsal"]["date"] == R_REH
      and occs["rehearsal"]["time"] == REH_TIME
      and occs["rehearsal"]["venue"] == "Rehearsal Ground", occs["rehearsal"])
check("event: the main convocation is confirmed with its ceremony time",
      occs["ceremony"]["state"] == "confirmed"
      and occs["ceremony"]["date"] == R_CER
      and occs["ceremony"]["time"] == CER_TIME
      and occs["ceremony"]["venue"] == "Main Hall", occs["ceremony"])
check("event: payload carries the ceremony time + portal timezone",
      event.get("ceremony_time") == CER_TIME
      and event.get("portal_tz") == config.DISPLAY_TZ,
      (event.get("ceremony_time"), event.get("portal_tz")))
check("event: starts_at is the real UTC instant for date+time in portal tz",
      occs["rehearsal"]["starts_at"] == utc_instant(R_REH, REH_TIME)
      and occs["ceremony"]["starts_at"] == utc_instant(R_CER, CER_TIME),
      (occs["rehearsal"]["starts_at"], occs["ceremony"]["starts_at"]))
check("event: both occasions are honestly upcoming with signed days_until",
      occs["rehearsal"]["phase"] == "upcoming"
      and occs["rehearsal"]["days_until"] == 10
      and occs["ceremony"]["phase"] == "upcoming"
      and occs["ceremony"]["days_until"] == 15,
      {k: (v["phase"], v["days_until"]) for k, v in occs.items()})

# ------------------------------------------ C. ordering is validated -----
try:
    ev.clean_details({"name": "X", "year": "2026",
                      "confirmed_date": R_CER,
                      "rehearsal_date": (R_CER and
                                         (TODAY + timedelta(days=20))
                                         .isoformat())})
    late_err = ""
except ev.EventError as e:
    late_err = str(e)
check("order: a rehearsal after the ceremony is refused",
      late_err.startswith("The rehearsal must be scheduled before"), late_err)
try:
    ev.clean_details({"name": "X", "year": "2026",
                      "confirmed_date": R_CER, "ceremony_time": "09:00",
                      "rehearsal_date": R_CER, "rehearsal_time": "10:00"})
    same_err = ""
except ev.EventError as e:
    same_err = str(e)
check("order: same-day rehearsal must START before the ceremony",
      same_err.startswith("On the same day, the rehearsal must start"),
      same_err)
ok_order = ev.clean_details({"name": "X", "year": "2026",
                             "confirmed_date": R_CER,
                             "ceremony_time": CER_TIME,
                             "rehearsal_date": R_CER,
                             "rehearsal_time": REH_TIME})
check("order: same-day rehearsal before the ceremony is accepted",
      ok_order["rehearsal_date"] == R_CER, ok_order)

# -------------------------------- D. status transitions (server truth) ---
staff_post("/exam/event/save",
           {"name": "LGU Convocation 2026", "year": "2026",
            "expected_date": (TODAY + timedelta(days=12)).isoformat(),
            "confirmed_date": TODAY.isoformat(), "ceremony_time": CER_TIME,
            "rehearsal_date": TODAY.isoformat(), "rehearsal_time": REH_TIME,
            "rehearsal_venue": "Rehearsal Ground", "venue": "Main Hall",
            "instructions": "Bring your student card."})
staff_post("/exam/event/publish", {})
live = {o["key"]: o for o in sget("/api/student/event")[1]["event"]["occasions"]}
check("status: on the day, both occasions report phase 'live' (0 days)",
      live["rehearsal"]["phase"] == "live"
      and live["rehearsal"]["days_until"] == 0
      and live["ceremony"]["phase"] == "live"
      and live["ceremony"]["days_until"] == 0,
      {k: (v["phase"], v["days_until"]) for k, v in live.items()})

staff_post("/exam/event/save",
           {"name": "LGU Convocation 2026", "year": "2026",
            "confirmed_date": (TODAY - timedelta(days=2)).isoformat(),
            "ceremony_time": CER_TIME,
            "rehearsal_date": (TODAY - timedelta(days=3)).isoformat(),
            "rehearsal_time": REH_TIME,
            "rehearsal_venue": "Rehearsal Ground", "venue": "Main Hall",
            "instructions": "Bring your student card."})
staff_post("/exam/event/publish", {})
past = {o["key"]: o for o in sget("/api/student/event")[1]["event"]["occasions"]}
check("status: passed dates report phase 'completed' with negative days",
      past["rehearsal"]["phase"] == "completed"
      and past["rehearsal"]["days_until"] == -3
      and past["ceremony"]["phase"] == "completed"
      and past["ceremony"]["days_until"] == -2,
      {k: (v["phase"], v["days_until"]) for k, v in past.items()})

# No ceremony time → NO starts_at (a date alone never fabricates a clock);
# empty rehearsal venue falls back to the ceremony venue.
staff_post("/exam/event/save",
           {"name": "LGU Convocation 2026", "year": "2026",
            "expected_date": (TODAY + timedelta(days=12)).isoformat(),
            "confirmed_date": R_CER,
            "rehearsal_date": R_REH, "rehearsal_time": REH_TIME,
            "venue": "Main Hall", "instructions": "Bring your card."})
staff_post("/exam/event/publish", {})
notime = {o["key"]: o
          for o in sget("/api/student/event")[1]["event"]["occasions"]}
check("status: a date without a published time yields no starts_at",
      notime["ceremony"]["starts_at"] is None
      and notime["ceremony"]["days_until"] == 15, notime["ceremony"])
check("status: rehearsal venue falls back to the ceremony venue",
      notime["rehearsal"]["venue"] == "Main Hall", notime["rehearsal"])

# Restore the fully-published two-occasion schedule for everything below.
staff_post("/exam/event/save",
           {"name": "LGU Convocation 2026", "year": "2026",
            "expected_date": (TODAY + timedelta(days=12)).isoformat(),
            "confirmed_date": R_CER, "ceremony_time": CER_TIME,
            "rehearsal_date": R_REH, "rehearsal_time": REH_TIME,
            "rehearsal_venue": "Rehearsal Ground", "venue": "Main Hall",
            "instructions": "Bring your student card."})
staff_post("/exam/event/publish", {})

# ------------------------------------ E. registrations + students in ----
batch = client.post(
    "/exam/registrations/import",
    data={"csrf_token": TOK,
          "file": (BytesIO(xlsx([["REG-9301", AVA[0], AVA[2], AVA[3],
                                  "Computer Science"],
                                 ["REG-9302", BOB[0], BOB[2], BOB[3],
                                  "Electrical Engineering"],
                                 ["REG-9303", CHEN[0], CHEN[2], CHEN[3],
                                  "Physics"]])), "regs.xlsx")},
    content_type="multipart/form-data")
BID = int(re.search(r"/import/(\d+)",
                    batch.headers.get("Location", "")).group(1))
client.post("/exam/registrations/import/%d/commit" % BID,
            data={"csrf_token": TOK})
ava_row = raw("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (AVA[2],))[0]
bob_row = raw("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (BOB[2],))[0]
chen_row = raw("SELECT * FROM convocation_registrations WHERE roll_number = ?",
               (CHEN[2],))[0]

signup(*AVA)
AVA_TOKEN = login(AVA[0])[1].get("token", "")
signup(*BOB)
BOB_TOKEN = login(BOB[0])[1].get("token", "")
signup(*CHEN)
CHEN_TOKEN = login(CHEN[0])[1].get("token", "")
check("boot: all three students sign in",
      bool(AVA_TOKEN) and bool(BOB_TOKEN) and bool(CHEN_TOKEN))

# ------------------- F. registration and profile are independent axes ----
st, me = sget("/api/student/me", AVA_TOKEN)
check("independence: registration status and profile completion are"
      " separate fields on /me",
      st == 200 and me.get("registration", {}).get("status") == "active"
      and isinstance(me.get("completion", {}).get("done"), int)
      and me.get("completion", {}).get("total", 0) >= 2, me.get("completion"))
done_before = me["completion"]["done"]
st, prof = spost("/api/student/profile",
                 {"phone": "03001234567"}, AVA_TOKEN)
me2 = sget("/api/student/me", AVA_TOKEN)[1]
check("independence: completing the profile never changes the registration",
      st == 200 and me2["registration"]["status"] == "active"
      and me2["profile"]["phone"] == "03001234567", (st, me2["registration"]))
# Revoke is PERMANENT (reinstate only applies from cancelled), so the
# reversible cancel/reinstate pair is what proves the two axes independent.
staff_post("/exam/registrations/%d/status" % ava_row["id"],
           {"action": "cancel"})
me3 = sget("/api/student/me", AVA_TOKEN)[1]
staff_post("/exam/registrations/%d/status" % ava_row["id"],
           {"action": "reinstate"})
me4 = sget("/api/student/me", AVA_TOKEN)[1]
check("independence: a cancelled registration reads cancelled; profile intact",
      me3["registration"]["status"] == "cancelled"
      and me3["profile"]["phone"] == "03001234567"
      and me4["registration"]["status"] == "active",
      (me3["registration"]["status"], me4["registration"]["status"]))
check("independence: completion count is unaffected by status flips",
      me4["completion"]["done"] == done_before, me4["completion"])

# ------------------------- G. one pass, occasion-scoped rehearsal entry --
reset_limits()
st, ib = issue(AVA_TOKEN)
AVA_PAYLOAD = ib["pass"]["payload"]
st, pass_body = sget("/api/student/pass", AVA_TOKEN)
check("pass: the invitation carries the annual cycle occasions",
      {o["key"] for o in pass_body["pass"]["event"]["occasions"]}
      == {"rehearsal", "ceremony"},
      pass_body["pass"]["event"].get("occasions"))
st, r = scan(AVA_PAYLOAD, occasion="rehearsal")
adm = raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?"
          " AND registration_id = ?", (CONV, ava_row["id"]))
check("rehearsal: the check-in is recorded with its own title",
      st == 200 and r.get("status") == "ok"
      and r.get("title") == "REHEARSAL ENTRY RECORDED"
      and r.get("occasion") == "rehearsal", r)
check("rehearsal: the ledger row is occasion-scoped",
      len(adm) == 1 and adm[0]["occasion"] == "rehearsal", adm)
check("rehearsal: a check-in NEVER marks the pass used",
      raw("SELECT status FROM convocation_passes WHERE token_hash = ?",
          (cqr.token_hash(AVA_PAYLOAD.split(":", 1)[1]),))[0]["status"]
      == "active")

# ---------------------- H. the same pass still admits the ceremony ------
st, r = scan(AVA_PAYLOAD, occasion="ceremony")
adm = raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?"
          " AND registration_id = ?", (CONV, ava_row["id"]))
check("ceremony: the same pass admits the main convocation separately",
      st == 200 and r.get("status") == "ok"
      and r.get("title") == "CONVOCATION ENTRY RECORDED"
      and r.get("occasion") == "ceremony", r)
check("ceremony: two ledger rows exist, one per occasion",
      len(adm) == 2
      and {a["occasion"] for a in adm} == {"rehearsal", "ceremony"}, adm)
check("ceremony: the ceremony admission marks the pass used",
      raw("SELECT status FROM convocation_passes WHERE token_hash = ?",
          (cqr.token_hash(AVA_PAYLOAD.split(":", 1)[1]),))[0]["status"]
      == "used")

# --------------------------- I. duplicates are per-occasion only --------
st, r = scan(AVA_PAYLOAD, occasion="rehearsal")
check("duplicate: re-checking the rehearsal is refused as already admitted",
      r.get("status") == "error" and r.get("title") == "ALREADY ADMITTED", r)
st, r = scan(AVA_PAYLOAD, occasion="ceremony")
check("duplicate: re-admitting the ceremony is refused the same way",
      r.get("status") == "error" and r.get("title") == "ALREADY ADMITTED", r)
c = sqlite3.connect(config.DB_PATH, timeout=30)
dup_rows = [("ceremony", True), ("rehearsal", True)]
for occ, blocked in dup_rows:
    try:
        c.execute("INSERT INTO convocation_admissions"
                  " (pass_id, convocation_id, registration_id, gate_id,"
                  "  volunteer, admitted_at, source, occasion)"
                  " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (999999, CONV, ava_row["id"], 2, "race",
                   "2026-11-15 10:00:00", "online", occ))
        c.commit()
        dup_rows_result = False
    except sqlite3.IntegrityError:
        dup_rows_result = True
    check("duplicate: the UNIQUE index blocks a second %s row atomically"
          % occ, dup_rows_result is blocked)
# A different registration on a different occasion is a legitimate row.
try:
    c.execute("INSERT INTO convocation_admissions"
              " (pass_id, convocation_id, registration_id, gate_id,"
              "  volunteer, admitted_at, source, occasion)"
              " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (999999, CONV, bob_row["id"], 2, "race",
               "2026-11-10 09:30:00", "online", "rehearsal"))
    c.commit()
    cross_ok = True
except sqlite3.IntegrityError:
    cross_ok = False
finally:
    c.close()
check("duplicate: another registration's rehearsal row is still allowed",
      cross_ok is True)

# -------------------------------- J. honest rejections at the gate ------
# verify_scan checks the pass status BEFORE the rehearsal schedule, so this
# needs a fresh (active) pass: BOB has no admissions and no support requests.
reset_limits()
st, bob_ib = issue(BOB_TOKEN)
BOB_PAYLOAD = bob_ib["pass"]["payload"]
# The rehearsal schedule lives on the convocations row (verify_scan reads
# conv["rehearsal_date"]), so clear it there — the publication snapshot is
# restored alongside it.
exec_sql("UPDATE convocations SET rehearsal_date = NULL WHERE id = ?",
         (CONV,))
exec_sql("UPDATE convocation_publications SET rehearsal_date = NULL"
         " WHERE convocation_id = ?", (CONV,))
bob_before = len(raw("SELECT * FROM convocation_admissions"
                     " WHERE convocation_id = ? AND registration_id = ?",
                     (CONV, bob_row["id"])))
st, r = scan(BOB_PAYLOAD, occasion="rehearsal")
check("reject: scanning a rehearsal that was never scheduled is refused",
      st == 200 and r.get("status") == "error" and r.get("level") == "red"
      and r.get("title") == "REHEARSAL NOT SCHEDULED"
      and r.get("occasion") == "rehearsal", r)
check("reject: the refused rehearsal records nothing",
      len(raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?"
              " AND registration_id = ?", (CONV, bob_row["id"])))
      == bob_before)
exec_sql("UPDATE convocations SET rehearsal_date = ? WHERE id = ?",
         (R_REH, CONV))
exec_sql("UPDATE convocation_publications SET rehearsal_date = ?"
         " WHERE convocation_id = ?", (R_REH, CONV))
st, r = scan(AVA_PAYLOAD, occasion="banquet")
check("reject: /api/scan with an unknown occasion is a 400",
      st == 400 and r.get("title") == "UNKNOWN OCCASION", (st, r))
st, body = sync([{"payload": AVA_PAYLOAD, "gate_id": 1, "mode": "entry",
                  "volunteer": "x", "scanned_at": None,
                  "occasion": "banquet"}])
check("reject: a queued item with an unknown occasion is refused per-item",
      st == 200 and body.get("results", [{}])[0]["result"]["title"]
      == "UNKNOWN OCCASION", body)
GATE2_HDRS = scanner_headers(client, [2])
r = client.post("/api/scan", json={"payload": AVA_PAYLOAD, "gate_id": 1,
                                   "mode": "entry", "occasion": "ceremony"},
                headers=GATE2_HDRS)
check("reject: an unauthorized gate is refused (403) before any admission",
      r.status_code == 403
      and r.get_json().get("title") == "GATE NOT AUTHORIZED", r.status_code)
staff_post("/exam/registrations/%d/status" % chen_row["id"],
           {"action": "cancel"})
st, chen_ib = issue(CHEN_TOKEN)
check("reject: a cancelled registration cannot issue at all (403)", st == 403)
reset_limits()
staff_post("/exam/registrations/%d/status" % chen_row["id"],
           {"action": "reinstate"})

# ------------------------ K. offline sync carries the occasion ----------
st, chen_ib = issue(CHEN_TOKEN)
CHEN_PAYLOAD = chen_ib["pass"]["payload"]
queued = {"payload": CHEN_PAYLOAD, "gate_id": 1, "mode": "entry",
          "volunteer": "ignored", "scanned_at": "2026-11-10 08:55:12",
          "occasion": "rehearsal"}
st, body = sync([queued])
chen_adm = raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?"
               " AND registration_id = ?", (CONV, chen_row["id"]))
check("sync: a queued rehearsal check-in records exactly once",
      st == 200 and body.get("synced") == 1
      and len(chen_adm) == 1 and chen_adm[0]["occasion"] == "rehearsal"
      and chen_adm[0]["source"] == "queued", (body, chen_adm))
st, body = sync([queued])
check("sync: replaying the same queued batch is answered ALREADY SYNCED",
      body.get("synced") == 0
      and body["results"][0]["result"]["title"] == "ALREADY SYNCED", body)
check("sync: the replay never double-counts the ledger",
      len(raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?"
              " AND registration_id = ?", (CONV, chen_row["id"]))) == 1)
legacy_qr = raw("SELECT qr_id FROM students"
                " WHERE roll_no NOT IN (SELECT host_roll_no FROM guests)"
                " ORDER BY id LIMIT 1")[0]
import ids  # noqa: E402  (late: legacy queued replay path)
st, body = sync([{"payload": ids.make_payload(legacy_qr["qr_id"]),
                   "gate_id": 1, "mode": "entry", "volunteer": "ignored",
                   "scanned_at": "2026-11-10 08:50:00"}])
st2, body2 = sync([{"payload": ids.make_payload(legacy_qr["qr_id"]),
                     "gate_id": 1, "mode": "entry", "volunteer": "ignored",
                     "scanned_at": "2026-11-10 08:50:00"}])
check("sync: a legacy queued row (no occasion) still replays as ceremony-era"
      " behaviour",
      body.get("synced") == 1
      and body2["results"][0]["result"]["title"] == "ALREADY SYNCED",
      (body, body2))

# ---------------- L. every student dashboard option, end-to-end ----------
reset_limits()
AVA2 = login(AVA[0])[1].get("token", "")
st, me = sget("/api/student/me", AVA2)
check("dashboard: /me answers with registration + completion + profile",
      st == 200 and me["registration"]["registration_number"] == AVA[1]
      and "profile" in me and "completion" in me, st)
st, _ = spost("/api/student/profile", {"phone": "03009876543"}, AVA2)
r = client.post("/api/student/profile/photo",
                json={"data": base64.b64encode(PNG_1PX).decode()},
                headers={"Authorization": "Bearer %s" % AVA2})
ph = r.get_json(silent=True) or {}
photo_ok = r.status_code == 200 and ph.get("ok") is True
st_img = client.get("/api/student/profile/photo",
                    headers={"Authorization": "Bearer %s" % AVA2}).status_code
check("dashboard: profile photo uploads a real image and serves it back",
      photo_ok and st_img == 200, (st, st_img))
st, pbody = sget("/api/student/pass", AVA2)
check("dashboard: the invitation reads back after the changes",
      st == 200 and pbody["pass"]["state"] in ("eligible", "pending_review"),
      pbody["pass"].get("state"))
st, hbody = sget("/api/student/history", AVA2)
hist = hbody.get("history", [])
check("dashboard: history lists the convocation with both occasions",
      st == 200 and any(e.get("event") and
                        {o["key"] for o in e["event"].get("occasions", [])}
                        == {"rehearsal", "ceremony"} for e in hist), hbody)
st, rb = sget("/api/student/readiness", AVA2)
rd_body = rb.get("readiness") or {}
check("dashboard: readiness answers with checklist + reminders",
      st == 200 and isinstance(rd_body.get("items"), list)
      and isinstance(rd_body.get("reminders"), list),
      (st, sorted(rd_body)))
dismissible = [x for x in rd_body.get("reminders", [])
               if x.get("dismissible")]
if dismissible:
    st, rmb = spost("/api/student/readiness/reminders",
                    {"key": dismissible[0]["key"], "action": "dismiss"},
                    AVA2)
    reminder_ok = st == 200 and rmb.get("state") == "dismissed"
else:
    st, rmb = spost("/api/student/readiness/reminders",
                    {"key": "not-a-real-key", "action": "dismiss"}, AVA2)
    reminder_ok = st == 400  # fail-closed on a key the student does not hold
check("dashboard: readiness reminders act on the real set, fail-closed",
      reminder_ok, (st, rmb))
st, sup = spost("/api/student/support",
                {"category": "correction", "subject": "P29 check",
                 "message": "Please confirm my department."}, AVA2)
req_id = sup.get("request", {}).get("id", 0)
check("dashboard: support request create + list + detail all answer",
      st == 200 and req_id > 0
      and any(r.get("id") == req_id
              for r in sget("/api/student/support", AVA2)[1].get("requests", []))
      and sget("/api/student/support/%d" % req_id, AVA2)[0] == 200,
      (st, sup))
staff_post("/exam/support/%d/status" % req_id, {"status": "resolved"})
st, ann = sget("/api/student/announcements")
check("dashboard: announcements feed answers", st == 200 and "total" in ann)
st, med = sget("/api/student/medalists")
check("dashboard: medalist board answers", st == 200 and "medalists" in med)
st, ev_body = sget("/api/student/event", AVA2)
check("dashboard: the event screen serves the annual cycle",
      st == 200 and len(ev_body["event"]["occasions"]) == 2)
st, out = spost("/api/student/logout", {}, AVA2)
st, me = sget("/api/student/me", AVA2)
check("dashboard: logout invalidates the token (401 afterwards)",
      st == 401, st)

# ------------------------------ M. role authorization, direct HTTP -------
# A FRESH client: the main one still holds the staff session from section A,
# so anonymous probes must never ride that cookie.
anon = app.test_client()
anon_scan = anon.post("/api/scan", json={}).status_code
anon_sync = anon.post("/api/sync", json={"items": []}).status_code
r = anon.put("/api/settings", json={"university_name": "x"})
anon_settings_put = r.status_code
r = anon.get("/api/settings")
anon_settings_get = r.status_code
r = anon.get("/exam/event")
exam_page = r.status_code
r = anon.get("/guests/directory")
dir_page = r.status_code
check("authz: /api/scan and /api/sync refuse anonymous callers (401)",
      anon_scan == 401 and anon_sync == 401, (anon_scan, anon_sync))
check("authz: /api/settings refuses anonymous read and write",
      anon_settings_get in (401, 403) and anon_settings_put in (401, 403),
      (anon_settings_get, anon_settings_put))
check("authz: exam staff pages redirect anonymous callers to login",
      exam_page in (301, 302, 401, 403), exam_page)
check("authz: the guest directory is gated for anonymous callers",
      dir_page in (301, 302, 401, 403), dir_page)

# ---------------------------- N. migration v11 → v12 backfill ------------
# Build a TRUE v11 schema: fresh SCHEMA + migrate to 12, then undo exactly
# what migration 12 did (columns, index shape, version) and seed a legacy
# admission row as a pre-Phase-29 database would hold it.
v11_path = os.path.join(TMP, "v11.db")
v11 = sqlite3.connect(v11_path)
v11.executescript(database.SCHEMA)
migrations.migrate(v11)
v11.executescript("""
DROP INDEX IF EXISTS idx_convocation_admissions_once;
DROP INDEX IF EXISTS idx_convocation_admissions_occasion;
ALTER TABLE convocation_admissions DROP COLUMN occasion;
ALTER TABLE convocation_publications DROP COLUMN ceremony_time;
ALTER TABLE convocation_publications DROP COLUMN rehearsal_venue;
ALTER TABLE convocations DROP COLUMN ceremony_time;
ALTER TABLE convocations DROP COLUMN rehearsal_venue;
-- Phase 34 (migration 13): a genuine v11 schema also reverts the guest
-- status column so re-running migrate() applies migration 13 cleanly.
ALTER TABLE guests DROP COLUMN status;
CREATE UNIQUE INDEX IF NOT EXISTS idx_convocation_admissions_once
    ON convocation_admissions(convocation_id, registration_id);
INSERT INTO convocations (name, year, status, venue, instructions,
                          is_active, created_at, updated_at)
    VALUES ('Legacy Convocation', '2025', 'completed', 'Old Hall', '', 1,
            '2025-01-01 00:00:00', '2025-01-01 00:00:00');
INSERT INTO gates (code, label) VALUES ('G1', 'Main Gate');
INSERT INTO convocation_registrations
    (convocation_id, registration_number, university_email, roll_number,
     student_name, department, status, created_at, updated_at)
    VALUES (1, 'REG-OLD', 'old@uni.edu.pk', '00001', 'Old Student',
            'Physics', 'active', '2025-01-01 00:00:00',
            '2025-01-01 00:00:00');
INSERT INTO convocation_admissions
    (pass_id, convocation_id, registration_id, gate_id, volunteer,
     admitted_at, source) VALUES (11, 1, 1, 1, 'legacy',
     '2025-12-01 10:00:00', 'online');
""")
v11.execute("PRAGMA user_version = 11")
v11.commit()
migrations.migrate(v11)
ver = v11.execute("PRAGMA user_version").fetchone()[0]
cols = {r[1] for r in v11.execute("PRAGMA table_info(convocation_admissions)")}
pub_cols = {r[1] for r in
            v11.execute("PRAGMA table_info(convocation_publications)")}
conv_cols = {r[1] for r in v11.execute("PRAGMA table_info(convocations)")}
latest = max(v for v, _ in migrations.MIGRATIONS)
check("migration: a v11 database migrates forward to the latest version",
      ver == latest and ver >= 12, (ver, latest))
check("migration: the occasion column + publication columns were added",
      "occasion" in cols and "ceremony_time" in pub_cols
      and "rehearsal_venue" in pub_cols and "ceremony_time" in conv_cols,
      (cols, pub_cols, conv_cols))
backfill = v11.execute("SELECT occasion FROM convocation_admissions"
                       " WHERE volunteer = 'legacy'").fetchone()[0]
check("migration: pre-Phase-29 admissions backfill as ceremony",
      backfill == "ceremony", backfill)
idx_names = {r[0] for r in v11.execute(
    "SELECT name FROM sqlite_master WHERE type='index'")}
check("migration: the once-per-admission index KEEPS its historical name",
      "idx_convocation_admissions_once" in idx_names
      and "idx_convocation_admissions_occasion" in idx_names, idx_names)
try:
    v11.execute("INSERT INTO convocation_admissions"
                " (pass_id, convocation_id, registration_id, gate_id,"
                "  volunteer, admitted_at, source, occasion)"
                " VALUES (12, 1, 1, 1, 'dup', 'x', 'online', 'ceremony')")
    v11.commit()
    dup_blocked = False
except sqlite3.IntegrityError:
    dup_blocked = True
try:
    v11.execute("INSERT INTO convocation_admissions"
                " (pass_id, convocation_id, registration_id, gate_id,"
                "  volunteer, admitted_at, source, occasion)"
                " VALUES (12, 1, 1, 1, 'reh', 'x', 'online', 'rehearsal')")
    v11.commit()
    reh_allowed = True
except sqlite3.IntegrityError:
    reh_allowed = False
finally:
    v11.close()
check("migration: the rebuilt index still blocks same-occasion duplicates",
      dup_blocked)
check("migration: a rehearsal row for the same registration is allowed",
      reh_allowed)

# -------------------------------- O. counters separate the occasions -----
summary = models.dashboard_summary()
full = models.dashboard()
led_cer = raw("SELECT COUNT(*) AS n FROM convocation_admissions"
              " WHERE convocation_id = ? AND occasion = 'ceremony'",
              (CONV,))[0]["n"]
led_reh = raw("SELECT COUNT(*) AS n FROM convocation_admissions"
              " WHERE convocation_id = ? AND occasion = 'rehearsal'",
              (CONV,))[0]["n"]
check("counters: dashboard summary splits ceremony vs rehearsal admissions",
      summary["ceremony_admitted"] == led_cer
      and summary["rehearsal_admitted"] == led_reh
      and led_cer >= 1 and led_reh >= 2,
      (summary["ceremony_admitted"], summary["rehearsal_admitted"],
       led_cer, led_reh))
check("counters: the full dashboard reports the same split",
      full["ceremony_admitted"] == led_cer
      and full["rehearsal_admitted"] == led_reh, full["ceremony_admitted"])
page = html(client.get("/exam/dashboard"))  # staff session from section A
check("counters: the exam dashboard shows BOTH occasion KPIs",
      "Admitted — main convocation" in page and "Admitted — rehearsal" in page
      and str(led_cer) in page and str(led_reh) in page)
page = html(client.get("/dashboard"))
check("counters: the live dashboard template keeps both occasion tiles",
      'id="k-ceremony"' in page and 'id="k-rehearsal"' in page)

# ------------------------------------------------------------- boundary --
if PROD_STAMP is not None:
    _s = os.stat(PROD_DB)
    check("boundary: app/lgu.db is byte-for-byte untouched",
          (_s.st_size, _s.st_mtime_ns) == PROD_STAMP)
else:
    check("boundary: app/lgu.db absent and never created",
          not os.path.exists(PROD_DB))

print("")
print("%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
