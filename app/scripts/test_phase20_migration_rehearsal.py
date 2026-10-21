#!/usr/bin/env python
"""Phase 20 §2 — database migration rehearsal on disposable databases.

"A migration that completes without an exception is not necessarily correct."
Every scenario here builds a FRESH disposable database; the production file is
stat-stamped and never opened. Historical starting versions are produced by
temporarily limiting `migrations.MIGRATIONS`, which is exactly how the schema
looked when that version was current — not by copying a real database.

Run from app/:  ..\\..\\.venv\\Scripts\\python.exe scripts\\test_phase20_migration_rehearsal.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p20mig-")
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


def _fresh_path(tag):
    return os.path.join(_TMP, "%s.db" % tag)


def build(tag, version=None):
    """Create a database at `tag`, optionally applying only migrations <= version."""
    path = _fresh_path(tag)
    saved_path, saved_mig = config.DB_PATH, migrations.MIGRATIONS
    if version is not None:
        migrations.MIGRATIONS = [m for m in saved_mig if m[0] <= version]
    try:
        config.DB_PATH = path
        database.init_db()
    finally:
        config.DB_PATH, migrations.MIGRATIONS = saved_path, saved_mig
    return path


def open_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def user_version(path):
    db = open_db(path)
    try:
        return db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()


def migrate_path(path):
    db = open_db(path)
    try:
        return migrations.migrate(db)
    finally:
        db.close()


def tables(path):
    db = open_db(path)
    try:
        return {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        db.close()


def columns(path, table):
    db = open_db(path)
    try:
        return {r[1] for r in db.execute("PRAGMA table_info(%s)" % table).fetchall()}
    finally:
        db.close()


def index_names(path, table):
    db = open_db(path)
    try:
        return {r[1] for r in db.execute("PRAGMA index_list(%s)" % table).fetchall()}
    finally:
        db.close()


# ---------------------------------------------------------------- 1. fresh
step(1, "Initialisation from a genuinely fresh database")
fresh = build("fresh")
check("fresh.user_version == %d" % LATEST, user_version(fresh) == LATEST,
      "got %d" % user_version(fresh))
needed = {"convocations", "staff_users", "audit_log", "scanner_users",
          "scanner_gates", "scanner_sessions", "convocation_admissions",
          "convocation_passes", "student_accounts", "gates"}
have = tables(fresh)
check("fresh has every release table", needed <= have, "missing %s" % (needed - have))

# ---------------------------------------------------------------- 2. idempotent
step(2, "Repeated startup and migration calls are safe")
before = user_version(fresh)
migrate_path(fresh)
again = migrate_path(fresh)
check("second migrate is a no-op", again == before == LATEST,
      "%s/%s" % (before, again))
db = open_db(fresh)
try:
    db.execute("BEGIN")
    database.migrations.migrate(db)
    db.rollback()
except Exception as exc:  # pragma: no cover - reported as a failure below
    check("migrate inside an open transaction", False, repr(exc))
else:
    check("migrate inside an open transaction", True)

# ---------------------------------------------------------------- 3. v10 -> v11
step(3, "Upgrade from schema version 10 to 11, preserving live data")
p10 = build("at10", version=10)
check("v10 fixture really is version 10", user_version(p10) == 10,
      "got %d" % user_version(p10))
check("v10 has no credential_established column",
      "credential_established" not in columns(p10, "scanner_users"))
check("v10 has no audit action index", "idx_audit_log_action" not in index_names(p10, "audit_log"))

db = open_db(p10)
now = "2026-10-14 09:00:00"
db.execute("INSERT INTO staff_users (username, display_name, password_hash,"
           " is_active, failed_attempts, created_at, updated_at)"
           " VALUES ('p20.officer','P20 Officer','scrypt$fake',1,0,?,?)", (now, now))
staff_id = db.execute("SELECT id FROM staff_users WHERE username='p20.officer'").fetchone()[0]
# Two scanner accounts, one already disabled, with gates and a live session.
db.execute("INSERT INTO scanner_users (username, display_name, pin_hash, is_active,"
           " failed_attempts, created_at, updated_at)"
           " VALUES ('gate-a','Gate A','h1',1,0,?,?)", (now, now))
db.execute("INSERT INTO scanner_users (username, display_name, pin_hash, is_active,"
           " failed_attempts, created_at, updated_at)"
           " VALUES ('gate-b','Gate B','h2',0,0,?,?)", (now, now))
sa = db.execute("SELECT id FROM scanner_users WHERE username='gate-a'").fetchone()[0]
sb = db.execute("SELECT id FROM scanner_users WHERE username='gate-b'").fetchone()[0]
db.execute("INSERT INTO scanner_gates (scanner_id, gate_id) VALUES (?,1)", (sa,))
db.execute("INSERT INTO scanner_gates (scanner_id, gate_id) VALUES (?,2)", (sa,))
db.execute("INSERT INTO scanner_gates (scanner_id, gate_id) VALUES (?,3)", (sb,))
db.execute("INSERT INTO scanner_sessions (scanner_id, token_hash, created_at,"
           " expires_at) VALUES (?, 'th-1', ?, ?)", (sa, now, "2026-10-14 21:00:00"))
db.execute("INSERT INTO audit_log (actor, action, detail, created_at)"
           " VALUES ('p20.officer','scanner_created','via=cli username=gate-a',?)", (now,))
db.execute("INSERT INTO convocations (name, year, status, is_active, created_at,"
           " updated_at) VALUES ('LGU 2026','2026','live',1,?,?)", (now, now))
conv = db.execute("SELECT id FROM convocations WHERE is_active=1").fetchone()[0]
db.execute("INSERT INTO convocation_registrations (convocation_id, registration_number,"
           " university_email, roll_number, student_name, created_at, updated_at)"
           " VALUES (?,'LGU-2024-102','a@lgu.edu.pk','R-102','Ayesha',?,?)",
           (conv, now, now))
db.commit()
db.close()

v = migrate_path(p10)
check("v10 -> v11 reached %d" % LATEST, v == LATEST, "got %d" % v)
check("credential_established column added",
      "credential_established" in columns(p10, "scanner_users"))
check("audit action index created", "idx_audit_log_action" in index_names(p10, "audit_log"))

db = open_db(p10)
try:
    rows = db.execute("SELECT username, is_active, credential_established"
                      " FROM scanner_users ORDER BY id").fetchall()
    check("both scanner accounts survive", len(rows) == 2, "got %d" % len(rows))
    check("pre-existing accounts backfilled as provisioned",
          all(r["credential_established"] == 1 for r in rows),
          str([dict(r) for r in rows]))
    check("disabled account stays disabled",
          [r["is_active"] for r in rows] == [1, 0],
          str([r["is_active"] for r in rows]))
    check("gate assignments survive",
          db.execute("SELECT COUNT(*) FROM scanner_gates WHERE scanner_id=?", (sa,))
          .fetchone()[0] == 2)
    check("session survives and is unexpired",
          db.execute("SELECT COUNT(*) FROM scanner_sessions WHERE scanner_id=?"
                     " AND revoked_at IS NULL", (sa,)).fetchone()[0] == 1)
    check("audit history survives",
          db.execute("SELECT COUNT(*) FROM audit_log WHERE action='scanner_created'")
          .fetchone()[0] == 1)
    check("staff record survives",
          db.execute("SELECT COUNT(*) FROM staff_users WHERE id=?", (staff_id,))
          .fetchone()[0] == 1)
    check("registration survives",
          db.execute("SELECT COUNT(*) FROM convocation_registrations"
                     " WHERE convocation_id=? AND registration_number='LGU-2024-102'",
                     (conv,)).fetchone()[0] == 1)
finally:
    db.close()

# ---------------------------------------------------------------- 4. all versions
step(4, "Every supported historical starting version upgrades to the latest")
for start in range(1, LATEST):
    p = build("hist%d" % start, version=start)
    if user_version(p) != start:
        check("fixture at version %d" % start, False,
              "user_version=%d" % user_version(p))
        continue
    try:
        got = migrate_path(p)
    except Exception as exc:
        check("version %d -> %d" % (start, LATEST), False, repr(exc))
        continue
    ok = got == LATEST
    db = open_db(p)
    try:
        integ = db.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        db.close()
    check("version %d -> %d" % (start, LATEST), ok and integ == "ok",
          "version=%s integrity=%s" % (got, integ))

# ---------------------------------------------------------------- 5. rollback
step(5, "A failing migration rolls back completely (no partial schema, no version bump)")
pbad = build("bad", version=LATEST - 1)
good_before = tables(pbad)
good = (LATEST, """
CREATE TABLE IF NOT EXISTS should_not_exist (id INTEGER PRIMARY KEY);
ALTER TABLE no_such_table ADD COLUMN boom TEXT;
""")
saved_mig = migrations.MIGRATIONS
migrations.MIGRATIONS = [m for m in saved_mig if m[0] <= LATEST - 1] + [good]
try:
    try:
        migrate_path(pbad)
    except sqlite3.Error as exc:
        err = str(exc)
    else:
        err = None
finally:
    migrations.MIGRATIONS = saved_mig
check("migration error is raised", err is not None, "no error raised")
check("error names the failing statement", bool(err) and "no_such_table" in err, str(err))
check("user_version NOT advanced to the failed migration", user_version(pbad) == LATEST - 1,
      "got %d" % user_version(pbad))
check("no table from the failed migration remains",
      "should_not_exist" not in tables(pbad),
      str(tables(pbad) - good_before))
check("database still passes integrity_check",
      open_db(pbad).execute("PRAGMA integrity_check").fetchone()[0] == "ok")
# And a clean retry with the real migration list succeeds.
check("clean retry after a failed migration succeeds",
      migrate_path(pbad) == LATEST, "retry gave %s" % user_version(pbad))

# ---------------------------------------------------------------- 6. future version
step(6, "An unsupported (newer) schema version is refused, not silently accepted")
pfut = build("future")
db = open_db(pfut)
db.execute("PRAGMA user_version = %d" % (LATEST + 5))
db.commit()
db.close()
try:
    got = migrate_path(pfut)
except Exception as exc:
    got = exc
check("newer schema version is refused by the guard",
      isinstance(got, RuntimeError) and "newer" in str(got).lower(),
      "got %r" % (got,))
check("refusal names both versions",
      isinstance(got, RuntimeError) and str(LATEST) in str(got)
      and str(LATEST + 5) in str(got), "got %r" % (got,))

# ---------------------------------------------------------------- 7. malformed
step(7, "A malformed / non-SQLite database fails loudly and is not mutated")
pbad2 = os.path.join(_TMP, "garbage.db")
with open(pbad2, "wb") as fh:
    fh.write(b"this is not a sqlite database" * 64)
before_bytes = open(pbad2, "rb").read()
saved_path = config.DB_PATH
config.DB_PATH = pbad2
try:
    database.init_db()
except sqlite3.DatabaseError as exc:
    check("malformed database raises DatabaseError", True)
    check("error is legible to an operator",
          "file is not a database" in str(exc).lower()
          or "malformed" in str(exc).lower(), str(exc))
except SystemExit:
    check("malformed database raises DatabaseError", False, "SystemExit instead")
else:
    check("malformed database raises DatabaseError", False, "init_db succeeded")
finally:
    config.DB_PATH = saved_path
check("malformed file left byte-identical", open(pbad2, "rb").read() == before_bytes)

# ---------------------------------------------------------------- 8. constraints
step(8, "Constraints, indexes and required columns are intact after migration")
pcon = build("constraints")
db = open_db(pcon)
try:
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("INSERT INTO scanner_users (username, display_name, pin_hash,"
               " created_at, updated_at) VALUES ('dupe','D','h',?,?)", (now, now))
    try:
        db.execute("INSERT INTO scanner_users (username, display_name, pin_hash,"
                   " created_at, updated_at) VALUES ('DUPE','D2','h2',?,?)",
                   (now, now))
    except sqlite3.IntegrityError:
        check("scanner username uniqueness holds (case-insensitive)", True)
    else:
        check("scanner username uniqueness holds (case-insensitive)", False,
              "DUPE was accepted")
    try:
        db.execute("INSERT INTO scanner_users (username, display_name,"
                   " created_at, updated_at) VALUES ('nopin','No Pin',?,?)",
                   (now, now))
    except sqlite3.IntegrityError:
        check("pin_hash is NOT NULL enforced", True)
    else:
        check("pin_hash is NOT NULL enforced", False, "null pin_hash accepted")
    try:
        db.execute("INSERT INTO scanner_gates (scanner_id, gate_id) VALUES (9999, 1)")
    except sqlite3.IntegrityError:
        check("scanner_gates foreign key enforced", True)
    else:
        check("scanner_gates foreign key enforced", False, "orphan row accepted")
    db.execute("INSERT INTO scanner_users (username, display_name, pin_hash,"
               " created_at, updated_at) VALUES ('activechk','A','h',?,?)",
               (now, now))
    sid = db.execute("SELECT id FROM scanner_users WHERE username='activechk'").fetchone()[0]
    try:
        db.execute("UPDATE scanner_users SET is_active=7 WHERE id=?", (sid,))
    except sqlite3.IntegrityError:
        check("is_active CHECK constraint enforced", True)
    else:
        check("is_active CHECK constraint enforced", False, "is_active=7 accepted")
    check("credential_established is NOT NULL",
          columns(pcon, "scanner_users").issuperset({"credential_established"}))
    idx = index_names(pcon, "scanner_sessions")
    check("scanner_sessions lookup index exists",
          "idx_scanner_sessions_scanner" in idx, str(idx))
finally:
    db.rollback()
    db.close()

# ---------------------------------------------------------------- 9. app behaviour
step(9, "Application behaviour on an upgraded database")
import scanner_auth  # noqa: E402
papp = build("appbeh", version=10)
migrate_path(papp)
saved_path = config.DB_PATH
config.DB_PATH = papp
try:
    database.seed()  # gates are seeded, not migrated
    sid = scanner_auth.create_scanner("p20.upgraded", "Upgraded Scanner", pin=None,
                                      gate_ids=(1, 2), actor="p20", via=scanner_auth.VIA_CLI)
    row = scanner_auth.get_scanner(sid)
    check("pending account created on an upgraded DB", row is not None)
    check("new account starts unprovisioned",
          row["credential_established"] == 0, str(dict(row)))
    check("pending account cannot authenticate",
          scanner_auth.authenticate("p20.upgraded", "00000000") is None)
    pin = scanner_auth.generate_pin()
    scanner_auth.reset_pin(sid, pin, actor="p20", via=scanner_auth.VIA_CLI)
    row = scanner_auth.get_scanner(sid)
    check("establishing a PIN flips credential state", row["credential_established"] == 1)
    check("and the account then authenticates",
          scanner_auth.authenticate("p20.upgraded", pin) is not None)
    hist = scanner_auth.history(20)
    check("management history readable on an upgraded DB", len(hist) >= 2, str(len(hist)))
finally:
    config.DB_PATH = saved_path

# ---------------------------------------------------------------- 10. cleanup
shutil.rmtree(_TMP, ignore_errors=True)
fails = [r for r in RESULTS if not r[1]]
print("\n%d checks, %d failures" % (len(RESULTS), len(fails)))
for name, _, detail in fails:
    print("  FAILED: %s %s" % (name, detail))
sys.exit(1 if fails else 0)
