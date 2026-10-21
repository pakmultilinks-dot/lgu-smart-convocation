"""Phase 37 DB-001 — v6 -> v13 migration rehearsal on a disposable copy.

Phase 36 audit DB-001: the codebase supports schema v13 while production
runs v6, and no supervised migration was ever rehearsed end-to-end against
production CONTENT. This suite rehearses the real ladder safely:

  * reads production strictly read-only (mode=ro URI) for a baseline;
  * takes the VERIFIED BACKUP created by scripts\\backup_db.py (so the
    rehearsal also proves the backup is restorable);
  * copies that artifact to %TEMP% and migrates THE COPY v6 -> v13;
  * asserts schema integrity, row preservation (students / guests / scans
    / settings / QR identifiers), the new v7..v13 objects, column
    backfills, and migrator idempotency;
  * re-stamps production afterwards — size, mtime and sha256 must be
    byte-identical to the baseline.

It performs NO write against app\\lgu.db and stops short of any real
production migration — that requires explicit operator approval after
reviewing this rehearsal (see docs/PHASE37_...REPORT.md).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase37_migration_rehearsal.py [backup.db]
"""

import glob
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

import config  # noqa: E402
import migrations  # noqa: E402

PROD = config.PRODUCTION_DB_PATH
if not os.path.isfile(PROD):
    print("SKIP: production-content audit requires a local production database; "
          "source-only review does not include it. Synthetic migration tests run separately.")
    sys.exit(0)

BASELINE_SHA256 = ("820113702b02cb2ea87bd5bc8253ba8733f89696dded209465e94b5ee8cb915f")

NEW_TABLES = {"support_requests", "support_events", "student_reminder_state",
              "convocation_passes", "convocation_admissions",
              "scanner_users", "scanner_gates", "scanner_sessions"}

# Column subsets that must hash identically across the migration (ordered,
# stable, values never printed — only row count + sha256 prefix).
TRACKED = {
    "students": "SELECT id, roll_no, name, qr_id"
                " FROM students ORDER BY id",
    "scans": "SELECT id, qr_id, person_type, gate_id, scanned_at"
             " FROM scans ORDER BY id",
    "guests": "SELECT id, host_roll_no, qr_id FROM guests ORDER BY id",
    "settings": "SELECT key, value FROM settings ORDER BY key",
    "gates": "SELECT id, code, label FROM gates ORDER BY id",
}

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    if not cond:
        print("  FAIL %s  %r" % (name, detail))


def step(n, title):
    print("\n[%02d] %s" % (n, title))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ro(path):
    """Open a database strictly read-only (file: URI, mode=ro)."""
    return sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"),
                           uri=True)


def snapshot(conn):
    tables = {r[0] for r in
              conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    counts = {t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
              for t in sorted(tables)}
    digests = {}
    for t, sql in TRACKED.items():
        if t in tables:
            rows = conn.execute(sql).fetchall()
            digests[t] = (len(rows),
                          hashlib.sha256(repr(rows).encode()).hexdigest()[:16])
    return tables, counts, digests


def columns(conn, table):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}


def fmt_digests(d):
    return {t: v for t, v in sorted(d.items())}


# ---------------------------------------------------- 1. production baseline
step(1, "Production baseline (read-only): version, tables, data digests")
_stat0 = os.stat(PROD)
_stamp0 = (_stat0.st_size, _stat0.st_mtime_ns)
_sha0 = sha256_file(PROD)
check("prod sha256 matches the Phase 37 baseline stamp",
      _sha0 == BASELINE_SHA256, _sha0)
prod = ro(PROD)
pv = prod.execute("PRAGMA user_version").fetchone()[0]
prod_tables, prod_counts, prod_digests = snapshot(prod)
prod.close()
check("prod user_version == 6 (unsupervised-migration finding confirmed)",
      pv == 6, pv)
check("prod has 27 tables", len(prod_tables) == 27, len(prod_tables))
check("tracked tables exist in prod",
      all(t in prod_tables for t in TRACKED), sorted(prod_tables))

# ------------------------------------------------------ 2. verified backup
step(2, "Locate the verified backup and confirm it mirrors production")
if len(sys.argv) > 1:
    backup_path = sys.argv[1]
else:
    candidates = sorted(glob.glob(os.path.join(APP, "backups",
                                               "convocation-*.db")))
    backup_path = candidates[-1] if candidates else None
check("backup artifact found", bool(backup_path), backup_path)
bk = ro(backup_path)
bv = bk.execute("PRAGMA user_version").fetchone()[0]
bk_tables, bk_counts, bk_digests = snapshot(bk)
bk.close()
check("backup user_version == 6", bv == 6, bv)
check("backup table set == production table set", bk_tables == prod_tables,
      sorted(bk_tables ^ prod_tables))
check("backup row counts == production row counts", bk_counts == prod_counts,
      (bk_counts, prod_counts))
