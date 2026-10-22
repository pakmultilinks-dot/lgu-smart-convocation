"""Regression: one student's requests must not throttle a different client.

Only Flask request contexts and in-memory counters are used. No SQLite,
student accounts, email delivery, production services or secrets are touched.
"""

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from web import student_routes  # noqa: E402


class StudentRateLimitIsolationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        with student_routes._HITS_LOCK:
            for hits in student_routes._HITS.values():
                hits.clear()

    def _attempt(self, ip, bucket="login", limit=2, forwarded=None):
        headers = {"X-Forwarded-For": forwarded} if forwarded else {}
        with self.app.test_request_context(
            "/api/student/login",
            environ_base={"REMOTE_ADDR": ip},
            headers=headers,
        ):
            return student_routes._limited(bucket, limit)

    def test_one_client_cannot_exhaust_another_clients_login_budget(self):
        with patch.object(student_routes.time, "time", return_value=1000):
            self.assertFalse(self._attempt("192.0.2.10"))
            self.assertFalse(self._attempt("192.0.2.10"))
            self.assertTrue(self._attempt("192.0.2.10"))
            self.assertFalse(self._attempt("192.0.2.11"))
            self.assertFalse(self._attempt("192.0.2.11"))
            self.assertTrue(self._attempt("192.0.2.11"))

    def test_client_and_operation_budgets_are_independent(self):
        with patch.object(student_routes.time, "time", return_value=1000):
            self.assertFalse(self._attempt("192.0.2.20", "send", 1))
            self.assertTrue(self._attempt("192.0.2.20", "send", 1))
            self.assertFalse(self._attempt("192.0.2.21", "send", 1))
            self.assertFalse(self._attempt("192.0.2.20", "recovery", 1))

    def test_untrusted_forwarded_for_does_not_reset_a_clients_limit(self):
        with patch.object(student_routes.time, "time", return_value=1000):
            self.assertFalse(self._attempt("192.0.2.30", limit=1,
                                           forwarded="198.51.100.1"))
            self.assertTrue(self._attempt("192.0.2.30", limit=1,
                                          forwarded="198.51.100.2"))

    def test_expired_hits_do_not_block_the_same_client(self):
        with patch.object(config, "STUDENT_RATE_WINDOW_SECONDS", 60):
            with patch.object(student_routes.time, "time", return_value=1000):
                self.assertFalse(self._attempt("192.0.2.40", limit=1))
                self.assertTrue(self._attempt("192.0.2.40", limit=1))
            with patch.object(student_routes.time, "time", return_value=1061):
                self.assertFalse(self._attempt("192.0.2.40", limit=1))


if __name__ == "__main__":
    unittest.main()
