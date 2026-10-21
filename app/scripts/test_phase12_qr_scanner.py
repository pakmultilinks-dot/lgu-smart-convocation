"""Phase 12 integration: secure convocation QR issuance + scanner verification.

Proves the WHOLE convocation QR loop on ONE disposable temp database: an
eligible student mints a high-entropy entry QR (POST /api/student/pass/issue),
the token's sha256 hash is stored (never the plaintext), the volunteer
scanner dispatches the version-prefixed LGU2 payload to convocation_qr (a
path SEPARATE from the legacy LGU1 roster), eligibility is recomputed at scan
time, and admission is recorded once in convocation_admissions under a UNIQUE
backstop. Issuing and scanning a convocation pass NEVER touch the legacy
students/qr_id roster or the scans ledger, and the token never leaks to the
audit trail. Synthetic records only; app/lgu.db is never opened (stat-stamped
before and after to prove it).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase12_qr_scanner.py
"""

import os
import re
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

TMP = tempfile.mkdtemp(prefix="lgu-p12qr-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "qr.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "student-photos")

from io import BytesIO  # noqa: E402

from openpyxl import Workbook  # noqa: E402

import config  # noqa: E402
config.require_test_db()
import convocation_pass as cp  # noqa: E402
import convocation_qr as cqr  # noqa: E402
import database  # noqa: E402
import emailer  # noqa: E402
import exam_auth  # noqa: E402
import exam_registrations as reg  # noqa: E402
import ids  # noqa: E402
import migrations  # noqa: E402
import web.routes as vr  # noqa: E402
import web.student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402
from _scanner_fixture import scanner_headers  # noqa: E402

failures = 0
checks = 0
STAFF_USER, STAFF_PW = "p12 officer", "qr-scanner-pass-12"
PW = "qr-scanner-pass-12"
AVA = ("ava.shah@uni.edu.pk", "REG-9201", "09201", "Ava Shah")
BOB = ("bob.reed@uni.edu.pk", "REG-9202", "09202", "Bob Reed")


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


def scan(payload, gate_id=1, mode="entry", volunteer="P12 Volunteer"):
    # Phase 14: scans require an authenticated scanner session; the server
    # derives the volunteer name from the session, not this argument.
    return client.post("/api/scan", json={"payload": payload,
                                          "gate_id": gate_id, "mode": mode,
                                          "volunteer": volunteer},
                       headers=SCANNER_HDRS).get_json()


def staff_post(path, data):
    global TOK
    TOK = csrf_of(html(client.get("/exam/event")))
    data = dict(data, csrf_token=TOK)
    return client.post(path, data=data, follow_redirects=True)


# ---------------------------------------------------------------- A. boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
# Phase 14: authenticate the scanner session used by every scan()/sync() call.
SCANNER_HDRS = scanner_headers(client)

CONV = raw("SELECT * FROM convocations WHERE is_active = 1")[0]["id"]
exam_auth.create_staff(STAFF_USER, "P12 Officer", STAFF_PW)
page = html(client.get("/exam/login"))
TOK = csrf_of(page)
client.post("/exam/login", data={"csrf_token": TOK, "username": STAFF_USER,
                                 "password": STAFF_PW},
            follow_redirects=True)
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
          "file": (BytesIO(xlsx([["REG-9201", AVA[0], AVA[2], AVA[3],
                                  "Computer Science"],
                                 ["REG-9202", BOB[0], BOB[2], BOB[3],
                                  "Electrical Engineering"]])), "regs.xlsx")},
    content_type="multipart/form-data")
BID = int(re.search(r"/import/(\d+)",
                    batch.headers.get("Location", "")).group(1))
client.post("/exam/registrations/import/%d/commit" % BID,
            data={"csrf_token": TOK})
