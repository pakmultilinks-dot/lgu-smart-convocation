"""Demo people are never inserted into a fresh production database.

This regression suite only uses random disposable SQLite paths. The production
file app/lgu.db is not opened, inspected, initialized, or modified.
"""

import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import config  # noqa: E402
import database  # noqa: E402


class SeedProductionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lgu-seed-safety-")
        self.old_db = config.DB_PATH
        config.DB_PATH = str(Path(self.tmp.name) / "synthetic.sqlite3")
        database.init_db()

    def tearDown(self):
        config.DB_PATH = self.old_db
        self.tmp.cleanup()

    def counts(self):
        with sqlite3.connect(config.DB_PATH) as db:
            return {
                name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                for name in ("gates", "settings", "convocations", "students", "guests")
            }

    def seed_with(self, *, environment=None, testing=None, opt_in=None):
        overrides = {}
        for key, val in (
            ("LGU_APP_ENV", environment),
            ("LGU_TESTING", testing),
            ("LGU_ALLOW_DEMO_SECRETS", opt_in),
        ):
            if val is not None:
                overrides[key] = val
        with patch.dict(
            os.environ,
            {
                "LGU_APP_ENV": "",
                "LGU_TESTING": "",
                "LGU_ALLOW_DEMO_SECRETS": "",
                **overrides,
            },
        ):
            return database.seed()

    def test_production_bootstrap_adds_gates_but_no_demo_people(self):
        self.seed_with(environment="production")
        counts = self.counts()
        self.assertEqual(counts["gates"], len(database.GATE_LABELS))
        self.assertGreaterEqual(counts["settings"], 1)
        self.assertEqual(counts["convocations"], 1)
        self.assertEqual(counts["students"], 0)
        self.assertEqual(counts["guests"], 0)

    def test_production_environment_overrides_unsafe_demo_optins(self):
        self.seed_with(
            environment="production", testing="1", opt_in="1"
        )
        counts = self.counts()
        self.assertEqual(counts["students"], 0)
        self.assertEqual(counts["guests"], 0)

    def test_no_optin_defaults_to_no_demo_records(self):
        self.seed_with()
        self.assertEqual(self.counts()["students"], 0)
        self.assertEqual(self.counts()["guests"], 0)

    def test_explicit_private_demo_optin_still_seeds_sample_people(self):
        self.seed_with(environment="development", opt_in="1")
        counts = self.counts()
        self.assertEqual(counts["students"], len(database.SEED_STUDENTS))
        self.assertEqual(counts["guests"], len(database.SEED_GUESTS))
        self.seed_with(environment="development", opt_in="1")
        self.assertEqual(self.counts(), counts)

    def test_test_mode_still_seeds_synthetic_fixture_people(self):
        self.seed_with(environment="test", testing="1")
        self.assertEqual(self.counts()["students"], len(database.SEED_STUDENTS))
        self.assertEqual(self.counts()["guests"], len(database.SEED_GUESTS))

    def test_protected_default_database_never_receives_demo_people(self):
        # The active SQLite remains the disposable one; the protection
        # predicate is overridden, not the DB path or production DB itself.
        with patch.object(config, "is_production_db", return_value=True):
            self.seed_with(environment="test", testing="1", opt_in="1")
        self.assertEqual(self.counts()["students"], 0)
        self.assertEqual(self.counts()["guests"], 0)

    def test_existing_records_survive_production_bootstrap(self):
        with sqlite3.connect(config.DB_PATH) as db:
            db.execute(
                "INSERT INTO students "
                "(roll_no,name,gender,program,qr_id,created_at) "
                "VALUES (?,?,?,?,?,?)",
                ("QA-EXISTING", "Existing synthetic student", "Male", "BSCS",
                 "QA-VALID-ID", "2026-01-01"),
            )
            db.commit()
        self.seed_with(environment="production")
        with sqlite3.connect(config.DB_PATH) as db:
            row = db.execute(
                "SELECT name FROM students WHERE roll_no = 'QA-EXISTING'"
            ).fetchone()
            self.assertEqual(row[0], "Existing synthetic student")
            self.assertEqual(db.execute(
                "SELECT count(*) FROM students"
            ).fetchone()[0], 1)
        self.assertEqual(self.counts()["guests"], 0)

    def test_repeat_production_startup_preserves_empty_demo_tables(self):
        self.seed_with(environment="production")
        self.seed_with(environment="production")
        self.assertEqual(self.counts()["students"], 0)
        self.assertEqual(self.counts()["guests"], 0)
        self.assertEqual(self.counts()["gates"], len(database.GATE_LABELS))


if __name__ == "__main__":
    unittest.main()
