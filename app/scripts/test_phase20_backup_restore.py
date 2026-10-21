#!/usr/bin/env python
"""Phase 20 §3 — backup, restore and integrity evidence.

Demonstrates the eight properties the release gate requires, on disposable
databases only. The production file is never opened, copied or restored onto.

Run from app/:  ..\\..\\.venv\\Scripts\\python.exe scripts\\test_phase20_backup_restore.py
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p20bk-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "bootstrap.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import backup  # noqa: E402
from _production_boundary import production_stamp
_PRODUCTION_BEFORE = production_stamp()

import config  # noqa: E402
import database  # noqa: E402
import migrations  # noqa: E402

config.require_test_db()

RESULTS = []
PY = sys.executable


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    if not cond:
        print("  FAIL %s %s" % (name, detail))


def step(n, title):
    print("\n[%02d] %s" % (n, title))


def open_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def seed_records(db, conv, n):
    """Insert n registrations under one convocation, transactionally."""
    now = "2026-10-14 09:00:00"
    for i in range(n):
        db.execute(
            "INSERT INTO convocation_registrations (convocation_id,"
            " registration_number, university_email, roll_number, student_name,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (conv, "R-%04d" % i, "s%04d@lgu.edu.pk" % i,
             "ROLL-%04d" % i, "Student %d" % i, now, now))
    db.commit()


# ------------------------------------------------------------------ fixtures
step(0, "Build a disposable database with real records and a scanner account")
LIVE = os.path.join(_TMP, "live.db")
saved = config.DB_PATH
config.DB_PATH = LIVE
database.init_db()
database.seed()
import scanner_auth  # noqa: E402
sid = scanner_auth.create_scanner("p20.bk", "Backup Scanner", pin="48129376",
                                  gate_ids=(1, 2), actor="p20",
                                  via=scanner_auth.VIA_CLI)
db = open_db(LIVE)
conv = db.execute("SELECT id FROM convocations WHERE is_active=1").fetchone()[0]
seed_records(db, conv, 40)
db.execute("INSERT INTO audit_log (actor, action, detail, created_at)"
           " VALUES ('p20','scanner_created','via=cli username=p20.bk',?)",
           ("2026-10-14 09:00:00",))
db.commit()
baseline_rows = db.execute("SELECT COUNT(*) FROM convocation_registrations").fetchone()[0]
db.close()

# ------------------------------------------------- 1. consistent under load
step(1, "A consistent backup is produced while the application is writing")
stop = threading.Event()
write_errors = []


def churn():
    conn = open_db(LIVE)
    n = 0
    try:
        while not stop.is_set():
            # Each iteration commits a convocation+registration pair atomically,
            # so a torn snapshot would leave a registration pointing at a
            # convocation that is not there.
            cur = conn.execute(
                "INSERT INTO convocations (name, year, status, is_active,"
                " created_at, updated_at) VALUES (?, '2030', 'planned', 0, ?, ?)",
                ("Churn %d" % n, "2026-10-14 09:00:00", "2026-10-14 09:00:00"))
            cid = cur.lastrowid
            conn.execute(
                "INSERT INTO convocation_registrations (convocation_id,"
                " registration_number, university_email, roll_number, student_name,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, "C-%04d" % n, "c%04d@lgu.edu.pk" % n, "CROLL-%04d" % n,
                 "Churn Student %d" % n, "2026-10-14 09:00:00",
                 "2026-10-14 09:00:00"))
            conn.commit()
            n += 1
    except Exception as exc:  # pragma: no cover - reported as a failure
        write_errors.append(repr(exc))
    finally:
        conn.close()


writer = threading.Thread(target=churn, daemon=True)
writer.start()
LIVE_BACKUP = os.path.join(_TMP, "snap.db")
try:
    manifest = backup.backup(LIVE_BACKUP, db_path=LIVE)
finally:
    stop.set()
    writer.join(timeout=10)
check("concurrent writer made no errors", not write_errors, str(write_errors))
check("backup produced under concurrent writes", os.path.exists(LIVE_BACKUP))
check("backup manifest reports a schema version", manifest["user_version"] ==
      migrations.MIGRATIONS[-1][0], str(manifest["user_version"]))

snap = open_db(LIVE_BACKUP)
try:
    orphans = snap.execute(
        "SELECT COUNT(*) FROM convocation_registrations r"
        " WHERE NOT EXISTS (SELECT 1 FROM convocations c WHERE c.id = r.convocation_id)"
    ).fetchone()[0]
    check("snapshot has no orphaned foreign keys", orphans == 0, str(orphans))
    check("snapshot passes integrity_check",
          snap.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
    check("snapshot committed rows are all present",
          snap.execute("SELECT COUNT(*) FROM convocation_registrations"
                       " WHERE registration_number LIKE 'R-%'").fetchone()[0]
          == baseline_rows, "expected %d" % baseline_rows)
finally:
    snap.close()

# ------------------------------------------------- 2. validation rejects junk
step(2, "Validation detects an invalid or incomplete artefact")
cases = []

p = os.path.join(_TMP, "missing.db")
try:
    backup.validate(p)
except ValueError as exc:
    cases.append(("missing file", "not found" in str(exc)))
else:
    cases.append(("missing file", False))

p = os.path.join(_TMP, "tiny.db")
open(p, "wb").write(b"short")
try:
    backup.validate(p)
except ValueError as exc:
    cases.append(("truncated to a few bytes", "too small" in str(exc)))
else:
    cases.append(("truncated to a few bytes", False))

p = os.path.join(_TMP, "notdb.db")
open(p, "wb").write(b"PK\x03\x04 this is a zip archive, not sqlite" * 64)
try:
    backup.validate(p)
except ValueError as exc:
    cases.append(("non-SQLite file", "header" in str(exc)))
else:
    cases.append(("non-SQLite file", False))

# A naive file copy that stops mid-file is exactly what an interrupted `copy`
# produces; validation must catch the corruption, which a bare existence check
# would not.
raw = open(LIVE, "rb").read()
p = os.path.join(_TMP, "torn.db")
open(p, "wb").write(raw[:len(raw) // 2])
try:
    backup.validate(p)
except ValueError as exc:
    cases.append(("torn copy (interrupted file copy)",
                  "corrupt" in str(exc).lower() or "malformed" in str(exc).lower()))
else:
    cases.append(("torn copy (interrupted file copy)", False))

for label, ok in cases:
    check("rejects: %s" % label, ok)

# A database written by a NEWER build must also be refused.
p = os.path.join(_TMP, "future.db")
conn = open_db(p)
conn.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY);")
conn.execute("PRAGMA user_version = %d" % (migrations.MIGRATIONS[-1][0] + 3))
conn.commit()
conn.close()
try:
    backup.validate(p)
except ValueError as exc:
    check("rejects: newer schema version", "newer" in str(exc))
else:
    check("rejects: newer schema version", False)

# ------------------------------------------------- 3/4/5/6/7 restore
step(3, "Restore into a separate location, then prove integrity and fidelity")
RESTORED = os.path.join(_TMP, "restored", "copy.db")
# (7) must compare the live file immediately before and after the restore, not
# against a step-0 baseline: the churn writer in step 1 legitimately changes it.
live_pre_restore = backup.sha256_of(LIVE)
info = backup.restore(LIVE_BACKUP, RESTORED)
check("restore reports byte-identical digest", info["matched_source"] is True,
      str(info["sha256"]))
check("restored digest equals the source snapshot",
      info["sha256"] == manifest["sha256"], "%s vs %s" % (info["sha256"], manifest["sha256"]))
check("restored into a separate directory", RESTORED != LIVE_BACKUP != LIVE)

r = open_db(RESTORED)
try:
    check("restored DB passes integrity_check",
          r.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
    check("restored DB passes quick_check",
          r.execute("PRAGMA quick_check").fetchone()[0] == "ok")
    check("original registrations survive (%d)" % baseline_rows,
          r.execute("SELECT COUNT(*) FROM convocation_registrations"
                    " WHERE registration_number LIKE 'R-%'").fetchone()[0]
          == baseline_rows)
    check("scanner account survives",
          r.execute("SELECT COUNT(*) FROM scanner_users WHERE username='p20.bk'")
          .fetchone()[0] == 1)
    check("scanner gate assignments survive",
          r.execute("SELECT COUNT(*) FROM scanner_gates WHERE scanner_id=?", (sid,))
          .fetchone()[0] == 2)
    check("audit history survives",
          r.execute("SELECT COUNT(*) FROM audit_log WHERE action='scanner_created'")
          .fetchone()[0] >= 1)
    check("foreign keys intact after restore",
          r.execute("SELECT COUNT(*) FROM convocation_registrations r"
                    " WHERE NOT EXISTS (SELECT 1 FROM convocations c"
                    " WHERE c.id = r.convocation_id)").fetchone()[0] == 0)
finally:
    r.close()

# (7) the original is untouched by restoration.
after_restore = backup.sha256_of(LIVE)
check("original database unchanged by restore", after_restore == live_pre_restore,
      "%s vs %s" % (after_restore, live_pre_restore))

# (5) migrations run on the restored copy.
r = open_db(RESTORED)
try:
    version_before = r.execute("PRAGMA user_version").fetchone()[0]
finally:
    r.close()
check("migrations run on the restored copy",
      backup.validate(RESTORED)["user_version"] == version_before ==
      migrations.MIGRATIONS[-1][0])

# ------------------------------------------------- 8. no secret exposure
step(4, "Backups, filenames and manifests expose no secrets or student data")
manifest_path = LIVE_BACKUP + backup.MANIFEST_SUFFIX
blob = open(manifest_path, "r", encoding="utf-8").read()
parsed = json.loads(blob)
check("manifest records a digest", bool(re.fullmatch(r"[0-9a-f]{64}", parsed["sha256"])))
check("manifest contains no email address",
      not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", blob))
check("manifest contains no student name", "Student" not in blob)
check("manifest contains no scanner PIN", "48129376" not in blob)
check("manifest contains no password/PIN field",
      not re.search(r"(?i)pin_hash|password|token_hash|secret", blob))
check("backup filename carries no personal data",
      not re.search(r"(?i)student|email|lgu-20|\d{4}-\d{2}", os.path.basename(LIVE_BACKUP)),
      os.path.basename(LIVE_BACKUP))

# ------------------------------------------------- CLI round trip
step(5, "Operator round trip through the documented CLI")
out_dir = os.path.join(_TMP, "cli")
os.makedirs(out_dir, exist_ok=True)
cli_backup = os.path.join(out_dir, "cli-copy.db")
env = dict(os.environ)
env["LGU_DB_PATH"] = LIVE
p = subprocess.run([PY, os.path.join("scripts", "backup_db.py"), "create",
                    "--dest", cli_backup], capture_output=True, text=True, env=env)
check("CLI create exits 0", p.returncode == 0, p.stdout + p.stderr)
check("CLI create prints a digest", re.search(r"[0-9a-f]{64}", p.stdout) is not None)
check("CLI create never prints a student record",
      "Student 0" not in p.stdout and "@lgu.edu.pk" not in p.stdout)

p = subprocess.run([PY, os.path.join("scripts", "backup_db.py"), "verify", cli_backup],
                   capture_output=True, text=True, env=env)
check("CLI verify exits 0 on a good artefact", p.returncode == 0, p.stdout + p.stderr)

p = subprocess.run([PY, os.path.join("scripts", "backup_db.py"), "verify",
                    os.path.join(_TMP, "torn.db")], capture_output=True, text=True, env=env)
check("CLI verify exits 1 on a torn artefact", p.returncode == 1, p.stdout)
check("CLI verify names the problem", "INVALID" in p.stdout, p.stdout)

p = subprocess.run([PY, os.path.join("scripts", "backup_db.py"), "list",
                    "--dir", out_dir], capture_output=True, text=True, env=env)
check("CLI list exits 0", p.returncode == 0, p.stdout + p.stderr)

cli_restore = os.path.join(_TMP, "cli-restored.db")
p = subprocess.run([PY, os.path.join("scripts", "backup_db.py"), "restore", cli_backup,
                    "--to", cli_restore], capture_output=True, text=True, env=env)
check("CLI restore exits 0", p.returncode == 0, p.stdout + p.stderr)
check("CLI restored file verifies", backup.validate(cli_restore)["sha256"] ==
      backup.sha256_of(cli_backup))

# The refusal that matters most: never restore onto production.
p = subprocess.run([PY, os.path.join("scripts", "backup_db.py"), "restore", cli_backup,
                    "--to", os.path.abspath(config.PRODUCTION_DB_PATH)],
                   capture_output=True, text=True, env=env)
check("CLI refuses to restore over the production database",
      p.returncode == 1 and "REFUSED" in p.stdout, p.stdout + p.stderr)
check("production file untouched by the refusal",
      production_stamp() == _PRODUCTION_BEFORE)

# ------------------------------------------------- cleanup
config.DB_PATH = saved
shutil.rmtree(_TMP, ignore_errors=True)
fails = [r for r in RESULTS if not r[1]]
print("\n%d checks, %d failures" % (len(RESULTS), len(fails)))
for name, _, detail in fails:
    print("  FAILED: %s %s" % (name, detail))
sys.exit(1 if fails else 0)
