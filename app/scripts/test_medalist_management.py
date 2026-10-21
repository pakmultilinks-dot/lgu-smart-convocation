"""Phase 6 regression: medalist management + public student board.

Covers: migration idempotence, CRUD + audit, award-slot uniqueness,
publish gate (picture required), picture validation/replacement/public
route, Excel import (valid/invalid/duplicate/conflict/rollback),
corrections, CSRF + authorization, public payload privacy, convocation
scoping, dashboard counts/warnings, and preservation of volunteer data.

Run:  python scripts/test_medalist_management.py   (from app/)
Disposable temp databases only - never touches app/lgu.db.
"""

import io
import json
import os
import re
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

TMP = tempfile.mkdtemp(prefix="lgu-p6med-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "fresh.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "photos")
os.environ["LGU_MEDALIST_PHOTO_DIR"] = os.path.join(TMP, "medalist_photos")

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import exam_auth  # noqa: E402
import medalists as med  # noqa: E402
import medalist_import  # noqa: E402
from flask import url_for  # noqa: E402
from openpyxl import Workbook, load_workbook  # noqa: E402
from PIL import Image  # noqa: E402
from web.exam_routes import dashboard_metrics  # noqa: E402
from web.routes import create_app  # noqa: E402

failures = 0
checks = 0
PW = "correct-horse-battery"
STAFF = "medalofficer"
NOW = "2026-10-01T00:00:00+00:00"
PRESERVE = ["students", "guests", "gates", "scans", "broadcasts",
            "settings", "convocations"]


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
    return {t: raw("SELECT * FROM %s ORDER BY rowid" % t) for t in names}


