"""Regression: one student's requests must not throttle unrelated clients.

All tests are in-memory Flask request contexts. No database is opened.
Only the direct socket address (REMOTE_ADDR) is trusted, never an
unverified X-Forwarded-For supplied by a client.
"""
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web import student_routes as sr  # noqa: E402


class StudentRateLimitPerIPTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        with sr._HITS_LOCK:
            for bucket in sr._HITS.values():
                bucket.clear()

    def call(self, ip, bucket="login", limit=2, forwarded=None):
        headers = {"X-Forwarded-For": forwarded} if forwarded else {}
        with self.app.test_request_context(
            "/api/student/login",
            environ_base={"REMOTE_ADDR": ip},
            headers=headers,
        ):
            return sr._limited(bucket, limit)

    def test_one_client_exhaustion_does_not_block_another(self):
        with patch.object(sr.time, "time", return_value=1000.0):
            self.assertFalse(self.call("192.0.2.10"))
            self.assertFalse(self.call("192.0.2.10"))
            self.assertTrue(self.call("192.0.2.10"))
            self.assertFalse(self.call("198.51.100.20"))
            self.assertFalse(self.call("198.51.100.20"))
            self.assertTrue(self.call("198.51.100.20"))

    def test_buckets_are_independent_for_the_same_client(self):
        with patch.object(sr.time, "time", return_value=1000.0):
            self.assertFalse(self.call("192.0.2.10", "login", 1))
            self.assertTrue(self.call("192.0.2.10", "login", 1))
            self.assertFalse(self.call("192.0.2.10", "recovery", 1))

    def test_client_supplied_forwarded_header_cannot_reset_limit(self):
        with patch.object(sr.time, "time", return_value=1000.0):
            self.assertFalse(self.call("192.0.2.10", limit=1, forwarded="1.1.1.1"))
            self.assertTrue(self.call("192.0.2.10", limit=1, forwarded="2.2.2.2"))

    def test_window_expiry_allows_client_again(self):
        with patch.object(sr.time, "time", return_value=1000.0):
            self.assertFalse(self.call("192.0.2.10", limit=1))
            self.assertTrue(self.call("192.0.2.10", limit=1))
        with patch.object(sr.time, "time", return_value=1000.0 + sr._bucket_window("login") + 1):
            self.assertFalse(self.call("192.0.2.10", limit=1))

    def test_concurrent_requests_respect_per_client_limit(self):
        def worker(ip):
            return self.call(ip, limit=5)
        with patch.object(sr.time, "time", return_value=1000.0):
            with ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(worker, ["192.0.2.10"] * 12 + ["198.51.100.20"] * 12))
        self.assertEqual(results[:12].count(False), 5)
        self.assertEqual(results[12:].count(False), 5)

    def test_stale_client_entries_are_pruned(self):
        with patch.object(sr.time, "time", return_value=1000.0):
            self.assertFalse(self.call("192.0.2.10", limit=1))
        with patch.object(sr.time, "time", return_value=1000.0 + sr._bucket_window("login") + 1):
            self.assertFalse(self.call("198.51.100.20", limit=1))
        self.assertNotIn("192.0.2.10", sr._HITS["login"])
        self.assertIn("198.51.100.20", sr._HITS["login"])


if __name__ == "__main__":
    unittest.main()
