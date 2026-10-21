"""Isolated environment and real authentication for the older GitHub suites.

These fixtures reconcile PRs #1-#9 with Phase 14+ scanner authentication.
They never weaken application authorization or open the production database.
"""
import os
from pathlib import Path
import sys
import tempfile

_sandbox = tempfile.TemporaryDirectory(prefix="lgu-review-tests-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = str(Path(_sandbox.name) / "isolated.db")
os.environ["LGU_ALLOW_DEMO_SECRETS"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def authenticate(client, scanner=True):
    import config
    from web import routes

    routes._PIN_FAILS.clear()
    routes._GUEST_REG_ATTEMPTS.clear()
    client.environ_base["HTTP_X_ADMIN_PIN"] = config.ADMIN_PIN
    with client.session_transaction() as session:
        session["lgu_admin"] = True
    if scanner:
        from _scanner_fixture import scanner_headers
        headers = scanner_headers(client)
        client.environ_base["HTTP_X_SCANNER_TOKEN"] = headers["X-Scanner-Token"]
        return headers["X-Scanner-Token"]
