"""Phase 5 regression: intelligent exam dashboard metrics + rendering.

Covers: unauthorised/volunteer access, KPI counts from real records,
claimed/incomplete profile counts, latest-import card, data-issue links,
read-only metrics, inactive-convocation state, cleanup to a clean board,
PII-free dashboard HTML, and preservation of volunteer/QR/gate data.

Run:  python scripts/test_exam_dashboard.py   (from app/)
Disposable temp databases only - never touches app/lgu.db.
"""

import base64
import io
import json
import os
import re
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

TMP = tempfile.mkdtemp(prefix="lgu-p5dash-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "fresh.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "photos")

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import emailer  # noqa: E402
import exam_auth  # noqa: E402
from flask import url_for  # noqa: E402
from PIL import Image  # noqa: E402
from web.exam_routes import dashboard_metrics  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
PW = "correct-horse-battery"
STAFF = "dashofficer"
NOW = "2026-10-01T00:00:00+00:00"
PRESERVE = ["students", "guests", "gates", "scans", "broadcasts",
            "settings", "convocations"]
SEED = [
    ("REG-9001", "s1@uni.edu.pk", "09001", "Student One", "active"),
    ("REG-9002", "s2@uni.edu.pk", "09002", "Student Two", "active"),
    ("REG-9003", "s3@uni.edu.pk", "09003", "Student Three", "active"),
    ("REG-9010", "s10@uni.edu.pk", "09010", "Student Ten", "active"),
    ("REG-9011", "s11@uni.edu.pk", "09011", "Student Eleven", "active"),
    ("REG-9020", "s20@uni.edu.pk", "09020", "Student Twenty", "cancelled"),
    ("REG-9021", "s21@uni.edu.pk", "09021", "Student Twenty One",
     "cancelled"),
    ("REG-9030", "s30@uni.edu.pk", "09030", "Student Thirty", "revoked"),
]


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def raw(sql, args=()):
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def run(sql, args=()):
    c = sqlite3.connect(config.DB_PATH)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def dump(names):
    out = {}
    for t in names:
        out[t] = raw("SELECT * FROM %s ORDER BY rowid" % t)
    return out


