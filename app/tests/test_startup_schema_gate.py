"""Production startup migration guard regressions: disposable SQLite only.

No production student database is opened or read. Tests create tiny temporary
SQLite files, and patch the run.py entrypoint before any write operation.
"""
import importlib
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
import migrations  # noqa: E402
import startup_schema  # noqa: E402


class ProductionStartupSchemaGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lgu-prod-schema-guard-")
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "synthetic.sqlite")
        self.current = migrations.MIGRATIONS[-1][0]

    def set_version(self, version):
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA user_version = %d" % version)

    def test_old_schema_is_rejected_without_writes(self):
        self.set_version(6)
        before = Path(self.path).read_bytes()
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "production"}),
            patch.object(config, "DB_PATH", self.path),
        ):
            with self.assertRaisesRegex(RuntimeError, "migration approval"):
                startup_schema.require_current_schema()
        self.assertEqual(Path(self.path).read_bytes(), before)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 6)

    def test_missing_production_db_is_not_created(self):
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "production"}),
            patch.object(config, "DB_PATH", self.path),
        ):
            with self.assertRaises(RuntimeError):
                startup_schema.require_current_schema()
        self.assertFalse(Path(self.path).exists())

    def test_current_schema_can_pass_read_only(self):
        self.set_version(self.current)
        before = Path(self.path).read_bytes()
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "production"}),
            patch.object(config, "DB_PATH", self.path),
        ):
            self.assertEqual(startup_schema.require_current_schema(), self.current)
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_dev_schema_bootstrap_remains_unchanged(self):
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "development"}),
            patch.object(config, "DB_PATH", self.path),
        ):
            self.assertIsNone(startup_schema.require_current_schema())
            database.init_db()
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                self.current,
            )

    def test_production_entrypoint_refuses_before_init_or_seed(self):
        self.set_version(6)
        before = Path(self.path).read_bytes()
        with (
            patch.dict(os.environ, {
                "LGU_APP_ENV": "production",
                "LGU_TESTING": "",
                "LGU_ALLOW_DEMO_SECRETS": "",
            }),
            patch.object(config, "DB_PATH", self.path),
            patch.object(config, "demo_secret_violation", return_value=None),
            patch.object(config, "demo_secrets", return_value=[]),
            patch.object(config, "assert_production_secrets"),
            patch.object(database, "init_db") as init_db,
            patch.object(database, "seed") as seed,
        ):
            sys.modules.pop("run", None)
            try:
                with self.assertRaisesRegex(RuntimeError, "migration approval"):
                    importlib.import_module("run")
                init_db.assert_not_called()
                seed.assert_not_called()
            finally:
                sys.modules.pop("run", None)
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_custom_db_without_environment_is_managed_and_unchanged(self):
        self.set_version(6)
        before = Path(self.path).read_bytes()
        with (
            patch.dict(os.environ, {
                "LGU_APP_ENV": "",
                "LGU_TESTING": "",
                "LGU_ALLOW_DEMO_SECRETS": "",
            }),
            patch.object(config, "DB_PATH", self.path),
        ):
            with self.assertRaisesRegex(RuntimeError, "migration approval"):
                startup_schema.require_current_schema()
            with self.assertRaisesRegex(RuntimeError, "migration approval"):
                database.init_db()
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_custom_db_without_environment_is_never_created(self):
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "", "LGU_TESTING": ""}),
            patch.object(config, "DB_PATH", self.path),
        ):
            with self.assertRaises(RuntimeError):
                database.init_db()
        self.assertFalse(Path(self.path).exists())

    def test_explicit_production_direct_init_refused_even_if_schema_current(self):
        self.set_version(self.current)
        before = Path(self.path).read_bytes()
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "production", "LGU_TESTING": ""}),
            patch.object(config, "DB_PATH", self.path),
        ):
            with self.assertRaisesRegex(RuntimeError, "migration approval"):
                database.init_db()
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_default_db_path_cannot_be_bootstrapped_even_as_development(self):
        # Rebind only the path constant to a disposable fixture. Nothing is
        # opened at the repository's actual app/lgu.db.
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "development", "LGU_TESTING": ""}),
            patch.object(config, "DB_PATH", self.path),
            patch.object(config, "PRODUCTION_DB_PATH", self.path),
        ):
            with self.assertRaises(RuntimeError):
                database.init_db()
        self.assertFalse(Path(self.path).exists())

    def test_current_schema_managed_startup_never_initializes_or_seeds(self):
        self.set_version(self.current)
        before = Path(self.path).read_bytes()
        with (
            patch.dict(os.environ, {
                "LGU_APP_ENV": "production",
                "LGU_TESTING": "",
                "LGU_ALLOW_DEMO_SECRETS": "",
            }),
            patch.object(config, "DB_PATH", self.path),
            patch.object(config, "demo_secret_violation", return_value=None),
            patch.object(config, "demo_secrets", return_value=[]),
            patch.object(config, "assert_production_secrets"),
            patch.object(database, "init_db") as init_db,
            patch.object(database, "seed") as seed,
        ):
            sys.modules.pop("run", None)
            try:
                imported = importlib.import_module("run")
                self.assertIsNotNone(imported.app)
                init_db.assert_not_called()
                seed.assert_not_called()
            finally:
                sys.modules.pop("run", None)
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_unmarked_custom_db_entrypoint_refuses_before_any_writes(self):
        self.set_version(6)
        original = Path(self.path).read_bytes()
        with (
            patch.dict(os.environ, {
                "LGU_APP_ENV": "",
                "LGU_TESTING": "",
                "LGU_ALLOW_DEMO_SECRETS": "",
            }),
            patch.object(config, "DB_PATH", self.path),
            patch.object(config, "demo_secret_violation", return_value=None),
            patch.object(config, "demo_secrets", return_value=[]),
            patch.object(config, "assert_production_secrets"),
            patch.object(database, "init_db") as init_db,
            patch.object(database, "seed") as seed,
        ):
            sys.modules.pop("run", None)
            try:
                with self.assertRaisesRegex(RuntimeError, "migration approval"):
                    importlib.import_module("run")
                init_db.assert_not_called()
                seed.assert_not_called()
            finally:
                sys.modules.pop("run", None)
        self.assertEqual(Path(self.path).read_bytes(), original)

    def test_operator_migration_rehearsal_uses_disposable_copy(self):
        # Build an actual synthetic v6 schema; PRAGMA-only empty DBs cannot
        # validate migration SQL that alters pre-existing legacy tables.
        legacy = [item for item in migrations.MIGRATIONS if item[0] <= 6]
        with (
            patch.object(config, "DB_PATH", self.path),
            patch.object(migrations, "MIGRATIONS", legacy),
            patch.dict(os.environ, {"LGU_APP_ENV": "development"}),
        ):
            database.init_db()
        original = Path(self.path).read_bytes()
        rehearsal = str(Path(self.tmp.name) / "rehearsal.sqlite")
        Path(rehearsal).write_bytes(original)
        with sqlite3.connect(rehearsal) as conn:
            migrations.migrate(conn)
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                self.current,
            )
        self.assertEqual(Path(self.path).read_bytes(), original)

    def test_runbook_matches_current_cli_schema_and_health(self):
        runbook = (APP_DIR.parent / "docs" / "RELEASE_CANDIDATE_RUNBOOK.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("v6→v%d" % self.current, runbook)
        self.assertIn("/api/health", runbook)
        self.assertNotIn("/healthz", runbook)
        self.assertNotIn("--label", runbook)
        self.assertNotIn("supports\n`11`", runbook)
        self.assertIn("backup_db.py verify", runbook)


if __name__ == "__main__":
    unittest.main()
