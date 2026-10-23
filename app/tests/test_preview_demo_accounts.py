"""Check synthetic three-role demo provisioning without real student data."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from werkzeug.security import check_password_hash

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "app" / "scripts" / "create_preview_demo.py"


class PreviewDemoProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lgu-synthetic-preview-")
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / "new-preview"
        self.env = dict(os.environ)
        self.env["LGU_APP_ENV"] = "development"
        self.env["LGU_TESTING"] = ""
        self.env.pop("LGU_DB_PATH", None)

    def run_script(self, path=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--output-dir", str(path or self.dir)],
            env=self.env, text=True, capture_output=True,
        )

    def test_new_database_has_all_three_accounts_and_hashed_passwords(self):
        created = self.run_script()
        self.assertEqual(created.returncode, 0, created.stderr)
        db_path = self.dir / "lgu-preview.sqlite3"
        self.assertTrue(db_path.is_file())
        creds = (self.dir / "TEST-LOGIN-DETAILS.txt").read_text("utf-8")
        env = (self.dir / "PRIVATE-BACKEND-ENV.txt").read_text("utf-8")
        self.assertIn("Student email: preview.student@example.invalid", creds)
        self.assertIn("Scanner username: preview-scanner", creds)
        self.assertIn("Admin PIN:", creds)
        self.assertIn("LGU_APP_ENV=production", env)
        student_pw = creds.split("Student password: ", 1)[1].splitlines()[0]
        scanner_pin = creds.split("Scanner PIN: ", 1)[1].splitlines()[0]
        with sqlite3.connect(db_path) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, 14)
            student_hash = db.execute(
                "SELECT password_hash FROM student_accounts "
                "WHERE university_email = ?", ("preview.student@example.invalid",)
            ).fetchone()[0]
            scanner_hash = db.execute(
                "SELECT pin_hash FROM scanner_users WHERE username = ?",
                ("preview-scanner",)
            ).fetchone()[0]
            self.assertTrue(check_password_hash(student_hash, student_pw))
            self.assertTrue(check_password_hash(scanner_hash, scanner_pin))
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM registration_claims").fetchone()[0], 1)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM scanner_gates").fetchone()[0], 1)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM students").fetchone()[0], 0)
        self.assertNotIn(student_pw, env)
        self.assertNotIn(scanner_pin, env)

    def test_refuses_existing_output_without_changes(self):
        self.dir.mkdir()
        sentinel = self.dir / "do-not-delete.txt"
        sentinel.write_text("keep me", encoding="utf-8")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text("utf-8"), "keep me")
        self.assertFalse((self.dir / "lgu-preview.sqlite3").exists())

    def test_refuses_production_environment(self):
        self.env["LGU_APP_ENV"] = "production"
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.dir.exists())

    def test_no_files_created_inside_repository(self):
        result = self.run_script(ROOT / "private-preview-output")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((ROOT / "private-preview-output").exists())


if __name__ == "__main__":
    unittest.main()
