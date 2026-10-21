#!/usr/bin/env python
"""Database backup, verification and recovery (Phase 20 §3).

Usage (from app/):

    ..\\..\\.venv\\Scripts\\python.exe scripts\\backup_db.py create
    ..\\..\\.venv\\Scripts\\python.exe scripts\\backup_db.py create --dest D:\\backups\\convocation.db
    ..\\..\\.venv\\Scripts\\python.exe scripts\\backup_db.py verify  <backup.db>
    ..\\..\\.venv\\Scripts\\python.exe scripts\\backup_db.py restore <backup.db> --to <new.db>
    ..\\..\\.venv\\Scripts\\python.exe scripts\\backup_db.py list    --dir D:\\backups

`create` uses SQLite's online backup API, so it is safe while the application
is running. `verify` opens the artefact read-only. `restore` refuses to write
over the live database and always targets a NEW location.

This script prints sizes, digests, schema versions and row counts only. It
never prints student records, credentials or secrets, so its output is safe to
paste into an incident log.
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backup  # noqa: E402
import config  # noqa: E402


def _default_dest():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(os.path.dirname(config.DB_PATH),
                        "backups", "convocation-%s.db" % stamp)


def cmd_create(args):
    manifest = backup.backup(args.dest or _default_dest())
    print("Backup written")
    print("  file ............. %s" % manifest["path"])
    print("  size ............. %s bytes" % manifest["size"])
    print("  sha256 ........... %s" % manifest["sha256"])
    print("  schema version ... %d" % manifest["user_version"])
    print("  tables ........... %d" % len(manifest["tables"]))
    print("  rows ............. %d" % sum(manifest["row_counts"].values()))
    print("  manifest ......... %s" % (manifest["path"] + backup.MANIFEST_SUFFIX))
    print("Verify later with: scripts\\backup_db.py verify \"%s\"" % manifest["path"])
    return 0


def cmd_verify(args):
    try:
        manifest = backup.validate(args.path)
    except ValueError as exc:
        print("INVALID: %s" % exc)
        return 1
    print("Valid SQLite backup")
    print("  size ............. %s bytes" % manifest["size"])
    print("  sha256 ........... %s" % manifest["sha256"])
    print("  schema version ... %d" % manifest["user_version"])
    print("  tables ........... %d" % len(manifest["tables"]))
    print("  rows ............. %d" % sum(manifest["row_counts"].values()))
    return 0


def cmd_restore(args):
    try:
        info = backup.restore(args.path, args.to)
    except ValueError as exc:
        print("REFUSED: %s" % exc)
        return 1
    print("Restored")
    print("  source sha256 .... %s" % info["sha256"])
    print("  restored to ...... %s" % info["restored_to"])
    print("  byte-identical ... %s" % ("yes" if info["matched_source"] else "NO"))
    print("  schema version ... %d" % info["user_version"])
    print("  rows ............. %d" % sum(info["row_counts"].values()))
    print("The live database was not modified. Inspect the restored file, then")
    print("adopt it deliberately if it is correct.")
    return 0 if info["matched_source"] else 1


def cmd_list(args):
    entries = backup.list_backups(args.dir)
    if not entries:
        print("No backups in %s" % args.dir)
        return 1
    bad = 0
    for entry in entries:
        if "error" in entry:
            bad += 1
            print("  UNSAFE   %s (%s)" % (entry["path"], entry["error"]))
        else:
            print("  ok       %s  %s bytes  v%d  %d rows"
                  % (entry["path"], entry["size"], entry["user_version"],
                     sum(entry["row_counts"].values())))
    return 1 if bad else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create", help="write a consistent snapshot")
    p.add_argument("--dest", default=None, help="output file (default: app/backups/)")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("verify", help="check an artefact without modifying it")
    p.add_argument("path")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("restore", help="restore into a NEW location")
    p.add_argument("path")
    p.add_argument("--to", required=True)
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("list", help="review a backup directory")
    p.add_argument("--dir", default=os.path.join(os.path.dirname(config.DB_PATH), "backups"))
    p.set_defaults(func=cmd_list)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
