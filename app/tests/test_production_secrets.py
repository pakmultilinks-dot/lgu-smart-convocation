"""Production-secret safety regressions.

Tests never initialize or open the default SQLite database.
"""

import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import review_test_support as review_support  # noqa: E402

import config  # noqa: E402
import database  # noqa: E402
from web.routes import create_app  # noqa: E402

SAFE_SESSION_KEY = "S" * 64
SAFE_HMAC_SECRET = b"H" * 64


class ProductionSecretValidationTests(unittest.TestCase):
    def assert_rejected(self, session_key, hmac_secret):
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "production"}),
            patch.object(config, "SECRET_KEY", session_key),
            patch.object(config, "HMAC_SECRET", hmac_secret),
        ):
            with self.assertRaises(RuntimeError):
                create_app()

    def test_default_demo_secrets_are_rejected_in_production(self):
        self.assert_rejected(
            "lgu-convocation-demo-key-change-in-production",
            b"lgu-convocation-hmac-secret-change-in-production",
        )

    def test_short_or_missing_session_secret_fails_closed(self):
        for value in ("", "short-secret", None):
            with self.subTest(value=value):
                self.assert_rejected(value, SAFE_HMAC_SECRET)

    def test_short_or_missing_signing_secret_fails_closed(self):
        for value in (b"", b"short", None):
            with self.subTest(value=value):
                self.assert_rejected(SAFE_SESSION_KEY, value)

    def test_reused_secrets_are_rejected(self):
        self.assert_rejected(SAFE_SESSION_KEY, SAFE_SESSION_KEY.encode())

    def test_custom_strong_secrets_allow_production_app_creation(self):
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "production"}),
            patch.object(config, "SECRET_KEY", SAFE_SESSION_KEY),
            patch.object(config, "HMAC_SECRET", SAFE_HMAC_SECRET),
            patch.object(config, "COOKIE_SECURE", True),
        ):
            app = create_app()
        self.assertIsNotNone(app)
        self.assertEqual(app.secret_key, SAFE_SESSION_KEY)

    def test_production_refuses_insecure_cookies_with_strong_secrets(self):
        # A strong session key does not make an unencrypted cookie safe.
        # The previous factory accepted this configuration.
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "production"}),
            patch.object(config, "SECRET_KEY", SAFE_SESSION_KEY),
            patch.object(config, "HMAC_SECRET", SAFE_HMAC_SECRET),
            patch.object(config, "COOKIE_SECURE", False),
            patch.object(database, "init_db") as init_db,
            patch.object(database, "seed") as seed,
        ):
            with self.assertRaisesRegex(RuntimeError, "LGU_COOKIE_SECURE=1"):
                create_app()
            init_db.assert_not_called()
            seed.assert_not_called()

    def test_development_still_allows_insecure_cookies_on_isolated_db(self):
        # Local testing and LAN rehearsal continue to work without TLS.
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "development"}),
            patch.object(config, "SECRET_KEY", SAFE_SESSION_KEY),
            patch.object(config, "HMAC_SECRET", SAFE_HMAC_SECRET),
            patch.object(config, "COOKIE_SECURE", False),
        ):
            app = create_app()
            self.assertFalse(app.config["SESSION_COOKIE_SECURE"])

    def test_demo_defaults_remain_available_in_development(self):
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "development"}),
            patch.object(
                config, "SECRET_KEY",
                "lgu-convocation-demo-key-change-in-production",
            ),
            patch.object(
                config, "HMAC_SECRET",
                b"lgu-convocation-hmac-secret-change-in-production",
            ),
        ):
            self.assertIsNotNone(create_app())

    def test_run_entrypoint_checks_before_any_database_bootstrap(self):
        # Import run.py only with patched DB operations, so the default
        # app/lgu.db is never touched even when this test fails.
        with (
            patch.dict(os.environ, {"LGU_APP_ENV": "production"}),
            patch.object(
                config, "SECRET_KEY",
                "lgu-convocation-demo-key-change-in-production",
            ),
            patch.object(
                config, "HMAC_SECRET",
                b"lgu-convocation-hmac-secret-change-in-production",
            ),
            patch.object(database, "init_db") as init_db,
            patch.object(database, "seed") as seed,
        ):
            sys.modules.pop("run", None)
            try:
                with self.assertRaises(RuntimeError):
                    importlib.import_module("run")
                init_db.assert_not_called()
                seed.assert_not_called()
            finally:
                sys.modules.pop("run", None)


if __name__ == "__main__":
    unittest.main()
