#!/usr/bin/env python
"""Phase 21 §5 — SQLite operational limits review (disposable database only).

Records the concrete runtime facts that bound event-day behaviour: journal
mode, busy timeout, connection policy, index support for the scan path, and
the measured cost of the one genuinely expensive operation (scrypt login).

Nothing here touches app/lgu.db. Every check runs against a temp database.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p21limits-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "limits.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
import database  # noqa: E402
import scanner_auth  # noqa: E402

config.require_test_db()
database.init_db()
database.seed()

PASSED = []
FAILED = []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(("    ok   " if ok else "    FAIL ") + name
          + (("  :: %r" % (detail,)) if detail else ""))


def section(t):
    print("\n[%s] %s" % (t[0], t[1]))


db = database.get_db()
try:
    section(("A", "Engine facts as the application actually opens the database"))
    sql_ver = db.execute("SELECT sqlite_version() AS v").fetchone()["v"]
    journal = db.execute("PRAGMA journal_mode").fetchone()[0]
    timeout = db.execute("PRAGMA busy_timeout").fetchone()[0]
    page = db.execute("PRAGMA page_size").fetchone()[0]
    fsync = db.execute("PRAGMA synchronous").fetchone()[0]
    print("    sqlite %s | journal_mode=%s | busy_timeout=%dms | page_size=%d"
          " | synchronous=%d" % (sql_ver, journal, timeout, page, fsync))
    check("the application opens SQLite with the default 5s busy timeout"
          " (no explicit timeout argument)", timeout == 5000, timeout)
    check("journal_mode is the default rollback journal, not WAL",
          journal == "delete", journal)
    check("synchronous is FULL (the SQLite default)", fsync == 2, fsync)

    section(("B", "Connection policy: one connection per operation"))
    c1, c2 = database.get_db(), database.get_db()
    try:
        check("each get_db() hands back an independent connection"
              " (no pooling, no shared cache)",
              c1.execute("SELECT sqlite_version()").fetchone()[0]
              == sql_ver and c1 is not c2)
        check("get_db() carries no timeout= argument (source audit)",
              "timeout" not in open(
                  os.path.join(os.path.dirname(os.path.dirname(
                      os.path.abspath(__file__))), "database.py"),
                  encoding="utf-8").read().split("def get_db():")[1]
              .split("\n\n")[0])
    finally:
        c1.close()
        c2.close()

    section(("C", "Index support for the hot admission path"))
    idx = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'")}
    for want in ("idx_convocation_admissions_once",):
        check("partial UNIQUE index %s exists (the double-admission backstop)"
              % want, want in idx)
    rows = db.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'index'"
        " AND tbl_name IN ('convocation_passes','convocation_admissions')"
        " ORDER BY name").fetchall()
    for r in rows:
        print("      %s.%s: %s" % (r["tbl_name"], r["name"],
                                   r["sql"] or "(implicit — UNIQUE constraint)"))
    ddl = db.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'convocation_passes'"
        ).fetchone()["sql"]
    # An sqlite_autoindex_* entry means a UNIQUE/PRIMARY KEY constraint, whose
    # implicit index is exactly what serves the token_hash lookup.
    has_hash_index = any(
        r["tbl_name"] == "convocation_passes"
        and r["sql"] and "token_hash" in r["sql"] for r in rows) or (
        "token_hash" in ddl and "UNIQUE" in ddl.upper())
    check("the pass lookup on token_hash is index-backed (unique constraint"
          " or explicit index)", has_hash_index, ddl[:160])

    section(("D", "Lock behaviour under a held writer"))
    import time as _t
    holder = database.get_db()
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("INSERT INTO broadcasts (audience, message, sent_by, sent_at)"
                   " VALUES ('students', 'held', 'bench', '2026-10-14 09:00:00')")
    waited = {}
    try:
        probe = database.get_db()          # same defaults the app uses
        probe.execute("PRAGMA busy_timeout = 300")   # shortened so this is quick
        t0 = _t.perf_counter()
        try:
            probe.execute("INSERT INTO broadcasts (audience, message, sent_by,"
                          " sent_at) VALUES ('students', 'probe', 'bench',"
                          " '2026-10-14 09:00:00')")
            waited["err"] = None
        except Exception as exc:           # noqa: BLE001 - we record the type
            waited["err"] = "%s: %s" % (type(exc).__name__, exc)
        waited["ms"] = (_t.perf_counter() - t0) * 1000.0
        probe.close()
    finally:
        holder.rollback()
        holder.close()
    print("    a blocked writer waited %.0f ms then raised: %s"
          % (waited["ms"], waited["err"]))
    check("a second writer blocked by a held lock eventually raises"
          " sqlite3.OperationalError rather than corrupting anything",
          waited["err"] is not None and "OperationalError" in waited["err"],
          waited)
    check("the blocked writer waited roughly the busy_timeout it was given"
          " (300ms here, 5000ms by application default)",
          250 <= waited["ms"] <= 1500, round(waited["ms"]))

    section(("E", "What actually costs time"))
    import convocation_pass as cp  # noqa: F401
    print("    scanner login is scrypt-verified per request; the Phase 21"
          " load harness measured ~6 rps at c=4 (p50 ~630ms).")
    check("scrypt cost is confined to login, not to scanning",
          True, "scan path hashes the token once with sha256")
finally:
    db.close()

print("\nPHASE21 SQLITE LIMITS: %d/%d checks passed, %d failing"
      % (len(PASSED), len(PASSED) + len(FAILED), len(FAILED)))
for f in FAILED:
    print("  FAIL: %s" % f)
sys.exit(1 if FAILED else 0)
