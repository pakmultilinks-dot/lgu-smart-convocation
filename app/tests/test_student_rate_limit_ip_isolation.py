"""Regression: one student must not consume another student's API request budget.

Uses Flask's in-memory test client only. No database is initialized or opened.
"""
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
_TEMP = tempfile.TemporaryDirectory(prefix="lgu-rate-tests-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = str(Path(_TEMP.name) / "unused.sqlite3")

from flask import Flask
import config
from web import student_routes as student


class StudentRateLimitIsolation(unittest.TestCase):
    def setUp(self):
        for bucket in student._HITS:
            student._HITS[bucket].clear()
        self.app = Flask(__name__)
        self.app.register_blueprint(student.bp)
        self.client = self.app.test_client()

    def post(self, ip, headers=None):
        return self.client.post(
            "/api/student/login", json={},
            environ_overrides={"REMOTE_ADDR": ip},
            headers=headers or {},
        )

    def test_different_clients_have_independent_login_budgets(self):
        with patch.object(config, "STUDENT_RATE_MAX_LOGIN", 2):
            self.assertEqual(self.post("192.0.2.10").status_code, 400)
            self.assertEqual(self.post("192.0.2.10").status_code, 400)
            self.assertEqual(self.post("192.0.2.10").status_code, 429)
            self.assertEqual(self.post("198.51.100.20").status_code, 400)
            self.assertEqual(self.post("198.51.100.20").status_code, 400)
            self.assertEqual(self.post("198.51.100.20").status_code, 429)

    def test_forwarded_header_cannot_bypass_limit(self):
        with patch.object(config, "STUDENT_RATE_MAX_LOGIN", 1):
            self.assertEqual(self.post("192.0.2.10").status_code, 400)
            self.assertEqual(
                self.post("192.0.2.10", {"X-Forwarded-For": "198.51.100.20"}).status_code,
                429,
            )

    def test_independent_rate_limit_buckets(self):
        with self.app.test_request_context("/", environ_base={"REMOTE_ADDR": "192.0.2.10"}):
            self.assertFalse(student._limited("login", 1))
            self.assertTrue(student._limited("login", 1))
            self.assertFalse(student._limited("send", 1))

    def test_expired_client_window_reopens(self):
        with patch.object(config, "STUDENT_RATE_WINDOW_SECONDS", 60):
            with patch.object(student.time, "time", return_value=1000.0):
                self.assertEqual(self.post("192.0.2.10").status_code, 400)
            with patch.object(student.time, "time", return_value=1061.0):
                self.assertEqual(self.post("192.0.2.10").status_code, 400)


if __name__ == "__main__":
    unittest.main()
