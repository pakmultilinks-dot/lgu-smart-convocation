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


def requires_managed_schema():
    """Require an operator-managed schema except in explicit isolated dev/test.

    An arbitrary LGU_DB_PATH is NOT proof that a database is safe for a
    migration. Missing/misspelled LGU_APP_ENV defaults to protected behavior.
    Even a development flag cannot authorize changes to the default DB.
    """
    db_path = os.path.realpath(os.path.abspath(config.DB_PATH))
    production_path = os.path.realpath(os.path.abspath(config.PRODUCTION_DB_PATH))
    if db_path == production_path:
        return True
    mode = os.environ.get("LGU_APP_ENV", "").strip().lower()
    if mode == "production":
        return True
    if mode == "development":
        return False
    if os.environ.get("LGU_TESTING") == "1" and mode in ("", "test"):
        return False
    return True


def require_current_schema():
    """Fail closed on missing/stale managed schemas BEFORE any bootstrap.

    Production and unclassified custom database paths are read-only checked.
    Only explicitly isolated dev/test databases may auto-initialize.
    """
    if not requires_managed_schema():
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
