#!/usr/bin/env python3
"""Phase 17 - Cross-role product acceptance & data integrity.

Runs the integrated product as three real roles (Examination Department
staff, students, volunteers) against a DISPOSABLE database, proves data
integrity end to end, and pins the two Phase 17 product fixes:

  (a) queued-scan timestamps are normalised and never junk
      (web/routes.py::_valid_scanned_at) so no lexicographically-late string
      can sit inside every models._throughput_map / _busiest_gate_label window;
  (b) the staff dashboard advertises only LIVE, usable convocation passes
      (web/exam_routes.py::dashboard_metrics) instead of every pass ever
      issued, which kept advertising a QR after cancel/revoke.

Usage (from app/):  ..\\.venv\\Scripts\\python.exe scripts\\test_phase17_cross_role_acceptance.py

The production DB app/lgu.db is only stat'ed + hashed - never opened.
No real student identities are used; every name/email/roll is synthetic.
"""
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from base64 import b64decode
from hashlib import sha256
from zipfile import ZipFile

# ---------------------------------------------------------------- guardrails
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD_DB = os.path.join(APP_DIR, "lgu.db")
PROD_STAMP = None
if os.path.exists(PROD_DB):
    _s = os.stat(PROD_DB)
    with open(PROD_DB, "rb") as fh:
        _PROD_SHA = sha256(fh.read()).hexdigest().upper()
    PROD_STAMP = (_s.st_size, _s.st_mtime_ns, _PROD_SHA)

TMP = tempfile.mkdtemp(prefix="lgu-p17x-")
for _k, _v in (("LGU_TESTING", "1"),
               ("LGU_DB_PATH", os.path.join(TMP, "accept.db")),
               ("LGU_EMAIL_MODE", "fake"),
               ("LGU_STUDENT_PHOTO_DIR", os.path.join(TMP, "student-photos")),
               ("LGU_MEDALIST_PHOTO_DIR", os.path.join(TMP, "medalist-photos"))):
    os.environ[_k] = _v
for _k in ("LGU_SMTP_HOST", "LGU_SMTP_USER", "LGU_SMTP_PASSWORD",
           "LGU_MAIL_FROM", "LGU_ADMIN_PIN", "LGU_SECRET_KEY", "LGU_HMAC_SECRET"):
    os.environ.pop(_k, None)

sys.path.insert(0, APP_DIR)
import config
config.require_test_db()
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import database
import emailer
import exam_auth
import exam_import
import exam_registrations as reg
import ids
import migrations
import models
import scanner_auth
import web.student_routes as sr
from web import exam_routes as ex
from web import routes as vr
from web.routes import create_app
from _scanner_fixture import scanner_headers  # noqa: E402  (script dir on path)

STAFF_USER, STAFF_PW = "p17 officer", "phase17-acceptance"
PW = "Phase17-Synthetic-Pass"
DEPT = "Department of Test Engineering"
AVA = ("p17.ava@synthetic.invalid", "P17-A001", "P17A001", "AVERY ALDRIN")
BOB = ("p17.bob@synthetic.invalid", "P17-B001", "P17B001", "BRUNO BARKER")
CAR = ("p17.carla@synthetic.invalid", "P17-C001", "P17C001", "CARLA CHEN")
DAV = ("p17.david@synthetic.invalid", "P17-D001", "P17D001", "DAVID DONNELLY")
BET = ("p17.betty@synthetic.invalid", "P17-E001", "P17E001", "BETTY ESCOBAR")
PEOPLE = (AVA, BOB, CAR, DAV, BET)
ROWS_OK = [(p[1], p[0], p[2], p[3], DEPT) for p in PEOPLE]

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$")
LEAKS = ("password_hash", "pin_hash", "token_hash", "code_hash",
         "secret_key", "hmac_secret")
TINY_PNG = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

checks = failures = steps = 0


def check(label, cond, detail=""):
    global checks, failures
    checks += 1
    if cond:
        print("ok   " + label)
        return True
    failures += 1
    print("FAIL " + label + (("  | " + str(detail)[:400]) if detail else ""))
    return False


def step(n, title):
    global steps
    steps += 1
    print("\n--- STEP %d: %s" % (n, title))


def repo_tree():
    """Every path under app/ that a run must not write into (caches skipped)."""
    out = set()
    for root, dirs, files in os.walk(APP_DIR):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv")]
        for f in files:
            if not f.endswith(".pyc"):
                out.add(os.path.relpath(os.path.join(root, f), APP_DIR))
    return out


def raw(sql, args=()):
    db = database.get_db()
    try:
        return [dict(r) for r in db.execute(sql, args).fetchall()]
    finally:
        db.close()


def one(sql, args=()):
    rows = raw(sql, args)
    return rows[0] if rows else {}


def exec_sql(sql, args=()):
    db = database.get_db()
    try:
        db.execute(sql, args)
        db.commit()
    finally:
        db.close()


def html(resp):
    return resp.get_data(as_text=True)


def csrf_of(s):
    m = re.search(r'name="csrf_token" value="([^"]+)"', s)
    return m.group(1) if m else ""


def new_csrf():
    return csrf_of(html(client.get("/exam/event")))


def staff_post(path, data):
    return client.post(path, data=dict(data, csrf_token=new_csrf()),
                       follow_redirects=True)


def staff_get(path):
    return client.get(path)


def spost(path, body, token=None):
    headers = {"Authorization": "Bearer %s" % token} if token else {}
    r = client.post(path, json=body, headers=headers)
    return r.status_code, (r.get_json(silent=True) or {})


def sget(path, token=None):
    headers = {"Authorization": "Bearer %s" % token} if token else {}
    r = client.get(path, headers=headers)
    return r.status_code, (r.get_json(silent=True) or {})


def signup(acc):
    """verify -> code read from the fake outbox -> complete. Returns token."""
    emailer.OUTBOX.clear()
    st, body = spost("/api/student/verify",
                     {"registration_number": acc[1], "university_email": acc[0],
                      "roll_number": acc[2], "student_name": acc[3]})
    if st != 200:
        return "", (st, body)
    code = emailer.OUTBOX[-1][1] if emailer.OUTBOX else ""
    st, done = spost("/api/student/complete",
                     {"challenge_id": body.get("challenge_id"), "code": code,
                      "password": PW})
    return done.get("token", ""), (st, done)


def login(acc, password=PW):
    return spost("/api/student/login", {"email": acc[0], "password": password})


def reset_limits():
    for bucket in sr._HITS.values():
        bucket.clear()
    vr._PIN_FAILS.clear()
    vr._SCAN_LOGIN_FAILS.clear()
    ex._EXAM_FAILS.clear()


def issue(token):
    return spost("/api/student/pass/issue", {}, token)


def hpost(path, body, headers):
    r = client.post(path, json=body, headers=headers)
    return r.status_code, (r.get_json(silent=True) or {})


def scan(payload, gate_id=1, mode="entry", headers=None):
    # Call sites only ever inspect the JSON body (title/level/status).
    return hpost("/api/scan",
                 {"payload": payload, "gate_id": gate_id, "mode": mode},
                 SCANNER_HDRS if headers is None else headers)[1]


def sync(items, headers=None):
    return hpost("/api/sync", {"items": items},
                 SCANNER_HDRS if headers is None else headers)


def upload(blob, filename="regs.xlsx", follow=False):
    return client.post(
        "/exam/registrations/import",
        data={"csrf_token": new_csrf(), "file": (io.BytesIO(blob), filename)},
        content_type="multipart/form-data", follow_redirects=follow)


def xlsx(rows, header=None, sheet="registrations"):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(list(header if header is not None else reg.CANONICAL_COLUMNS))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def last_batch():
    return raw("SELECT id FROM import_batches ORDER BY id DESC")[0]["id"]


def metrics():
    # dashboard_metrics() builds issue hrefs with url_for -> needs a request ctx.
    with app.test_request_context("/exam/dashboard"):
        return ex.dashboard_metrics(database.get_db())


