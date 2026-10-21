"""Restore safeguards for custom configured SQLite paths.

Only synthetic, disposable files are involved. Validation is mocked so
these tests cannot read or restore a real production database.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backup  # noqa: E402
import config  # noqa: E402


class RestoreTargetSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lgu-restore-safety-")
        self.directory = Path(self.tmp.name)
        self.configured = self.directory / "cloud-volume" / "live.sqlite3"
        self.configured.parent.mkdir(parents=True)
        self.configured.write_bytes(b"DO-NOT-OVERWRITE-SYNTHETIC-LIVE")
        self.backup_file = self.directory / "sample.bak"
        self.backup_file.write_bytes(b"VALIDATED-SYNTHETIC-BACKUP")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def fake_manifest(filename):
        return {
            "path": str(filename),
            "sha256": "simulated-validated-snapshot",
            "size": 25,
            "tables": [],
            "row_counts": {},
        }

    def test_refuses_current_configured_database_even_on_custom_path(self):
        original = self.configured.read_bytes()
        with (
            patch.object(config, "DB_PATH", str(self.configured)),
            patch.object(backup, "validate", side_effect=self.fake_manifest) as validate,
        ):
            with self.assertRaisesRegex(ValueError, "refus"):
                backup.restore(str(self.backup_file), str(self.configured))
            validate.assert_not_called()
        self.assertEqual(self.configured.read_bytes(), original)

    def test_refuses_symlink_alias_of_configured_database(self):
        alias = self.directory / "db-alias.sqlite3"
        try:
            alias.symlink_to(self.configured)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links unavailable on this platform")
        original = self.configured.read_bytes()
        with (
            patch.object(config, "DB_PATH", str(self.configured)),
            patch.object(backup, "validate", side_effect=self.fake_manifest),
        ):
            with self.assertRaisesRegex(ValueError, "refus"):
                backup.restore(str(self.backup_file), str(alias))
        self.assertEqual(self.configured.read_bytes(), original)

    def test_refuses_protected_destination_even_if_file_is_not_created_yet(self):
        future = self.directory / "new-live.sqlite3"
        self.assertFalse(future.exists())
        with (
            patch.object(config, "DB_PATH", str(future)),
            patch.object(backup, "validate", side_effect=self.fake_manifest),
        ):
            with self.assertRaisesRegex(ValueError, "refus"):
                backup.restore(str(self.backup_file), str(future))
        self.assertFalse(future.exists())

    def test_restore_to_separate_disposable_path_remains_available(self):
        dest = self.directory / "rehearsal-copy.sqlite3"
        original = self.configured.read_bytes()
        with (
            patch.object(config, "DB_PATH", str(self.configured)),
            patch.object(backup, "validate", side_effect=self.fake_manifest),
        ):
            result = backup.restore(str(self.backup_file), str(dest))
        self.assertEqual(dest.read_bytes(), self.backup_file.read_bytes())
        self.assertEqual(self.configured.read_bytes(), original)
        self.assertTrue(result["matched_source"])

    def test_original_default_production_path_is_still_blocked(self):
        # Do not access the actual default database; this must fail before
        # validation, file creation, or copying.
        with (
            patch.object(config, "DB_PATH", str(self.configured)),
            patch.object(backup, "validate") as validate,
        ):
            with self.assertRaises(ValueError):
                backup.restore(
                    str(self.backup_file), str(config.PRODUCTION_DB_PATH)
                )
            validate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
