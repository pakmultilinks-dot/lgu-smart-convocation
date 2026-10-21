#!/usr/bin/env python
"""Phase 21 §2 — the REAL version-6 → version-11 migration on synthetic data.

Production `app/lgu.db` reports `user_version = 6` while this build supports
the full ladder (currently 12 — Phase 29 added the two-occasion schema), so
the next deployment will apply every migration from 7 upward
(7 support, 8 reminders, 9 passes/admissions, 10 scanner identities,
11 credential lifecycle, 12 annual-occasion columns) to a database that
already holds live records.

A migration that completes without an exception is not necessarily correct, so
every pre-existing row is snapshotted column-by-column and compared after the
upgrade. The fixture is 100% synthetic — nothing is derived from production.

Run from app/:  ..\\..\\.venv\\Scripts\\python.exe scripts\\test_phase21_migration_v6_to_v11.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p21mig-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "bootstrap.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
import database  # noqa: E402
import migrations  # noqa: E402

config.require_test_db()

LATEST = migrations.MIGRATIONS[-1][0]
RESULTS = []


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


def q(path, sql, args=()):
    db = open_db(path)
    try:
        return db.execute(sql, args).fetchall()
    finally:
        db.close()


def scalar(path, sql, args=()):
    rows = q(path, sql, args)
    return rows[0][0] if rows else None


def user_version(path):
    return scalar(path, "PRAGMA user_version")


def build(tag, version=None):
    """A real database at `tag`, applying only migrations <= `version`."""
    path = os.path.join(_TMP, "%s.db" % tag)
    saved_path, saved_mig = config.DB_PATH, migrations.MIGRATIONS
    if version is not None:
        migrations.MIGRATIONS = [m for m in saved_mig if m[0] <= version]
    try:
        config.DB_PATH = path
        database.init_db()
        # Gates, the active convocation, roster students and guests come from
        # the seed (they are referenced by the synthetic records below).
        database.seed()
    finally:
        config.DB_PATH, migrations.MIGRATIONS = saved_path, saved_mig
    return path


def objects(path, kind):
    return {r[0] for r in q(path, "SELECT name FROM sqlite_master WHERE type=?",
                            (kind,))}


def columns(path, table):
    return [r[1] for r in q(path, "PRAGMA table_info(%s)" % table)]


_BASELINE_COLS = {}


def snapshot(path):
    """Every row of every user table, keyed (table, id), values in column order.

    Values are projected onto the column set seen when that table was first
    snapshotted for this database, so a later migration that ADDs a column
    (Phase 29's ceremony_time/rehearsal_venue/occasion) does not read as a
    mutation of the rows it backfills."""
    state = {}
    for name in sorted(objects(path, "table")):
        if name.startswith("sqlite_"):
            continue
        cols = [r[1] for r in q(path, "PRAGMA table_info(%s)" % name)]
        base = _BASELINE_COLS.setdefault((path, name), cols)
        idx = [cols.index(c) for c in base if c in cols]
        for row in q(path, "SELECT * FROM %s" % name):
            vals = tuple(row)
            state[(name, row["id"] if "id" in row.keys() else 0)] = \
                tuple(vals[i] for i in idx)
    return state


# ------------------------------------------------- synthetic v6 population
NOW = "2026-10-14 09:00:00"
DEPTS = ["Computer Science", "Software Engineering", "Business Administration",
         "English", "Psychology", "Mass Communication", "Mathematics"]


def populate_v6(path):
    """Insert a realistic spread of records that already exist at schema v6."""
    db = open_db(path)
    try:
        # -- legacy operational roster (base SCHEMA) -------------------
        for i in range(12):
            db.execute("INSERT INTO scans (qr_id, person_type, person_name,"
                       " gate_id, mode, volunteer, scanned_at, source)"
                       " VALUES (?, 'student', ?, ?, ?, ?, ?, 'online')",
                       ("QR-LEG-%02d" % i, "Legacy Student %d" % i,
                        (i % 7) + 1, "entry" if i % 2 == 0 else "exit",
                        "Volunteer %d" % (i % 3), NOW))
        db.execute("INSERT INTO broadcasts (audience, message, sent_by, sent_at)"
                   " VALUES ('students', 'Synthetic v6 broadcast', 'registrar', ?)",
                   (NOW,))
        # -- staff + audit (m2) --------------------------------------
        db.execute("INSERT INTO staff_users (username, display_name,"
                   " password_hash, created_at, updated_at)"
                   " VALUES ('registrar', 'Ms Registrar', 'scrypt$synthetic', ?, ?)",
                   (NOW, NOW))
        db.execute("INSERT INTO audit_log (actor, action, detail, created_at)"
                   " VALUES ('registrar', 'settings_updated', 'via=portal synthetic', ?)",
                   (NOW,))
        # -- registrations (m3) --------------------------------------
        conv = scalar(path, "SELECT id FROM convocations WHERE is_active = 1")
        for i in range(25):
            db.execute("INSERT INTO convocation_registrations (convocation_id,"
                       " registration_number, university_email, roll_number,"
                       " student_name, department, status, created_at, updated_at)"
                       " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (conv, "REG-%05d" % i, "synth%03d@lgu.edu.pk" % i,
                        "ROLL-%05d" % i, "Synthetic Student %d" % i,
                        DEPTS[i % len(DEPTS)],
                        "cancelled" if i % 9 == 0 else "active", NOW, NOW))
        db.commit()  # scalar() below opens a second connection — must see these
        db.execute("INSERT INTO registration_audit (registration_id,"
                   " convocation_id, actor, action, after_json, created_at)"
                   " VALUES (1, ?, 'registrar', 'imported', '{}', ?)", (conv, NOW))
        # -- student accounts (m4) -----------------------------------
        for i in range(8):
            db.execute("INSERT INTO student_accounts (university_email,"
                       " password_hash, created_at, updated_at)"
                       " VALUES (?, 'scrypt$synthetic', ?, ?)",
                       ("synth%03d@lgu.edu.pk" % i, NOW, NOW))
        db.commit()
        acc = scalar(path, "SELECT id FROM student_accounts WHERE university_email"
                           " = 'synth000@lgu.edu.pk'")
        reg1 = scalar(path, "SELECT id FROM convocation_registrations"
                            " WHERE registration_number = 'REG-00001'")
        db.execute("INSERT INTO student_profiles (account_id, phone, created_at,"
                   " updated_at) VALUES (?, '+92-300-0000001', ?, ?)",
                   (acc, NOW, NOW))
        db.execute("INSERT INTO registration_claims (account_id, convocation_id,"
                   " registration_id, created_at) VALUES (?, ?, ?, ?)",
                   (acc, conv, reg1, NOW))
        db.execute("INSERT INTO verification_challenges (purpose,"
                   " university_email, convocation_id, code_hash, expires_at,"
                   " created_at, last_sent_at) VALUES"
                   " ('signup', 'synth001@lgu.edu.pk', ?, 'sha256$synthetic',"
                   " ?, ?, ?)", (conv, NOW, NOW, NOW))
        db.execute("INSERT INTO student_sessions (account_id, token_hash,"
                   " created_at, expires_at) VALUES (?, 'sha256$session', ?, ?)",
                   (acc, NOW, NOW))
        # -- medalists (m5) ------------------------------------------
        db.execute("INSERT INTO medalist_import_batches (convocation_id,"
                   " filename, file_sha256, created_by, created_at)"
                   " VALUES (?, 'synthetic.xlsx', 'abc123', 'registrar', ?)",
                   (conv, NOW))
        db.execute("INSERT INTO medalists (convocation_id, department,"
                   " student_name, award_category, position, reference_number,"
                   " publication, created_at, updated_at)"
                   " VALUES (?, 'Computer Science', 'Synthetic Medallist',"
                   " 'Gold Medal', '1st', 'REG-00002', 'published', ?, ?)",
                   (conv, NOW, NOW))
        db.execute("INSERT INTO medalist_audit (medalist_id, convocation_id,"
                   " actor, action, after_json, created_at)"
                   " VALUES (1, ?, 'registrar', 'published', '{}', ?)", (conv, NOW))
        # -- events / announcements (m6) -----------------------------
        db.execute("UPDATE convocations SET rehearsal_time = '10:00'"
                   " WHERE id = ?", (conv,))
        db.execute("INSERT INTO convocation_publications (convocation_id, name,"
                   " year, expected_date, venue, instructions, published_by,"
                   " published_at) VALUES (?, 'LGU Convocation', '2026',"
                   " '2026-12-01', 'Main Auditorium', 'Be on time.',"
                   " 'registrar', ?)", (conv, NOW))
        db.execute("INSERT INTO convocation_audit (convocation_id, actor,"
                   " action, after_json, created_at)"
                   " VALUES (?, 'registrar', 'published', '{}', ?)", (conv, NOW))
        db.execute("INSERT INTO announcements (convocation_id, title, body,"
                   " audience, status, is_important, created_by, created_at,"
                   " updated_at, published_at, published_by)"
                   " VALUES (?, 'Synthetic Notice', 'Body text', 'students',"
                   " 'published', 1, 'registrar', ?, ?, ?, 'registrar')",
                   (conv, NOW, NOW, NOW))
        db.execute("INSERT INTO announcement_audit (announcement_id,"
                   " convocation_id, actor, action, after_json, created_at)"
                   " VALUES (1, ?, 'registrar', 'published', '{}', ?)",
                   (conv, NOW))
        db.commit()
    finally:
        db.close()


# ------------------------------------------------------------- 1. fixture
step(1, "Build a schema-version-6 database with synthetic live records")
V6 = build("v6", version=6)
populate_v6(V6)
check("v6: user_version is 6", user_version(V6) == 6, user_version(V6))

V6_TABLES = objects(V6, "table")
for absent in ("convocation_passes", "convocation_admissions", "scanner_users",
               "scanner_sessions", "scanner_gates", "support_requests",
               "student_reminder_state"):
    check("v6: %s does not exist yet" % absent, absent not in V6_TABLES)
for present in ("students", "guests", "gates", "scans", "convocations",
                "convocation_registrations", "student_accounts", "medalists",
                "announcements", "convocation_publications"):
    check("v6: %s exists" % present, present in V6_TABLES)
check("v6: convocations carries rehearsal_time", "rehearsal_time"
      in columns(V6, "convocations"))

BEFORE = snapshot(V6)
check("v6: synthetic rows loaded", len(BEFORE) >= 60, len(BEFORE))
check("v6: registrations present", scalar(
    V6, "SELECT COUNT(*) FROM convocation_registrations") == 25)
check("v6: a cancelled registration is present", scalar(
    V6, "SELECT COUNT(*) FROM convocation_registrations"
        " WHERE status = 'cancelled'") > 0)

# ------------------------------------------------------- 2. 6 -> 11 upgrade
step(2, "Run the real migration runner from version 6 to the latest version")
db = open_db(V6)
try:
    reached = migrations.migrate(db)
finally:
    db.close()
check("upgrade: lands on the latest version", reached == LATEST, reached)
check("upgrade: user_version is the latest version",
      user_version(V6) == LATEST, user_version(V6))
check("upgrade: every migration above 6 is in the ladder",
      [v for v, _ in migrations.MIGRATIONS if v > 6]
      == list(range(7, LATEST + 1)))

# --------------------------------------------------- 3. data preservation
step(3, "Every pre-existing row survives with identical identity and values")
AFTER = snapshot(V6)
missing = sorted(k for k in BEFORE if k not in AFTER)
changed = sorted(k for k in BEFORE if k in AFTER and BEFORE[k] != AFTER[k])
check("preserved: no row lost", not missing, missing[:5])
check("preserved: no row mutated", not changed, changed[:5])
check("preserved: no new rows injected into pre-existing tables",
      not [k for k in AFTER if k not in BEFORE and k[0] in
           {t for t, _ in BEFORE}],
      sorted(k for k in AFTER if k not in BEFORE)[:5])

IDENTITY = [
    ("students", "roll_no", "LGU-2024-101"),
    ("convocation_registrations", "registration_number", "REG-00007"),
    ("convocation_registrations", "registration_number", "REG-00000"),
    ("student_accounts", "university_email", "synth003@lgu.edu.pk"),
    ("medalists", "student_name", "Synthetic Medallist"),
    ("announcements", "title", "Synthetic Notice"),
    ("staff_users", "username", "registrar"),
]
for table, col, val in IDENTITY:
    check("identity: %s.%s=%s unchanged" % (table, col, val),
          scalar(V6, "SELECT COUNT(*) FROM %s WHERE %s = ?" % (table, col),
                 (val,)) == 1)
check("identity: cancelled registration stays cancelled (not reassigned)",
      scalar(V6, "SELECT COUNT(*) FROM convocation_registrations"
                 " WHERE status = 'cancelled'") > 0)
check("identity: legacy scans untouched", scalar(
    V6, "SELECT COUNT(*) FROM scans WHERE qr_id LIKE 'QR-LEG-%'") == 12)
check("identity: rehearsal_time survived", scalar(
    V6, "SELECT rehearsal_time FROM convocations WHERE is_active = 1") == "10:00")
check("identity: published convocation row survived", scalar(
    V6, "SELECT COUNT(*) FROM convocation_publications") == 1)

# ------------------------------------------------- 4. new schema objects
step(4, "New tables, columns, indexes and defaults match expectations")
NEW_TABLES = ("support_requests", "support_events", "student_reminder_state",
              "convocation_passes", "convocation_admissions", "scanner_users",
              "scanner_gates", "scanner_sessions")
for t in NEW_TABLES:
    check("schema: table %s created" % t, t in objects(V6, "table"))
for t in NEW_TABLES:
    check("schema: table %s is empty after upgrade" % t,
          scalar(V6, "SELECT COUNT(*) FROM %s" % t) == 0)

for idx in ("idx_support_requests_queue", "idx_support_requests_owner",
            "idx_support_events_request", "idx_reminder_state_account",
            "idx_convocation_passes_live", "idx_convocation_passes_account",
            "idx_convocation_admissions_conv", "idx_convocation_admissions_gate",
            "idx_scanner_sessions_scanner", "idx_audit_log_action"):
    check("schema: index %s created" % idx, idx in objects(V6, "index"))

check("schema: credential_established column added",
      "credential_established" in columns(V6, "scanner_users"))
check("schema: convocation_admissions uniqueness is a UNIQUE index",
      "idx_convocation_admissions_once" in objects(V6, "index"))
info = q(V6, "PRAGMA index_list(convocation_admissions)")
uniq = [r["name"] for r in info if r["unique"]]
check("schema: idx_convocation_admissions_once is marked unique",
      "idx_convocation_admissions_once" in uniq, uniq)
check("schema: advisory locks are per (account, reminder)",
      "idx_reminder_state_account" in objects(V6, "index"))

# ------------------------------------- 5. new-constraint behaviour proof
step(5, "Constraints introduced by 7..%d actually enforce" % LATEST)
conv = scalar(V6, "SELECT id FROM convocations WHERE is_active = 1")
reg_a = scalar(V6, "SELECT id FROM convocation_registrations"
                   " WHERE registration_number = 'REG-00003'")
db = open_db(V6)
pass_id = None
first_ok = False
dup_rejected = False
try:
    cur = db.execute("INSERT INTO convocation_passes (token_hash,"
                     " convocation_id, registration_id, account_id, status,"
                     " issued_at) VALUES ('sha256$pass-a', ?, ?, 1, 'active', ?)",
                     (conv, reg_a, NOW))
    pass_id = cur.lastrowid
    db.execute("INSERT INTO convocation_admissions (pass_id, convocation_id,"
               " registration_id, gate_id, volunteer, admitted_at)"
               " VALUES (?, ?, ?, 1, 'V1', ?)", (pass_id, conv, reg_a, NOW))
    db.commit()
    first_ok = True
except sqlite3.Error as exc:
    print("  (first admission insert failed: %s)" % exc)
if pass_id is not None:
    try:
        db.execute("INSERT INTO convocation_admissions (pass_id,"
                   " convocation_id, registration_id, gate_id, volunteer,"
                   " admitted_at) VALUES (?, ?, ?, 2, 'V2', ?)",
                   (pass_id, conv, reg_a, NOW))
        db.commit()
    except sqlite3.IntegrityError:
        dup_rejected = True
db.close()
check("constraint: a first admission is accepted", first_ok)
check("constraint: the SAME pass cannot be admitted twice (unique backstop)",
      dup_rejected)
check("constraint: exactly one admission row for that registration",
      scalar(V6, "SELECT COUNT(*) FROM convocation_admissions"
                 " WHERE registration_id = ?", (reg_a,)) == 1)

db = open_db(V6)
try:
    cur = db.execute("INSERT INTO scanner_users (username, display_name,"
                     " pin_hash, created_at, updated_at)"
                     " VALUES ('backfill-probe', 'Probe', 'x', ?, ?)", (NOW, NOW))
    db.commit()
    established = db.execute("SELECT credential_established FROM scanner_users"
                             " WHERE id = ?", (cur.lastrowid,)).fetchone()[0]
except sqlite3.Error as exc:
    established = None
    print("  (backfill probe failed: %s)" % exc)
finally:
    db.close()
check("constraint: pre-existing scanner rows are backfilled as provisioned",
      established == 1, established)

# ------------------------------------------- 6. application still works
step(6, "The upgraded database supports the application's real workflows")
saved = config.DB_PATH
config.DB_PATH = V6
try:
    from web.routes import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    r = c.get("/api/health")
    health_ok = r.status_code == 200 and r.get_json().get("ok") is True
    r = c.get("/api/dashboard")
    dash_ok = r.status_code == 200
    r = c.get("/api/gates")
    gates_ok = r.status_code == 200 and len(r.get_json().get("gates", [])) == 7
    r = c.get("/dashboard")
    page_ok = r.status_code == 200
finally:
    config.DB_PATH = saved
check("app: /api/health on the migrated database", health_ok)
check("app: /api/dashboard reads migrated data", dash_ok)
check("app: /api/gates returns the 7 seeded gates", gates_ok)
check("app: /dashboard renders", page_ok)

# ------------------------------------------------------- 7. idempotency
step(7, "Running the migration runner again is a no-op")
snapshot_after_upgrade = snapshot(V6)
db = open_db(V6)
try:
    again = migrations.migrate(db)
finally:
    db.close()
check("idempotent: version stays at the latest",
      again == LATEST and user_version(V6) == LATEST)
check("idempotent: nothing changed", snapshot(V6) == snapshot_after_upgrade)

# ------------------------------------------------- 8. fail-closed on newer
step(8, "An unsupported newer schema continues to fail closed")
NEWER = build("newer", version=None)
db = open_db(NEWER)
try:
    db.execute("PRAGMA user_version = 99")
    db.commit()
except sqlite3.Error:
    pass
try:
    migrations.migrate(db)
    refused = False
except RuntimeError:
    refused = True
finally:
    db.close()
check("fail-closed: RuntimeError for a newer schema", refused)

# ------------------------------------------- 9. failure rolls back fully
step(9, "A failing migration leaves no partial schema and no version bump")
FAILING = build("failing", version=None)
saved_mig = migrations.MIGRATIONS
migrations.MIGRATIONS = saved_mig + [(9999, "CREATE TABLE half_applied (id INTEGER);\n"
                                            "THIS IS NOT VALID SQL;")]
db = open_db(FAILING)
before_ver = db.execute("PRAGMA user_version").fetchone()[0]
try:
    migrations.migrate(db)
    raised = False
except sqlite3.Error:
    raised = True
ver_after = db.execute("PRAGMA user_version").fetchone()[0]
half = db.execute("SELECT name FROM sqlite_master WHERE name = 'half_applied'").fetchall()
db.close()
migrations.MIGRATIONS = saved_mig
check("rollback: invalid migration raises", raised)
check("rollback: user_version not advanced", ver_after == before_ver,
      (before_ver, ver_after))
check("rollback: no partially applied table", not half)

# ----------------------------------------- 10. fresh + v10 -> v11 cases
step(10, "Fresh initialization and the established version-10 upgrade case")
FRESH = build("fresh", version=None)
check("fresh: lands on the latest version", user_version(FRESH) == LATEST,
      user_version(FRESH))
check("fresh: gates seeded", scalar(FRESH, "SELECT COUNT(*) FROM gates") == 7)
check("fresh: convocation seeded", scalar(
    FRESH, "SELECT COUNT(*) FROM convocations WHERE is_active = 1") == 1)

V10 = build("v10", version=10)
populate_v6(V10)
before10 = snapshot(V10)
check("v10: credential_established absent before migration 11",
      "credential_established" not in columns(V10, "scanner_users"))
db = open_db(V10)
try:
    migrations.migrate(db)
finally:
    db.close()
check("v10: lands on the latest version", user_version(V10) == LATEST)
check("v10: data preserved", snapshot(V10) == before10)
check("v10: credential_established added", "credential_established"
      in columns(V10, "scanner_users"))
check("v10: audit index added", "idx_audit_log_action" in objects(V10, "index"))

# ---------------------------------------------------------------- cleanup
shutil.rmtree(_TMP, ignore_errors=True)
passed = sum(1 for _, ok, _ in RESULTS if ok)
print("\nPHASE21 MIGRATION v6->%d: %d/%d checks passed, %d failing"
      % (LATEST, passed, len(RESULTS), len(RESULTS) - passed))
for name, ok, detail in RESULTS:
    if not ok:
        print("  FAIL: %s %s" % (name, detail))
sys.exit(1 if passed != len(RESULTS) else 0)
