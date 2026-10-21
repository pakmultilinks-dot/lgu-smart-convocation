"""Phase 38 — DB-002 (FK enforcement + concurrent guest registration) and
DB-003 (connection cleanup) on a disposable database only.

Covers:
1. connect() enables PRAGMA foreign_keys; declared REFERENCES now bind
   (a bogus convocation_admissions row is refused with FOREIGN KEY).
2. Migration v14 lands: UNIQUE index on guests(host_roll_no) + the
   scan_rejections event log; idempotent on re-run.
3. The one-guest-per-host rule enforces at the database: two concurrent
   registrations for the same host produce EXACTLY one success, and the
   loser gets the same friendly message as the sequential path.
4. Connection cleanup: database.connection() and models helpers close
   their handle even when a statement raises mid-function (fault
   injection via a wrapping connect()).
5. Production DB re-stamp: sha256/size/user_version untouched (read-only).

The production DB is never opened for writing; every behavioural check
runs against a temp database via LGU_TESTING=1 + LGU_DB_PATH.
"""
import hashlib
import os
import sqlite3
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p38db-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "p38.db")
os.environ["LGU_ALLOW_DEMO_SECRETS"] = "1"

from _production_boundary import production_stamp
_PRODUCTION_BEFORE = production_stamp()

import config                      # noqa: E402
import database                    # noqa: E402
import ids                         # noqa: E402
import migrations                  # noqa: E402
import models                      # noqa: E402

config.require_test_db()
database.init_db()
database.seed()

PASS = 0
FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok   " + label)
    else:
        FAIL += 1
        print("FAIL " + label + (("  <- " + repr(extra)) if extra else ""))


print("=" * 70)
print("Phase 38 — DB-002 FK/concurrency + DB-003 connection cleanup")
print("disposable DB:", os.environ["LGU_DB_PATH"])
print("=" * 70)

# ---------------------------------------------------- 1. FK enforcement
print("\n[1] Foreign keys are ON for every application connection")
db = database.connect()
fk = db.execute("PRAGMA foreign_keys").fetchone()[0]
db.close()
check("connect() reports PRAGMA foreign_keys = 1", fk == 1, fk)

db = database.connect()
try:
    db.execute(
        "INSERT INTO convocation_admissions (pass_id, convocation_id,"
        " registration_id, gate_id, volunteer, admitted_at)"
        " VALUES (99999, 99999, 99999, 1, 'probe', '2026-01-01 00:00:00')")
    db.commit()
    fk_blocked = False
    fk_err = ""
except Exception as exc:            # noqa: BLE001 — assertion below
    fk_blocked = "FOREIGN KEY" in str(exc).upper()
    fk_err = str(exc)
    db.rollback()
finally:
    db.close()
check("bogus admission row refused by FOREIGN KEY constraint",
      fk_blocked, fk_err)

# ------------------------------------------------------- 2. migration v14
print("\n[2] Migration v14 (host unique index + scan_rejections log)")
db = database.connect()
ver = db.execute("PRAGMA user_version").fetchone()[0]
again = migrations.migrate(db)
idx = [r["name"] for r in db.execute(
    "PRAGMA index_list(guests)").fetchall()]
