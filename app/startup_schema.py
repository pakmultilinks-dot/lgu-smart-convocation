"""Read-only schema gate for application startup.

A production-mode launch must not silently run pending SQLite migrations.
The dedicated approval/backup/migration procedure belongs to an operator,
not to application startup. This module never opens a writable connection.
"""
import os
import sqlite3
from contextlib import closing
from urllib.request import pathname2url

import config
import migrations


def require_current_schema():
    """Fail closed on missing/stale production schemas BEFORE init_db/seed.

    Production includes explicit LGU_APP_ENV=production and the historical
    default database path even if the environment flag is accidentally absent.
    Synthetic development/test databases remain bootstrap-compatible.
    """
    production = (
        os.environ.get("LGU_APP_ENV", "").strip().lower() == "production"
        or config.is_production_db()
    )
    if not production:
        return None

    latest = migrations.MIGRATIONS[-1][0]
    path = os.path.abspath(config.DB_PATH)
    # immutable=1 ensures this check cannot create a WAL/SHM sidecar;
    # it must be performed on a quiescent database during deployment.
    uri = "file:" + pathname2url(path) + "?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError(
            "Refusing production startup: schema cannot be verified read-only. "
            "An operator must verify the database and migration approval "
            "before bootstrapping (%s)." % type(exc).__name__
        ) from None
    if version != latest:
        raise RuntimeError(
            "Refusing production startup: schema version %d, required %d. "
            "A verified backup and explicit migration approval are required; "
            "never migrate implicitly during startup." % (version, latest)
        )
    return version