def csrf_of(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def html(resp):
    return resp.get_data(as_text=True)


def db():
    return database.get_db()


def add(dept, name, cat, pos="", ref="", conv=None):
    d = db()
    try:
        clean, errs = med.clean_row({"department": dept, "student_name": name,
                                     "award_category": cat, "position": pos,
                                     "reference_number": ref})
        assert not errs, errs
        mid = med.insert(d, conv or CONV, clean, STAFF)
        d.commit()
        return mid
    finally:
        d.close()


def jpeg_bytes(size=(40, 40), color=(10, 120, 60)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def xlsx_bytes(rows, headers=("department", "student_name", "award_category",
                              "position", "reference_number")):
    wb = Workbook()
    ws = wb.active
    ws.title = "medalists"
    ws.append(list(headers))
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload_xlsx(data, name="list.xlsx"):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(data), filename=name,
                       content_type="application/vnd.openxmlformats-"
                                    "officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------- boot
database.init_db()
database.seed()
app = create_app()
app.config["TESTING"] = True
client = app.test_client()
exam_auth.create_staff(STAFF, "Medalist Officer", PW)

CONV = raw("SELECT * FROM convocations WHERE is_active = 1")[0]["id"]
PRE = dump(PRESERVE)

# 1. Migration v5 exists and repeat startup is idempotent.
tables = {r["name"] for r in raw(
    "SELECT name FROM sqlite_master WHERE type = 'table'")}
check("migration: medalist tables exist",
      {"medalists", "medalist_import_batches", "medalist_import_staging",
       "medalist_audit"} <= tables, tables)
idx = {r["name"] for r in raw(
    "SELECT name FROM sqlite_master WHERE type = 'index'")}
check("migration: award-slot unique index exists",
      "idx_medalists_award_slot" in idx, idx)
try:
    database.init_db()
    check("migration: repeat startup idempotent", True)
except Exception as exc:  # pragma: no cover
    check("migration: repeat startup idempotent", False, exc)

# 2. Staff login (CSRF on the login form).
r = client.get("/exam/login")
ltok = csrf_of(html(r))
r = client.post("/exam/login",
                data={"username": STAFF, "password": PW, "csrf_token": ltok})
check("staff login succeeds", r.status_code == 302, r.status_code)

# 3. CRUD + audit.
mid = add("Computer Science", "Jane Doe", "gold", "1", "REG-9001")
d = db()
row = med.get(d, mid)
trail = med.audit_trail(d, mid)
d.close()
check("create: record stored as draft",
      row is not None and row["publication"] == "draft", dict(row) if row else None)
check("create: award_category normalised to lowercase",
      row["award_category"] == "gold", row["award_category"])
check("create: audit row written with actor",
      len(trail) == 1 and trail[0]["action"] == "create" and
      trail[0]["actor"] == STAFF, trail)

# 4. Award-slot uniqueness -> 409.
d = db()
try:
    clean, _ = med.clean_row({"department": "Computer Science",
                              "student_name": "John Roe",
                              "award_category": "GOLD", "position": "1",
                              "reference_number": ""})
    med.insert(d, CONV, clean, STAFF)
    d.rollback()
    check("uniqueness: duplicate slot rejected 409", False, "no error")
except med.MedalistError as exc:
    d.rollback()
    check("uniqueness: duplicate slot rejected 409",
          exc.status == 409 and exc.code == "award_conflict", str(exc))
finally:
    d.close()
check("uniqueness: only one row for the slot",
      len(raw("SELECT * FROM medalists WHERE department = 'Computer Science'"
              " AND award_category = 'gold' AND position = '1'")) == 1)

# 5. Publish without a picture is refused.
d = db()
row = med.get(d, mid)
try:
    med.set_publication(d, row, "published", STAFF)
    check("publish gate: refused without picture", False, "no error")
except med.MedalistError as exc:
    d.rollback()
    check("publish gate: refused without picture", exc.status == 400, str(exc))
finally:
    d.close()

# 6. Picture validation: oversize, non-image, then a valid JPEG.
d = db()
row = med.get(d, mid)
try:
    med.store_photo(d, row, b"\xff\xd8\xff" + b"x" * (5 * 1024 * 1024), STAFF)
    check("photo: oversize rejected", False, "no error")
except med.MedalistError as exc:
    d.rollback()
    check("photo: oversize rejected", exc.status == 400, str(exc))
try:
    med.store_photo(d, row, b"not-an-image-at-all", STAFF)
    check("photo: non-image rejected", False, "no error")
except med.MedalistError as exc:
    d.rollback()
    check("photo: non-image rejected", exc.status == 400, str(exc))
try:
    med.store_photo(d, row, jpeg_bytes(size=(9000, 2)), STAFF)
    check("photo: too-large edge rejected", False, "no error")
except med.MedalistError as exc:
    d.rollback()
    check("photo: too-large edge rejected", exc.status == 400, str(exc))
row = med.store_photo(d, row, jpeg_bytes(), STAFF)
check("photo: valid jpeg stored under random name",
      bool(re.fullmatch(r"[0-9a-f]{32}\.jpg", row["photo_file"])),
      row["photo_file"])
first_file = row["photo_file"]
row = med.store_photo(d, row, jpeg_bytes(color=(200, 30, 30)), STAFF)
check("photo: replace swaps file and deletes the old one",
      row["photo_file"] != first_file and
      not os.path.exists(os.path.join(config.MEDALIST_PHOTO_DIR, first_file)),
      row["photo_file"])
d.close()

# 7. Publish now works; audit records publish; unpublish works.
d = db()
row = med.get(d, mid)
med.set_publication(d, row, "published", STAFF)
row = med.get(d, mid)
trail = med.audit_trail(d, mid)
d.close()
check("publish: record published", row["publication"] == "published")
check("publish: audit action recorded",
      any(e["action"] == "publish" for e in trail), trail)
d = db()
row = med.get(d, mid)
med.set_publication(d, row, "draft", STAFF)
d.close()
check("unpublish: back to draft", med.get(db(), mid)["publication"] == "draft")

# 8. Public photo route: draft hidden (404), published served with cache.
r = client.get("/api/student/medalists/photo/%d" % mid)
check("photo route: draft record 404", r.status_code == 404, r.status_code)
d = db()
med.set_publication(d, med.get(d, mid), "published", STAFF)
d.close()
r = client.get("/api/student/medalists/photo/%d" % mid)
check("photo route: published served with public cache",
      r.status_code == 200 and r.mimetype == "image/jpeg" and
      r.headers.get("Cache-Control", "").startswith("public"),
      (r.status_code, r.headers.get("Cache-Control")))

# 9. Public payload privacy: exact keys, no private fields, drafts hidden.
mid2 = add("Computer Science", "Draft Student", "silver", "2")
d = db()
payload = med.public_payload(d, CONV)
d.close()
check("payload: only published records present",
      [m["student_name"] for m in payload] == ["Jane Doe"], payload)
check("payload: exact public key set",
      all(set(m) == {"id", "department", "student_name", "award_category",
                     "position", "has_photo"} for m in payload), payload)
r = client.get("/api/student/medalists")
body = r.get_json()
check("board: convocation + counts present",
      r.status_code == 200 and body["convocation"]["name"] and
      body["total"] == len(body["medalists"]) == 1, body)
check("board: no private fields anywhere in JSON",
      "reference_number" not in r.get_data(as_text=True) and
      "publication" not in r.get_data(as_text=True) and
      "photo_file" not in r.get_data(as_text=True))
check("board: department/category filters work",
      client.get("/api/student/medalists?department=Nope").get_json()
      ["total"] == 0 and
      client.get("/api/student/medalists?category=silver").get_json()
      ["total"] == 0)

# 10. Convocation scoping: a second convocation's records never leak.
# is_active is UNIQUE - deactivate A before activating B.
run("UPDATE convocations SET is_active = 0 WHERE id = ?", (CONV,))
run("INSERT INTO convocations (name, year, is_active, created_at, updated_at)"
    " VALUES ('Other Event', '2027', 1, ?, ?)", (NOW, NOW))
CONV_B = raw("SELECT id FROM convocations WHERE name = 'Other Event'")[0]["id"]
midb = add("Physics", "Other Person", "gold", "1", conv=CONV_B)
d = db()
med.store_photo(d, med.get(d, midb), jpeg_bytes(), STAFF)
med.set_publication(d, med.get(d, midb), "published", STAFF)
d.close()
d = db()
names = [m["student_name"] for m in med.public_payload(d, CONV)]
d.close()
check("scoping: convocation B absent from convocation A board",
      names == ["Jane Doe"], names)
run("UPDATE convocations SET is_active = 0 WHERE id = ?", (CONV,))
run("UPDATE convocations SET is_active = 1 WHERE id = ?", (CONV_B,))
r = client.get("/api/student/medalists")
check("scoping: active convocation switches the board",
      [m["student_name"] for m in r.get_json()["medalists"]] ==
      ["Other Person"], r.get_json())
run("UPDATE convocations SET is_active = 0 WHERE id = ?", (CONV_B,))
run("UPDATE convocations SET is_active = 1 WHERE id = ?", (CONV,))
run("DELETE FROM medalists WHERE convocation_id = ?", (CONV_B,))
run("DELETE FROM convocations WHERE id = ?", (CONV_B,))  # convocations is PRESERVE-listed

# 11. Excel import: template structure.
tpl = medalist_import.build_template()
wb = load_workbook(io.BytesIO(tpl))
check("template: medalists sheet with canonical headers",
      wb.sheetnames[0] == "medalists" and
      [c.value for c in wb["medalists"][1]] == list(med.FIELDS),
      wb.sheetnames)
check("template: notes sheet documents assumptions",
      "notes" in wb.sheetnames and
      any("Assumption" in str(c.value or "")
          for row in wb["notes"].iter_rows() for c in row))

# 12. Import: valid + invalid + duplicate + conflict in one workbook.
rows = [
    ("Computer Science", "Alice Add", "gold", "2", "REG-9001"),   # valid
    ("Computer Science", "Bob Bad", "", "1", ""),                 # invalid
    ("Computer Science", "Jane Doe", "gold", "1", ""),            # db conflict
    ("Computer Science", "Alice Add", "silver", "1", ""),         # in-file dup (same dept+name)
    ("Mathematics", "Carol New", "silver", "1", "NOMATCH99"),     # valid (unmatched ref)
]
try:
    bid, _ = medalist_import.parse_upload(upload_xlsx(xlsx_bytes(rows)),
                                          CONV, STAFF)
    rejected = None
except medalist_import.ImportRejected as exc:
    bid, rejected = None, str(exc)
check("import: workbook accepted and staged", bid is not None, rejected)
d = db()
batch = medalist_import.get_batch(d, bid)
errs = medalist_import.error_rows(d, bid)
d.close()
check("import: staging counts (1 invalid, 1 duplicate, 1 conflict)",
      (batch["valid_rows"], batch["invalid_rows"], batch["duplicate_rows"],
       batch["conflict_rows"]) == (2, 1, 1, 1), dict(batch))
check("import: conflict row names the existing slot",
      any("Computer Science" in e["errors_json"] for e in errs), errs)

# 13. Missing required column -> ImportRejected (no batch).
try:
    medalist_import.parse_upload(
        upload_xlsx(xlsx_bytes([("A", "B", "C")],
                               headers=("dept", "name", "award"))),
        CONV, STAFF)
    check("import: missing required column rejected", False, "no error")
except medalist_import.ImportRejected as exc:
    check("import: missing required column rejected",
          "student_name" in str(exc) or "department" in str(exc), str(exc))

# 14. Commit: valid rows inserted as drafts, others skipped, audited.
before = raw("SELECT COUNT(*) AS n FROM medalists")[0]["n"]
medalist_import.commit_batch(bid, STAFF)
after = raw("SELECT COUNT(*) AS n FROM medalists")[0]["n"]
d = db()
batch = medalist_import.get_batch(d, bid)
d.close()
check("commit: exactly the 2 valid rows inserted",
      after - before == 2 and batch["status"] == "committed",
      (before, after, batch["status"]))
check("commit: imported rows start as drafts",
      all(r["publication"] == "draft" for r in raw(
          "SELECT publication FROM medalists WHERE student_name IN"
          " ('Alice Add', 'Carol New')")))
check("commit: audit records the batch commit",
      any(r["action"] == "medalist_import_committed" for r in raw(
          "SELECT action FROM audit_log WHERE detail LIKE ?",
          ("batch %d:%%" % bid,))))

# 15. Transaction rollback: fault-injected mid-commit failure.
rows2 = [("Biology", "Dan Roll", "gold", "1", ""),
         ("Biology", "Eve Roll", "silver", "1", "")]
bid2, _ = medalist_import.parse_upload(upload_xlsx(xlsx_bytes(rows2)),
                                       CONV, STAFF)
orig_insert = medalist_import._insert_row
calls = {"n": 0}


def boom(db_, conv, clean, batch_id, actor):
    calls["n"] += 1
    if calls["n"] >= 2:
        raise RuntimeError("injected failure")
    return orig_insert(db_, conv, clean, batch_id, actor)


medalist_import._insert_row = boom
try:
    medalist_import.commit_batch(bid2, STAFF)
    check("rollback: injected failure raises", False, "no error")
except RuntimeError:
    pass
finally:
    medalist_import._insert_row = orig_insert
d = db()
batch2 = medalist_import.get_batch(d, bid2)
d.close()
check("rollback: no partial rows survive",
      len(raw("SELECT * FROM medalists WHERE student_name IN"
              " ('Dan Roll', 'Eve Roll')")) == 0)
check("rollback: batch marked failed",
      batch2["status"] == "failed", batch2["status"])
check("rollback: failure audited",
      any(r["action"] == "medalist_import_failed" for r in raw(
          "SELECT action FROM audit_log WHERE detail LIKE ?",
          ("batch %d:%%" % bid2,))))

# 16. Corrections + audit history.
d = db()
row = med.get(d, mid)
med.correct(d, row, {"student_name": "Jane M. Doe"}, STAFF)
row = med.get(d, mid)
trail = med.audit_trail(d, mid)
d.close()
check("correct: value updated", row["student_name"] == "Jane M. Doe")
check("correct: before/after diff audited",
      any(e["action"] == "correct" and
          ("student_name", "Jane Doe", "Jane M. Doe") in e["changes"]
          for e in trail), trail)

# 17. CSRF + authorization on the medalists blueprint.
fresh = app.test_client()
check("auth: anonymous medalist list redirects",
      fresh.get("/exam/medalists/").status_code == 302)
with fresh.session_transaction() as s:
    s["lgu_admin"] = "1"
check("auth: volunteer session cannot open medalist list",
      fresh.get("/exam/medalists/").status_code == 302)
r = client.get("/exam/medalists/new")
tok = csrf_of(html(r))
check("csrf: form carries a token", bool(tok))
r = client.post("/exam/medalists/new",
                data={"department": "CS", "student_name": "No Token",
                      "award_category": "gold", "csrf_token": "wrong"})
check("csrf: POST without valid token rejected",
      r.status_code == 403, r.status_code)
r = client.post("/exam/medalists/new",
                data={"department": "CS", "student_name": "With Token",
                      "award_category": "gold", "csrf_token": tok})
check("csrf: POST with valid token accepted", r.status_code == 302,
      r.status_code)

# 18. Dashboard: medalist counts + warnings from real records.
mid3 = add("Statistics", "Stat One", "gold", "1")  # gold-only dept: gap
d = db()
with app.test_request_context():
    m = dashboard_metrics(d)
d.close()
mc = m["medalists"]
check("dashboard: medalist counts are real",
      mc["total"] >= 3 and mc["published"] >= 1 and
      mc["missing_photo"] >= 1 and mc["coverage_missing"] >= 1, mc)
texts = " ".join(i["text"] for i in m["issues"])
check("dashboard: warns about missing pictures",
      "no picture" in texts, texts)
check("dashboard: warns about coverage gaps",
      "coverage" in texts or "missing" in texts, texts)
check("dashboard: warns about unpublished records",
      "unpublished" in texts, texts)
page = html(client.get("/exam/dashboard"))
# 24 = 11 base (7 registration + 4 medalist) + 4 Phase 7 event tiles
# + 4 later-phase tiles + 2 Phase 29 per-occasion admission tiles.
check("dashboard: page renders medalist KPI tiles",
      page.count("kpi-tile") == 24, page.count("kpi-tile"))
check("dashboard: medalist card links to the list",
      "/exam/medalists/" in page)

# 19. Medalist list page renders records + filters.
page = html(client.get("/exam/medalists/"))
check("list: renders records", "Jane M. Doe" in page, page[:200])
page = html(client.get("/exam/medalists/?department=Computer%20Science"))
check("list: department filter applies",
      "Jane M. Doe" in page and "Carol New" not in page)

# 20. Volunteer/QR/gate data untouched.
check("preserve: volunteer/QR/gate tables untouched",
      dump(PRESERVE) == PRE)

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)