ava_row = raw("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (AVA[2],))[0]
bob_row = raw("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (BOB[2],))[0]

# ---------------------------------------------------------- B. students in
signup(*AVA)
AVA_TOKEN = login(AVA[0])[1].get("token", "")
signup(*BOB)
BOB_TOKEN = login(BOB[0])[1].get("token", "")
check("boot: both students sign in",
      bool(AVA_TOKEN) and bool(BOB_TOKEN))
check("boot: both invitations start eligible",
      sget("/api/student/pass", AVA_TOKEN)[1]["pass"]["state"] == "eligible"
      and sget("/api/student/pass", BOB_TOKEN)[1]["pass"]["state"] == "eligible")

# ---------------------------------------- C. issuance requires a session --
reset_limits()
st, body = issue("")
check("security: issuing a QR requires a signed-in student (401)",
      st == 401, (st, body))
st, body = issue(None)
check("security: an unsigned issue request is refused (401)", st == 401, st)

# ------------------------------------------- D. eligible student is issued -
reset_limits()
st, ib = issue(AVA_TOKEN)
ava_pass = ib.get("pass", {})
AVA_PAYLOAD = ava_pass.get("payload", "")
check("issue: an eligible student receives a convocation QR",
      st == 200 and ib.get("ok") is True and AVA_PAYLOAD.startswith("LGU2:"),
      (st, ib))
check("issue: the issued pass carries an id and an expiry",
      ava_pass.get("pass_id", 0) > 0 and bool(ava_pass.get("expires_at")),
      ava_pass)
prow = raw("SELECT * FROM convocation_passes WHERE id = ?",
           (ava_pass["pass_id"],))[0]
check("issue: only the sha256 hash is stored, never the plaintext token",
      prow["token_hash"] == cqr.token_hash(AVA_PAYLOAD.split(":", 1)[1])
      and prow["token_hash"] != AVA_PAYLOAD.split(":", 1)[1], prow)
check("issue: the pass is bound to the account + convocation",
      prow["convocation_id"] == CONV and prow["account_id"] > 0
      and prow["registration_id"] == ava_row["id"], prow)
check("issue: no operational roster row is fabricated for the roll",
      raw("SELECT COUNT(*) FROM students WHERE roll_no = ?",
          (AVA[2],))[0]["COUNT(*)"] == 0)
check("issue: GET /pass still embeds no QR payload (invitation is read-only)",
      sget("/api/student/pass", AVA_TOKEN)[1]["pass"]["qr_available"] is False)

# ------------------------------------------- E. reissue revokes the prior --
reset_limits()
st, ib2 = issue(AVA_TOKEN)
AVA_TOKEN2 = ib2["pass"]["payload"]
check("reissue: reissuing returns a different token",
      st == 200 and AVA_TOKEN2 != AVA_PAYLOAD, (AVA_TOKEN2, AVA_PAYLOAD))
first = raw("SELECT status FROM convocation_passes WHERE token_hash = ?",
            (cqr.token_hash(AVA_PAYLOAD.split(":", 1)[1]),))[0]
second = raw("SELECT status FROM convocation_passes WHERE token_hash = ?",
             (cqr.token_hash(AVA_TOKEN2.split(":", 1)[1]),))[0]
check("reissue: the prior pass is revoked, the new one active",
      first["status"] == "revoked" and second["status"] == "active",
      (first, second))

# ------------------------------------ F. a replaced token no longer scans --
r = scan(AVA_PAYLOAD)
check("reissue: the replaced token is refused at the gate",
      r["status"] == "error" and r["title"] == "PASS INVALID", r)

# ------------------------------------ G. valid scan records one admission --
reset_limits()
before_scans = raw("SELECT COUNT(*) FROM scans")[0]["COUNT(*)"]
r = scan(AVA_TOKEN2, gate_id=1)
adm = raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?",
          (CONV,))
check("scan: a valid convocation QR records an entry",
      r["status"] == "ok" and r["title"] == "CONVOCATION ENTRY RECORDED"
      and r.get("name") == AVA[3] and r.get("gate"), r)
check("scan: exactly one admission is recorded for the registration",
      len(adm) == 1 and adm[0]["registration_id"] == ava_row["id"]
      and adm[0]["gate_id"] == 1, adm)
check("scan: the pass is marked used",
      raw("SELECT status FROM convocation_passes WHERE token_hash = ?",
          (cqr.token_hash(AVA_TOKEN2.split(":", 1)[1]),))[0]["status"] == "used")
check("scan: the legacy scans ledger is untouched by a convocation entry",
      raw("SELECT COUNT(*) FROM scans")[0]["COUNT(*)"] == before_scans)

# ---------------------------------------- H. repeat scan is a safe duplicate -
r = scan(AVA_TOKEN2, gate_id=2)
check("repeat: a second scan of the same pass is refused as already admitted",
      r["status"] == "error" and r["title"] == "ALREADY ADMITTED", r)
check("repeat: still exactly one admission row after the duplicate",
      len(raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?",
              (CONV,))) == 1)

# ---------------------------------------- I. UNIQUE backstop under concurrency
c = sqlite3.connect(config.DB_PATH, timeout=30)
try:
    c.execute("INSERT INTO convocation_admissions"
              " (pass_id, convocation_id, registration_id, gate_id, volunteer,"
              "  admitted_at, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (999999, CONV, ava_row["id"], 2, "race", "2026-11-15 10:00:00",
               "online"))
    c.commit()
    dup_ok = True
except sqlite3.IntegrityError:
    dup_ok = False
finally:
    c.close()
check("concurrency: the UNIQUE index blocks a second admission atomically",
      dup_ok is False)

# ---------------------------------------- J. fabricated token is rejected --
before_adm = len(raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?",
                     (CONV,)))
r = scan("LGU2:forged-token-does-not-exist")
check("fabricated: an unknown convocation token is refused",
      r["status"] == "error" and r["title"] == "PASS INVALID", r)
check("fabricated: a failed verify records nothing",
      len(raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?",
              (CONV,))) == before_adm)
r = scan("LGU1:not-even-a-real-legacy-code")
check("fabricated: a bad legacy code still fails signature (regression)",
      r["title"] == "INVALID CODE", r)