def send_email_mode(mode):
    old = config.EMAIL_MODE
    config.EMAIL_MODE = mode
    return old


# ---------------------------------------------------------------- boot
BEFORE_TREE = repo_tree()
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
anon = app.test_client()                 # separate client: no staff session
SCANNER_HDRS = scanner_headers(client)

CONV = one("SELECT id FROM convocations WHERE is_active = 1")["id"]

# ================================================================ STEP 1
step(1, "Boot, publish the real event, import the roster, sign students up")

check("BOOT: production DB stamped for a byte-identical end check",
      PROD_STAMP is not None or not os.path.exists(PROD_DB), PROD_DB)
check("BOOT: config points at the disposable DB, not production",
      os.path.abspath(config.DB_PATH)
      == os.path.abspath(os.environ["LGU_DB_PATH"])
      and os.path.abspath(config.DB_PATH) != os.path.abspath(PROD_DB),
      config.DB_PATH)
check("BOOT: photo storage redirected into the temp dir",
      config.STUDENT_PHOTO_DIR.startswith(TMP)
      and config.MEDALIST_PHOTO_DIR.startswith(TMP),
      (config.STUDENT_PHOTO_DIR, config.MEDALIST_PHOTO_DIR))

redirs = [(p, anon.get(p)) for p in
          ("/exam/", "/exam/dashboard", "/exam/support", "/exam/registrations",
           "/exam/announcements", "/exam/event", "/exam/medalists/",
           "/exam/medalists/new", "/exam/support/1", "/exam/registrations/1")]
check("ANON: every /exam/* route demands staff login (302 -> exam/login)",
      all(r.status_code == 302 and "/exam/login" in r.headers.get("Location", "")
          for _, r in redirs),
      [(p, r.status_code, r.headers.get("Location")) for p, r in redirs])
check("ANON: /admin is 401 unlock.html for an anonymous browser",
      anon.get("/admin").status_code == 401)
check("ANON: legacy LAN-trust GETs stay public (accepted, documented design)",
      all(anon.get(p).status_code == 200
          for p in ("/dashboard", "/guests",
                    "/api/gates", "/api/config", "/api/health",
                    "/api/student/medalists", "/api/student/event",
                    "/api/student/announcements")))
# Phase 28: /api/settings left the LAN-trust list. Its payload was never
# uniquely secret — /api/config above still publishes the same event
# identity to the kiosk and the landing page — but the settings table is
# administrator-editable, so READING it is now an administrator action with
# the same PIN as the write. See test_phase28_authorization_closure.
_r = anon.get("/api/settings")
check("ANON: /api/settings is no longer LAN-trust (401, PIN required)",
      _r.status_code == 401, _r.status_code)
# /broadcast is NOT LAN-trust: master audit V-AUTH-03/04 PIN-gates it.
_r = anon.get("/broadcast")
check("ANON: /broadcast is PIN-gated (401 unlock.html), not LAN-trust",
      _r.status_code == 401 and "unlock" in html(_r).lower(),
      (_r.status_code, html(_r)[:120]))

# Staff sign-in: in-process account creation (the CLI helper is interactive).
exam_auth.create_staff(STAFF_USER, "P17 Officer", STAFF_PW)
client.post("/exam/login",
            data={"csrf_token": csrf_of(html(client.get("/exam/login"))),
                  "username": STAFF_USER, "password": STAFF_PW},
            follow_redirects=True)
check("STAFF: signed in to the Examination Department portal",
      "Sign out" in html(client.get("/exam/dashboard")))

r = client.post("/exam/event/save", data={"name": "Forged", "year": "2026"})
check("STAFF: a staff POST without a CSRF token is refused (403)",
      r.status_code == 403, r.status_code)

# The seeded convocation is already active - save + publish on THAT event
# (/exam/event/create would mint a second, non-active convocation).
r = staff_post("/exam/event/save",
               {"name": "LGU Synthetic Convocation 2026", "year": "2026",
                "expected_date": "2026-11-01", "confirmed_date": "2027-03-15",
                "rehearsal_date": "2027-03-14", "rehearsal_time": "10:30",
                "venue": "Pass Hall", "instructions": "Bring your student card."})
check("STAFF: draft event saved on the active convocation", r.status_code == 200)
r = staff_post("/exam/event/publish", {})
check("STAFF: event published (students can derive an invitation)",
      r.status_code == 200
      and one("SELECT 1 x FROM convocation_publications"
              " WHERE convocation_id = ?", (CONV,)) != {})
check("STAFF: confirmed date is exactly what staff published",
      one("SELECT confirmed_date c FROM convocation_publications"
          " WHERE convocation_id = ?", (CONV,))["c"] == "2027-03-15")

r = upload(xlsx(ROWS_OK))
loc = r.headers.get("Location", "")
ok_batch = int(re.search(r"/import/(\d+)", loc).group(1)) if loc else 0
check("STAFF: the import workflow issues a preview batch", ok_batch > 0, loc)
r = staff_post("/exam/registrations/import/%d/commit" % ok_batch,
               {"mode": "insert"})
result = json.loads(one("SELECT result_json r FROM import_batches WHERE id = ?",
                        (ok_batch,))["r"] or "{}")
check("STAFF: 5 synthetic registrations imported through the real workflow",
      result.get("inserted") == 5, result)
check("STAFF: import batch marked committed",
      one("SELECT status s FROM import_batches WHERE id = ?",
          (ok_batch,))["s"] == "committed")
check("STAFF: import_committed audited in audit_log (not registration_audit)",
      one("SELECT COUNT(*) c FROM audit_log"
          " WHERE action = 'import_committed'")["c"] >= 1
      and one("SELECT COUNT(*) c FROM registration_audit"
              " WHERE action LIKE 'import_commit%'")["c"] == 0)

# ------------------------------------------------ upload rejection matrix
r = upload(b"this is not a spreadsheet at all", "not-a-workbook.xlsx")
check("IMPORT: non-zip upload rejected with the .xls/CSV message",
      "Not a valid .xlsx file" in html(r), html(r)[:250])
_zipbuf = io.BytesIO()
with ZipFile(_zipbuf, "w") as zf:
    zf.writestr("hello.txt", "hi")
r = upload(_zipbuf.getvalue(), "fake-workbook.xlsx")
check("IMPORT: a zip that is not a workbook is rejected cleanly",
      "could not be read as an Excel workbook" in html(r), html(r)[:250])
r = upload(xlsx([["P17-X001"]], header=("registration_number",)),
           "missing-column.xlsx")
check("IMPORT: a missing required header names the exact column",
      "Missing required column(s): university_email" in html(r), html(r)[:250])
from openpyxl import Workbook as _WB
_buf = io.BytesIO()
_WB().save(_buf)
r = upload(_buf.getvalue(), "empty-sheet.xlsx")
check("IMPORT: an empty first worksheet is rejected",
      "The first worksheet is empty." in html(r), html(r)[:250])

upload(xlsx([["P17-Z001", "p17.zoe@synthetic.invalid", "P17Z001",
              "ZOE ZAMORA", DEPT],
             ["P17-Z001", "p17.zoe@synthetic.invalid", "P17Z001",
              "ZOE ZAMORA", DEPT]]), "dup.xlsx", follow=True)
dup_rows = raw("SELECT status, errors_json e FROM import_staging"
               " WHERE batch_id = ? ORDER BY row_no", (last_batch(),))
check("IMPORT: in-file duplicate staged as duplicate, first row as valid",
      len(dup_rows) == 2 and dup_rows[0]["status"] == "valid"
      and dup_rows[1]["status"] == "duplicate"
      and "duplicates row 2" in dup_rows[1]["e"], dup_rows)
upload(xlsx([["P17-A001", AVA[0], AVA[2], AVA[3], DEPT]]),
       "conflict.xlsx", follow=True)
