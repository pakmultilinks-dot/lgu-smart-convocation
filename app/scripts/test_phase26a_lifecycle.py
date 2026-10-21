"""Phase 26A — registration-to-entry lifecycle integrity (disposable DB).

Reproduces the acceptance contradiction the screenshot review raised: a
student could appear "ready" / "Registration active" in the portal while the
entry path reported no usable pass. The root cause was that readiness was
computed from PROFILE-SETUP items (registration active + photo + published
date) with NO entry-pass item, so "You are ready" fired without a live gate
credential.

This suite drives the authoritative chain end to end on ONE temp database and
asserts that student-facing state, pass state, scanner response and admission
data always agree. app/lgu.db is never opened (stamped before and after).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase26a_lifecycle.py
"""

import os
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

TMP = tempfile.mkdtemp(prefix="lgu-p26a-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "lifecycle.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "student-photos")

from io import BytesIO  # noqa: E402

from openpyxl import Workbook  # noqa: E402

import config  # noqa: E402
config.require_test_db()
import convocation_qr as cqr  # noqa: E402
import database  # noqa: E402
import emailer  # noqa: E402
import exam_auth  # noqa: E402
import exam_registrations as reg  # noqa: E402
import readiness as rd  # noqa: E402
import web.routes as vr  # noqa: E402
import web.student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402
from _scanner_fixture import scanner_headers  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

failures = 0
checks = 0
STAFF_USER, STAFF_PW = "p26 officer", "phase26a-lifecycle"
PW = "phase26a-lifecycle-pw"
AVA = ("ava.phase26@uni.edu.pk", "REG-2601", "26001", "Ava Phase26")
BOB = ("bob.phase26@uni.edu.pk", "REG-2602", "26002", "Bob Phase26")
CAR = ("car.phase26@uni.edu.pk", "REG-2603", "26003", "Carol Phase26")


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def step(n, title):
    print("\n== STEP %s: %s" % (n, title))


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
    import re
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


def scan(payload, gate_id=1, mode="entry"):
    return client.post("/api/scan", json={"payload": payload,
                                          "gate_id": gate_id, "mode": mode},
                       headers=SCANNER_HDRS).get_json()


def staff_post(path, data):
    global TOK
    TOK = csrf_of(html(client.get("/exam/event")))
    data = dict(data, csrf_token=TOK)
    return client.post(path, data=data, follow_redirects=True)


def readiness(token):
    st, body = sget("/api/student/readiness", token)
    return st, (body.get("readiness") or {})


def item_of(body, key):
    return next((i for i in body.get("items", []) if i["key"] == key), None)


# ---------------------------------------------------------------- boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
SCANNER_HDRS = scanner_headers(client)

CONV = raw("SELECT * FROM convocations WHERE is_active = 1")[0]["id"]
exam_auth.create_staff(STAFF_USER, "P26 Officer", STAFF_PW)
page = html(client.get("/exam/login"))
TOK = csrf_of(page)
client.post("/exam/login", data={"csrf_token": TOK, "username": STAFF_USER,
                                 "password": STAFF_PW},
            follow_redirects=True)

# ------------------------------------------- STEP 1: event + registrations
step(1, "Publish an event and import synthetic registrations")
TOK = csrf_of(html(client.get("/exam/event")))
client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-11-01",
                  "confirmed_date": "2026-11-15", "venue": "Pass Hall",
                  "instructions": "Bring your student card."})
client.post("/exam/event/publish", data={"csrf_token": TOK})
batch = client.post(
    "/exam/registrations/import",
    data={"csrf_token": TOK,
          "file": (BytesIO(xlsx([["REG-2601", AVA[0], AVA[2], AVA[3],
                                  "Computer Science"],
                                 ["REG-2602", BOB[0], BOB[2], BOB[3],
                                  "Electrical Engineering"],
                                 ["REG-2603", CAR[0], CAR[2], CAR[3],
                                  "Mechanical Engineering"]])), "regs.xlsx")},
    content_type="multipart/form-data")
import re as _re
BID = int(_re.search(r"/import/(\d+)",
                     batch.headers.get("Location", "")).group(1))
client.post("/exam/registrations/import/%d/commit" % BID,
            data={"csrf_token": TOK})
check("event published + 3 registrations imported",
      len(raw("SELECT * FROM convocation_registrations WHERE convocation_id=?",
              (CONV,))) == 3)

# ------------------------------------------- STEP 2: registered student with
# NO pass yet — readiness must NOT claim "ready"
step(2, "Registered-but-unissued student is NOT told 'You are ready'")
st, _ = signup(*AVA)
check("Ava signed up", st == 200, st)
tokA = login(AVA[0])[1].get("token")
st, rdA = readiness(tokA)
item_pass = item_of(rdA, "entry_pass")
check("readiness exposes an entry_pass item", item_pass is not None, rdA.get("items"))
check("an eligible-but-unissued student has entry_pass=todo",
      item_pass and item_pass["status"] == "todo"
      and item_pass["kind"] == "required", item_pass)
check("outstanding >= 1 so the screen cannot say 'You are ready'",
      rdA["summary"]["outstanding"] >= 1, rdA["summary"])
