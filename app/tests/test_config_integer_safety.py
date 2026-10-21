"""Bound integer configuration values without touching production data.

Only the config module is imported under an isolated name and temporary
environment overrides. No Flask app or database is initialized.
"""

import importlib.util
import os
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.py"

# Config key, exported Python name, default value.
TUNABLES = (
    ("LGU_GATE_WINDOW_MINUTES", "GATE_ACTIVITY_WINDOW_MINUTES", 15),
    ("LGU_MESSAGE_LIMIT", "MESSAGE_CHAR_LIMIT", 160),
    ("LGU_PIN_WINDOW", "PIN_RATE_WINDOW_SECONDS", 60),
    ("LGU_PIN_MAX_FAILS", "PIN_RATE_MAX_FAILS", 5),
    ("LGU_EXAM_WINDOW", "EXAM_RATE_WINDOW_SECONDS", 60),
    ("LGU_EXAM_MAX_FAILS", "EXAM_RATE_MAX_FAILS", 5),
    ("LGU_SMTP_PORT", "SMTP_PORT", 587),
    ("LGU_SMTP_TIMEOUT", "SMTP_TIMEOUT", 10),
    ("LGU_VERIFICATION_TTL", "VERIFICATION_TTL_SECONDS", 600),
    ("LGU_CODE_MAX_ATTEMPTS", "CODE_MAX_ATTEMPTS", 5),
    ("LGU_CODE_MAX_SENDS", "CODE_MAX_SENDS", 3),
    ("LGU_STUDENT_SESSION_HOURS", "SESSION_HOURS", 168),
    ("LGU_SUPPORT_SUBJECT_MAX", "SUPPORT_SUBJECT_MAX", 160),
    ("LGU_SUPPORT_MESSAGE_MAX", "SUPPORT_MESSAGE_MAX", 4000),
    ("LGU_SUPPORT_MAX_OPEN", "SUPPORT_MAX_OPEN", 20),
    ("LGU_SUPPORT_STALE_DAYS", "SUPPORT_STALE_DAYS", 7),
    ("LGU_SUPPORT_RECENT_DAYS", "SUPPORT_RECENT_DAYS", 7),
    ("LGU_PASS_TTL_HOURS", "CONVOCATION_PASS_TTL_HOURS", 72),
    ("LGU_SCANNER_SESSION_HOURS", "SCANNER_SESSION_HOURS", 12),
    ("LGU_SCANNER_WINDOW", "SCANNER_RATE_WINDOW_SECONDS", 60),
    ("LGU_SCANNER_MAX_FAILS", "SCANNER_RATE_MAX_FAILS", 5),
)


def load_config(overrides):
    """Import only this module; bypass cached imports and all DB startup."""
    with patch.dict(os.environ, overrides):
        spec = importlib.util.spec_from_file_location(
            "lgu_config_safety_fixture", CONFIG_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class ConfigIntegerSafetyTests(TestCase):
    def test_malformed_integer_values_fallback_to_documented_defaults(self):
        # An invalid env setting must not prevent the backend from importing.
        config = load_config({key: "not-a-number" for key, _, _ in TUNABLES})
        for key, exported_name, default in TUNABLES:
            with self.subTest(key=key):
                self.assertEqual(getattr(config, exported_name), default)

    def test_zero_values_cannot_disable_protective_limits_or_expiry(self):
        config = load_config({key: "0" for key, _, _ in TUNABLES})
        for key, exported_name, default in TUNABLES:
            with self.subTest(key=key):
                self.assertEqual(getattr(config, exported_name), default)

    def test_negative_values_cannot_disable_protective_limits_or_expiry(self):
        config = load_config({key: "-10" for key, _, _ in TUNABLES})
        for key, exported_name, default in TUNABLES:
            with self.subTest(key=key):
                self.assertEqual(getattr(config, exported_name), default)

    def test_explicit_positive_custom_values_are_preserved(self):
        config = load_config({key: str(default + 3) for key, _, default in TUNABLES})
        for key, exported_name, default in TUNABLES:
            with self.subTest(key=key):
                self.assertEqual(getattr(config, exported_name), default + 3)

    def test_existing_positive_int_helper_is_used_for_security_limits(self):
        config = load_config({
            "LGU_PIN_MAX_FAILS": "-1",
            "LGU_EXAM_MAX_FAILS": "abc",
            "LGU_SCANNER_MAX_FAILS": "0",
            "LGU_CODE_MAX_ATTEMPTS": "-1",
        })
        self.assertEqual(config.PIN_RATE_MAX_FAILS, 5)
        self.assertEqual(config.EXAM_RATE_MAX_FAILS, 5)
        self.assertEqual(config.SCANNER_RATE_MAX_FAILS, 5)
        self.assertEqual(config.CODE_MAX_ATTEMPTS, 5)


if __name__ == "__main__":
    main()
