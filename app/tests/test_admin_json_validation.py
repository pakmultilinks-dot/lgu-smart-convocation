"""HTTP JSON validation on admin and guest routes, using temporary SQLite.

Tests do not access or initialize the repository's real app/lgu.db.
"""

import sqlite3
import sys
import tempfile
from pathlib import Path
import unittest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import review_test_support as review_support  # noqa: E402

import config  # noqa: E402
import database  # noqa: E402
from web.routes import create_app  # noqa: E402


class AdminApiJsonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lgu-admin-json-")
        self.original_path = config.DB_PATH
        self.db_path = str(Path(self.temp.name) / "qa.sqlite")
        config.DB_PATH = self.db_path
        database.init_db()
        database.seed()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        review_support.authenticate(self.client)
        self.client.environ_base["HTTP_X_ADMIN_PIN"] = str(config.ADMIN_PIN)

    def tearDown(self):
        config.DB_PATH = self.original_path
        self.temp.cleanup()

    def scalar(self, sql, params=()):
        db = sqlite3.connect(self.db_path)
        try:
            return db.execute(sql, params).fetchone()[0]
        finally:
            db.close()

    def assert_invalid(self, path, method="POST", body=None):
        res = self.client.open(path, method=method, json=body)
        self.assertEqual(res.status_code, 400)
        self.assertTrue(res.is_json)
        self.assertFalse(res.get_json()["ok"])
        self.assertIsInstance(res.get_json().get("error"), str)

    def test_non_object_json_rejected_for_all_mutating_admin_routes(self):
        routes = [
            ("/api/settings", "PUT"),
            ("/api/guests", "POST"),
            ("/api/broadcasts", "POST"),
            ("/api/gates/1/rename", "POST"),
        ]
        for path, method in routes:
            for payload in ([], ["item"], "hello", 7, True, None):
                with self.subTest(path=path, method=method, payload=payload):
                    self.assert_invalid(path, method=method, body=payload)

    def test_malformed_json_is_not_silently_accepted(self):
        for path, method in [
            ("/api/settings", "PUT"),
            ("/api/guests", "POST"),
            ("/api/broadcasts", "POST"),
            ("/api/gates/1/rename", "POST"),
        ]:
            with self.subTest(path=path):
                response = self.client.open(
                    path, method=method, data="{invalid",
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.is_json)
                self.assertFalse(response.get_json()["ok"])

    def test_bad_settings_value_does_not_change_existing_configuration(self):
        old_venue = self.scalar(
            "SELECT value FROM settings WHERE key = 'venue'"
        )
        for bad in ([], {}, True, None):
            with self.subTest(bad=bad):
                self.assert_invalid(
                    "/api/settings", method="PUT", body={"venue": bad}
                )
                self.assertEqual(
                    self.scalar("SELECT value FROM settings WHERE key = 'venue'"),
                    old_venue,
                )

    def test_invalid_guest_fields_do_not_create_passes(self):
        before = self.scalar("SELECT count(*) FROM guests")
        baseline = {
            "name": "QA",
            "phone": "03000000001",
            "host_roll_no": "LGU-2024-104",
        }
        for field in baseline:
            for bad in ([], {}, True, 123):
                with self.subTest(field=field, bad=bad):
                    self.assert_invalid(
                        "/api/guests", body={**baseline, field: bad}
                    )
        self.assertEqual(self.scalar("SELECT count(*) FROM guests"), before)

    def test_invalid_broadcast_fields_do_not_write_log(self):
        before = self.scalar("SELECT count(*) FROM broadcasts")
        baseline = {
            "message": "QA announcement",
            "audience": "All students",
            "sent_by": "Registrar",
        }
        for field in baseline:
            for bad in ([], {}, True, 123):
                with self.subTest(field=field, bad=bad):
                    self.assert_invalid(
                        "/api/broadcasts", body={**baseline, field: bad}
                    )
        self.assertEqual(
            self.scalar("SELECT count(*) FROM broadcasts"), before
        )

    def test_invalid_gate_label_does_not_rename_gate(self):
        old_label = self.scalar("SELECT label FROM gates WHERE id = 1")
        for bad in ([], {}, True, 123):
            with self.subTest(bad=bad):
                self.assert_invalid(
                    "/api/gates/1/rename", body={"label": bad}
                )
        self.assertEqual(
            self.scalar("SELECT label FROM gates WHERE id = 1"), old_label
        )

    def test_valid_requests_keep_existing_response_contracts(self):
        settings = self.client.put("/api/settings", json={"venue": "QA Hall"})
        self.assertEqual(settings.status_code, 200)
        self.assertEqual(settings.get_json()["venue"], "QA Hall")
        broadcast = self.client.post(
            "/api/broadcasts", json={
                "message": "QA notice", "audience": "All students",
                "sent_by": "Registrar",
            },
        )
        self.assertEqual(broadcast.status_code, 200)
        self.assertTrue(broadcast.get_json()["ok"])
        gate = self.client.post("/api/gates/1/rename", json={"label": "QA Gate"})
        self.assertEqual(gate.status_code, 200)
        self.assertEqual(gate.get_json()["gate"]["label"], "QA Gate")
        guest = self.client.post(
            "/api/guests", json={
                "name": "QA Guest", "phone": "03000000001",
                "host_roll_no": "LGU-2024-104", "payment_reference": "QA-RECEIPT-104", "payment_verified": True,
            },
        )
        self.assertEqual(guest.status_code, 200)
        self.assertTrue(guest.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
