"""HTTP request-size and CSV encoding regressions; no production DB access."""

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Make app/ importable when invoked from the repository root or directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web import routes  # noqa: E402


class UploadBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.app = routes.create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_api_oversized_body_returns_json_413(self):
        self.app.config["MAX_CONTENT_LENGTH"] = 1024
        response = self.client.put(
            "/api/settings",
            data=json.dumps({"venue": "x" * 2048}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.content_type, "application/json")
        self.assertEqual(response.get_json()["ok"], False)

    def test_browser_oversized_roster_returns_413(self):
        self.app.config["MAX_CONTENT_LENGTH"] = 1024
        response = self.client.post(
            "/admin",
            data={
                "action": "upload_roster",
                "roster": (io.BytesIO(b"x" * 2048), "large.csv"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("Request too large", response.get_data(as_text=True))

    def test_invalid_utf8_roster_does_not_call_import(self):
        with (
            patch.object(routes.models, "gates", return_value=[]),
            patch.object(routes.models, "all_students", return_value=[]),
            patch.object(routes.models, "students_with_ids", return_value=[]),
            patch.object(routes.models, "add_students") as add_students,
        ):
            response = self.client.post(
                "/admin",
                data={
                    "action": "upload_roster",
                    "roster": (io.BytesIO(b"\xff\xfe\xfd"), "bad.csv"),
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("UTF-8 encoded CSV", response.get_data(as_text=True))
        add_students.assert_not_called()

    def test_utf8_bom_valid_roster_still_imports(self):
        content = (
            "roll_no,name,gender,program\n"
            "FA25-BSCS-201,Test Student,M,BSCS\n"
        ).encode("utf-8-sig")
        with (
            patch.object(routes.models, "gates", return_value=[]),
            patch.object(routes.models, "all_students", return_value=[]),
            patch.object(routes.models, "students_with_ids", return_value=[]),
            patch.object(routes.models, "students_missing_ids", return_value=[]),
            patch.object(routes.models, "assign_ids", return_value=0),
            patch.object(routes.models, "add_students", return_value=(1, 0)) as add_students,
        ):
            response = self.client.post(
                "/admin",
                data={
                    "action": "upload_roster",
                    "roster": (io.BytesIO(content), "valid.csv"),
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        add_students.assert_called_once_with(
            [("FA25-BSCS-201", "Test Student", "Male", "BSCS")]
        )


if __name__ == "__main__":
    unittest.main()
