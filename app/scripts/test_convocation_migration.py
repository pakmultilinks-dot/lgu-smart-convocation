"""Phase 2 regression: migrations + convocation seed on disposable temp databases only.

Run:  python scripts/test_convocation_migration.py   (from app/)
"""

import os
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

TMP = tempfile.mkdtemp(prefix="lgu-p2-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "fresh.db")

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import migrations  # noqa: E402

failures = 0


def check(label, cond, detail=""):
    global failures
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def rows(path, sql, args=()):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    out = [dict(r) for r in c.execute(sql, args).fetchall()]
    c.close()
    return out


def boot(path):
    config.DB_PATH = path
    database.init_db()
    database.seed()


def convocation_rows(path):
    return rows(path, "SELECT * FROM convocations")


# 1. Fresh database
fresh = os.path.join(TMP, "fresh.db")
boot(fresh)
conv = convocation_rows(fresh)
check("fresh: exactly one convocation created", len(conv) == 1, len(conv))
check("fresh: convocation is active", conv and conv[0]["is_active"] == 1)
check("fresh: user_version is latest", rows(fresh, "PRAGMA user_version")[0]["user_version"] == len(migrations.MIGRATIONS))
check("fresh: legacy datetime stored only as expected_date",
      conv and conv[0]["expected_date"] == "2026-12-12T09:00:00+05:00"
      and conv[0]["confirmed_date"] is None and conv[0]["rehearsal_date"] is None)
check("fresh: convocation seeded with status planned", conv and conv[0]["status"] == "planned")
check("fresh: venue copied from legacy settings",
      conv and conv[0]["venue"] == "Lahore Garrison University, Lahore")

# 2. Repeated startup: no duplicate events, settings and gates stable
boot(fresh)
boot(fresh)
check("repeat: still exactly one convocation", len(convocation_rows(fresh)) == 1)
check("repeat: one active convocation", len([r for r in convocation_rows(fresh) if r["is_active"]]) == 1)
check("repeat: gates not duplicated", len(rows(fresh, "SELECT id FROM gates")) == 7)

# 3. Legacy-schema database (pre-migration, with customised settings)
legacy = os.path.join(TMP, "legacy.db")
c = sqlite3.connect(legacy)
c.executescript("""
CREATE TABLE students (id INTEGER PRIMARY KEY AUTOINCREMENT, roll_no TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL, gender TEXT NOT NULL, program TEXT NOT NULL, qr_id TEXT UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE guests (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT NOT NULL,
  host_roll_no TEXT NOT NULL, qr_id TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE gates (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, label TEXT NOT NULL);
CREATE TABLE scans (id INTEGER PRIMARY KEY AUTOINCREMENT, qr_id TEXT NOT NULL, person_type TEXT NOT NULL,
  person_name TEXT NOT NULL, gate_id INTEGER NOT NULL, mode TEXT NOT NULL, volunteer TEXT NOT NULL,
  scanned_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'online');
CREATE TABLE broadcasts (id INTEGER PRIMARY KEY AUTOINCREMENT, audience TEXT NOT NULL, message TEXT NOT NULL,
  sent_by TEXT NOT NULL, sent_at TEXT NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO settings VALUES ('convocation_name', 'Legacy Custom 2027', '2026-01-01');
INSERT INTO settings VALUES ('convocation_year', '2027', '2026-01-01');
INSERT INTO settings VALUES ('convocation_datetime', '2027-03-05T10:30:00+05:00', '2026-01-01');
INSERT INTO settings VALUES ('venue', 'Legacy Hall', '2026-01-01');
INSERT INTO settings VALUES ('expected_attendance', '640', '2026-01-01');
""")
c.commit()
c.close()
boot(legacy)
legacy_settings = {r["key"]: r["value"] for r in rows(legacy, "SELECT key, value FROM settings")}
check("legacy: custom settings preserved",
      legacy_settings.get("convocation_name") == "Legacy Custom 2027"
      and legacy_settings.get("expected_attendance") == "640"
      and legacy_settings.get("venue") == "Legacy Hall")
legacy_conv = convocation_rows(legacy)
check("legacy: one convocation seeded from settings", len(legacy_conv) == 1, len(legacy_conv))
check("legacy: seeded from legacy values",
      legacy_conv and legacy_conv[0]["name"] == "Legacy Custom 2027"
      and legacy_conv[0]["year"] == "2027" and legacy_conv[0]["venue"] == "Legacy Hall"
      and legacy_conv[0]["expected_date"] == "2027-03-05T10:30:00+05:00"
      and legacy_conv[0]["confirmed_date"] is None)
check("legacy: migration bumped user_version", rows(legacy, "PRAGMA user_version")[0]["user_version"] == len(migrations.MIGRATIONS))
boot(legacy)
check("legacy: second startup does not duplicate", len(convocation_rows(legacy)) == 1)

# 4. Active selection: the single-active index rejects a second active row
try:
    c = sqlite3.connect(legacy)
    c.execute("INSERT INTO convocations (name, year, is_active, created_at, updated_at) VALUES ('x','2028',1,'n','n')")
    c.commit()
    c.close()
    check("active: second active convocation rejected", False)
except sqlite3.IntegrityError:
    check("active: second active convocation rejected", True)

# 5. Migration runner is idempotent when re-applied
db = sqlite3.connect(legacy)
check("migrate: re-running is a no-op", migrations.migrate(db) == len(migrations.MIGRATIONS))
db.close()

print("\n%s" % ("PASS" if failures == 0 else "%d FAILURE(S)" % failures))
sys.exit(1 if failures else 0)
