"""Student rate-limit regression: one client's requests must not block another.

Only Flask request contexts and in-memory timestamps are used. No SQLite,
production accounts, HTTP server, or student data is accessed.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web import student_routes as routes  # noqa: E402


class StudentClientRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.original_hits = routes._HITS
        # Work with both the old (list) and fixed (per-IP dict) bucket shape,
        # so these tests demonstrate the original defect before the fix.
        routes._HITS = {key: type(value)()
                        for key, value in self.original_hits.items()}

    def tearDown(self):
        routes._HITS = self.original_hits

    def limited(self, ip, bucket="login", limit=2, headers=None):
        with self.app.test_request_context(
            "/api/student/login",
            environ_base={"REMOTE_ADDR": ip},
            headers=headers or {},
        ):
            with patch.object(routes.database, "get_db",
                              side_effect=AssertionError("No DB access allowed")):
                return routes._limited(bucket, limit)

    def test_one_client_cannot_exhaust_another_clients_login_budget(self):
        with patch.object(routes.time, "time", return_value=1000):
            self.assertFalse(self.limited("192.0.2.10"))
            self.assertFalse(self.limited("192.0.2.10"))
            self.assertTrue(self.limited("192.0.2.10"))
            self.assertFalse(self.limited("192.0.2.11"))
            self.assertFalse(self.limited("192.0.2.11"))
            self.assertTrue(self.limited("192.0.2.11"))

    def test_untrusted_forwarded_for_cannot_reset_a_clients_budget(self):
        with patch.object(routes.time, "time", return_value=1000):
            self.assertFalse(self.limited("192.0.2.10", limit=1,
                                          headers={"X-Forwarded-For": "1.1.1.1"}))
            self.assertTrue(self.limited("192.0.2.10", limit=1,
                                         headers={"X-Forwarded-For": "8.8.8.8"}))
            self.assertFalse(self.limited("192.0.2.11", limit=1,
                                          headers={"X-Forwarded-For": "1.1.1.1"}))

    def test_client_buckets_are_independent(self):
        with patch.object(routes.time, "time", return_value=1000):
            self.assertFalse(self.limited("192.0.2.10", "login", 1))
            self.assertTrue(self.limited("192.0.2.10", "login", 1))
            self.assertFalse(self.limited("192.0.2.10", "send", 1))
            self.assertFalse(self.limited("192.0.2.11", "login", 1))

    def test_window_expiry_releases_the_same_client(self):
        with patch.object(routes.config, "STUDENT_RATE_WINDOW_SECONDS", 60):
            with patch.object(routes.time, "time", return_value=1000):
                self.assertFalse(self.limited("192.0.2.10", limit=1))
                self.assertTrue(self.limited("192.0.2.10", limit=1))
            with patch.object(routes.time, "time", return_value=1061):
                self.assertFalse(self.limited("192.0.2.10", limit=1))


if __name__ == "__main__":
    unittest.main()
