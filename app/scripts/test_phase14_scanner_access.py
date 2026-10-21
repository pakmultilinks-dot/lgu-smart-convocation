"""Phase 14: volunteer scanner access control (server-side authorization).

Secures the real /api/scan + /api/sync endpoints, which previously trusted a
client-supplied `volunteer` name and `gate_id` with NO authentication. A
scanner now proves who it is with a per-account PIN (scrypt hash at rest),
receives a short-lived session token, and the SERVER decides the volunteer
identity and the gates it may admit. This suite drives the real routes on ONE
disposable temp database and proves both legacy (LGU1) and convocation (LGU2)
QR workflows still work through an authorized scanner.

app/lgu.db is never opened — stat-stamped before and after to prove it.

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase14_scanner_access.py
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

TMP = tempfile.mkdtemp(prefix="lgu-p14-access-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "access.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

from io import BytesIO  # noqa: E402

from openpyxl import Workbook  # noqa: E402

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import emailer  # noqa: E402
import exam_auth  # noqa: E402
import exam_registrations as reg  # noqa: E402
import ids  # noqa: E402
import scanner_auth  # noqa: E402
import convocation_qr as cqr  # noqa: E402
import web.routes as vr  # noqa: E402
import web.student_routes as sr  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
PW = "phase14-access-14"
STAFF_USER, STAFF_PW = "p14 officer", "phase14-officer"
AVA = ("ava.shah@uni.edu.pk", "REG-9401", "09401", "Ava Shah")
BOB = ("omar.farouk@uni.edu.pk", "REG-9402", "09402", "Omar Farouk")


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def step(n, title):
    print("\n== CASE %s: %s" % (n, title))


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
    vr._SCAN_LOGIN_FAILS.clear()


def post_scan(payload, gate_id=1, mode="entry", headers=None, volunteer="Spoofed"):
    return client.post("/api/scan",
                       json={"payload": payload, "gate_id": gate_id,
                             "mode": mode, "volunteer": volunteer},
                       headers=headers or {})


def scan_body(payload, gate_id=1, mode="entry", headers=None, volunteer="Spoofed"):
    r = post_scan(payload, gate_id, mode, headers, volunteer)
    try:
        return r.status_code, r.get_json(silent=True) or {}
    except Exception:
        return r.status_code, {}


# ---------------------------------------------------------------- boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
CONV = raw("SELECT * FROM convocations WHERE is_active = 1")[0]["id"]

# A legacy roster student whose QR is signed the LGU1 way (legacy flow).
STU = raw("SELECT * FROM students WHERE roll_no = 'LGU-2024-102'")[0]
STU_PAYLOAD = ids.make_payload(STU["qr_id"])
OTHER_STU = raw("SELECT * FROM students WHERE roll_no = 'LGU-2024-104'")[0]
OTHER_PAYLOAD = ids.make_payload(OTHER_STU["qr_id"])


def mint(gate_ids=(1,), username="scan-op", display="Gate Op", pin="84726153"):
    """Provision a scanner + open a session → (headers, scanner_id, token)."""
    sid = scanner_auth.create_scanner(username, display, pin, list(gate_ids),
                                      actor="p14-test")
    token, _ = scanner_auth.create_session(sid)
    return {"X-Scanner-Token": token}, sid, token


def fresh(roll):
    """Return (row, payload) for a seeded legacy student, so each case uses a
    distinct student and earlier admissions never leak into later assertions."""
    row = raw("SELECT * FROM students WHERE roll_no = ?", (roll,))[0]
    return row, ids.make_payload(row["qr_id"])


# =============================== CASE 1 ====================================
step(1, "Unauthenticated /api/scan is rejected 401 (no open admission path)")
r = post_scan(STU_PAYLOAD, gate_id=1, headers=None)
body = r.get_json(silent=True) or {}
check("scan without a token -> 401", r.status_code == 401, r.status_code)
check("response code is scanner_auth_required",
      body.get("code") == "scanner_auth_required", body)
check("unauthenticated scan recorded NO admission row",
      raw("SELECT COUNT(*) c FROM scans WHERE qr_id = ?",
          (STU["qr_id"],))[0]["c"] == 0)
rs = client.post("/api/sync", json={"items": [{"payload": STU_PAYLOAD,
                                               "gate_id": 1, "mode": "entry"}]})
check("sync without a token -> 401 (the exact bypass is closed too)",
      rs.status_code == 401, rs.status_code)

# =============================== CASE 2 ====================================
step(2, "Invalid / forged session token is rejected")
fake = {"X-Scanner-Token": "not-a-real-token-" + "0" * 40}
code, b = scan_body(STU_PAYLOAD, gate_id=1, headers=fake)
check("forged token -> 401", code == 401, code)
check("forged token admitted nothing",
      raw("SELECT COUNT(*) c FROM scans WHERE qr_id = ?",
          (STU["qr_id"],))[0]["c"] == 0)

# =============================== CASE 3 ====================================
step(3, "A revoked session (logout) is rejected on the next scan")
_stu3, pay3 = fresh("LGU-2024-103")
h3, _sid3, tok3 = mint(gate_ids=(1,), username="scan-revoke", display="Rev Scanner")
code, b = scan_body(pay3, gate_id=1, headers=h3)
check("authorized scan before logout -> admitted", code == 200 and
      "RECORDED" in b.get("title", ""), b)
client.post("/api/scanner/logout", headers=h3)
code, b = scan_body(pay3, gate_id=1, headers=h3)
check("same token after logout -> 401", code == 401, code)

# =============================== CASE 4 ====================================
step(4, "An expired session is rejected")
h4, _sid4, tok4 = mint(gate_ids=(1,), username="scan-expire", display="Exp Scanner")
exec_sql("UPDATE scanner_sessions SET expires_at = ? WHERE token_hash = ?",
         ("2000-01-01T00:00:00", scanner_auth._token_hash(tok4)))
code, b = scan_body(OTHER_PAYLOAD, gate_id=1, headers=h4)
check("expired session -> 401", code == 401, code)

# =============================== CASE 5 ====================================
step(5, "Repeated login failures are rate-limited 429")
reset_limits()
sid5 = scanner_auth.create_scanner("scan-lock", "Lock Scanner", "11223344",
                                   [1], actor="p14-test")
statuses = []
for i in range(6):
    rr = client.post("/api/scanner/login",
                     json={"username": "scan-lock", "pin": "00000000"})
    statuses.append(rr.status_code)
check("wrong PIN 401 for the first attempts", statuses[0] == 401 and
      statuses[1] == 401, statuses)
check("6th attempt is rate-limited 429", statuses[-1] == 429, statuses)
# Even the CORRECT pin is refused while the window is hot.
rr = client.post("/api/scanner/login", json={"username": "scan-lock",
                                             "pin": "11223344"})
check("correct PIN still 429 during the hot window", rr.status_code == 429,
      rr.status_code)
reset_limits()

# =============================== CASE 6 ====================================
step(6, "A scanner admits ONLY its authorized gates (403 on the others)")
h6, sid6, _ = mint(gate_ids=(1,), username="scan-gate6", display="Gate One Only")
code, b = scan_body(STU_PAYLOAD, gate_id=1, headers=h6)
check("authorized gate 1 -> admitted", code == 200 and
      "RECORDED" in b.get("title", ""), b)
code, b = scan_body(OTHER_PAYLOAD, gate_id=2, headers=h6)
check("unauthorized real gate 2 -> 403 GATE NOT AUTHORIZED",
      code == 403 and b.get("title") == "GATE NOT AUTHORIZED", (code, b))
check("gate-2 refusal recorded NO admission row for that student",
      raw("SELECT COUNT(*) c FROM scans WHERE qr_id = ?",
          (OTHER_STU["qr_id"],))[0]["c"] == 0)
# A non-existent gate is NOT shadowed by the auth layer — UNKNOWN GATE.
code, b = scan_body(OTHER_PAYLOAD, gate_id=99999, headers=h6)
check("non-existent gate falls through to UNKNOWN GATE",
      b.get("title") == "UNKNOWN GATE", b)

# =============================== CASE 7 ====================================
step(7, "Client fields cannot escalate — server derives identity + gates")
_stu7, pay7 = fresh("LGU-2024-105")
h7, sid7, _ = mint(gate_ids=(1,), username="scan-honest", display="Honest Op")
# An unauthorized gate is refused (403) even when the body spoofs a volunteer.
code, b = scan_body(pay7, gate_id=3, headers=h7, volunteer="FAKE ADMIN")
check("spoofed volunteer + unauthorized gate -> refused (403)",
      code == 403, (code, b))
# Authorized gate but a spoofed volunteer body field: recorded name is the
# authenticated display name, NEVER the client-supplied value.
code, b = scan_body(pay7, gate_id=1, headers=h7)
row = raw("SELECT volunteer FROM scans WHERE qr_id = ? ORDER BY id DESC LIMIT 1",
          (_stu7["qr_id"],))[0]
check("recorded volunteer is the session identity, not the client field",
      row["volunteer"] == "Honest Op" and row["volunteer"] != "FAKE ADMIN",
      row["volunteer"])

# =============================== CASE 8 ====================================
step(8, "Legacy LGU1 flow works through an authorized scanner")
_stu8, pay8 = fresh("LGU-2024-107")
h8, _s8, _ = mint(gate_ids=(1, 2), username="scan-lgu1", display="LGU1 Op")
code, b = scan_body(pay8, gate_id=1, mode="entry", headers=h8)
check("LGU1 entry -> ENTRY RECORDED (green)", code == 200 and
      b.get("title") == "ENTRY RECORDED" and b.get("level") == "green", b)
code, b = scan_body(pay8, gate_id=2, mode="exit", headers=h8)
check("LGU1 exit -> EXIT RECORDED", b.get("title") == "EXIT RECORDED", b)

# =============================== CASE 9 ====================================
step(9, "LGU2 convocation pass admits exactly once through a scanner")
# Minimal convocation setup: import → signup → login → publish → issue.
exam_auth.create_staff(STAFF_USER, "P14 Officer", STAFF_PW)
TOK = csrf_of(html(client.get("/exam/login")))
client.post("/exam/login", data={"csrf_token": TOK, "username": STAFF_USER,
                                 "password": STAFF_PW},
            follow_redirects=True)
TOK = csrf_of(html(client.get("/exam/event")))
client.post("/exam/event/save",
            data={"csrf_token": TOK, "name": "LGU Convocation 2026",
                  "year": "2026", "expected_date": "2026-11-01",
                  "confirmed_date": "2026-11-15", "venue": "Pass Hall",
                  "instructions": "Bring your card."})
batch = client.post(
    "/exam/registrations/import",
    data={"csrf_token": TOK,
          "file": (BytesIO(xlsx([["REG-9401", AVA[0], AVA[2], AVA[3],
                                  "Computer Science"],
                                 ["REG-9402", BOB[0], BOB[2], BOB[3],
                                  "Electrical Engineering"]])), "regs.xlsx")},
    content_type="multipart/form-data")
BID = int(re.search(r"/import/(\d+)",
                    batch.headers.get("Location", "")).group(1))
client.post("/exam/registrations/import/%d/commit" % BID,
            data={"csrf_token": TOK})
signup(*AVA)
AVA_TOKEN = login(AVA[0])[1].get("token", "")
signup(*BOB)
BOB_TOKEN = login(BOB[0])[1].get("token", "")
TOK = csrf_of(html(client.get("/exam/event")))
client.post("/exam/event/publish", data={"csrf_token": TOK})
reset_limits()
st, ib = spost("/api/student/pass/issue", {}, AVA_TOKEN)
AVA_PAYLOAD = ib.get("pass", {}).get("payload", "")
check("eligible student received an LGU2 convocation pass",
      st == 200 and AVA_PAYLOAD.startswith("LGU2:"), (st, ib))
h9, _s9, _ = mint(gate_ids=(1,), username="scan-lgu2", display="LGU2 Op")
code, b = scan_body(AVA_PAYLOAD, gate_id=1, mode="entry", headers=h9)
adm = raw("SELECT COUNT(*) c FROM convocation_admissions")[0]["c"]
check("LGU2 pass admitted through the scanner", code == 200 and adm == 1,
      (code, b, adm))
code, b = scan_body(AVA_PAYLOAD, gate_id=1, mode="entry", headers=h9)
adm2 = raw("SELECT COUNT(*) c FROM convocation_admissions")[0]["c"]
check("second LGU2 scan is refused — admitted exactly once",
      adm2 == 1 and ("ALREADY" in b.get("title", "") or
                     "RECORDED" not in b.get("title", "")), (b, adm2))
# Keep a second (unadmitted) pass for the CASE-11 expiry check.
st_b, ib_b = spost("/api/student/pass/issue", {}, BOB_TOKEN)
BOB_PAYLOAD = ib_b.get("pass", {}).get("payload", "")
check("second student also issued a pass (kept unadmitted for CASE 11)",
      st_b == 200 and BOB_PAYLOAD.startswith("LGU2:"), (st_b, ib_b))

# =============================== CASE 10 ===================================
step(10, "Duplicates impossible — UNIQUE admission backstop holds")
admissions = raw("SELECT COUNT(*) c FROM convocation_admissions")[0]["c"]
check("convocation_admissions UNIQUE index exists (atomic backstop)",
      raw("SELECT name FROM sqlite_master WHERE type='index' AND name="
          "'idx_convocation_admissions_once'") != [])
check("no duplicate convocation admission rows after all scans",
      admissions == raw("SELECT COUNT(DISTINCT convocation_id || ':' ||"
                        " registration_id) c FROM convocation_admissions")[0]["c"])
# Legacy roster: a second entry for the same student is ALREADY INSIDE.
_stu10, pay10 = fresh("LGU-2024-109")
h10, _s10, _ = mint(gate_ids=(1,), username="scan-dup", display="Dup Op")
code, b = scan_body(pay10, gate_id=1, mode="entry", headers=h10)
first = b.get("title")
code, b = scan_body(pay10, gate_id=1, mode="entry", headers=h10)
check("duplicate legacy entry -> ALREADY INSIDE (never a second row)",
      first == "ENTRY RECORDED" and b.get("title") == "ALREADY INSIDE",
      (first, b))

# =============================== CASE 11 ===================================
step(11, "Expired / forged / ineligible passes are rejected by the server")
h11, _s11, _ = mint(gate_ids=(1,), username="scan-bad", display="Bad Op")
for bad in ("LGU2:" + "z" * 43, "LGU1:garbage", None, ""):
    code, b = scan_body(bad, gate_id=1, headers=h11)
    check("bad pass %r rejected (no admission)" % (bad,),
          "RECORDED" not in b.get("title", ""), b)
check("forged/unknown passes recorded NO scans",
      raw("SELECT COUNT(*) c FROM scans WHERE qr_id LIKE 'garbage'")[0]["c"] == 0)
# A live, unadmitted pass whose expiry is forced into the past is rejected.
if BOB_PAYLOAD:
    tok = BOB_PAYLOAD.split(":", 1)[1]
    exec_sql("UPDATE convocation_passes SET expires_at = ? WHERE token_hash = ?",
             ("2000-01-01T00:00:00", cqr.token_hash(tok)))
    code, b = scan_body(BOB_PAYLOAD, gate_id=1, headers=h11)
    check("expired LGU2 pass rejected at scan time",
          "RECORDED" not in b.get("title", ""), b)

# =============================== CASE 12 ===================================
step(12, "Failed scans create no admission row")
before = raw("SELECT COUNT(*) c FROM scans")[0]["c"]
h12, _s12, _ = mint(gate_ids=(1,), username="scan-fail", display="Fail Op")
post_scan("LGU1:FORGED0000", gate_id=1, headers=h12)
post_scan(None, gate_id=1, headers=h12)
after = raw("SELECT COUNT(*) c FROM scans")[0]["c"]
check("invalid/absent payloads recorded nothing", before == after,
      (before, after))

# =============================== CASE 13 ===================================
step(13, "Deactivating a scanner revokes it — later scans are rejected")
_stu13, pay13 = fresh("LGU-2024-111")
h13, sid13, _ = mint(gate_ids=(1,), username="scan-revoke-me",
                     display="To Revoke")
code, b = scan_body(pay13, gate_id=1, mode="entry", headers=h13)
check("scanner works before deactivation", code == 200 and
      "RECORDED" in b.get("title", ""), (code, b))
scanner_auth.deactivate_scanner(sid13, actor="p14-test")
_stu13b, pay13b = fresh("LGU-2024-112")
code, b = scan_body(pay13b, gate_id=1, headers=h13)
check("deactivated scanner -> 401 (session revoked + account inactive)",
      code == 401, code)

# =============================== CASE 14 ===================================
step(14, "Session secrets + QR tokens never leak into logs/responses")
h14, sid14, tok14 = mint(gate_ids=(1,), username="scan-secret",
                         display="Secret Op")
srow = raw("SELECT token_hash FROM scanner_sessions WHERE scanner_id = ?",
           (sid14,))[0]
check("stored token is a sha256 hash, never the plaintext",
      srow["token_hash"] == scanner_auth._token_hash(tok14) and
      srow["token_hash"] != tok14 and len(srow["token_hash"]) == 64)
audits = raw("SELECT detail FROM audit_log")
leaked = [a["detail"] for a in audits if a["detail"] and tok14 in a["detail"]]
check("plaintext session token absent from the audit log", leaked == [], leaked)
pinleak = [a["detail"] for a in audits if a["detail"] and "84726153" in a["detail"]]
check("PIN never written to the audit log", pinleak == [], pinleak)
check("login response never echoes a pin_hash",
      "pin_hash" not in html(client.post("/api/scanner/login",
                                         json={"username": "scan-secret",
                                               "pin": "wrong-pin-x"})))

# =============================== CASE 15 ===================================
step(15, "No bypass via /api/sync or malformed bodies; legacy surfaces intact")
# /api/sync requires auth and enforces per-item gate authorization.
h15, _s15, _ = mint(gate_ids=(1,), username="scan-sync", display="Sync Op")
_stu15, pay15 = fresh("LGU-2024-114")
rs = client.post("/api/sync", json={"items": [{"payload": pay15,
                                               "gate_id": 2, "mode": "entry"}]},
                 headers=h15)
item = (rs.get_json(silent=True) or {}).get("results", [{}])[0].get("result", {})
check("sync item for an unauthorized gate is refused (not admitted)",
      item.get("title") == "GATE NOT AUTHORIZED", item)
_stu15b, pay15b = fresh("LGU-2024-115")
rs2 = client.post("/api/sync", json={"items": [{"payload": pay15b,
                                                "gate_id": 1, "mode": "entry"}]},
                  headers=h15)
item2 = (rs2.get_json(silent=True) or {}).get("results", [{}])[0].get("result", {})
check("sync item for an authorized gate is processed",
      "RECORDED" in item2.get("title", ""), item2)
# A malformed / bare-list body never bypasses the scanner gate.
rmal = client.post("/api/sync", json=[{"payload": OTHER_PAYLOAD, "gate_id": 1}])
check("bare-list sync body is rejected without a crash", rmal.status_code in (400, 401),
      rmal.status_code)
# Legacy + student surfaces remain reachable and functional (regression).
check("GET /api/gates still answers", client.get("/api/gates").status_code == 200)
check("GET /api/dashboard still answers", client.get("/api/dashboard").status_code == 200)
# Phase 26C: the guest roster carries phone PII + used to leak the signed
# qr_id credential. It is now scanner-gated and returns minimum fields.
check("GET /api/guests refuses an anonymous caller",
      client.get("/api/guests").status_code == 401,
      client.get("/api/guests").status_code)
_rg = client.get("/api/guests", headers=h15).get_json(silent=True) or {}
_rrows = _rg.get("guests", [])
check("GET /api/guests answers for a signed-in scanner",
      isinstance(_rrows, list), _rg)
check("guest roster omits the qr_id credential and created_at",
      all(("qr_id" not in r) and ("created_at" not in r) for r in _rrows),
      _rrows[:3])
st, _b = spost("/api/student/verify", {"registration_number": "REG-XXXX",
                                       "university_email": "x@uni.edu.pk",
                                       "roll_number": "09999",
                                       "student_name": "Probe"})
check("student registration endpoint intact (responds, not 500/crash)",
      st in (200, 400, 401, 403, 404, 429), st)
check("admin auth intact (unlock without PIN is challenged)",
      client.get("/admin").status_code == 401)

# ---------------------------------------------------------------- summary
print("\n%d checks, %d failures" % (checks, failures))
if PROD_STAMP is not None:
    _s = os.stat(PROD_DB)
    after = (_s.st_size, _s.st_mtime_ns)
    print("production db before=%s after=%s" % (PROD_STAMP, after))
    check("production database untouched", PROD_STAMP == after,
          (PROD_STAMP, after))
sys.exit(1 if failures else 0)
