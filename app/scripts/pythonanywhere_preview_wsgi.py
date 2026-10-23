"""PythonAnywhere FREE *synthetic preview* WSGI app; NOT a campus release.

Your Web tab WSGI file should contain:
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path.home() / "lgu-smart-convocation" / "app"))
    from scripts.pythonanywhere_preview_wsgi import application

Private demo accounts, DB, and secrets must be created on the host with
scripts/create_preview_demo.py --output-dir ~/lgu-preview-private.
Never upload real student records, copy .env files into git, or set
LGU_ALLOW_DEMO_SECRETS=1 on a public host.
"""
import os
from pathlib import Path
import stat
import sys

APP_DIR = Path(__file__).resolve().parents[1]
PRIVATE_DIR = Path.home() / "lgu-preview-private"
PRIVATE_CONFIG = PRIVATE_DIR / "PRIVATE-BACKEND-ENV.txt"
PRIVATE_DB = PRIVATE_DIR / "lgu-preview.sqlite3"

# Require a dedicated location outside the code checkout, and refuse to
# start against any operator-supplied arbitrary database path.
if APP_DIR in PRIVATE_DIR.resolve().parents or PRIVATE_DIR.resolve() == APP_DIR:
    raise RuntimeError("Preview secrets and data must live outside source checkout.")
if not PRIVATE_CONFIG.is_file() or not PRIVATE_DB.is_file():
    raise RuntimeError(
        "Synthetic preview backend not provisioned. Run create_preview_demo.py "
        "in a private directory before reloading the demo web app."
    )
if PRIVATE_DB.is_symlink() or PRIVATE_CONFIG.is_symlink():
    raise RuntimeError("Refusing symlinked preview database or secret settings.")

required = {"LGU_SECRET_KEY", "LGU_HMAC_SECRET", "LGU_ADMIN_PIN"}
values = {}
for line in PRIVATE_CONFIG.read_text(encoding="utf-8").splitlines():
    if not line or line.lstrip().startswith("#"):
        continue
    if "=" not in line:
        raise RuntimeError("Invalid private preview config format.")
    key, value = line.split("=", 1)
    if key in required:
        if not value or key in values:
            raise RuntimeError("Missing or duplicate preview credential setting.")
        values[key] = value
if set(values) != required:
    raise RuntimeError("Synthetic preview credentials have not been provisioned.")

# Always require the existing v14 schema read-only. Never migrate the DB
# at web worker startup; never seed synthetic identities on each request.
os.environ.update(values)
os.environ.update({
    "LGU_APP_ENV": "production",
    "LGU_TESTING": "0",
    "LGU_ALLOW_DEMO_SECRETS": "0",
    "LGU_EMAIL_MODE": "disabled",
    "LGU_COOKIE_SECURE": "1",
    "LGU_DB_PATH": str(PRIVATE_DB),
    "LGU_STUDENT_PHOTO_DIR": str(PRIVATE_DIR / "photos"),
    "LGU_MEDALIST_PHOTO_DIR": str(PRIVATE_DIR / "medalist-photos"),
})
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
from run import app as application  # noqa: E402
