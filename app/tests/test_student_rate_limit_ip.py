"""Regression: one student must not rate-limit unrelated student IPs.

Pure request-context unit tests: no application startup, no SQLite connection,
no student records, and no production database access.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web import student_routes as student  # noqa: E402

app = Flask(__name__)


class StudentRateLimitIPTests(unittest.TestCase):
    def setUp(self):
        self.original = {key: list(values) for key, values in student._HITS.items()}
        for values in student._HITS.values():
            values.clear()

    def tearDown(self):
        student._HITS.clear()
        student._HITS.update(self.original)

    def hit(self, ip, bucket="login", limit=2, forwarded=None):
        headers = {"X-Forwarded-For": forwarded} if forwarded else {}
        with app.test_request_context(
            "/api/student/login", environ_base={"REMOTE_ADDR": ip}, headers=headers
        ):
            return student._limited(bucket, limit)

    def test_client_a_cannot_exhaust_client_b_login_quota(self):
        self.assertFalse(self.hit("192.0.2.11"))
        self.assertFalse(self.hit("192.0.2.11"))
        self.assertTrue(self.hit("192.0.2.11"))
        self.assertFalse(self.hit("198.51.100.22"))
        self.assertFalse(self.hit("198.51.100.22"))
        self.assertTrue(self.hit("198.51.100.22"))

    def test_independent_ips_across_student_operations(self):
        for bucket in ("send", "recovery", "confirm", "support", "readiness", "passissue"):
            for values in student._HITS.values():
                values.clear()
            self.assertFalse(self.hit("192.0.2.11", bucket, 1))
            self.assertTrue(self.hit("192.0.2.11", bucket, 1))
            self.assertFalse(self.hit("198.51.100.22", bucket, 1))

    def test_bucket_isolation_same_client(self):
        self.assertFalse(self.hit("192.0.2.11", "login", 1))
        self.assertTrue(self.hit("192.0.2.11", "login", 1))
        self.assertFalse(self.hit("192.0.2.11", "recovery", 1))

    def test_forwarded_header_cannot_impersonate_another_ip(self):
        self.assertFalse(self.hit("192.0.2.11", limit=1, forwarded="198.51.100.22"))
        self.assertTrue(self.hit("192.0.2.11", limit=1, forwarded="203.0.113.33"))
        self.assertFalse(self.hit("198.51.100.22", limit=1, forwarded="192.0.2.11"))

    def test_expired_entries_reclaim_quota(self):
        with patch.object(student.time, "time", return_value=1000):
            self.assertFalse(self.hit("192.0.2.11", limit=1))
            self.assertTrue(self.hit("192.0.2.11", limit=1))
        with patch.object(student.time, "time", return_value=1000 + student._bucket_window("login") + 1):
            self.assertFalse(self.hit("192.0.2.11", limit=1))


if __name__ == "__main__":
    unittest.main()
