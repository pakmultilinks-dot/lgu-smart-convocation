import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "lgu.db")

SECRET_KEY = os.environ.get("LGU_SECRET_KEY", "lgu-convocation-demo-key-change-in-production")
# QR signing secret (bytes). Set LGU_HMAC_SECRET in the environment on the
# real server; the committed value is a demo default. Changing it
# invalidates previously issued QR codes, so set it once before cards
# are printed.
HMAC_SECRET = os.environ.get("LGU_HMAC_SECRET", "lgu-convocation-hmac-secret-change-in-production").encode("utf-8")

ID_VERSION = "LGU1"
ID_LENGTH = 8
ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I to avoid misreads

DISPLAY_TZ = "Asia/Karachi"

APP_NAME = "LGU Smart Convocation System"
UNIVERSITY = "Lahore Garrison University"
MOTTO = "Nurturing the Future of Pakistan in an Excellent Environment"


def assert_production_secrets():
    """Reject weak or demo credentials before serving production traffic.

    Called by the WSGI app factory and by run.py before any DB bootstrap.
    This is one prerequisite for production readiness, not a replacement
    for authorization, TLS, backup, or operator-approved DB migrations.
    """
    if os.environ.get("LGU_APP_ENV", "").strip().lower() != "production":
        return

    session_secret = SECRET_KEY
    qr_secret = HMAC_SECRET
    if (
        not isinstance(session_secret, str)
        or len(session_secret) < 32
        or "demo" in session_secret.lower()
        or "change-in-production" in session_secret.lower()
    ):
        raise RuntimeError(
            "Production requires a unique LGU_SECRET_KEY "
            "of at least 32 characters (not the demo key)."
        )
    if (
        not isinstance(qr_secret, bytes)
        or len(qr_secret) < 32
        or b"demo" in qr_secret.lower()
        or b"change-in-production" in qr_secret.lower()
    ):
        raise RuntimeError(
            "Production requires a unique LGU_HMAC_SECRET "
            "of at least 32 bytes (not the demo signing key)."
        )
    if session_secret.encode("utf-8") == qr_secret:
        raise RuntimeError(
            "LGU_SECRET_KEY and LGU_HMAC_SECRET must be different."
        )
