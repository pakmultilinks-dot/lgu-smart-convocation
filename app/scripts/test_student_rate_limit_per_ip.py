"""Regression tests for isolated student request limits; no database use."""
import os
import tempfile
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "isolated.db")

from flask import Flask
from web import student_routes as api


class RateLimitIsolation(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(api.bp)
        for bucket in api._HITS.values():
            bucket.clear()

    def call(self, ip, bucket="login", limit=2):
        with self.app.test_request_context(
            "/api/student/login", environ_base={"REMOTE_ADDR": ip}
        ):
            return api._limited(bucket, limit)

    def test_independent_clients(self):
        self.assertFalse(self.call("192.0.2.1"))
        self.assertFalse(self.call("192.0.2.1"))
        self.assertTrue(self.call("192.0.2.1"))
        self.assertFalse(self.call("198.51.100.2"))

    def test_independent_operations(self):
        self.assertFalse(self.call("192.0.2.1", "login", 1))
        self.assertTrue(self.call("192.0.2.1", "login", 1))
        self.assertFalse(self.call("192.0.2.1", "confirm", 1))


if __name__ == "__main__":
    unittest.main()
