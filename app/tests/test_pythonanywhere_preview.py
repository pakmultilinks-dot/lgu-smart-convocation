"""PythonAnywhere staging: real route auth on isolated temp synthetic DB."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
APP_DIR = REPO / "app"
CREATE = APP_DIR / "scripts" / "create_preview_demo.py"


class PythonAnywherePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lgu-pa-demo-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.private = self.home / "lgu-preview-private"
        self.env = os.environ.copy()
        self.env["HOME"] = str(self.home)
        # Path.home() reads USERPROFILE on Windows and HOME on the Linux host.
        self.env["USERPROFILE"] = str(self.home)
        self.env["LGU_APP_ENV"] = "development"
        self.env.pop("LGU_DB_PATH", None)
        self.env.pop("LGU_TESTING", None)

    def test_preview_wsgi_refuses_missing_database(self):
        code = "import sys; sys.path.insert(0, sys.argv[1]); import scripts.pythonanywhere_preview_wsgi"
        res = subprocess.run(
            [sys.executable, "-c", code, str(APP_DIR)],
            env=self.env, capture_output=True, text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not provisioned", res.stderr)
        self.assertFalse(self.private.exists())

    def test_preview_wsgi_authenticates_three_roles_without_real_students(self):
        result = subprocess.run(
            [sys.executable, str(CREATE), "--output-dir", str(self.private)],
            env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        creds = {}
        for line in (self.private / "TEST-LOGIN-DETAILS.txt").read_text(
            encoding="utf-8"
        ).splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                creds[key] = value
        # Inject only synthetic generated credentials over stdin. Never expose
        # the PIN, password, or signing secrets in test logs.
        code = """
import sys, json
sys.path.insert(0, sys.argv[1])
from scripts.pythonanywhere_preview_wsgi import application
client = application.test_client()
v = json.load(sys.stdin)
health = client.get("/api/health")
assert health.status_code == 200
h = health.get_json()
assert h.get("ok") is True and h.get("app") == "LGU Smart Convocation"
student = client.post("/api/student/login", json={
  "email":v["Student email"], "password":v["Student password"]})
scanner = client.post("/api/scanner/login", json={
  "username":v["Scanner username"], "pin":v["Scanner PIN"]})
admin = client.post("/api/admin/verify", json={"pin":v["Admin PIN"]})
assert student.status_code == 200 and student.get_json().get("token")
assert scanner.status_code == 200 and scanner.get_json().get("token")
assert admin.status_code == 200 and admin.get_json().get("ok") is True
print("PASS: HTTPS-ready synthetic WSGI and three authenticated roles")
"""
        import json
        res = subprocess.run(
            [sys.executable, "-c", code, str(APP_DIR)],
            env=self.env, input=json.dumps(creds), capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("PASS: HTTPS-ready synthetic WSGI", res.stdout)

    def test_symlinked_preview_db_is_refused(self):
        result = subprocess.run(
            [sys.executable, str(CREATE), "--output-dir", str(self.private)],
            env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        db = self.private / "lgu-preview.sqlite3"
        target = self.private / "original-disposable.sqlite3"
        db.rename(target)
        try:
            db.symlink_to(target)
        except OSError:
            self.skipTest("Symlinks unavailable on this test host")
        code = "import sys;sys.path.insert(0,sys.argv[1]);import scripts.pythonanywhere_preview_wsgi"
        r = subprocess.run(
            [sys.executable, "-c", code, str(APP_DIR)],
            env=self.env, capture_output=True, text=True,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("symlinked", r.stderr)


if __name__ == "__main__":
    unittest.main()