cf_id = last_batch()
cf_rows = raw("SELECT status, errors_json e FROM import_staging"
              " WHERE batch_id = ?", (cf_id,))
check("IMPORT: a row already in the official records stages as conflict",
      len(cf_rows) == 1 and cf_rows[0]["status"] == "conflict"
      and "Already exists in the official records" in cf_rows[0]["e"], cf_rows)
ava_before = dict(one("SELECT id, status, updated_at, import_batch_id"
                       " FROM convocation_registrations"
                       " WHERE convocation_id = ? AND registration_number = ?",
                       (CONV, AVA[1])))
staff_post("/exam/registrations/import/%d/commit" % cf_id, {"mode": "insert"})
cf_result = json.loads(one("SELECT result_json r FROM import_batches"
                           " WHERE id = ?", (cf_id,))["r"] or "{}")
# The invariant is that an over-claiming conflict batch mutates NOTHING. An
# identical re-upload lands as `unchanged` (same fields, same row); a
# differing one is refused as `skipped_conflict`. Either way: 0 inserted,
# 0 updated, and the official row is byte-identical afterwards.
check("IMPORT: committing a conflict-only batch inserts nothing",
      cf_result.get("inserted") == 0 and cf_result.get("updated") == 0
      and (cf_result.get("skipped_conflict", 0)
           + cf_result.get("unchanged", 0)) == 1, cf_result)
ava_after = dict(one("SELECT id, status, updated_at, import_batch_id"
                     " FROM convocation_registrations"
                     " WHERE convocation_id = ? AND registration_number = ?",
                     (CONV, AVA[1])))
check("IMPORT: the conflicting official record is untouched",
      ava_after == ava_before and one(
          "SELECT COUNT(*) c FROM convocation_registrations"
          " WHERE convocation_id = ? AND registration_number = ?",
          (CONV, AVA[1]))["c"] == 1, (ava_before, ava_after))

over = [[("P17-O%05d" % i), ("p17.over%05d@synthetic.invalid" % i),
         ("P17O%05d" % i), ("OVERFLOW STUDENT %05d" % i), DEPT]
        for i in range(6501)]
r = upload(xlsx(over), "too-many-rows.xlsx")
check("IMPORT: more than 6500 data rows is refused before staging",
      "More than 6500 data rows" in html(r), html(r)[:250])

# Forced mid-commit failure: rollback, batch failed, audit in the right table.
r = upload(xlsx([["P17-F001", "p17.fay@synthetic.invalid", "P17F001",
                  "FAY FLETCHER", DEPT]]), "forced-failure.xlsx")
boom_batch = int(re.search(r"/import/(\d+)",
                           r.headers.get("Location", "")).group(1)) \
    if r.headers.get("Location") else 0
audit_before = one("SELECT COUNT(*) c FROM audit_log"
                   " WHERE action = 'import_failed'")["c"]
regaudit_before = one("SELECT COUNT(*) c FROM registration_audit")["c"]
_true_insert = exam_import._insert_row


def _boom(*a, **k):
    raise RuntimeError("forced mid-commit failure injected by Phase 17")


exam_import._insert_row = _boom
try:
    r = staff_post("/exam/registrations/import/%d/commit" % boom_batch,
                   {"mode": "insert"})
finally:
    exam_import._insert_row = _true_insert
check("IMPORT: a mid-commit failure reports a full rollback",
      "fully rolled back" in html(r), html(r)[:300])
check("IMPORT: the failed batch is marked failed, never committed",
      one("SELECT status s FROM import_batches WHERE id = ?",
          (boom_batch,))["s"] == "failed")
check("IMPORT: no registration survived the rolled-back batch",
      raw("SELECT 1 x FROM convocation_registrations"
          " WHERE registration_number = 'P17-F001'") == [])
check("IMPORT: import_failed audited in audit_log only",
      one("SELECT COUNT(*) c FROM audit_log"
          " WHERE action = 'import_failed'")["c"] == audit_before + 1
      and one("SELECT COUNT(*) c FROM registration_audit")["c"]
      == regaudit_before,
      (one("SELECT COUNT(*) c FROM audit_log"
           " WHERE action = 'import_failed'")["c"], audit_before))

# ------------------------------------------------ student sign-ups
TOKENS = {}
for acc in PEOPLE:
    reset_limits()
    tok, (st, body) = signup(acc)
    TOKENS[acc[0]] = tok
    check("STUDENT: %s verified, claimed and signed in" % acc[3],
          st == 200 and bool(tok), (st, body))
check("STUDENT: 5 registration claims established",
      len(raw("SELECT * FROM registration_claims WHERE convocation_id = ?",
              (CONV,))) == 5)
check("STUDENT: login takes the `email` field", login(BOB)[0] == 200)
check("STUDENT: a wrong password is refused (401)",
      login(BOB, "not-the-password")[0] == 401)

st, me = sget("/api/student/me", TOKENS[AVA[0]])
check("STUDENT: /me exposes account.email at the documented path",
      st == 200 and me.get("account", {}).get("email") == AVA[0], me)
check("STUDENT: no password material in the identity payload",
      "password" not in json.dumps(me).lower(), json.dumps(me)[:300])
st, _ = spost("/api/student/logout", {}, TOKENS[AVA[0]])
st2, _ = sget("/api/student/me", TOKENS[AVA[0]])
check("STUDENT: logout revokes the session immediately (401)",
      st == 200 and st2 == 401, (st, st2))
TOKENS[AVA[0]] = login(AVA)[1].get("token", "")

# ================================================================ STEP 2
step(2, "Staff workflow: support queue, corrections, medalists, dashboard truth")

reset_limits()
st, body = spost("/api/student/support",
                 {"category": "correction",
                  "subject": "Synthetic record check",
                  "message": "Please confirm my synthetic department."},
                 TOKENS[BET[0]])
bet_id = body.get("request", {}).get("id", 0)
check("STAFF: student filed a support request", st == 200 and bet_id > 0, body)
r = staff_post("/exam/support/%d/respond" % bet_id,
               {"message": "PUBLIC-REPLY-MARKER 445566"})
check("STAFF: a public reply is recorded", r.status_code == 200, r.status_code)
st, det = sget("/api/student/support/%d" % bet_id, TOKENS[BET[0]])
check("STUDENT: the public reply is in the student-visible history",
      "PUBLIC-REPLY-MARKER 445566" in json.dumps(det), json.dumps(det)[:400])
r = staff_post("/exam/support/%d/status" % bet_id, {"status": "info_required"})
check("STAFF: request moved to info_required via a real transition",
      r.status_code == 200, r.status_code)
r = staff_post("/exam/support/%d/respond" % bet_id,
               {"message": "INTERNAL-ONLY-MARKER 918273", "internal": "1"})
staff_html = html(staff_get("/exam/support/%d" % bet_id))
check("STAFF: the internal note is stored and shown to staff only",
      r.status_code == 200 and "INTERNAL-ONLY-MARKER 918273" in staff_html,
      (r.status_code,))
st, det = sget("/api/student/support/%d" % bet_id, TOKENS[BET[0]])
check("STUDENT: the internal staff note never reaches the student",
      "INTERNAL-ONLY-MARKER 918273" not in json.dumps(det), json.dumps(det)[:400])
st, _ = sget("/api/student/support/%d" % bet_id, TOKENS[AVA[0]])
check("STUDENT: another account cannot read this request (404)", st == 404, st)
st, body = sget("/api/student/readiness", TOKENS[BET[0]])
ready = body.get("readiness", {})
check("STUDENT: info_required surfaces as readiness item support:<id>",
      ("support:%d" % bet_id) in [i.get("key") for i in ready.get("items", [])]
      and ("support:%d:info_required" % bet_id)
      in [x.get("key") for x in ready.get("reminders", [])],
      (ready.get("items"), ready.get("reminders")))
check("STUDENT: readiness always carries summary/items/reminders",
      set(ready) >= {"summary", "items", "reminders"}, sorted(ready))

