"""Phase 13: full end-to-end product acceptance (student → gate → dashboard).

Drives the REAL application routes in realistic sequence on ONE disposable temp
database — no direct SQL for the main acceptance path (SQL only for assertions
and setup where a supported workflow is impractical). Covers §2's ten steps,
the §3 security/failure-handling audit (including the expiry-at-scan fix), and
§5 data-integrity checks. app/lgu.db is never opened (stat-stamped before and
after to prove it).

Registration lifecycle note: cancel is reversible (reinstate), revoke is
PERMANENT (reinstate only applies from cancelled) — tests use cancel wherever a
student must be restored, and demonstrate revoke's permanence as a terminal case.

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase13_e2e_acceptance.py
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

TMP = tempfile.mkdtemp(prefix="lgu-p13e2e-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "e2e.db")
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
import ids  # noqa: E402
import migrations  # noqa: E402
import web.routes as vr  # noqa: E402
import web.student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402
from _scanner_fixture import scanner_headers  # noqa: E402

failures = 0
checks = 0
# Print unicode step labels (arrows, section signs) regardless of the parent
# console codepage, so piping this script's output (tests, CI) never trips a
# UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
STAFF_USER, STAFF_PW = "p13 officer", "e2e-acceptance-13"
PW = "e2e-acceptance-13"
AVA = ("ava.shah@uni.edu.pk", "REG-9301", "09301", "Ava Shah")
BOB = ("bob.reed@uni.edu.pk", "REG-9302", "09302", "Bob Reed")
CAR = ("car.olivia@uni.edu.pk", "REG-9303", "09303", "Carol Olivia")


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


def scan(payload, gate_id=1, mode="entry", volunteer="P13 Volunteer"):
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


# ---------------------------------------------------------------- boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
# Phase 14: authenticate the scanner session used by every scan() call.
SCANNER_HDRS = scanner_headers(client)

CONV = raw("SELECT * FROM convocations WHERE is_active = 1")[0]["id"]
exam_auth.create_staff(STAFF_USER, "P13 Officer", STAFF_PW)
page = html(client.get("/exam/login"))
TOK = csrf_of(page)
client.post("/exam/login", data={"csrf_token": TOK, "username": STAFF_USER,
                                 "password": STAFF_PW},
            follow_redirects=True)

# ------------------------------------------- STEP 1: import registrations
step(1, "Import synthetic convocation registrations (supported workflow)")
TOK = csrf_of(html(client.get("/exam/event")))
client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-11-01",
                  "confirmed_date": "2026-11-15", "venue": "Pass Hall",
                  "instructions": "Bring your student card."})
batch = client.post(
    "/exam/registrations/import",
    data={"csrf_token": TOK,
          "file": (BytesIO(xlsx([["REG-9301", AVA[0], AVA[2], AVA[3],
                                  "Computer Science"],
                                 ["REG-9302", BOB[0], BOB[2], BOB[3],
                                  "Electrical Engineering"],
                                 ["REG-9303", CAR[0], CAR[2], CAR[3],
                                  "Mechanical Engineering"]])), "regs.xlsx")},
    content_type="multipart/form-data")
BID = int(re.search(r"/import/(\d+)",
                    batch.headers.get("Location", "")).group(1))
client.post("/exam/registrations/import/%d/commit" % BID,
            data={"csrf_token": TOK})
ava_row = raw("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (AVA[2],))[0]
bob_row = raw("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (BOB[2],))[0]
car_row = raw("SELECT * FROM convocation_registrations WHERE roll_number = ?",
              (CAR[2],))[0]
check("S1: three registrations imported via the real import workflow",
      bool(ava_row) and bool(bob_row) and bool(car_row))

# ------------------------------------------- STEP 2: authenticate students
step(2, "Authenticate synthetic students + establish registration claim")
signup(*AVA)
AVA_TOKEN = login(AVA[0])[1].get("token", "")
signup(*BOB)
BOB_TOKEN = login(BOB[0])[1].get("token", "")
signup(*CAR)
CAR_TOKEN = login(CAR[0])[1].get("token", "")
check("S2: all three students signed in with bearer sessions",
      bool(AVA_TOKEN) and bool(BOB_TOKEN) and bool(CAR_TOKEN))
check("S2: registration claims established for all three accounts",
      len(raw("SELECT * FROM registration_claims WHERE convocation_id = ?",
              (CONV,))) == 3)

# ------------------------------------------- STEP 3: publish the event
step(3, "Publish the convocation event")
TOK = csrf_of(html(client.get("/exam/event")))
client.post("/exam/event/publish", data={"csrf_token": TOK})
check("S3: event published (invitation can derive an event snapshot)",
      raw("SELECT * FROM convocation_publications WHERE convocation_id = ?",
          (CONV,)) != [])

# ------------------------------------------- STEP 4: open invitation
step(4, "Open invitation; verify server-derived eligibility")
st, body = sget("/api/student/pass", AVA_TOKEN)
check("S4: invitation is server-derived and eligible",
      st == 200 and body["pass"]["state"] == "eligible", (st, body))
check("S4: invitation embeds NO QR payload (read-only, qr_available false)",
      body["pass"]["qr_available"] is False and body["pass"]["qr"] is None)

# ------------------------------------------- STEP 5: issue QR
step(5, "Issue a QR through the real issuance endpoint")
reset_limits()
st, ib = issue(AVA_TOKEN)
ava_pass = ib.get("pass", {})
AVA_PAYLOAD = ava_pass.get("payload", "")
check("S5: eligible student receives an LGU2 convocation QR",
      st == 200 and ib.get("ok") is True and AVA_PAYLOAD.startswith("LGU2:"),
      (st, ib))
prow = raw("SELECT * FROM convocation_passes WHERE id = ?",
           (ava_pass["pass_id"],))[0]
check("S5: only the sha256 hash is stored (never plaintext)",
      prow["token_hash"] == cqr.token_hash(AVA_PAYLOAD.split(":", 1)[1])
      and prow["token_hash"] != AVA_PAYLOAD.split(":", 1)[1])
check("S5: pass bound to account + convocation + registration",
      prow["account_id"] > 0 and prow["convocation_id"] == CONV
      and prow["registration_id"] == ava_row["id"])
check("S5: no legacy roster row fabricated for the roll",
      raw("SELECT COUNT(*) FROM students WHERE roll_no = ?",
          (AVA[2],))[0]["COUNT(*)"] == 0)

# ------------------------------------------- STEP 6: real /api/scan dispatch
step(6, "QR payload accepted by the real /api/scan dispatch path")
before_scans = raw("SELECT COUNT(*) FROM scans")[0]["COUNT(*)"]
r = scan(AVA_PAYLOAD, gate_id=1)
check("S6: /api/scan dispatches LGU2 and admits the student",
      r["status"] == "ok" and r["title"] == "CONVOCATION ENTRY RECORDED"
      and r.get("name") == AVA[3] and r.get("gate"), r)

# ------------------------------------------- STEP 7: admission exactly once
step(7, "Correct convocation admission recorded exactly once")
adm = raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?",
          (CONV,))
check("S7: exactly one admission row for the registration",
      len(adm) == 1 and adm[0]["registration_id"] == ava_row["id"]
      and adm[0]["gate_id"] == 1, adm)
check("S7: pass marked used after admission",
      raw("SELECT status FROM convocation_passes WHERE id = ?",
          (ava_pass["pass_id"],))[0]["status"] == "used")
check("S7: legacy scans ledger untouched by the convocation entry",
      raw("SELECT COUNT(*) FROM scans")[0]["COUNT(*)"] == before_scans)

# ------------------------------------------- STEP 8: repeat scan duplicate
step(8, "Repeat the same scan → safe duplicate-admission response")
r = scan(AVA_PAYLOAD, gate_id=2)
check("S8: repeat scan refused as ALREADY ADMITTED (safe, not a crash)",
      r["status"] == "error" and r["title"] == "ALREADY ADMITTED", r)
check("S8: still exactly one admission row after the duplicate",
      len(raw("SELECT * FROM convocation_admissions WHERE convocation_id = ?",
              (CONV,))) == 1)

# --- issue Carol a (live) pass so the dashboard shows a real active count
reset_limits()
st, cb = issue(CAR_TOKEN)
CAR_PAYLOAD = cb["pass"]["payload"]
check("S8b: Carol issued a live (active) pass for the dashboard check",
      st == 200 and CAR_PAYLOAD.startswith("LGU2:"), (st, cb))

# ------------------------------------------- STEP 9: dashboard reflects DB
step(9, "Examination dashboard issued-pass + admission counts match the DB")
dash = html(client.get("/exam/dashboard"))
db_active = raw("SELECT COUNT(*) FROM convocation_passes"
                " WHERE convocation_id = ? AND status = 'active'",
                (CONV,))[0]["COUNT(*)"]
db_admitted = raw("SELECT COUNT(*) FROM convocation_admissions"
                  " WHERE convocation_id = ?", (CONV,))[0]["COUNT(*)"]
check("S9: dashboard shows the live-pass count from the database",
      ("%d live entry pass" % db_active) in dash, (db_active,))
check("S9: dashboard shows the admitted count from the database",
      ("%d attendee" % db_admitted) in dash
      or ("%d attendees" % db_admitted) in dash, (db_admitted,))
check("S9: dashboard reports convocation QR entry active iff a live pass exists",
      ("Convocation QR entry active" in dash) == (db_active > 0), db_active)
check("S9: dashboard still reports the honest legacy roster prerequisite",
      "Legacy operational-QR prerequisite not satisfied" in dash)

# ------------------------------- STEP 10: invalidate eligibility → pass dead
step(10, "Invalidate eligibility (cancel); the issued pass can no longer admit")
reset_limits()
st, bb = issue(BOB_TOKEN)
BOB_PAYLOAD = bb["pass"]["payload"]
check("S10: Bob issued a pass while eligible",
      st == 200 and BOB_PAYLOAD.startswith("LGU2:"), (st, bb))
staff_post("/exam/registrations/%d/status" % bob_row["id"],
           {"action": "cancel"})
r = scan(BOB_PAYLOAD, gate_id=1)
check("S10: cancelled registration stops validating at the gate",
      r["status"] == "error" and r["title"] == "REGISTRATION NOT ELIGIBLE", r)
check("S10: no admission recorded for the cancelled student",
      raw("SELECT COUNT(*) FROM convocation_admissions WHERE registration_id = ?",
          (bob_row["id"],))[0]["COUNT(*)"] == 0)
st, body = issue(BOB_TOKEN)
check("S10: cancelled student cannot reissue (403)", st == 403, (st, body))
staff_post("/exam/registrations/%d/status" % bob_row["id"],
           {"action": "reinstate"})

# ================================================== §3 SECURITY AUDIT ======
print("\n== SECURITY AUDIT (§3) ==")

# --- secure generation + hash-only storage
tok = AVA_PAYLOAD.split(":", 1)[1]
check("SEC: token is high-entropy (>=32 urlsafe chars)", len(tok) >= 32, tok)
stored = {r["token_hash"] for r in raw("SELECT token_hash FROM convocation_passes")}
check("SEC: only hashes stored — the plaintext token is never persisted",
      tok not in stored and cqr.token_hash(tok) in stored, tok)

# --- no unrelated student data / secrets in public responses
r = scan("LGU2:" + "z" * 43)
check("SEC: invalid token response leaks no student data or hash",
      r["status"] == "error" and "PASS INVALID" in r["title"]
      and tok not in str(r) and "token_hash" not in str(r), r)

# --- pass cannot transfer between accounts/registrations (Bob's own reg only)
reset_limits()
st, bb2 = issue(BOB_TOKEN)
check("SEC: Bob can reissue while eligible", st == 200, (st, bb2))
BOB_PAYLOAD2 = bb2.get("pass", {}).get("payload", "")
r = scan(BOB_PAYLOAD2, gate_id=1)
bob_adm = raw("SELECT * FROM convocation_admissions WHERE registration_id = ?",
              (bob_row["id"],))
check("SEC: Bob's pass admits Bob's registration only (no cross-binding)",
      r["status"] == "ok" and len(bob_adm) == 1
      and bob_adm[0]["registration_id"] == bob_row["id"], (r, bob_adm))
check("SEC: Ava's admission still points at Ava's registration",
      raw("SELECT registration_id FROM convocation_admissions WHERE"
          " registration_id = ?", (ava_row["id"],))[0]["registration_id"]
      == ava_row["id"])

# --- eligibility recomputed at scan time (cancel a second student mid-flight)
reset_limits()
st, cb2 = issue(CAR_TOKEN)   # reissues Carol: CAR_PAYLOAD revoked, new active
CAR_PAYLOAD2 = cb2.get("pass", {}).get("payload", "")
staff_post("/exam/registrations/%d/status" % car_row["id"],
           {"action": "cancel"})
r = scan(CAR_PAYLOAD2, gate_id=1)
check("SEC: eligibility recomputed at scan — cancelled registration refused",
      r["status"] == "error" and r["title"] == "REGISTRATION NOT ELIGIBLE", r)

# --- blocking support request invalidates admission permission immediately
reset_limits()
st, sup_body = spost("/api/student/support",
                     {"category": "correction", "subject": "Fix dept",
                      "message": "Please fix my department."}, CAR_TOKEN)
CORR_ID = sup_body.get("request", {}).get("id", 0)
r = scan(CAR_PAYLOAD2, gate_id=1)
check("SEC: an open blocking review immediately stops admission",
      r["status"] == "error" and r["title"] == "REGISTRATION NOT ELIGIBLE", r)
staff_post("/exam/support/%d/status" % CORR_ID, {"status": "resolved"})
staff_post("/exam/registrations/%d/status" % car_row["id"],
           {"action": "reinstate"})

# --- reissued token: the superseded (revoked) one is rejected (lifecycle)
r = scan(CAR_PAYLOAD, gate_id=1)
check("SEC: a reissued (revoked) token is rejected as PASS INVALID",
      r["status"] == "error" and r["title"] == "PASS INVALID", r)

# --- expired token rejected at scan (the Phase 13 fix)
exec_sql("UPDATE convocation_passes SET expires_at = ? WHERE token_hash = ?",
         ("2000-01-01T00:00:00", cqr.token_hash(CAR_PAYLOAD2.split(":", 1)[1])))
r = scan(CAR_PAYLOAD2, gate_id=1)
check("SEC: an expired pass is rejected at scan (PASS EXPIRED)",
      r["status"] == "error" and r["title"] == "PASS EXPIRED", r)
exec_sql("UPDATE convocation_passes SET expires_at = NULL WHERE token_hash = ?",
         (cqr.token_hash(CAR_PAYLOAD2.split(":", 1)[1]),))

# --- failed scans create no admission records
before = len(raw("SELECT * FROM convocation_admissions"))
for bad in ("LGU2:", "LGU2:" + "z" * 43, "LGU1:garbage", None):
    scan(bad, gate_id=1)
check("SEC: failed scans record no admissions",
      len(raw("SELECT * FROM convocation_admissions")) == before)

# --- invalid gate / mode fail safely
check("SEC: unknown gate fails safely",
      scan(CAR_PAYLOAD2, gate_id=999)["title"] == "UNKNOWN GATE")
check("SEC: non-numeric gate fails safely",
      scan(CAR_PAYLOAD2, gate_id="abc")["title"] == "NO GATE SELECTED")
check("SEC: exit mode is entry-only (amber, not a crash)",
      scan(CAR_PAYLOAD2, gate_id=1, mode="exit")["level"] == "amber")

# --- unauthenticated issuance refused
reset_limits()
st, body = issue("")
check("SEC: unauthenticated issuance refused (401)", st == 401, (st, body))

# --- rate limiting on issuance
reset_limits()
codes = [issue(AVA_TOKEN)[0] for _ in range(config.PASS_ISSUE_RATE_MAX + 3)]
check("SEC: issuance is rate-limited (429 after the cap)",
      429 in codes, codes)
reset_limits()

# --- audit never leaks a token
audit = str(raw("SELECT * FROM convocation_audit WHERE convocation_id = ?",
                (CONV,)))
check("SEC: audit trail never contains a plaintext token",
      tok not in audit
      and CAR_PAYLOAD2.split(":", 1)[1] not in audit
      and BOB_PAYLOAD2.split(":", 1)[1] not in audit)

# --- admin metrics are distinct, correctly scoped (not mixed with legacy)
dash2 = html(client.get("/exam/dashboard"))
live_adm = len(raw("SELECT * FROM convocation_admissions"
                   " WHERE convocation_id = ?", (CONV,)))
check("SEC: dashboard admitted count == convocation_admissions rows (scoped)",
      ("%d attendee" % live_adm) in dash2
      or ("%d attendees" % live_adm) in dash2, live_adm)
check("SEC: convocation admissions never written to legacy scans",
      raw("SELECT COUNT(*) FROM scans")[0]["COUNT(*)"] == before_scans)

# --- terminal: revoke is PERMANENT (reinstate does not apply from revoked)
staff_post("/exam/registrations/%d/status" % car_row["id"],
           {"action": "revoke"})
staff_post("/exam/registrations/%d/status" % car_row["id"],
           {"action": "reinstate"})   # no-op: reinstate only applies from cancelled
st, body = issue(CAR_TOKEN)
check("SEC: a revoked registration stays revoked — permanent (403 after "
      "reinstate attempt)", st == 403, (st, body))

# ================================================== §5 INTEGRITY ===========
print("\n== INTEGRITY (§5) ==")

# --- legacy guest pass still works
guest = raw("SELECT qr_id, name FROM guests ORDER BY id LIMIT 1")[0]
g = scan(ids.make_payload(guest["qr_id"]), gate_id=1)
check("INT: legacy guest pass still records an entry",
      g["status"] == "ok" and "GUEST" in g["title"], g)

# --- legacy student QR still works (entry / already inside / exit)
qr = raw("SELECT qr_id, name, roll_no FROM students"
         " WHERE roll_no NOT IN (SELECT host_roll_no FROM guests)"
         " ORDER BY id LIMIT 1")[0]
p = ids.make_payload(qr["qr_id"])
check("INT: legacy student entry still recorded",
      scan(p, gate_id=1)["title"] == "ENTRY RECORDED")
check("INT: legacy duplicate entry still refused",
      scan(p, gate_id=2)["title"] == "ALREADY INSIDE")
check("INT: legacy exit still closes the entry",
      scan(p, gate_id=2, mode="exit")["title"] == "EXIT RECORDED")

# --- migration on a fresh temp DB + a disposable copy (never production)
mc_path = os.path.join(TMP, "mig.db")
mc = sqlite3.connect(mc_path)
mc.executescript(database.SCHEMA)
migrations.migrate(mc)
ver = mc.execute("PRAGMA user_version").fetchone()[0]
check("INT: fresh schema migrates to the latest version",
      ver == migrations.MIGRATIONS[-1][0], ver)
mc.close()
# A disposable copy at the PREVIOUS schema version, migrated forward — never
# the production database, and never a user_version reset on a fully migrated
# DB (non-idempotent ADD COLUMN migrations would re-run).
copy_path = os.path.join(TMP, "copy.db")
cc = sqlite3.connect(copy_path)
cc.executescript(database.SCHEMA)
latest = migrations.MIGRATIONS[-1][0]
for version, script in migrations.MIGRATIONS:
    if version >= latest:
        break
    cc.executescript("BEGIN;\n%sPRAGMA user_version = %d;\nCOMMIT;"
                     % (script, version))
check("INT: disposable copy starts at the previous schema version",
      cc.execute("PRAGMA user_version").fetchone()[0] == latest - 1)
migrations.migrate(cc)
check("INT: a disposable copy migrates from the previous version to latest",
      cc.execute("PRAGMA user_version").fetchone()[0] == latest
      and cc.execute("SELECT name FROM sqlite_master WHERE type='table'"
                     " AND name='convocation_admissions'").fetchone() is not None)
cc.close()

# --- production DB untouched
if PROD_STAMP is not None:
    _s = os.stat(PROD_DB)
    check("INT: app/lgu.db byte-identical (size+mtime)",
          (_s.st_size, _s.st_mtime_ns) == PROD_STAMP)

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)