def csrf_of(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def html(resp):
    return resp.get_data(as_text=True)


def signup(reg_no, email, roll, name, password=PW):
    """Full student flow: verify -> code from fake outbox -> complete."""
    emailer.OUTBOX.clear()
    r = client.post("/api/student/verify", json={
        "registration_number": reg_no, "university_email": email,
        "roll_number": roll, "student_name": name})
    if r.status_code != 200:
        return r.status_code, r.get_json()
    code = emailer.OUTBOX[-1][1]
    r = client.post("/api/student/complete", json={
        "challenge_id": r.get_json()["challenge_id"],
        "code": code, "password": password})
    return r.status_code, r.get_json()


def metrics_of():
    db = database.get_db()
    try:
        with app.test_request_context():
            return dashboard_metrics(db)
    finally:
        db.close()


# ---------------------------------------------------------------- boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
exam_auth.create_staff(STAFF, "Dashboard Officer", PW)

CONV = raw("SELECT * FROM convocations WHERE is_active = 1")[0]["id"]
for reg_no, email, roll, name, status in SEED:
    run("INSERT INTO convocation_registrations"
        " (convocation_id, registration_number, university_email,"
        "  roll_number, student_name, department, status,"
        "  created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (CONV, reg_no, email, roll, name, "BSCS", status, NOW, NOW))

# 1. Authorisation: dashboard is exam-staff only.
fresh = app.test_client()
check("unauth: dashboard redirects to login",
      fresh.get("/exam/dashboard").status_code == 302)
with fresh.session_transaction() as s:
    s["lgu_admin"] = "1"
check("volunteer session cannot open exam dashboard",
      fresh.get("/exam/dashboard").status_code == 302)

# 2. Staff login (CSRF on the login form).
r = client.get("/exam/login")
ltok = csrf_of(html(r))
r = client.post("/exam/login",
                data={"username": STAFF, "password": PW, "csrf_token": ltok})
check("staff login succeeds", r.status_code == 302, r.status_code)

# 3. Three students claim registrations; one photo uploaded; one later
#    cancelled so a stale claim exists.
st, b = signup(*SEED[0][:4])
check("signup: student one claims", st == 200, (st, b))
tok1 = b["token"]
st, b = signup(*SEED[1][:4])
check("signup: student two claims", st == 200, (st, b))
tok2 = b["token"]
png = io.BytesIO()
Image.new("RGB", (40, 40), (10, 120, 60)).save(png, "PNG")
r = client.post("/api/student/profile/photo",
                json={"data": base64.b64encode(png.getvalue()).decode()},
                headers={"Authorization": "Bearer %s" % tok2})
check("signup: student two uploads photo", r.status_code == 200 and
      r.get_json().get("profile", {}).get("photo"),
      (r.status_code, r.get_json().get("code")))
st, b = signup(*SEED[2][:4])
check("signup: student three claims", st == 200, (st, b))
run("UPDATE convocation_registrations SET status = 'cancelled'"
    " WHERE registration_number = 'REG-9003'")

# 4. Import history: one committed (with skipped rows), one preview, one
#    failed — the failed one is newest so it drives the latest-import card.
def insert_batch(status, filename, result_json="", committed_at=None,
                 valid=0, invalid=0, duplicate=0):
    c = sqlite3.connect(config.DB_PATH)
    try:
        c.execute(
            "INSERT INTO import_batches"
            " (convocation_id, filename, file_sha256, status, mode,"
            "  total_rows, valid_rows, invalid_rows, duplicate_rows,"
            "  conflict_rows, notes, result_json, created_by, created_at,"
            "  committed_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (CONV, filename, "sha-" + filename, status, "insert",
             valid + invalid + duplicate, valid, invalid, duplicate, 0,
             "", result_json, STAFF, NOW, committed_at))
        c.commit()
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        c.close()


committed_id = insert_batch(
    "committed", "official-list.xlsx",
    json.dumps({"inserted": 5, "updated": 1, "unchanged": 0,
                "skipped_invalid": 1, "skipped_duplicate": 1,
                "skipped_conflict": 1, "mode": "insert"}),
    committed_at=NOW, valid=8, invalid=2, duplicate=1)
preview_id = insert_batch("preview", "staged-upload.xlsx",
                          valid=6, invalid=1, duplicate=1)
failed_id = insert_batch("failed", "broken.xlsx",
                         json.dumps({"error": "commit rolled back"}))

# 5. Metrics: exact numbers from real records.
m = metrics_of()
t = m["totals"]
check("metrics: totals 8 / 4 / 3 / 1",
      (t["total"], t["active"], t["cancelled"], t["revoked"]) ==
      (8, 4, 3, 1), t)
check("metrics: claimed 3, unclaimed 5",
      m["claimed"] == 3 and m["unclaimed"] == 5,
      (m["claimed"], m["unclaimed"]))
check("metrics: 2 profiles missing a photo",
      m["incomplete_profiles"] == 2, m["incomplete_profiles"])
check("metrics: latest import is the failed batch",
      m["latest_import"] and m["latest_import"]["filename"] == "broken.xlsx"
      and m["latest_import"]["status"] == "failed",
      m["latest_import"] and m["latest_import"]["filename"])
labels = [(i["level"], i["label"]) for i in m["issues"]]
# Phase 6 appends the medalist empty-board warning after the four
# registration issues (warn: no medalist records for this convocation).
check("metrics: five data issues in order",
      labels == [("warn", "Review the pending import"),
                 ("bad", "Open import history"),
                 ("warn", "Review the skipped rows"),
                 ("warn", "Open registrations"),
                 ("warn", "Open the medalist board")], labels)
with app.test_request_context():
    check("metrics: issue links point at real screens",
          [i["href"] for i in m["issues"]] ==
          [url_for("exam.import_review", batch_id=preview_id),
           url_for("exam.import_history"),
           url_for("exam.import_review", batch_id=committed_id),
           url_for("exam.registrations"),
           url_for("medalists.list_view")],
          [i["href"] for i in m["issues"]])
check("metrics: skipped wording counts 3 rows",
      "skipped 3 rows" in m["issues"][2]["text"], m["issues"][2]["text"])
check("metrics: stale claim wording counts 1 account",
      "1 student account" in m["issues"][3]["text"], m["issues"][3]["text"])

# 6. Read-only: computing metrics never mutates anything.
before = dump([r["name"] for r in raw(
    "SELECT name FROM sqlite_master WHERE type='table'"
    " AND name NOT LIKE 'sqlite_%'")])
metrics_of()
after = dump([r["name"] for r in raw(
    "SELECT name FROM sqlite_master WHERE type='table'"
    " AND name NOT LIKE 'sqlite_%'")])
check("metrics: computing the dashboard is read-only", before == after)

PRE = dump(PRESERVE)
r = client.get("/exam/dashboard")
page = html(r)
check("dashboard: 200 with staff session", r.status_code == 200,
      r.status_code)
nums = re.findall(r'<div class="num">(\d+)</div>', page)
# Phase 6: 7 registration tiles + 4 medalist tiles. Phase 7 adds 3 event
# tiles (published announcements, announcement drafts, event info published
# - all zero in this fixture; the convocation-date tile carries a style
# attribute and a date value, so this digit-only regex skips it by design).
# Phase 29 adds the two per-occasion admission tiles (main convocation /
# rehearsal) - both zero here, no admission has been recorded.
check("dashboard: exact KPI numbers 8/4/3/1/3/5/2 + four medalist"
      " zeros + three Phase 7 event zeros + two Phase 29 occasion zeros",
      nums == ["8", "4", "3", "1", "3", "5", "2", "0", "0", "0", "0",
               "0", "0", "0", "0", "0"], nums)
check("dashboard: convocation name shown",
      raw("SELECT name FROM convocations WHERE id = ?", (CONV,))[0]["name"]
      in page)
check("dashboard: latest import card shows failed batch",
      "broken.xlsx" in page and "badge bad" in page and "failed" in page)
check("dashboard: all five issue links rendered",
      all(lbl in page for lbl in
          ("Review the pending import", "Open import history",
           "Review the skipped rows", "Open registrations",
           "Open the medalist board")), "")
check("dashboard: notice levels 4 warn + 1 bad (incl. empty medalist board)",
      page.count("notice warn") == 4 and page.count("notice bad") == 1,
      (page.count("notice warn"), page.count("notice bad")))
check("dashboard: no student emails or reg numbers leak",
      "@uni.edu.pk" not in page and "REG-9" not in page and
      "09001" not in page)
check("dashboard: does not disturb volunteer/QR/gate data",
      dump(PRESERVE) == PRE)

# 7. Inactive convocation state.
run("UPDATE convocations SET is_active = 0 WHERE id = ?", (CONV,))
m2 = metrics_of()
check("inactive: totals None with reload issue",
      m2["totals"] is None and m2["conv"] is None and
      len(m2["issues"]) == 1 and m2["issues"][0]["label"] == "Reload"
      " dashboard", m2["issues"])
page = html(client.get("/exam/dashboard"))
check("inactive: page explains missing convocation",
      "No active convocation is configured" in page and
      not re.findall(r'<div class="num">', page))
run("UPDATE convocations SET is_active = 1 WHERE id = ?", (CONV,))

# 8. Cleanup -> a clean board with zero false alerts.
run("UPDATE convocation_registrations SET status = 'active'"
    " WHERE registration_number = 'REG-9003'")
run("DELETE FROM import_batches WHERE id IN (?, ?)",
    (preview_id, failed_id))
run("UPDATE import_batches SET result_json = ? WHERE id = ?",
    (json.dumps({"inserted": 8, "updated": 0, "unchanged": 0,
                 "skipped_invalid": 0, "skipped_duplicate": 0,
                 "skipped_conflict": 0, "mode": "insert"}), committed_id))
m3 = metrics_of()
t3 = m3["totals"]
check("clean: totals back to 8 / 5 / 2 / 1",
      (t3["total"], t3["active"], t3["cancelled"], t3["revoked"]) ==
      (8, 5, 2, 1), t3)
# Phase 6: the empty medalist board intentionally keeps one warning alive
# (staff must add records) — every registration/import issue is gone.
check("clean: only the empty medalist board warning remains",
      [(i["level"], i["label"]) for i in m3["issues"]] ==
      [("warn", "Open the medalist board")], m3["issues"])
page = html(client.get("/exam/dashboard"))
check("clean: medalist warning rendered as the sole notice",
      page.count("notice warn") == 1 and page.count("notice bad") == 0 and
      "Open the medalist board" in page,
      (page.count("notice warn"), page.count("notice bad")))
check("clean: still no PII on the dashboard",
      "@uni.edu.pk" not in page and "REG-9" not in page)
check("clean: volunteer/QR/gate data still untouched",
      dump(PRESERVE) == PRE)

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
