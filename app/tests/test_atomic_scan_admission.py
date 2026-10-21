"""Concurrency regression for QR admission; disposable SQLite only.

Two volunteers can scan the same QR simultaneously. A pre-insert duplicate
check is insufficient; only one transaction may record the admission.
"""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import sys
import tempfile
from pathlib import Path
from threading import Barrier
from contextlib import nullcontext
import unittest
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import review_test_support as review_support  # noqa: E402

import config  # noqa: E402
import database  # noqa: E402
import ids  # noqa: E402
import models  # noqa: E402
from web import routes  # noqa: E402


class AtomicAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lgu-atomic-admission-")
        self.original_db_path = config.DB_PATH
        self.db_path = str(Path(self.temp.name) / "qa.sqlite")
        config.DB_PATH = self.db_path
        database.init_db()
        database.seed()
        self.app = routes.create_app()
        self.app.config.update(TESTING=True)
        self.lock_patch = patch.object(routes, "_SCAN_LOCK", nullcontext())
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)

    def tearDown(self):
        config.DB_PATH = self.original_db_path
        self.temp.cleanup()

    def person(self, table, where, parameter):
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT qr_id FROM " + table + " WHERE " + where + " = ?",
                (parameter,),
            ).fetchone()
            self.assertIsNotNone(row)
            return row[0]
        finally:
            conn.close()

    def number_of_scans(self, qr_id):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT count(*) FROM scans WHERE qr_id = ?",
                (qr_id,),
            ).fetchone()[0]
        finally:
            conn.close()

    def send_two_scans(self, payload, mode):
        def send(_):
            with self.app.test_client() as client:
                review_support.authenticate(client)
                response = client.post("/api/scan", json={
                    "payload": payload,
                    "gate_id": 1,
                    "mode": mode,
                    "volunteer": "Gate QA",
                })
                self.assertEqual(response.status_code, 200)
                return response.get_json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(send, range(2)))

    def test_simultaneous_guest_scans_admit_exactly_once(self):
        guest_id = self.person("guests", "host_roll_no", "LGU-2024-101")
        payload = ids.make_payload(guest_id)
        original = models.guest_used
        barrier = Barrier(2)

        def check_and_pause(qr_id):
            before = original(qr_id)
            barrier.wait(timeout=10)
            return before

        # Deterministically put both requests after the old check but before
        # any insertion. A second guarded check must happen in the transaction.
        with patch.object(routes.models, "guest_used", check_and_pause):
            results = self.send_two_scans(payload, "entry")
        self.assertCountEqual(
            [r["title"] for r in results],
            ["GUEST ENTRY RECORDED", "ALREADY USED"],
        )
        self.assertEqual(self.number_of_scans(guest_id), 1)

    def test_simultaneous_student_entries_admit_exactly_once(self):
        student_id = self.person("students", "roll_no", "LGU-2024-104")
        payload = ids.make_payload(student_id)
        original = models.student_inside
        barrier = Barrier(2)

        def check_and_pause(qr_id):
            before = original(qr_id)
            barrier.wait(timeout=10)
            return before

        with patch.object(routes.models, "student_inside", check_and_pause):
            results = self.send_two_scans(payload, "entry")
        self.assertCountEqual(
            [r["title"] for r in results],
            ["ENTRY RECORDED", "ALREADY INSIDE"],
        )
        self.assertEqual(self.number_of_scans(student_id), 1)

    def test_simultaneous_student_exits_record_exactly_once(self):
        student_id = self.person("students", "roll_no", "LGU-2024-104")
        payload = ids.make_payload(student_id)
        with self.app.test_client() as client:
            review_support.authenticate(client)
            first = client.post("/api/scan", json={
                "payload": payload,
                "gate_id": 1,
                "mode": "entry",
                "volunteer": "QA",
            })
            self.assertEqual(first.get_json()["title"], "ENTRY RECORDED")

        original = models.student_inside
        barrier = Barrier(2)

        def check_and_pause(qr_id):
            before = original(qr_id)
            barrier.wait(timeout=10)
            return before

        with patch.object(routes.models, "student_inside", check_and_pause):
            results = self.send_two_scans(payload, "exit")
        self.assertCountEqual(
            [r["title"] for r in results],
            ["EXIT RECORDED", "NOT INSIDE"],
        )
        self.assertEqual(self.number_of_scans(student_id), 2)

    def test_ordinary_student_entry_and_exit_still_work(self):
        student_id = self.person("students", "roll_no", "LGU-2024-104")
        payload = ids.make_payload(student_id)
        with self.app.test_client() as client:
            review_support.authenticate(client)
            scan = lambda mode: client.post("/api/scan", json={
                "payload": payload, "gate_id": 1,
                "mode": mode, "volunteer": "QA",
            }).get_json()["title"]
            self.assertEqual(scan("entry"), "ENTRY RECORDED")
            self.assertEqual(scan("entry"), "ALREADY INSIDE")
            self.assertEqual(scan("exit"), "EXIT RECORDED")
            self.assertEqual(scan("exit"), "NOT INSIDE")
        self.assertEqual(self.number_of_scans(student_id), 2)

    def test_guest_pass_remains_entry_only_and_non_reusable(self):
        guest_id = self.person("guests", "host_roll_no", "LGU-2024-101")
        payload = ids.make_payload(guest_id)
        with self.app.test_client() as client:
            review_support.authenticate(client)
            def scan(mode):
                return client.post("/api/scan", json={
                    "payload": payload, "gate_id": 1,
                    "mode": mode, "volunteer": "QA",
                }).get_json()["title"]
            self.assertEqual(scan("exit"), "GUEST PASS IS ENTRY ONLY")
            self.assertEqual(scan("entry"), "GUEST ENTRY RECORDED")
            self.assertEqual(scan("entry"), "ALREADY USED")
        self.assertEqual(self.number_of_scans(guest_id), 1)


if __name__ == "__main__":
    unittest.main()