# ------------------------------------------------ registration corrections
ava_row = one("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (AVA[2],))
bob_row = one("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (BOB[2],))
dav_row = one("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (DAV[2],))
r = staff_post("/exam/registrations/%d/correct" % ava_row["id"],
               {"university_email": AVA[0], "roll_number": AVA[2],
                "student_name": AVA[3] + " JR", "department": DEPT})
check("STAFF: a legitimate correction is saved and audited",
      r.status_code == 200
      and one("SELECT student_name n FROM convocation_registrations"
              " WHERE id = ?", (ava_row["id"],))["n"] == AVA[3] + " JR"
      and one("SELECT COUNT(*) c FROM registration_audit"
              " WHERE registration_id = ? AND action = 'correct'",
              (ava_row["id"],))["c"] == 1, r.status_code)
r = staff_post("/exam/registrations/%d/correct" % ava_row["id"],
               {"university_email": AVA[0], "roll_number": AVA[2],
                "student_name": AVA[3] + " JR", "department": DEPT})
check("STAFF: a no-op correction is refused, not silently accepted",
      r.status_code == 400 and "Nothing changed" in html(r), r.status_code)
r = staff_post("/exam/registrations/%d/correct" % ava_row["id"],
               {"university_email": BOB[0], "roll_number": AVA[2],
                "student_name": AVA[3] + " JR", "department": DEPT})
check("STAFF: taking another student's email is refused",
      r.status_code == 400
      and "already belongs to another registration" in html(r), html(r)[:250])

# ------------------------------------------------ status lifecycle
clean, errs = reg.clean_row({"registration_number": "P17-T001",
                             "university_email": "p17.timmy@synthetic.invalid",
                             "roll_number": "P17T001",
                             "student_name": "TIMMY TORRES",
                             "department": DEPT})
check("STAFF: a throwaway registration validates cleanly", not errs, errs)
db = database.get_db()
reg.insert(db, CONV, clean, None, STAFF_USER)
db.commit()
db.close()
tim_id = one("SELECT id FROM convocation_registrations"
             " WHERE registration_number = 'P17-T001'")["id"]
r = staff_post("/exam/registrations/%d/status" % tim_id, {"action": "cancel"})
check("STAFF: cancel moves active -> cancelled",
      r.status_code == 200
      and one("SELECT status s FROM convocation_registrations WHERE id = ?",
              (tim_id,))["s"] == "cancelled", r.status_code)
r = staff_post("/exam/registrations/%d/status" % tim_id, {"action": "reinstate"})
check("STAFF: reinstate moves cancelled -> active",
      one("SELECT status s FROM convocation_registrations WHERE id = ?",
          (tim_id,))["s"] == "active", r.status_code)
r = staff_post("/exam/registrations/%d/status" % tim_id, {"action": "revoke"})
check("STAFF: revoke moves active -> revoked",
      one("SELECT status s FROM convocation_registrations WHERE id = ?",
          (tim_id,))["s"] == "revoked", r.status_code)
r = staff_post("/exam/registrations/%d/status" % tim_id, {"action": "cancel"})
check("STAFF: a revoked registration cannot be cancelled",
      r.status_code == 400
      and "Cannot cancel a registration that is revoked." in html(r),
      r.status_code)
r = staff_post("/exam/registrations/%d/status" % tim_id, {"action": "reinstate"})
check("STAFF: revoke is permanent (cannot be reinstated)",
      r.status_code == 400
      and "Cannot reinstate a registration that is revoked." in html(r),
      r.status_code)
check("STAFF: every status change is audited",
      len(raw("SELECT * FROM registration_audit WHERE registration_id = ?",
              (tim_id,))) >= 3)

# ------------------------------------------------ medalists
m1 = {"department": DEPT, "student_name": "MEDALIST ONE SYNTHETIC",
      "award_category": "gold", "position": "1st", "reference_number": "M17-1"}
r = staff_post("/exam/medalists/new", m1)
m1_row = one("SELECT id FROM medalists WHERE reference_number = 'M17-1'")
check("STAFF: medalist created as a draft", r.status_code == 200 and m1_row,
      r.status_code)
m1_id = m1_row.get("id", 0)
names = [m.get("student_name")
         for m in sget("/api/student/medalists")[1].get("medalists", [])]
check("STUDENT: a draft medalist is invisible to students",
      "MEDALIST ONE SYNTHETIC" not in names, names)
r = staff_post("/exam/medalists/%d/publish" % m1_id, {})
check("STAFF: publishing before a photo is refused with a clear reason",
      r.status_code == 400
      and "Upload and approve a picture before publishing this record."
      in html(r), (r.status_code, html(r)[:250]))
r = client.post("/exam/medalists/%d/photo" % m1_id,
                data={"csrf_token": new_csrf(),
                      "photo": (io.BytesIO(TINY_PNG), "p17.png")},
                content_type="multipart/form-data", follow_redirects=True)
check("STAFF: photo upload accepted", r.status_code == 200, r.status_code)
r = staff_post("/exam/medalists/%d/publish" % m1_id, {})
feed = sget("/api/student/medalists")[1]
names = [m.get("student_name") for m in feed.get("medalists", [])]
check("STUDENT: a published medalist appears in the public feed",
      r.status_code == 200 and "MEDALIST ONE SYNTHETIC" in names,
      (r.status_code, names))
check("STUDENT: the public medalist payload omits private fields",
      all("reference_number" not in m and "publication" not in m
          for m in feed.get("medalists", [])), feed.get("medalists", [])[:1])
r = staff_post("/exam/medalists/new",
               dict(m1, reference_number="M17-2"))
check("STAFF: a duplicate award (same dept/category/position) is refused",
      r.status_code == 400 and "already has an award record" in html(r),
      (r.status_code, html(r)[:250]))

# ------------------------------------------------ announcements
staff_post("/exam/announcements/create",
           {"title": "Synthetic Phase 17 Notice", "body": "Synthetic body.",
            "audience": "students"})
ann_row = one("SELECT id FROM announcements WHERE title = ?",
              ("Synthetic Phase 17 Notice",))
check("STAFF: announcement created as a draft", bool(ann_row))
ann_id = ann_row.get("id", 0)
titles = [a.get("title")
          for a in sget("/api/student/announcements")[1].get("announcements", [])]
check("STUDENT: a draft announcement is invisible to students",
      "Synthetic Phase 17 Notice" not in titles, titles)
staff_post("/exam/announcements/%d/publish" % ann_id, {})
titles = [a.get("title")
          for a in sget("/api/student/announcements")[1].get("announcements", [])]
check("STUDENT: publishing makes the announcement visible",
      "Synthetic Phase 17 Notice" in titles, titles)

# ------------------------------------------------ dashboard truth
met = metrics()
counts = reg.count_status(database.get_db(), CONV)
total = one("SELECT COUNT(*) c FROM convocation_registrations"
            " WHERE convocation_id = ?", (CONV,))["c"]
check("DASHBOARD: registration totals equal the authoritative ledger",
      met["totals"] == {**counts, "total": total},
      (met["totals"], counts, total))
check("DASHBOARD: no pass has been issued yet, so none is advertised",
      met["invitations"]["passes_issued_active"] == 0
      and met["invitations"]["passes_issued_total"] == 0
      and met["invitations"]["qr_active"] is False
      and met["invitations"]["admitted"] == 0, met["invitations"])

# ------------------------------------------------ every dashboard link resolves
KNOWN = {"/", "/dashboard", "/exam", "/exam/", "/exam/dashboard", "/exam/login",
         "/exam/support", "/exam/registrations", "/exam/registrations/template",
         "/exam/registrations/import", "/exam/registrations/history",
         "/exam/announcements", "/exam/event", "/exam/medalists",
         "/exam/medalists/new", "/exam/medalists/import",
         "/exam/medalists/import/template",
         # Phase 19: the authenticated scanner-administration surface, linked
         # from the Event publishing card on the dashboard.
         "/exam/scanners", "/exam/scanners/new",
         # Global chrome linked from every exam page.
         "/admin", "/broadcast", "/exam/medalists/", "/guests", "/scan",
         "/static/css/style.css"}
DYN = ((re.compile(r"^/exam/support/\d+$"), "/exam/support/%d" % bet_id),
       (re.compile(r"^/exam/registrations/import/\d+$"),
        "/exam/registrations/import/%d" % ok_batch),
       (re.compile(r"^/exam/registrations/\d+$"),
        "/exam/registrations/%d" % ava_row["id"]),
       (re.compile(r"^/exam/medalists/import/\d+$"), "/exam/medalists/import"),
       (re.compile(r"^/exam/medalists/\d+$"), "/exam/medalists/%d" % m1_id),
       (re.compile(r"^/exam/announcements/\d+$"),
        "/exam/announcements/%d" % ann_id))
hrefs = set(re.findall(r'href="([^"]+)"', html(staff_get("/exam/dashboard"))))
hrefs |= set(re.findall(r'href="([^"]+)"', html(staff_get("/exam/"))))
bad_links, unmapped = [], []
for h in sorted(hrefs):
    if h.startswith(("http://", "https://", "#", "mailto:")):
        continue
    target = next((repl for pat, repl in DYN if pat.match(h.split("?")[0])), h)
    if target == h and target.split("?")[0] not in KNOWN:
        unmapped.append(h)
        continue
    rr = staff_get(target)
    # /admin and /broadcast are deliberately PIN-gated (401 unlock.html) for
    # a plain staff session: a link that exists but demands a higher
    # credential resolves; only a missing or crashing target is a defect.
    if rr.status_code == 404 or rr.status_code >= 500:
        bad_links.append((h, rr.status_code))
check("DASHBOARD: every rendered href resolves without a 404/500",
      not bad_links, bad_links)
check("DASHBOARD: no unrecognised link target remains", not unmapped, unmapped)

# ------------------------------------------------ deactivated staff
exec_sql("UPDATE staff_users SET is_active = 0 WHERE username = ?",
         (STAFF_USER,))
r = staff_get("/exam/dashboard")
check("STAFF: a deactivated account is bounced to the login page",
      r.status_code in (302, 401)
      or "/exam/login" in r.headers.get("Location", ""), r.status_code)
exec_sql("UPDATE staff_users SET is_active = 1 WHERE username = ?",
         (STAFF_USER,))
r = client.post("/exam/login",
                data={"csrf_token": csrf_of(html(client.get("/exam/login"))),
                      "username": STAFF_USER, "password": STAFF_PW},
                follow_redirects=True)
check("STAFF: re-authentication succeeds after reactivation",
      "Sign out" in html(client.get("/exam/dashboard")), r.status_code)

# ================================================================ STEP 3
step(3, "Student lifecycle: profile, published-only truth, email outage, isolation")

reset_limits()
st, prof = spost("/api/student/profile",
                 {"phone": "0300-0000001", "student_name": "FORGED NAME",
                  "roll_number": "FORGEDROLL"}, TOKENS[BOB[0]])
st, me = sget("/api/student/me", TOKENS[BOB[0]])
check("STUDENT: profile stores the phone and ignores identity fields",
      st == 200 and prof.get("profile", {}).get("phone") == "0300-0000001"
      and me["account"]["email"] == BOB[0], prof)

# ---- published-only event truth
exec_sql("DELETE FROM convocation_publications WHERE convocation_id = ?",
         (CONV,))
st, ev_body = sget("/api/student/event")
check("STUDENT: with no publication the event payload is explicitly null",
      st == 200 and ev_body.get("convocation") is None
      and ev_body.get("event") is None, ev_body)
st, p = issue(TOKENS[AVA[0]])
check("STUDENT: an unpublished event blocks pass issuance (403)",
      st == 403, (st, p))
staff_post("/exam/event/publish", {})
st, ev_body = sget("/api/student/event")
check("STUDENT: republishing restores the real confirmed date, not the draft",
      ev_body.get("event", {}).get("confirmed_date") == "2027-03-15"
      and ev_body["event"]["date_state"] == "confirmed", ev_body)
blob = json.dumps(ev_body)
check("STUDENT: the event payload leaks no internal draft state",
      "is_active" not in blob and '"status"' not in blob, blob[:400])

# ---- legacy roster path through the volunteer scanner
models.add_students([("P17-LEG-1", "P17 LEGACY ONE", "Male", "BS Test"),
                     ("P17-LEG-2", "P17 LEGACY TWO", "Female", "BS Test")])
missing = models.students_missing_ids()
models.assign_ids(missing, ids.generate_id)
leg_row = one("SELECT * FROM students WHERE roll_no = 'P17-LEG-1'")
LEG = ids.make_payload(leg_row["qr_id"])
check("SCANNER: synthetic roster rows carry a real operational QR id",
      len(missing) == 2 and ids.verify_payload(LEG)[0]
      and LEG.startswith("LGU1:"), (missing, LEG))

# ---- rate limits and admin PIN boundaries
reset_limits()
for _ in range(5):
    spost("/api/student/login", {"email": BOB[0], "password": "x"})
st, _ = spost("/api/student/login", {"email": BOB[0], "password": "x"})
check("STUDENT: repeated failed logins hit the 429 rate limit", st == 429, st)
reset_limits()
# config.PIN_RATE_MAX_FAILS wrong PINs are tolerated, the next is 429.
codes = [client.post("/api/admin/verify", json={"pin": "000000"}).status_code
         for _ in range(config.PIN_RATE_MAX_FAILS + 1)]
check("ADMIN: a wrong PIN on /api/admin/verify is 401",
      codes[0] == 401, codes)
check("ADMIN: repeated wrong PINs are rate limited (429)",
      codes == [401] * config.PIN_RATE_MAX_FAILS + [429], codes)
reset_limits()
st = client.put("/api/settings", json={"convocation_name": "Hijack"},
                headers={"X-Admin-Pin": "000000"}).status_code
check("ADMIN: /api/settings PUT refuses a wrong admin PIN", st == 401, st)
reset_limits()

# ---- private student surfaces reject anonymous + forged callers
PRIVATE = (("/api/student/me", "GET"), ("/api/student/pass", "GET"),
           ("/api/student/history", "GET"), ("/api/student/readiness", "GET"),
           ("/api/student/support", "GET"), ("/api/student/profile", "POST"),
           ("/api/student/support", "POST"),
           ("/api/student/pass/issue", "POST"),
           ("/api/student/readiness/reminders", "POST"))
bad = []
for p, m in PRIVATE:
    r = anon.get(p) if m == "GET" else anon.post(p, json={})
    if r.status_code != 401:
        bad.append((p, m, "anon", r.status_code))
    st, _ = sget(p) if m == "GET" else spost(p, {})
    if st != 401:
        bad.append((p, m, "forged", st))
check("PRIVACY: every private student route is 401 anonymous and forged",
      not bad, bad)

# ---- email outage fails closed (needs a registration nobody has claimed yet)
upload(xlsx([["P17-G001", "p17.gina@synthetic.invalid", "P17G001",
              "GINA GRANT", DEPT]]), "outage.xlsx", follow=True)
_ob = last_batch()
staff_post("/exam/registrations/import/%d/commit" % _ob, {"mode": "insert"})
reset_limits()
chal_before = one("SELECT COUNT(*) c FROM verification_challenges")["c"]
old = config.EMAIL_MODE
config.EMAIL_MODE = "disabled"
try:
    st, body = spost("/api/student/verify",
                     {"registration_number": "P17-G001",
                      "university_email": "p17.gina@synthetic.invalid",
                      "roll_number": "P17G001", "student_name": "GINA GRANT"})
finally:
    config.EMAIL_MODE = old
chal_after = one("SELECT COUNT(*) c FROM verification_challenges")["c"]
check("PRIVACY: an email outage is a 503, never a silent success",
      st == 503 and body.get("code") == "email_unavailable", (st, body))
check("PRIVACY: an outage leaves no half-created verification challenge",
      chal_after == chal_before, (chal_before, chal_after))

# ================================================================ STEP 4
step(4, "Volunteer scanner: provisioning, authorization, timestamps, idempotency")

cli = subprocess.run([sys.executable,
                      os.path.join(APP_DIR, "scripts",
                                   "manage_scanner_staff.py"),
                      "create", "--username", "p17.cli", "--name",
                      "P17 CLI Gate", "--gates", "1,2", "--pin", "844192"],
                     cwd=APP_DIR, capture_output=True, text=True,
                     errors="replace")
out = (cli.stdout or "") + (cli.stderr or "")
check("SCANNER: manage_scanner_staff.py create provisions a real account",
      cli.returncode == 0 and "Created scanner" in out
      and "username=p17.cli" in out, out[:400])
check("SCANNER: the CLI shows the PIN exactly once",
      "PIN (shown once, not recoverable): 844192" in out, out[:400])
cli_list = subprocess.run([sys.executable,
                           os.path.join(APP_DIR, "scripts",
                                        "manage_scanner_staff.py"), "list"],
                          cwd=APP_DIR, capture_output=True, text=True,
                          errors="replace")
check("SCANNER: manage_scanner_staff.py list reports the account",
      cli_list.returncode == 0
      and "username=p17.cli" in (cli_list.stdout + cli_list.stderr),
      (cli_list.stdout + cli_list.stderr)[:400])

reset_limits()
st, body = hpost("/api/scanner/login", {"username": "p17.cli", "pin": "844192"},
                 {})
check("SCANNER: the provisioned volunteer signs in for real",
      st == 200 and bool(body.get("token")), (st, body))
st, body = hpost("/api/scanner/login", {"username": "p17.cli", "pin": "000000"}, {})
check("SCANNER: a wrong PIN is refused (401)", st == 401, (st, body))
st, body = hpost("/api/scanner/login", {"username": "nobody", "pin": "123456"}, {})
check("SCANNER: an unknown account is refused (401)", st == 401, (st, body))
reset_limits()
st, body = hpost("/api/scanner/login", {"username": "p17.cli", "pin": "844192"},
                 {})
CLI_ALL = {"X-Scanner-Token": body.get("token", "")}
CLI_G1 = scanner_headers(client, [1])
reset_limits()

# ---- gate scope (online and queued)
st, b = hpost("/api/scan", {"payload": LEG, "gate_id": 3, "mode": "entry"},
              CLI_G1)
check("SCANNER: a gate-1-2 scanner is refused on gate 3 (403)",
      st == 403 and b.get("title") == "GATE NOT AUTHORIZED", (st, b))
st, b = sync([{"payload": LEG, "gate_id": 3, "mode": "entry"}], CLI_G1)
check("SCANNER: queued scans honour the same gate authorization",
      b.get("results", [{}])[0].get("result", {}).get("title")
      == "GATE NOT AUTHORIZED", b)
st, b = hpost("/api/scan", {"payload": LEG, "mode": "entry"}, CLI_G1)
check("SCANNER: a scan with no gate is a 400, not a crash",
      st == 400 and b.get("title") == "NO GATE SELECTED", (st, b))

# ---- legacy roster flow + server-derived volunteer identity
st, b = hpost("/api/scan",
              {"payload": LEG, "gate_id": 1, "mode": "entry",
               "volunteer": "CLIENT-FORGED"}, SCANNER_HDRS)
check("SCANNER: roster entry recorded", b.get("title") == "ENTRY RECORDED", b)
stored = one("SELECT * FROM scans WHERE qr_id = ? ORDER BY id DESC",
             (leg_row["qr_id"],))
check("SCANNER: the volunteer comes from the session, never the request body",
      stored.get("volunteer") not in ("", "CLIENT-FORGED"), stored)
check("SCANNER: a duplicate entry is refused as ALREADY INSIDE",
      scan(LEG, 1, "entry").get("title") == "ALREADY INSIDE")
check("SCANNER: exit closes the entry",
      scan(LEG, 2, "exit").get("title") == "EXIT RECORDED")
check("SCANNER: re-entry after exit is accepted",
      scan(LEG, 1, "entry").get("title") == "ENTRY RECORDED")
r = scan(LEG, 1, "entry")
check("SCANNER: the duplicate check writes no extra row",
      r.get("title") == "ALREADY INSIDE"
      and one("SELECT COUNT(*) c FROM scans WHERE qr_id = ?",
              (leg_row["qr_id"],))["c"] == 3, r)

# ---- FIX (a): queued-scan timestamp normalisation
cases = (("2026-10-12 21:10:12", "2026-10-12 21:10:12"),
         ("2026-10-12, 21:10:12", "2026-10-12 21:10:12"),
         ("2026-01-01T10:00:00", "2026-01-01T10:00:00"),
         ("zzz", None), (None, None), ("2026-13-45 99:99:99", None))
models.add_students([("P17-SC-%d" % i, "SCAN CASE %d" % i, "Male", "BS Test")
                     for i in range(len(cases))])
models.assign_ids(models.students_missing_ids(), ids.generate_id)
qr_for = [one("SELECT qr_id q FROM students WHERE roll_no = ?",
              ("P17-SC-%d" % i,))["q"] for i in range(len(cases))]
rows_before = one("SELECT COUNT(*) c FROM scans")["c"]
items = []
for i, (src, _) in enumerate(cases):
    it = {"payload": ids.make_payload(qr_for[i]), "gate_id": 1, "mode": "entry"}
    if src is not None:
        it["scanned_at"] = src
    items.append(it)
st, b = sync(items, CLI_ALL)
check("FIX-A: all queued scans synced", b.get("synced") == len(cases), b)
for i, (src, want) in enumerate(cases):
    got = one("SELECT scanned_at t FROM scans WHERE qr_id = ?"
              " ORDER BY id DESC", (qr_for[i],))["t"]
    if want is None:
        check("FIX-A: %r falls back to a real server timestamp" % (src,),
              bool(TS_RE.match(got)) and "zzz" not in got, got)
    else:
        check("FIX-A: %r stores %r" % (src, want), got == want, got)
bad_ts = [r0 for r0 in raw("SELECT DISTINCT scanned_at t FROM scans")
          if not TS_RE.match(r0["t"])]
check("FIX-A: no stored scanned_at can out-sort every dashboard window",
      not bad_ts, bad_ts[:5])

# ---- sync idempotency + malformed batches
st, s1 = sync([dict(items[0])], CLI_ALL)
st, s2 = sync([dict(items[0])], CLI_ALL)
t2 = s2.get("results", [{}])[0].get("result", {}).get("title")
check("SCANNER: a replayed sync is ALREADY SYNCED, never re-counted",
      s1.get("synced") == 0 and t2 == "ALREADY SYNCED" and s2.get("synced") == 0,
      (s1, s2))
st, b = sync([{"payload": "x"}] * 501, CLI_ALL)
check("SCANNER: a sync larger than 500 items is rejected (400)",
      st == 400 and "max 500" in b.get("error", ""), (st, b))
st, b = sync("not-a-list", CLI_ALL)
check("SCANNER: a non-list sync body is rejected (400)",
      st == 400 and b.get("error") == "items must be a list.", (st, b))
st, b = sync([42, None, {"payload": None}], CLI_ALL)
check("SCANNER: malformed sync batches are rejected before any write",
      st == 400 and b.get("ok") is False and isinstance(b.get("error"), str), b)
check("SCANNER: rejected batches record nothing",
      one("SELECT COUNT(*) c FROM scans")["c"] == rows_before + len(cases),
      one("SELECT COUNT(*) c FROM scans"))

# ---- session lifecycle: expiry, logout, re-mint
short = scanner_headers(client, [1])
exec_sql("UPDATE scanner_sessions SET expires_at = '2000-01-01T00:00:00+00:00'"
         " WHERE token_hash = ?",
         (scanner_auth._token_hash(short["X-Scanner-Token"]),))
st, b = hpost("/api/scan", {"payload": LEG, "gate_id": 1, "mode": "entry"}, short)
check("SCANNER: an expired session is refused (401)",
      st == 401 and b.get("code") == "scanner_auth_required", (st, b))
r = client.post("/api/scanner/logout", headers=CLI_ALL)
st, b = hpost("/api/scan", {"payload": LEG, "gate_id": 1, "mode": "entry"},
              CLI_ALL)
check("SCANNER: logout revokes the token (401 on reuse)",
      (r.get_json() or {}).get("ok") is True and st == 401,
      (r.status_code, st, b))
SCANNER_HDRS = scanner_headers(client)
st, _ = hpost("/api/scan", {"payload": LEG, "gate_id": 1, "mode": "entry"},
              SCANNER_HDRS)
check("SCANNER: a fresh session can be minted after logout", st == 200, st)

# ================================================================ STEP 5
step(5, "Cross-role privacy, security headers and payload purity")

r = client.get("/api/health")
check("SECURITY: nosniff / SAMEORIGIN / no-referrer on every response",
      r.headers.get("X-Content-Type-Options") == "nosniff"
      and r.headers.get("X-Frame-Options") == "SAMEORIGIN"
      and r.headers.get("Referrer-Policy") == "no-referrer",
      dict(r.headers))
r = client.get("/api/health", headers={"Origin": "https://evil.example"})
check("SECURITY: a foreign Origin gets no CORS grant",
      "Access-Control-Allow-Origin" not in r.headers, dict(r.headers))
r = client.get("/api/health", headers={"Origin": "http://localhost:19999"})
check("SECURITY: loopback dev origins (Expo web) stay allowlisted",
      r.headers.get("Access-Control-Allow-Origin") == "http://localhost:19999",
      dict(r.headers))

reset_limits()
st, pb = issue(TOKENS[CAR[0]])
CAR_PAYLOAD = pb.get("pass", {}).get("payload", "")
check("STUDENT: CARLA issued a real LGU2 convocation pass",
      st == 200 and CAR_PAYLOAD.startswith("LGU2:"), (st, pb))
car_secret = CAR_PAYLOAD.split(":", 1)[1] if CAR_PAYLOAD else ""

SURFACES = (("/api/student/me", TOKENS[BOB[0]]),
            ("/api/student/pass", TOKENS[BOB[0]]),
            ("/api/student/history", TOKENS[BOB[0]]),
            ("/api/student/readiness", TOKENS[BOB[0]]),
            ("/api/student/support", TOKENS[BOB[0]]),
            ("/api/student/event", None),
            ("/api/student/announcements", None),
            ("/api/student/medalists", None))
surfaces = {p: json.dumps(sget(p, tok)[1]).lower() for p, tok in SURFACES}
leaks = [(p, w) for p, blob in surfaces.items() for w in LEAKS if w in blob]
check("PRIVACY: no credential material in any student payload", not leaks, leaks)
leaked = [p for p, blob in surfaces.items() if car_secret and car_secret in blob]
dav_history = json.dumps(sget("/api/student/history", TOKENS[DAV[0]])[1])
check("PRIVACY: a pass token never appears in another student's surfaces",
      not leaked and car_secret not in dav_history, leaked)

bad = [(p, anon.get(p).status_code)
       for p in ("/api/dashboard", "/api/dashboard/summary")
       if anon.get(p).status_code >= 500]
check("PRIVACY: no anonymous request crashes the server", not bad, bad)

# ================================================================ STEP 6
step(6, "Convocation-pass integrity, admissions, migrations and scale")

reset_limits()
st, body = spost("/api/student/pass/issue", {}, TOKENS[CAR[0]])
CAR_PAYLOAD = body.get("pass", {}).get("payload", "")
r = scan(CAR_PAYLOAD, 1, "entry")
check("PASS: an eligible pass admits exactly once",
      r.get("status") == "ok"
      and r.get("title") == "CONVOCATION ENTRY RECORDED", r)
check("PASS: exactly one admission row for that registration",
      one("SELECT COUNT(*) c FROM convocation_admissions"
          " WHERE registration_id = ?", (ava_row["id"],))["c"] == 0
      and one("SELECT COUNT(*) c FROM convocation_admissions"
              " WHERE registration_id = ?",
              (one("SELECT id i FROM convocation_registrations"
                   " WHERE roll_number = ?", (CAR[2],))["i"],))["c"] == 1)
car_id = one("SELECT id i FROM convocation_registrations"
             " WHERE roll_number = ?", (CAR[2],))["i"]
r = scan(CAR_PAYLOAD, 1, "entry")
check("PASS: a second scan of the same pass is ALREADY ADMITTED",
      r.get("title") == "ALREADY ADMITTED"
      and one("SELECT COUNT(*) c FROM convocation_admissions"
              " WHERE registration_id = ?", (car_id,))["c"] == 1, r)
r = scan(CAR_PAYLOAD, 2, "exit")
check("PASS: convocation passes are entry-only (amber, no extra admission)",
      r.get("title") == "CONVOCATION PASSES ARE ENTRY-ONLY"
      and r.get("level") == "amber"
      and one("SELECT COUNT(*) c FROM convocation_admissions"
              " WHERE registration_id = ?", (car_id,))["c"] == 1, r)
adm_before = one("SELECT COUNT(*) c FROM convocation_admissions")["c"]
r = scan(CAR_PAYLOAD[:-4] + "AAAA", 1, "entry")
check("PASS: a forged pass is refused and records nothing",
      r.get("title") in ("INVALID CODE", "PASS INVALID")
      and one("SELECT COUNT(*) c FROM convocation_admissions")["c"] == adm_before,
      r)

# ---- FIX (b): only LIVE passes are advertised
reset_limits()
st, body = spost("/api/student/pass/issue", {}, TOKENS[BOB[0]])
BOB_PAYLOAD = body.get("pass", {}).get("payload", "")
check("PASS: BOB holds a live, unused pass", bool(BOB_PAYLOAD), body)
m_before = metrics()["invitations"]
r = staff_post("/exam/registrations/%d/status" % bob_row["id"],
               {"action": "cancel"})
m_cancel = metrics()["invitations"]
check("FIX-B: cancelling the holder stops advertising the pass",
      r.status_code == 200
      and m_cancel["passes_issued_active"]
      == m_before["passes_issued_active"] - 1
      and m_cancel["passes_issued_total"] == m_before["passes_issued_total"]
      and m_cancel["admitted"] == m_before["admitted"]
      and m_cancel["qr_active"] is False, (m_before, m_cancel))
r = scan(BOB_PAYLOAD, 1, "entry")
check("FIX-B: the cancelled holder's pass no longer admits",
      r.get("title") == "REGISTRATION NOT ELIGIBLE", r)
staff_post("/exam/registrations/%d/status" % bob_row["id"],
           {"action": "reinstate"})
m_after = metrics()["invitations"]
check("FIX-B: reinstating restores the live-pass count exactly",
      m_after["passes_issued_active"] == m_before["passes_issued_active"]
      and m_after["passes_issued_total"] == m_before["passes_issued_total"]
      and m_after["qr_active"] is True, (m_before, m_after))
r = scan(BOB_PAYLOAD, 1, "entry")
check("FIX-B: after reinstatement the same pass admits once",
      r.get("title") == "CONVOCATION ENTRY RECORDED", r)

# ---- 12 concurrent scans of one pass -> exactly one admission
staff_post("/exam/support/%d/status" % bet_id, {"status": "resolved"})
st, body = spost("/api/student/pass/issue", {}, TOKENS[BET[0]])
BET_PAYLOAD = body.get("pass", {}).get("payload", "")
check("PASS: a resolved support request restores pass eligibility",
      st == 200 and BET_PAYLOAD.startswith("LGU2:"), (st, body))
headers = scanner_headers(client, [1, 2, 3, 4, 5, 6, 7])
results, rlock = [], threading.Lock()


def worker():
    c = app.test_client()
    rr = c.post("/api/scan",
                json={"payload": BET_PAYLOAD, "gate_id": 1, "mode": "entry"},
                headers=headers)
    with rlock:
        results.append(rr.get_json() or {})


threads = [threading.Thread(target=worker) for _ in range(12)]
for t in threads:
    t.start()
for t in threads:
    t.join()
bet_id_reg = one("SELECT id i FROM convocation_registrations"
                 " WHERE roll_number = ?", (BET[2],))["i"]
titles = sorted({x.get("title") for x in results})
check("PASS: 12 concurrent scans of one pass produce exactly one admission",
      len([x for x in results if x.get("status") == "ok"]) == 1
      and one("SELECT COUNT(*) c FROM convocation_admissions"
              " WHERE registration_id = ?", (bet_id_reg,))["c"] == 1,
      titles)
check("PASS: every losing scan reports ALREADY ADMITTED",
      titles == ["ALREADY ADMITTED", "CONVOCATION ENTRY RECORDED"], titles)

# ---- reissue revokes the previous token
st, body = spost("/api/student/pass/issue", {}, TOKENS[DAV[0]])
DAV_PAYLOAD = body.get("pass", {}).get("payload", "")
check("PASS: DAV issued an unused pass", DAV_PAYLOAD.startswith("LGU2:"), body)
st, body2 = spost("/api/student/pass/issue", {}, TOKENS[DAV[0]])
check("PASS: reissuing revokes the previous token (PASS INVALID)",
      scan(DAV_PAYLOAD, 1, "entry").get("title") == "PASS INVALID"
      and body2.get("pass", {}).get("payload") != DAV_PAYLOAD, body2)

# ---- malformed payloads never create an admission
adm_before = one("SELECT COUNT(*) c FROM convocation_admissions")["c"]
for bad_payload in ("", "garbage", "LGU1:ZZZZZZZZ:deadbeef", "LGU2:AAAA"):
    scan(bad_payload, 1, "entry")
check("PASS: malformed payloads never create an admission",
      one("SELECT COUNT(*) c FROM convocation_admissions")["c"] == adm_before)

# ---- migrations on fresh + previous-version disposable DBs
mc = sqlite3.connect(os.path.join(TMP, "mig.db"))
mc.executescript(database.SCHEMA)
migrations.migrate(mc)
latest = migrations.MIGRATIONS[-1][0]
check("MIGRATION: a fresh schema migrates to the latest user_version",
      mc.execute("PRAGMA user_version").fetchone()[0] == latest,
      mc.execute("PRAGMA user_version").fetchone()[0])
mc.close()
cc = sqlite3.connect(os.path.join(TMP, "copy.db"))
cc.executescript(database.SCHEMA)
for version, script in migrations.MIGRATIONS:
    if version >= latest:
        break
    cc.executescript("BEGIN;\n%sPRAGMA user_version = %d;\nCOMMIT;"
                     % (script, version))
check("MIGRATION: the disposable copy starts one version behind",
      cc.execute("PRAGMA user_version").fetchone()[0] == latest - 1,
      cc.execute("PRAGMA user_version").fetchone()[0])
migrations.migrate(cc)
tables = {r[0] for r in cc.execute("SELECT name FROM sqlite_master"
                                   " WHERE type = 'table'")}
check("MIGRATION: a previous version migrates forward to latest",
      cc.execute("PRAGMA user_version").fetchone()[0] == latest
      and {"convocation_passes", "convocation_admissions"} <= tables)
cc.close()
check("MIGRATION: the production DB is never the migration target",
      os.path.abspath(config.DB_PATH) != os.path.abspath(PROD_DB)
      and not os.path.abspath(config.DB_PATH).startswith(
          os.path.dirname(os.path.abspath(PROD_DB)) + os.sep + "lgu.db"),
      (config.DB_PATH, PROD_DB))

# ---- scale: a measured 6000-row import through the real workflow
# Prefix must not collide with any fixture registration (BOB is P17-B001,
# which would match a naive 'P17-B%' count and report 6001).
big = [[("P17-SCALE-%05d" % i), ("p17.big%05d@synthetic.invalid" % i),
        ("P17B%05d" % i), ("SCALE STUDENT %05d" % i), DEPT]
       for i in range(6000)]
t0 = time.perf_counter()
r = upload(xlsx(big), "scale.xlsx")
t_up = time.perf_counter() - t0
big_loc = r.headers.get("Location", "")
big_batch = int(re.search(r"/import/(\d+)", big_loc).group(1)) if big_loc else 0
check("SCALE: a 6000-row workbook uploads and previews quickly",
      big_batch > 0 and t_up < 60, (big_batch, round(t_up, 2), html(r)[:200]))
t0 = time.perf_counter()
staff_post("/exam/registrations/import/%d/commit" % big_batch,
           {"mode": "insert"})
t_commit = time.perf_counter() - t0
big_result = json.loads(one("SELECT result_json r FROM import_batches"
                            " WHERE id = ?", (big_batch,))["r"] or "{}")
check("SCALE: 6000 rows committed in one transaction",
      big_result.get("inserted") == 6000, big_result)
check("SCALE: the commit completes in a realistic window", t_commit < 60,
      round(t_commit, 2))
check("SCALE: the ledger really holds 6000 new rows",
      one("SELECT COUNT(*) c FROM convocation_registrations"
          " WHERE registration_number LIKE 'P17-SCALE-%'")["c"] == 6000)
print("     scale import: upload %.2fs, commit %.2fs" % (t_up, t_commit))

# ================================================================ STEP 7
step(7, "Final consistency: ledgers agree, repo clean, production untouched")

counts = reg.count_status(database.get_db(), CONV)
total = one("SELECT COUNT(*) c FROM convocation_registrations"
            " WHERE convocation_id = ?", (CONV,))["c"]
met = metrics()
check("FINAL: dashboard totals still mirror the ledger after the scale import",
      met["totals"] == {**counts, "total": total},
      (met["totals"], counts, total))
check("FINAL: metric totals are internally consistent",
      met["totals"]["active"] + met["totals"]["cancelled"]
      + met["totals"]["revoked"] == met["totals"]["total"], met["totals"])

cols = sorted(r0["name"] for r0 in
              raw("PRAGMA table_info(convocation_registrations)"))
check("FINAL: the registration ledger still carries no roster QR id",
      "qr_id" not in cols, cols)

bad_ts = [r0 for r0 in raw("SELECT DISTINCT scanned_at t FROM scans")
          if not TS_RE.match(r0["t"])]
check("FINAL: every stored scanned_at is a parseable timestamp",
      not bad_ts, bad_ts[:5])

new_files = sorted(repo_tree() - BEFORE_TREE)
check("FINAL: the test run wrote no file into the repository",
      not new_files, new_files[:10])

if PROD_STAMP is not None:
    _s = os.stat(PROD_DB)
    with open(PROD_DB, "rb") as fh:
        _sha = sha256(fh.read()).hexdigest().upper()
    check("FINAL: app/lgu.db byte-identical (size + mtime_ns + SHA256)",
          (_s.st_size, _s.st_mtime_ns, _sha) == PROD_STAMP,
          ((_s.st_size, _s.st_mtime_ns, _sha), PROD_STAMP))
    print("\nPROD_DB before: size=%d sha256=%s" % (PROD_STAMP[0], PROD_STAMP[2]))
    print("PROD_DB after : size=%d sha256=%s" % (_s.st_size, _sha))

print("\n%d checks, %d failures (across %d steps)"
      % (checks, failures, steps))
sys.exit(1 if failures else 0)
