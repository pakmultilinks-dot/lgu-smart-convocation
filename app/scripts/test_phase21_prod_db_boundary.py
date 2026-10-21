#!/usr/bin/env python
"""Phase 21 §8 — prove the production database was not modified.

Read-only: the connection is opened with mode=ro. Only file metadata and a
SHA-256 digest are taken; nothing is written. The digest is compared against
the Phase 21 baseline captured in §2.
"""
import datetime
import hashlib
import os
import sqlite3
import sys

BASELINE = {
    "size": 278528,
    "mtime_ns": 1791660921839278500,
    "sha256": "820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F",
    "user_version": 6,
    "tables": 27,
}

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "lgu.db")
if not os.path.isfile(path):
    print("SKIP: production-content audit requires a local production database; "
          "source-only review does not include it. Synthetic migration tests run separately.")
    sys.exit(0)

st = os.stat(path)
digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
try:
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    tables = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
finally:
    conn.close()

now = {
    "size": st.st_size,
    "mtime_ns": st.st_mtime_ns,
    "sha256": digest.upper(),
    "user_version": user_version,
    "tables": tables,
}

print("production database: %s" % path)
print("  size         %d -> %d" % (BASELINE["size"], now["size"]))
print("  mtime_ns     %d -> %d" % (BASELINE["mtime_ns"], now["mtime_ns"]))
print("  mtime_utc    %s" % datetime.datetime.fromtimestamp(
    st.st_mtime, datetime.timezone.utc).isoformat())
print("  sha256       %s" % now["sha256"])
print("  user_version %d -> %d" % (BASELINE["user_version"], now["user_version"]))
print("  tables       %d -> %d" % (BASELINE["tables"], now["tables"]))
print("  integrity_check = %s" % integrity)

mismatch = {k: (BASELINE[k], now[k]) for k in BASELINE if BASELINE[k] != now[k]}
if mismatch or integrity != "ok":
    for k, (a, b) in mismatch.items():
        print("  !! CHANGED %s: %r -> %r" % (k, a, b))
    print("PRODUCTION DATABASE BOUNDARY: FAIL")
    sys.exit(1)
print("PRODUCTION DATABASE BOUNDARY: UNCHANGED — all %d stamp fields match"
      " the Phase 21 baseline" % len(BASELINE))
sys.exit(0)
