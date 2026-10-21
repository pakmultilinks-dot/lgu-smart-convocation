"""Protect demo QR discovery from accidentally exposing valid student passes.

All tests mock roster access. No production/default SQLite database is opened.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import review_test_support as review_support  # noqa: E402

from web import routes  # noqa: E402


class DemoQrAccessTests(unittest.TestCase):
    def setUp(self):
        self.app = routes.create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_demo_helper_disabled_by_default(self):
        with (
            patch.dict(os.environ, {
                "LGU_ENABLE_DEMO_QR": "",
                "LGU_APP_ENV": "development",
            }),
            patch.object(routes.models, "first_outside_student") as find_student,
        ):
            response = self.client.get("/api/demo-payload")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json().get("ok"), False)
        self.assertNotIn("payload", response.get_json())
        find_student.assert_not_called()

    def test_explicit_demo_opt_in_returns_synthetic_qr(self):
        fake_student = {
            "qr_id": "SYNTHETIC",
            "name": "QA Student",
            "roll_no": "QA-001",
        }
        with (
            patch.dict(os.environ, {
                "LGU_ENABLE_DEMO_QR": "1",
                "LGU_APP_ENV": "development",
            }),
            patch.object(
                routes.models, "first_outside_student",
                return_value=fake_student,
            ) as find_student,
            patch.object(
                routes.ids, "make_payload",
                return_value="TEST-SIGNED-PAYLOAD",
            ),
        ):
            response = self.client.get("/api/demo-payload")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json().get("payload"), "TEST-SIGNED-PAYLOAD"
        )
        self.assertIn("QA Student", response.get_json().get("hint", ""))
        find_student.assert_called_once()

    def test_production_disables_helper_even_when_opted_in(self):
        with (
            patch.dict(os.environ, {
                "LGU_ENABLE_DEMO_QR": "1",
                "LGU_APP_ENV": "production",
            }),
            patch.object(routes.models, "first_outside_student") as find_student,
        ):
            response = self.client.get("/api/demo-payload")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("payload", response.get_json())
        find_student.assert_not_called()

    def test_invalid_opt_in_values_are_disabled(self):
        for value in ("false", "0", "off", "unexpected", ""):
            with self.subTest(value=value), (
                patch.dict(os.environ, {
                    "LGU_ENABLE_DEMO_QR": value,
                    "LGU_APP_ENV": "development",
                })
            ), patch.object(
                routes.models, "first_outside_student"
            ) as find_student:
                response = self.client.get("/api/demo-payload")
                self.assertEqual(response.status_code, 404)
                find_student.assert_not_called()


if __name__ == "__main__":
    unittest.main()