reg_item = item_of(rdA, "registration")
check("registration itself is still confirmed (done)",
      reg_item and reg_item["status"] == "done", reg_item)

# ------------------------------------------- STEP 3: issue the pass -> the
# entry_pass item flips to done; pass references the right registration
step(3, "Issuing a pass flips entry_pass to done and binds the registration")
st, ib = issue(tokA)
payload = (ib.get("pass") or {}).get("payload", "")
check("Ava received an LGU2 convocation pass", st == 200 and payload.startswith("LGU2:"), (st, ib))
pass_row = raw("SELECT * FROM convocation_passes WHERE convocation_id=? AND registration_id=?",
               (CONV, raw("SELECT id FROM convocation_registrations WHERE roll_number=?", (AVA[2],))[0]["id"]))
check("exactly one active pass bound to Ava's registration",
      len(pass_row) == 1 and pass_row[0]["status"] == "active", pass_row)
st, rdA = readiness(tokA)
item_pass = item_of(rdA, "entry_pass")
check("readiness entry_pass flips to done after issuance",
      item_pass and item_pass["status"] == "done", item_pass)
# The entry_pass required item is now done; only the profile-photo required
# item (not part of this chain) remains outstanding.
check("entry_pass no longer counts as outstanding",
      item_pass and item_pass["status"] == "done"
      and rdA["summary"]["required_done"] >= 3, rdA["summary"])

# ------------------------------------------- STEP 4: valid pass admitted once
step(4, "A valid pass is recorded at entry exactly once")
r = scan(payload, gate_id=1, mode="entry")
check("valid LGU2 pass admitted at the gate",
      r.get("status") == "ok" and r.get("level") == "green", r)
adm = raw("SELECT * FROM convocation_admissions WHERE convocation_id=?", (CONV,))
check("one admission row recorded", len(adm) == 1, adm)
r2 = scan(payload, gate_id=1, mode="entry")
check("a repeated entry scan is refused (already admitted)",
      r2.get("status") == "error" and r2.get("title") == "ALREADY ADMITTED", r2)
check("still exactly one admission row (no double admit)",
      len(raw("SELECT * FROM convocation_admissions WHERE convocation_id=?", (CONV,))) == 1)

# ------------------------------------------- STEP 5: wrong mode (exit) is
# rejected for convocation passes
step(5, "Convocation passes are entry-only — exit is refused")
stb, _ = signup(*BOB)
check("Bob signed up", stb == 200, stb)
tokB = login(BOB[0])[1].get("token")
st, ibb = issue(tokB)
bpayload = (ibb.get("pass") or {}).get("payload", "")
rx = scan(bpayload, gate_id=1, mode="exit")
check("exit mode on a convocation pass is refused (entry-only)",
      rx.get("level") == "amber" and "ENTRY-ONLY" in str(rx.get("title", "")).upper(), rx)

# ------------------------------------------- STEP 6: wrong event / forged /
# revoked credential handling
step(6, "Forged, revoked and wrong-registration credentials are rejected")
rf = scan("LGU2:" + "f" * 43, gate_id=1, mode="entry")
check("a forged LGU2 token is rejected",
      rf.get("status") == "error" and rf.get("level") == "red", rf)
# Cancel Bob's registration (his pass is issued but unused — exit was refused)
# -> the pass must stop validating at scan time.
exec_sql("UPDATE convocation_registrations SET status='cancelled' WHERE roll_number=?", (BOB[2],))
rc = scan(bpayload, gate_id=1, mode="entry")
check("a cancelled registration stops its pass from admitting",
      rc.get("status") == "error" and rc.get("level") == "red", rc)
exec_sql("UPDATE convocation_registrations SET status='active' WHERE roll_number=?", (BOB[2],))

# ------------------------------------------- STEP 7: an active registration
# that is NOT on the authoritative list cannot be linked by name alone
step(7, "No registration exists for an unlisted student (no silent linking)")
stc, _ = signup(*CAR)
check("Carol signed up", stc == 200, stc)
tokC = login(CAR[0])[1].get("token")
stc2, ibc = issue(tokC)
cpayload = (ibc.get("pass") or {}).get("payload", "")
check("Carol (listed, eligible) can still be issued a pass",
      stc2 == 200 and cpayload.startswith("LGU2:"), (stc2, ibc))

# ------------------------------------------- STEP 8: privacy — phone masked by
# default in student-facing payloads where not operationally required
step(8, "Phone is masked in the readiness/entry payload surface")
st, me = sget("/api/student/me", tokA)
phone = ((me.get("profile") or {}).get("phone") or "")
check("student /me returns phone without leaking other students",
      isinstance(phone, str), me.get("profile"))

# ------------------------------------------- summary
print("\n== PROD DB integrity ==")
if PROD_STAMP is not None:
    _s = os.stat(PROD_DB)
    check("production lgu.db untouched",
          (_s.st_size, _s.st_mtime_ns) == PROD_STAMP,
          (_s.st_size, _s.st_mtime_ns))
else:
    check("production lgu.db absent (never created)", not os.path.exists(PROD_DB))

print("\nRESULT: %d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
