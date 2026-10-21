"""Regression tests: test-only HTTP endpoints must require explicit test mode.

The database path is deliberately set to a synthetic alternate location, the
same layout a production deployment might use. All read/write helpers are
mocked; these tests NEVER connect to or initialize SQLite.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from web import routes  # noqa: E402


class TestToolBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="lgu-test-boundary-")
        self.custom_db = str(Path(self.temp_dir.name) / "custom-app.sqlite3")

    def tearDown(self):
        self.temp_dir.cleanup()

    def client_for(self, *, testing=None, env="production"):
        # A different database filename is NOT evidence of a test deployment.
        settings = {"LGU_APP_ENV": env, "LGU_ENABLE_DEMO_QR": "1"}
        if testing is not None:
            settings["LGU_TESTING"] = testing
        with (
            patch.dict(os.environ, settings),
            patch.object(config, "DB_PATH", self.custom_db),
            patch.object(config, "assert_production_secrets"),
            patch.object(config, "demo_secret_violation", return_value=None),
        ):
            app = routes.create_app()
            app.config["TESTING"] = True
            yield app.test_client()

    def test_production_environment_hides_every_test_endpoint_on_custom_db(self):
        for testing in ("1", "0", None):
            with self.subTest(testing=testing):
                with (
                    patch.object(routes.scanner_auth, "create_scanner") as scanner,
                    patch.object(
                        routes.scanner_auth, "create_session",
                        return_value=("TEST-ONLY-TOKEN", "2030-01-01"),
                    ),
                    patch.object(
                        routes.scanner_auth, "resolve_session",
                        return_value={
                            "username": "test-only", "display_name": "Test",
                            "gates": [1],
                        },
                    ),
                    patch.object(routes.models, "test_records", return_value=[]) as records,
                    patch.object(routes.models, "reset_test_scans", return_value=0) as reset,
                    patch.object(routes, "_require_admin_pin", return_value=None),
                ):
                    for client in self.client_for(testing=testing, env="production"):
                        scanner_response = client.post(
                            "/api/test-scanner-session", json={"gate_ids": [1]}
                        )
                        records_response = client.get("/api/test-records")
                        reset_response = client.post("/api/test-reset")
                self.assertEqual(scanner_response.status_code, 404)
                self.assertEqual(records_response.status_code, 404)
                self.assertEqual(reset_response.status_code, 404)
                scanner.assert_not_called()
                records.assert_not_called()
                reset.assert_not_called()

    def test_non_testing_development_environment_hides_test_endpoints(self):
        with (
            patch.object(routes.scanner_auth, "create_scanner") as scanner,
            patch.object(
                routes.scanner_auth, "create_session",
                return_value=("TEST-ONLY-TOKEN", "2030-01-01"),
            ),
            patch.object(
                routes.scanner_auth, "resolve_session",
                return_value={
                    "username": "test-only", "display_name": "Test", "gates": [1],
                },
            ),
            patch.object(routes.models, "test_records", return_value=[]) as records,
        ):
            for client in self.client_for(testing=None, env="development"):
                self.assertEqual(
                    client.post("/api/test-scanner-session", json={}).status_code,
                    404,
                )
                self.assertEqual(client.get("/api/test-records").status_code, 404)
        scanner.assert_not_called()
        records.assert_not_called()

    def test_explicit_test_mode_preserves_isolated_http_test_harness(self):
        with (
            patch.object(routes.scanner_auth, "create_scanner", return_value=13),
            patch.object(
                routes.scanner_auth, "create_session",
                return_value=("TEST-ONLY-TOKEN", "2030-01-01"),
            ),
            patch.object(
                routes.scanner_auth, "resolve_session",
                return_value={
                    "username": "synthetic-qa-scanner",
                    "display_name": "QA Scanner",
                    "gates": [1],
                },
            ),
            patch.object(
                routes.models, "test_records",
                return_value=[{"kind": "synthetic-qa"}],
            ),
            patch.object(routes, "_require_admin_pin", return_value=None),
            patch.object(routes.models, "reset_test_scans", return_value=0),
        ):
            for client in self.client_for(testing="1", env="test"):
                resp = client.post("/api/test-scanner-session", json={})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.get_json()["token"], "TEST-ONLY-TOKEN")
                resp = client.get("/api/test-records")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.get_json()["records"], [{"kind": "synthetic-qa"}])
                resp = client.post("/api/test-reset")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.get_json()["removed"], 0)

    def test_demo_qr_is_independent_opt_in_not_a_test_admin_endpoint(self):
        # Normal private development can still enable the QR demo helper,
        # without gaining anonymous scanner provisioning or test-reset.
        fake = {"qr_id": "DEMO", "name": "Synthetic", "roll_no": "QA-001"}
        with (
            patch.object(
                routes.models, "first_outside_student", return_value=fake
            ),
            patch.object(routes.ids, "make_payload", return_value="SYNTHETIC-QR"),
        ):
            for client in self.client_for(testing=None, env="development"):
                resp = client.get("/api/demo-payload")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.get_json()["payload"], "SYNTHETIC-QR")


if __name__ == "__main__":
    unittest.main()
