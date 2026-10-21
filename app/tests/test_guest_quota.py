"""One guest per student, using a temporary SQLite database only."""

import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import config  # noqa: E402
import database  # noqa: E402
import models  # noqa: E402
from web.routes import create_app  # noqa: E402


class GuestQuotaTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="lgu-guest-qa-")
        self.path_override = patch.object(
            config, "DB_PATH", os.path.join(self.sandbox.name, "qa.sqlite")
        )
        self.path_override.start()
        database.init_db()
        db = database.get_db()
        for roll in ("QA-001", "QA-002"):
            db.execute(
                "INSERT INTO students "
                "(roll_no, name, gender, program, qr_id, created_at) "
                "VALUES (?, ?, 'Male', 'BSCS', ?, '2026-10-21 12:00:00')",
                (roll, "Synthetic Student", "STUDENT-" + roll),
            )
        db.commit()
        db.close()
        self.client = create_app().test_client()

    def tearDown(self):
        self.path_override.stop()
        self.sandbox.cleanup()

    def count_guests(self):
        db = database.get_db()
        count = db.execute("SELECT COUNT(*) FROM guests").fetchone()[0]
        db.close()
        return count

    def test_second_guest_for_same_student_is_rejected(self):
        first_id, first_error = models.register_guest(
            "First Guest", "03000000001", "QA-001", lambda: "GUEST-001"
        )
        second_id, second_error = models.register_guest(
            "Second Guest", "03000000002", "QA-001", lambda: "GUEST-002"
        )
        self.assertIsNotNone(first_id)
        self.assertIsNone(first_error)
        self.assertIsNone(second_id)
        self.assertIn("already", second_error.lower())
        self.assertEqual(self.count_guests(), 1)

    def test_used_pass_does_not_restore_student_guest_quota(self):
        gid, _ = models.register_guest(
            "First Guest", "03000000001", "QA-001", lambda: "GUEST-001"
        )
        self.assertIsNotNone(gid)
        db = database.get_db()
        db.execute(
            "INSERT INTO scans (qr_id, person_type, person_name, gate_id, "
            "mode, volunteer, scanned_at, source) "
            "VALUES ('GUEST-001', 'guest', 'First Guest', 1, 'entry', "
            "'QA', '2026-10-21 12:00:00', 'online')"
        )
        db.commit()
        db.close()
        second_id, error = models.register_guest(
            "Second Guest", "03000000002", "QA-001", lambda: "GUEST-002"
        )
        self.assertIsNone(second_id)
        self.assertIn("already", error.lower())
        self.assertEqual(self.count_guests(), 1)

    def test_different_student_can_register(self):
        for roll, qr in (("QA-001", "GUEST-001"), ("QA-002", "GUEST-002")):
            gid, error = models.register_guest(
                "Synthetic Guest", "03000000001", roll, lambda qr=qr: qr
            )
            self.assertIsNotNone(gid)
            self.assertIsNone(error)
        self.assertEqual(self.count_guests(), 2)

    def test_whitespace_in_host_roll_does_not_bypass_limit(self):
        first_id, error = models.register_guest(
            "First Guest", "03000000001", " QA-001 ", lambda: "GUEST-001"
        )
        self.assertIsNotNone(first_id)
        self.assertIsNone(error)
        second_id, error = models.register_guest(
            "Second Guest", "03000000002", "QA-001", lambda: "GUEST-002"
        )
        self.assertIsNone(second_id)
        self.assertIn("already", error.lower())
        db = database.get_db()
        stored_roll = db.execute(
            "SELECT host_roll_no FROM guests"
        ).fetchone()[0]
        db.close()
        self.assertEqual(stored_roll, "QA-001")

    def test_api_rejects_second_guest_with_400(self):
        payload = {
            "name": "First Guest",
            "phone": "03000000001",
            "host_roll_no": "QA-001",
        }
        first = self.client.post("/api/guests", json=payload)
        self.assertEqual(first.status_code, 200)
        payload["name"] = "Second Guest"
        second = self.client.post("/api/guests", json=payload)
        self.assertEqual(second.status_code, 400)
        self.assertFalse(second.get_json()["ok"])
        self.assertIn("already", second.get_json()["error"].lower())
        self.assertEqual(self.count_guests(), 1)

    def test_html_form_displays_quota_error(self):
        payload = {
            "name": "First Guest",
            "phone": "03000000001",
            "host_roll_no": "QA-001",
        }
        first = self.client.post("/guests", data=payload)
        self.assertEqual(first.status_code, 302)
        payload["name"] = "Second Guest"
        second = self.client.post("/guests", data=payload)
        self.assertEqual(second.status_code, 200)
        self.assertIn(b"already", second.data.lower())
        self.assertEqual(self.count_guests(), 1)

    def test_simultaneous_requests_cannot_register_two_guests(self):
        start = threading.Barrier(2)
        results = []
        lock = threading.Lock()

        def register(index):
            start.wait(timeout=5)
            result = models.register_guest(
                "Concurrent Guest", "03000000001", "QA-001",
                lambda: "GUEST-%03d" % index,
            )
            with lock:
                results.append(result)

        threads = [
            threading.Thread(target=register, args=(i,)) for i in (1, 2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(gid is not None for gid, _ in results), 1)
        self.assertEqual(self.count_guests(), 1)


if __name__ == "__main__":
    unittest.main()
