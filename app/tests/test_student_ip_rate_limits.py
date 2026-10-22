"""Regression tests for independent student API client rate limits.

Only Flask request contexts and synthetic addresses are used. No SQLite,
student records, or live network requests are accessed.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from web import student_routes as routes  # noqa: E402


class StudentRateLimitIsolationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.original_hits = routes._HITS
        # Preserve the production implementation's bucket storage type.
        routes._HITS = {name: type(hits)() for name, hits in self.original_hits.items()}

    def tearDown(self):
        routes._HITS = self.original_hits

    def attempt(self, address, bucket="login", limit=2, forwarded=None):
        headers = {"X-Forwarded-For": forwarded} if forwarded else {}
        with self.app.test_request_context(
            "/api/student/login", method="POST",
            environ_base={"REMOTE_ADDR": address}, headers=headers
        ):
            return routes._limited(bucket, limit)

    def test_one_client_cannot_exhaust_another_clients_login_budget(self):
        with patch.object(routes.time, "time", return_value=1000):
            self.assertFalse(self.attempt("192.0.2.10"))
            self.assertFalse(self.attempt("192.0.2.10"))
            self.assertTrue(self.attempt("192.0.2.10"))
            self.assertFalse(self.attempt("192.0.2.11"))
            self.assertFalse(self.attempt("192.0.2.11"))
            self.assertTrue(self.attempt("192.0.2.11"))

    def test_verify_and_recovery_budgets_are_isolated_by_client(self):
        with patch.object(routes.time, "time", return_value=1000):
            self.assertFalse(self.attempt("192.0.2.10", "send", 1))
            self.assertTrue(self.attempt("192.0.2.10", "send", 1))
            self.assertFalse(self.attempt("192.0.2.11", "send", 1))
            self.assertFalse(self.attempt("192.0.2.10", "recovery", 1))
            self.assertFalse(self.attempt("192.0.2.11", "recovery", 1))

    def test_untrusted_forwarded_header_does_not_reset_budget(self):
        with patch.object(routes.time, "time", return_value=1000):
            self.assertFalse(self.attempt("192.0.2.10", limit=1, forwarded="198.51.100.1"))
            self.assertTrue(self.attempt("192.0.2.10", limit=1, forwarded="198.51.100.2"))

    def test_expired_attempts_do_not_block_same_client(self):
        with patch.object(config, "STUDENT_RATE_WINDOW_SECONDS", 60):
            with patch.object(routes.time, "time", return_value=1000):
                self.assertFalse(self.attempt("192.0.2.10", limit=1))
                self.assertTrue(self.attempt("192.0.2.10", limit=1))
            with patch.object(routes.time, "time", return_value=1061):
                self.assertFalse(self.attempt("192.0.2.10", limit=1))


if __name__ == "__main__":
    unittest.main()
