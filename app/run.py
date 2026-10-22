"""Entry point. Run with:  python run.py   ->  http://localhost:5000"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from database import init_db, seed  # noqa: E402
from web.routes import create_app  # noqa: E402

# Phase 35I — test execution safety: when LGU_TESTING=1 the configured
# database MUST NOT be the production file. The guard fails loudly before
# init_db/seed ever touch the database.
if os.environ.get("LGU_TESTING") == "1":
    config.require_test_db()

# Phase 20 + Phase 37 BE-002 — demo-secret guard, now a single policy in
# config.demo_secret_violation(startup=True) with TWO layered refusals:
#   1. committed demo secrets without LGU_ALLOW_DEMO_SECRETS=1 (Phase 20);
#   2. demo secrets against the PRODUCTION database — opt-in or not — so a
#      mis-set LGU_DB_PATH can never let the public defaults sign session
#      cookies or QR codes over real data (BE-002 previously checked only
#      this script, and only for case 1).
# The committed defaults are public knowledge (they are in this repository)
# and run.py binds 0.0.0.0. Checked BEFORE init_db/seed so a refused start
# never touches any database. Values are never printed — names only.
_violation = config.demo_secret_violation(startup=True)
if _violation:
    sys.stderr.write("FATAL: %s\n" % _violation)
    sys.exit(1)
if config.demo_secrets():
    print("WARNING: running with demo secrets (LGU_ALLOW_DEMO_SECRETS=1) —"
          " development only: %s" % ", ".join(config.demo_secrets()))

config.assert_production_secrets()
# Production startup is NOT a migration command. A stale/missing database
# must be refused before init_db() can create tables or execute migrations.
from startup_schema import require_current_schema  # noqa: E402
require_current_schema()
init_db()
seed()

app = create_app()

if __name__ == "__main__":
    # LGU_PORT lets the isolated test suite boot on a free port without
    # colliding with a production server on :5000.
    port = int(os.environ.get("LGU_PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