check("backup data digests == production data digests",
      bk_digests == prod_digests,
      (fmt_digests(bk_digests), fmt_digests(prod_digests)))

# ------------------------------------------- 3. migrate a disposable copy
step(3, "Migrate the disposable copy v6 -> v13")
tmpdir = tempfile.mkdtemp(prefix="lgu-p37rehearsal-")
copy_path = os.path.join(tmpdir, "rehearsal.db")
shutil.copy2(backup_path, copy_path)
check("disposable copy created outside the repo", os.path.exists(copy_path),
      copy_path)

db = sqlite3.connect(copy_path)
cv = db.execute("PRAGMA user_version").fetchone()[0]
check("copy starts at user_version 6", cv == 6, cv)
pre_tables, pre_counts, pre_digests = snapshot(db)
check("no v7+ table exists before migrating",
      not (pre_tables & NEW_TABLES), sorted(pre_tables & NEW_TABLES))

try:
    migrations.migrate(db)
    migrated_ok, migrated_err = True, ""
except Exception as exc:  # noqa: BLE001 — surfaced as a failed check
    migrated_ok, migrated_err = False, repr(exc)
check("migrations.migrate() completed without error", migrated_ok,
      migrated_err)

# ------------------------------------------- 4. post-migration verification
step(4, "Schema integrity on the migrated copy")
mv = db.execute("PRAGMA user_version").fetchone()[0]
check("user_version == 14 (latest supported)", mv == 14, mv)
integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
check("PRAGMA integrity_check == ok", integrity == "ok", integrity)
post_tables, post_counts, post_digests = snapshot(db)
check("all v7..v13 tables created", NEW_TABLES <= post_tables,
      sorted(NEW_TABLES - post_tables))
check("no table lost", post_tables >= pre_tables,
      sorted(pre_tables - post_tables))

step(5, "Data preservation: counts + digests (students / scans / guests / "
         "settings / QR)")
check("row counts for every pre-existing table are unchanged",
      all(post_counts.get(t) == c for t, c in pre_counts.items()),
      {t: (c, post_counts.get(t)) for t, c in pre_counts.items()
       if post_counts.get(t) != c})
check("tracked data digests unchanged (incl. students.qr_id QR data)",
      post_digests == pre_digests,
      (fmt_digests(pre_digests), fmt_digests(post_digests)))
check("student roster preserved (%d rows)" % post_counts.get("students", 0),
      post_counts.get("students") == pre_counts.get("students"))
check("attendance/scans ledger preserved (%d rows)"
      % post_counts.get("scans", 0),
      post_counts.get("scans") == pre_counts.get("scans"))

step(6, "New columns and backfills (v11..v13)")
check("guests.status column added", "status" in columns(db, "guests"))
if post_counts.get("guests", 0):
    vals = [r[0] for r in db.execute("SELECT DISTINCT status FROM guests")]
    check("every existing guest backfilled to 'active'",
          set(vals) <= {"active"}, vals)
check("convocations.ceremony_time + rehearsal_venue added",
      {"ceremony_time", "rehearsal_venue"} <= columns(db, "convocations"))
check("convocation_admissions.occasion column added",
      "occasion" in columns(db, "convocation_admissions"))
check("scanner_users.credential_established column added",
      "credential_established" in columns(db, "scanner_users"))

step(7, "Migrator idempotency and refusal contract on the copy")
try:
    migrations.migrate(db)
    again = db.execute("PRAGMA user_version").fetchone()[0]
    check("re-running migrate() is a no-op at v14", again == 14, again)
except Exception as exc:  # noqa: BLE001
    check("re-running migrate() is a no-op at v14", False, repr(exc))
db.execute("PRAGMA user_version = 99")
db.commit()
try:
    migrations.migrate(db)
    check("newer-than-supported database refused", False,
          "migrate() returned normally")
except RuntimeError:
    check("newer-than-supported database refused", True)
db.close()

# -------------------------------------------------- 5. production untouched
step(8, "Production re-stamp: unchanged after the whole rehearsal")
_stat1 = os.stat(PROD)
_stamp1 = (_stat1.st_size, _stat1.st_mtime_ns)
_sha1 = sha256_file(PROD)
check("prod size + mtime identical", _stamp1 == _stamp0, (_stamp0, _stamp1))
check("prod sha256 identical", _sha1 == _sha0, (_sha0, _sha1))
check("prod sha256 still the recorded Phase 37 baseline",
      _sha1 == BASELINE_SHA256, _sha1)

shutil.rmtree(tmpdir, ignore_errors=True)
failed = [n for n, ok in RESULTS if not ok]
print("\n%d checks, %d failures" % (len(RESULTS), len(failed)))
print("NOTE: this rehearsal stops before any real production migration —"
      " operator approval required (DB-001).")
sys.exit(1 if failed else 0)