# --------------------------------------------- K. entry-only + gate checks --
reset_limits()
st, bb = issue(BOB_TOKEN)
BOB_PAYLOAD = bb["pass"]["payload"]
r = scan(BOB_PAYLOAD, gate_id=1, mode="exit")
check("exit: a convocation pass is entry-only (amber, not a red forgery)",
      r["status"] == "error" and r["level"] == "amber"
      and "ENTRY-ONLY" in r["title"], r)
r = scan("LGU2:" + "x" * 43, gate_id="abc")
check("gate: a non-numeric gate is refused", r["title"] == "NO GATE SELECTED", r)
r = scan("LGU2:" + "x" * 43, gate_id=999)
check("gate: an unknown gate is refused", r["title"] == "UNKNOWN GATE", r)

# ------------------------------------ L. token unusable after eligibility lost
staff_post("/exam/registrations/%d/status" % bob_row["id"],
           {"action": "revoke"})
r = scan(BOB_PAYLOAD, gate_id=1)
check("lost-eligibility: a revoked registration stops validating at the gate",
      r["status"] == "error" and r["title"] == "REGISTRATION NOT ELIGIBLE", r)
staff_post("/exam/registrations/%d/status" % bob_row["id"],
           {"action": "reinstate"})

# ------------------------------------------- M. ineligible students can't issue
reset_limits()
staff_post("/exam/registrations/%d/status" % bob_row["id"],
           {"action": "cancel"})
st, body = issue(BOB_TOKEN)
check("ineligible: a cancelled registration cannot issue a QR (403)",
      st == 403, (st, body))
staff_post("/exam/registrations/%d/status" % bob_row["id"],
           {"action": "reinstate"})
staff_post("/exam/registrations/%d/status" % bob_row["id"],
           {"action": "revoke"})
st, body = issue(BOB_TOKEN)
check("ineligible: a revoked registration cannot issue a QR (403)",
      st == 403, (st, body))
staff_post("/exam/registrations/%d/status" % bob_row["id"],
           {"action": "reinstate"})
exec_sql("DELETE FROM convocation_publications WHERE convocation_id = ?", (CONV,))
st, body = issue(BOB_TOKEN)
check("ineligible: an unpublished event cannot issue a QR (403)",
      st == 403, (st, body))
client.post("/exam/event/publish", data={"csrf_token": TOK})
reset_limits()
st, sup_body = spost("/api/student/support",
                     {"category": "correction", "subject": "Fix dept",
                      "message": "Please fix my department."}, BOB_TOKEN)
CORR_ID = sup_body.get("request", {}).get("id", 0)
st, body = issue(BOB_TOKEN)
check("ineligible: a pending registration review cannot issue a QR (403)",
      st == 403, (st, body))
staff_post("/exam/support/%d/status" % CORR_ID, {"status": "resolved"})

# ------------------------------------------- N. audit trail never leaks token -
audit = raw("SELECT * FROM convocation_audit WHERE convocation_id = ?", (CONV,))
blob = str(audit)
check("privacy: the audit trail never contains a plaintext token",
      AVA_PAYLOAD.split(":", 1)[1] not in blob
      and AVA_TOKEN2.split(":", 1)[1] not in blob
      and BOB_PAYLOAD.split(":", 1)[1] not in blob, blob[:200])
check("privacy: issuance and admission are both audited",
      any(a["action"] == "pass_issue" for a in audit)
      and any(a["action"] == "pass_admit" for a in audit), blob[:200])

# ------------------------------- O. legacy QR + attendance fully intact ----
qr = raw("SELECT qr_id, name, roll_no FROM students"
         " WHERE roll_no NOT IN (SELECT host_roll_no FROM guests)"
         " ORDER BY id LIMIT 1")[0]
payload = ids.make_payload(qr["qr_id"])
r = scan(payload, gate_id=1)
check("legacy: a real student QR still records an entry",
      r["status"] == "ok" and r["title"] == "ENTRY RECORDED", r)
r = scan(payload, gate_id=2)
check("legacy: a second entry is still refused as already inside",
      r["title"] == "ALREADY INSIDE", r)
r = scan(payload, gate_id=2, mode="exit")
check("legacy: exit tracking still closes the entry",
      r["title"] == "EXIT RECORDED", r)

# ------------------------------------ P. migration reaches latest version ---
mc_path = os.path.join(TMP, "mig.db")
mc = sqlite3.connect(mc_path)
mc.executescript(database.SCHEMA)
migrations.migrate(mc)
ver = mc.execute("PRAGMA user_version").fetchone()[0]
LATEST = migrations.MIGRATIONS[-1][0]
check("migration: a fresh schema migrates to the latest version (%d)" % LATEST,
      ver == LATEST, ver)
tables = {r[0] for r in mc.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
check("migration: convocation pass + admission tables exist",
      {"convocation_passes", "convocation_admissions"} <= tables, tables)
check("migration: scanner auth tables exist (phase 14)",
      {"scanner_users", "scanner_gates", "scanner_sessions"} <= tables, tables)
migrations.migrate(mc)
check("migration: migrate is idempotent",
      mc.execute("PRAGMA user_version").fetchone()[0] == LATEST)
mc.close()

# ------------------------------------------------------------- boundary ----
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
