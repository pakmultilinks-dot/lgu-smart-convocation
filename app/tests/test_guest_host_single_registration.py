"""One guest per student: model, API, and concurrency regression tests.

Every test uses an isolated temporary SQLite database. No production database
or app/run.py is opened, migrated, or seeded.
"""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import sys
import tempfile
from pathlib import Path
from threading import Barrier
import unittest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import review_test_support as review_support  # noqa: E402

import config  # noqa: E402
import database  # noqa: E402
import ids  # noqa: E402
import models  # noqa: E402
from web.routes import create_app  # noqa: E402

HOST = "LGU-2024-104"
OTHER_HOST = "LGU-2024-105"
SEEDED_HOST = "LGU-2024-101"


class OneGuestPerStudentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lgu-guest-host-test-")
        self.original_db_path = config.DB_PATH
        config.DB_PATH = str(Path(self.temp.name) / "test.sqlite3")
        database.init_db()
        database.seed()
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        review_support.authenticate(self.client)

    def tearDown(self):
        config.DB_PATH = self.original_db_path
        self.temp.cleanup()

    def count(self, host):
        conn = sqlite3.connect(config.DB_PATH)
        try:
            return conn.execute(
                "SELECT count(*) FROM guests WHERE host_roll_no = ?", (host,)
            ).fetchone()[0]
        finally:
            conn.close()

    def test_first_guest_succeeds_and_second_is_rejected(self):
        first_id, first_error = models.register_guest(
            "First Guest", "03000000001", HOST, ids.generate_id
        )
        self.assertIsNone(first_error)
        self.assertIsInstance(first_id, int)
        second_id, second_error = models.register_guest(
            "Second Guest", "03000000002", HOST, ids.generate_id
        )
        self.assertIsNone(second_id)
        self.assertIn("already", second_error.lower())
        self.assertEqual(self.count(HOST), 1)

    def test_seeded_host_cannot_register_another_guest(self):
        self.assertEqual(self.count(SEEDED_HOST), 1)
        gid, error = models.register_guest(
            "Extra", "03000000000", SEEDED_HOST, ids.generate_id
        )
        self.assertIsNone(gid)
        self.assertIn("already", error.lower())
        self.assertEqual(self.count(SEEDED_HOST), 1)

    def test_different_students_can_each_register_one_guest(self):
        for host in (HOST, OTHER_HOST):
            gid, error = models.register_guest(
                "Guest for " + host, "03000000001", host, ids.generate_id
            )
            self.assertIsNone(error)
            self.assertIsInstance(gid, int)
            self.assertEqual(self.count(host), 1)

    def test_unknown_student_preserves_existing_error(self):
        gid, error = models.register_guest(
            "Guest", "03000000001", "UNKNOWN-ROLL-NO", ids.generate_id
        )
        self.assertIsNone(gid)
        self.assertIn("No student found", error)

    def test_duplicate_guest_json_api_returns_400_without_second_pass(self):
        body = {
            "name": "First Guest",
            "phone": "03000000001",
            "host_roll_no": HOST,
        }
        first = self.client.post("/api/guests", json=body)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.get_json()["ok"])
        second = self.client.post(
            "/api/guests", json={**body, "name": "Second Guest"}
        )
        self.assertEqual(second.status_code, 400)
        self.assertFalse(second.get_json()["ok"])
        self.assertIn("already", second.get_json()["error"].lower())
        self.assertEqual(self.count(HOST), 1)

    def test_duplicate_guest_web_form_shows_error(self):
        data = {
            "name": "First Guest",
            "phone": "03000000001",
            "host_roll_no": HOST,
        }
        first = self.client.post("/guests", data=data)
        self.assertEqual(first.status_code, 302)
        second = self.client.post(
            "/guests", data={**data, "name": "Second Guest"}
        )
        self.assertEqual(second.status_code, 200)
        self.assertIn(
            "already", second.get_data(as_text=True).lower()
        )
        self.assertEqual(self.count(HOST), 1)

    def test_simultaneous_registrations_never_create_two_guest_passes(self):
        # Synchronize requests so every thread attempts registration together.
        count = 12
        barrier = Barrier(count)

        def register(index):
            barrier.wait(timeout=10)
            return models.register_guest(
                "Guest %s" % index,
                "0300%07d" % index,
                HOST,
                ids.generate_id,
            )

        with ThreadPoolExecutor(max_workers=count) as executor:
            attempts = list(executor.map(register, range(count)))
        accepted = [gid for gid, err in attempts if gid is not None]
        refused = [err for gid, err in attempts if gid is None]
        self.assertEqual(len(accepted), 1, attempts)
        self.assertEqual(len(refused), count - 1, attempts)
        self.assertTrue(all("already" in err.lower() for err in refused))
        self.assertEqual(self.count(HOST), 1)

    def test_legacy_duplicates_are_not_deleted_by_registration(self):
        # Existing duplicates may be present in a deployed older schema.
        conn = sqlite3.connect(config.DB_PATH)
        try:
            # Emulate a legacy pre-v14 database, on this disposable fixture only.
            conn.execute("DROP INDEX IF EXISTS idx_guests_host_once")
            conn.execute(
                "INSERT INTO guests (name,phone,host_roll_no,qr_id,created_at)"
                " VALUES (?,?,?,?,?)",
                ("Old A", "03000000001", HOST, ids.generate_id(), "2026-01-01"),
            )
            conn.execute(
                "INSERT INTO guests (name,phone,host_roll_no,qr_id,created_at)"
                " VALUES (?,?,?,?,?)",
                ("Old B", "03000000002", HOST, ids.generate_id(), "2026-01-02"),
            )
            conn.commit()
        finally:
            conn.close()
        gid, error = models.register_guest(
            "Third", "03000000003", HOST, ids.generate_id
        )
        self.assertIsNone(gid)
        self.assertIn("already", error.lower())
        self.assertEqual(self.count(HOST), 2)


if __name__ == "__main__":
    unittest.main()