tables = {r[0] for r in db.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
db.close()
check("user_version advanced to 14", ver == 14 and again == 14, (ver, again))
check("idx_guests_host_once exists and is unique", "idx_guests_host_once" in idx, idx)
check("scan_rejections table exists", "scan_rejections" in tables, tables)
db = database.connect()
migrations.migrate(db)              # idempotent re-run
ver2 = db.execute("PRAGMA user_version").fetchone()[0]
try:
    db.execute("INSERT INTO scan_rejections (occurred_at, title)"
               " VALUES ('2026-01-01 00:00:00', 'probe')")
    db.commit()
    log_ok = True
except Exception:                   # noqa: BLE001
    log_ok = False
    db.rollback()
db.close()
check("re-run is a no-op at version 14", ver2 == 14, ver2)
check("scan_rejections accepts an event row", log_ok)

# ------------------------------------- 3. host uniqueness + concurrency
print("\n[3] One guest per host — sequential and CONCURRENT registration")
db = database.connect()
row = db.execute("SELECT roll_no FROM students WHERE qr_id IS NOT NULL"
                 " AND roll_no NOT IN (SELECT host_roll_no FROM guests)"
                 " ORDER BY roll_no LIMIT 1").fetchone()
db.close()
HOST = row["roll_no"]

gid1, err1 = models.register_guest("P38 Guest A", "0300 1110001", HOST,
                                   ids.generate_id)
gid2, err2 = models.register_guest("P38 Guest B", "0300 1110002", HOST,
                                   ids.generate_id)
check("first registration succeeds", gid1 is not None and err1 is None,
      (gid1, err1))
check("second registration refused with the friendly message",
      gid1 is not None and gid2 is None
      and err2 == "This student already has a guest registered.",
      (gid2, err2))

# Raw duplicate insert must be refused by the INDEX itself (not app code).
db = database.connect()
try:
    db.execute("INSERT INTO guests (name, phone, host_roll_no, qr_id,"
               " created_at, status) VALUES ('Raw Dup', '0300 1110003', ?,"
               " ?, '2026-01-01 00:00:00', 'active')", (HOST, ids.generate_id()))
    db.commit()
    idx_blocked, idx_err = False, ""
except Exception as exc:            # noqa: BLE001
    idx_blocked, idx_err = True, str(exc)
    db.rollback()
finally:
    db.close()
check("UNIQUE index refuses a duplicate host at INSERT time", idx_blocked,
      idx_err)

# Concurrency: two threads race the SAME host. Exactly one may win; the
# loser must surface the same friendly message whether it lost at the
# check or at the INSERT (IntegrityError backstop).
HOST2 = None
db = database.connect()
row = db.execute("SELECT roll_no FROM students WHERE qr_id IS NOT NULL"
                 " AND roll_no NOT IN (SELECT host_roll_no FROM guests)"
                 " AND roll_no != ? ORDER BY roll_no LIMIT 1",
                 (HOST,)).fetchone()
db.close()
HOST2 = row["roll_no"]
barrier = threading.Barrier(2)
results = []


def racer(tag):
    barrier.wait()
    try:
        results.append(models.register_guest(
            "P38 Racer %s" % tag, "0300 222000%s" % tag, HOST2,
            ids.generate_id))
    except Exception as exc:        # noqa: BLE001 — recorded as failure
        results.append((None, "EXC:%s" % exc))


threads = [threading.Thread(target=racer, args=(i,)) for i in (1, 2)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=30)
wins = [r for r in results if r[0] is not None]
losses = [r for r in results if r[0] is None]
check("concurrent race: exactly one registration wins", len(wins) == 1,
      results)
check("concurrent race: loser gets the friendly host message",
      len(losses) == 1 and losses[0][1]
      == "This student already has a guest registered.", results)
db = database.connect()
n = db.execute("SELECT COUNT(*) FROM guests WHERE host_roll_no = ?",
               (HOST2,)).fetchone()[0]
db.close()
check("concurrent race: exactly one guest row persisted", n == 1, n)

# --------------------------------------------- 4. connection cleanup
print("\n[4] Connection cleanup (fault injection)")


class TrackedConn:
    """Delegating wrapper that records whether close() ran."""

    def __init__(self, real):
        self._real = real
        self.closed = False

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        self.closed = True
        return self._real.close()


real_connect = database.connect
tracked = []


def failing_connect(when="commit"):
    """connect() replacement whose `when` operation raises busy."""
    def _connect(*a, **k):
        c = TrackedConn(real_connect(*a, **k))
        tracked.append(c)

        def boom(*args, **kw):
            raise sqlite3.OperationalError("database is locked")

        setattr(c, when, boom)
        return c
    return _connect


# database.connection() must close even when the body raises.
database.connect = failing_connect("commit")
try:
    try:
        with database.connection() as c:
            raise RuntimeError("mid-function failure")
    except RuntimeError:
        pass
    check("database.connection() closes on exception",
          tracked and tracked[-1].closed, tracked)

    # models.record_scan: commit raises busy -> handle must still close.
    try:
        models.record_scan("qr-p38-probe", "student", "Probe", 1, "entry",
                           "P38", scanned_at="2026-01-01 00:00:00")
        raised = False
    except Exception:               # noqa: BLE001
        raised = True
    check("record_scan propagates the busy error", raised)
    check("record_scan closed its connection despite the error",
          tracked and tracked[-1].closed, tracked)
finally:
    database.connect = real_connect

# Read path: dashboard_summary never commits, so fail the FIRST execute.
database.connect = failing_connect("execute")
try:
    try:
        models.dashboard_summary()
        raised2 = False
    except Exception:               # noqa: BLE001
        raised2 = True
    check("dashboard_summary propagates the busy error", raised2)
    check("dashboard_summary closed its connection despite the error",
          tracked and tracked[-1].closed, tracked)
finally:
    database.connect = real_connect

# Happy path still works after restore.
summary = models.dashboard_summary()
check("dashboard_summary works after restore",
      isinstance(summary, dict) and "inside_total" in summary)

# ------------------------------------------------- 5. production re-stamp
print("\n[5] Production database untouched (read-only re-stamp)")
PROD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "lgu.db")
check("production database unchanged or remains absent",
      production_stamp() == _PRODUCTION_BEFORE)
print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)