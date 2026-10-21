"""Regression tests for scanner API JSON boundaries.

Only disposable SQLite databases are used. Import create_app directly,
never app/run.py, which initializes the default database on import.
"""

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import config  # noqa: E402
import database  # noqa: E402
import ids  # noqa: E402
from web.routes import create_app  # noqa: E402


class ScanSyncRequestValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prod_path = APP_DIR / "lgu.db"
        cls.prod_checksum = cls._prod_checksum()

    @classmethod
    def _prod_checksum(cls):
        if not cls.prod_path.exists():
            return None
        return hashlib.sha256(cls.prod_path.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        if cls._prod_checksum() != cls.prod_checksum:
            raise AssertionError("Production/default app/lgu.db was modified")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lgu-scan-json-")
        self.old_db_path = config.DB_PATH
        self.db_path = str(Path(self.temp.name) / "qa.sqlite")
        config.DB_PATH = self.db_path
        database.init_db()
        database.seed()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        config.DB_PATH = self.old_db_path
        self.temp.cleanup()

    def _valid_scan(self):
        db = sqlite3.connect(self.db_path)
        try:
            qr_id = db.execute(
                "SELECT qr_id FROM students WHERE qr_id IS NOT NULL "
                "ORDER BY id LIMIT 1"
            ).fetchone()[0]
        finally:
            db.close()
        return {
            "payload": ids.make_payload(qr_id),
            "gate_id": 1,
            "mode": "entry",
            "volunteer": "QA",
        }

    def _scan_count(self):
        db = sqlite3.connect(self.db_path)
        try:
            return db.execute("SELECT count(*) FROM scans").fetchone()[0]
        finally:
            db.close()

    def _assert_json_error(self, response):
        self.assertEqual(400, response.status_code)
        self.assertTrue(response.is_json)
        body = response.get_json()
        self.assertEqual(body.get("ok"), False)
        self.assertIsInstance(body.get("error"), str)

    def test_scan_rejects_non_object_json(self):
        for body in ([], ["scan"], "hello", 8, True, None):
            with self.subTest(body=body):
                self._assert_json_error(self.client.post("/api/scan", json=body))
        self.assertEqual(self._scan_count(), 0)

    def test_scan_rejects_broken_json_with_json_error(self):
        response = self.client.post(
            "/api/scan", data="{bad", content_type="application/json"
        )
        self._assert_json_error(response)

    def test_scan_rejects_non_string_volunteer(self):
        for value in ({}, [], 10, True):
            with self.subTest(value=value):
                item = self._valid_scan()
                item["volunteer"] = value
                self._assert_json_error(self.client.post("/api/scan", json=item))
        self.assertEqual(self._scan_count(), 0)

    def test_sync_rejects_non_object_json(self):
        for body in ([], ["sync"], "hello", 12, True, None):
            with self.subTest(body=body):
                self._assert_json_error(self.client.post("/api/sync", json=body))
        self.assertEqual(self._scan_count(), 0)

    def test_sync_rejects_non_array_items(self):
        for bad in ({}, "entry", 4, True, None):
            with self.subTest(items=bad):
                self._assert_json_error(
                    self.client.post("/api/sync", json={"items": bad})
                )
        self.assertEqual(self._scan_count(), 0)

    def test_sync_validates_whole_batch_before_any_write(self):
        good = self._valid_scan()
        for bad in (7, None, "bad entry", ["scan"], {"volunteer": []}):
            with self.subTest(bad=bad):
                items = [good, bad]
                self._assert_json_error(
                    self.client.post("/api/sync", json={"items": items})
                )
                self.assertEqual(self._scan_count(), 0)

    def test_sync_rejects_non_string_offline_timestamp(self):
        for bad in (123, [], {"day": "today"}, True):
            with self.subTest(timestamp=bad):
                item = self._valid_scan()
                item["scanned_at"] = bad
                self._assert_json_error(
                    self.client.post("/api/sync", json={"items": [item]})
                )
        self.assertEqual(self._scan_count(), 0)

    def test_sync_rejects_broken_json_as_json(self):
        response = self.client.post(
            "/api/sync", data="{bad", content_type="application/json"
        )
        self._assert_json_error(response)

    def test_valid_scan_and_duplicate_rules_still_work(self):
        scan = self._valid_scan()
        first = self.client.post("/api/scan", json=scan)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["title"], "ENTRY RECORDED")
        duplicate = self.client.post("/api/scan", json=scan)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.get_json()["title"], "ALREADY INSIDE")
        self.assertEqual(self._scan_count(), 1)

    def test_valid_offline_sync_and_empty_batch_still_work(self):
        empty = self.client.post("/api/sync", json={"items": []})
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.get_json()["synced"], 0)
        item = self._valid_scan()
        item["scanned_at"] = "2026-10-21 20:00:00"
        response = self.client.post("/api/sync", json={"items": [item]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["synced"], 1)
        self.assertEqual(self._scan_count(), 1)

    def test_forged_code_keeps_existing_scan_result_contract(self):
        item = self._valid_scan()
        item["payload"] = "LGU1:FORGED!!:bad"
        response = self.client.post("/api/scan", json=item)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["title"], "INVALID CODE")
        self.assertEqual(self._scan_count(), 0)


if __name__ == "__main__":
    unittest.main()
