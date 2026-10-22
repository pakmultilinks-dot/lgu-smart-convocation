"""Consistent SQLite backup, validation and restore (Phase 20 §3).

Why this exists: the product had NO backup mechanism at all — `app/lgu.db`
was the only copy of every registration, admission and scanner account. This
module is the minimal workflow appropriate to a single-file SQLite deployment.

Why not `copy` the file: a plain file copy of a database under write can
capture a torn page or miss `-wal`/`-shm` state, producing an artifact that
opens fine, passes a cursory look, and is missing recent rows. `sqlite3`
exposes SQLite's online backup API, which copies page-by-page while honouring
locks, so the snapshot is transactionally consistent even while the app is
running. This is the only supported creation path here.

Safety properties this module guarantees:
  * `validate()` opens the candidate STRICTLY READ-ONLY (`mode=ro` URI), so
    verifying a backup can never modify it — nor a production file it is
    pointed at by mistake.
  * `restore()` refuses to write to the production database path. Restoring
    is a recovery operation onto a NEW location; overwriting the live file is
    never an automatic behaviour.
  * The manifest records only artefact facts (size, digest, schema version,
    table count, timestamps). No student data, no credentials, no secrets —
    a backup filename or log line can be shared safely.

Limitations stated honestly: this backs up ONE database file. It does not
capture photo assets under `app/data/`, and it is not a point-in-time
recovery story for multi-file deployments.
"""

import hashlib
import json
import os
import shutil
import sqlite3

import config
import database
import migrations

MANIFEST_SUFFIX = ".manifest.json"
_DB_MAGIC = b"SQLite format 3\x00"
_MIN_SIZE = 512  # a SQLite header plus one page


def sha256_of(path):
    """Chunked digest so a large artefact is never held in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _readonly(path):
    """Open strictly read-only; verifying must never mutate what it inspects."""
    return sqlite3.connect("file:%s?mode=ro" % os.path.abspath(path).replace("?", "%3f"),
                           uri=True,
                           # Read-only, but a concurrent writer can still make
                           # us wait for a page lock — the same bounded budget.
                           timeout=config.sqlite_busy_timeout())


def validate(path):
    """Return a manifest for a backup artefact, or raise ValueError.

    Detects the artefacts that a naive file copy actually produces: a missing
    or truncated file, a file that is not SQLite at all, a database whose
    pages fail `integrity_check`, and one whose schema version this build does
    not understand.
    """
    if not os.path.exists(path):
        raise ValueError("backup not found: %s" % path)
    size = os.path.getsize(path)
    if size < _MIN_SIZE:
        raise ValueError("backup is too small to be a SQLite database"
                         " (%d bytes): %s" % (size, path))
    with open(path, "rb") as fh:
        header = fh.read(len(_DB_MAGIC))
    if header != _DB_MAGIC:
        raise ValueError("not a SQLite database (bad file header): %s" % path)

    conn = _readonly(path)
    try:
        # A truncated or corrupt artefact makes SQLite raise rather than return
        # a failed check, and an operator running `verify` against a bad file
        # needs a clean verdict and exit code 1 — not a traceback.
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise ValueError("database is corrupt: %s" % exc)
        if result != "ok":
            raise ValueError("integrity_check failed: %s" % result)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = sorted(r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        rows = {}
        for name in tables:
            # Identifiers come from sqlite_master, not from user input; quoted
            # anyway so an unusual table name cannot break the statement.
            rows[name] = conn.execute(
                'SELECT COUNT(*) FROM "%s"' % name.replace('"', '""')).fetchone()[0]
    finally:
        conn.close()

    latest = migrations.MIGRATIONS[-1][0]
    if version > latest:
        raise ValueError("backup schema version %d is newer than this build"
                         " supports (latest: %d)" % (version, latest))

    return {"path": os.path.abspath(path), "size": size, "sha256": sha256_of(path),
            "user_version": version, "tables": tables, "row_counts": rows}


def backup(dest_path, db_path=None):
    """Write a consistent snapshot of `db_path` (default: configured DB).

    Returns the manifest of the artefact it produced, which is also written
    next to it as `<dest>.manifest.json` so an operator can re-verify a backup
    later without this module's source to hand.
    """
    src = os.path.abspath(db_path or config.DB_PATH)
    if not os.path.exists(src):
        raise ValueError("source database not found: %s" % src)
    dest_path = os.path.abspath(dest_path)
    if os.path.dirname(dest_path) and not os.path.isdir(os.path.dirname(dest_path)):
        os.makedirs(os.path.dirname(dest_path))

    conn = database.connect(src)
    try:
        dest = database.connect(dest_path)
        try:
            conn.backup(dest)  # online backup: consistent under concurrent writes
        finally:
            dest.close()
    finally:
        conn.close()

    manifest = validate(dest_path)
    manifest["source"] = src
    manifest["created_at"] = _utc_now()
    with open(dest_path + MANIFEST_SUFFIX, "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in manifest.items() if k != "path"},
                  fh, indent=2, sort_keys=True)
    return manifest


def restore(backup_path, dest_path):
    """Restore a validated backup into `dest_path`.

    Refuses to write over the production database — recovery targets a new
    location that an operator inspects before adopting.
    """
    dest = os.path.abspath(dest_path)

    # The active production DB may live on a volume rather than app/lgu.db.
    # Protect BOTH locations and their symlink/relative-path aliases. The
    # restore operator must choose a separate destination for inspection.
    def canonical(path):
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    protected = {
        canonical(config.PRODUCTION_DB_PATH),
        canonical(config.DB_PATH),
    }
    if config.is_production_db(dest) or canonical(dest) in protected:
        raise ValueError(
            "refusing to restore over the production or configured active"
            " database (%s). Restore into a separate location, inspect it,"
            " then adopt it deliberately." % dest)
    if os.path.lexists(dest):
        raise ValueError("refusing to overwrite an existing restore destination (%s). "
                         "Choose a new location for inspection." % dest)
    manifest = validate(backup_path)  # raises before any write happens
    if os.path.dirname(dest) and not os.path.isdir(os.path.dirname(dest)):
        os.makedirs(os.path.dirname(dest))
    # Exclusive creation also closes the check/copy race and refuses aliases
    # (including hard links) created after the initial destination check.
    try:
        with open(backup_path, "rb") as source, open(dest, "xb") as target:
            shutil.copyfileobj(source, target)
    except FileExistsError as exc:
        raise ValueError("refusing to overwrite an existing restore destination (%s)." % dest) from exc
    restored = validate(dest)
    return {"restored_to": restored["path"], "size": restored["size"],
            "sha256": restored["sha256"], "user_version": restored["user_version"],
            "tables": restored["tables"], "row_counts": restored["row_counts"],
            "matched_source": restored["sha256"] == manifest["sha256"]}


def list_backups(directory):
    """Manifests for every artefact in `directory`, sorted newest first."""
    if not os.path.isdir(directory):
        return []
    found = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(MANIFEST_SUFFIX):
            continue
        try:
            found.append(validate(os.path.join(directory, name)))
        except ValueError:
            found.append({"path": os.path.join(directory, name),
                          "error": "not a usable backup"})
    return sorted(found, key=lambda m: m.get("size", 0), reverse=True)


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
