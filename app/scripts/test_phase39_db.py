"""Phase 39 STEP 6 — database testing on a DISPOSABLE database.

Mandate item 6: migration chain, backup/restore, foreign keys, unique
constraints, concurrent writes, rollback, connection cleanup, integrity,
attendance aggregation, busy/lock retries — plus the Q-1 regression
(medalist edit/publish/photo connection leak, counting proxy around
``database.connect``).

NEVER touches production ``app/lgu.db``: LGU_DB_PATH points at a temp file
and the production file is only read (sha256/size/user_version) at start and
end. Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase39_db.py
Exit code 1 if any check fails.
"""

import hashlib
import io
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p39db-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "p39.db")
os.environ["LGU_ALLOW_DEMO_SECRETS"] = "1"

import config  # noqa: E402

config.require_test_db()

import database  # noqa: E402
import exam_auth  # noqa: E402
import ids  # noqa: E402
import migrations  # noqa: E402
import models  # noqa: E402
import scanner_auth  # noqa: E402
import backup  # noqa: E402
from web.routes import create_app  # noqa: E402

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------------------- prod stamp
_PROD = config.PRODUCTION_DB_PATH
_PROD_STAMP = None
_PROD_SHA = None
if os.path.exists(_PROD):
    _s = os.stat(_PROD)
    _PROD_STAMP = (_s.st_size, _s.st_mtime_ns)
    with open(_PROD, "rb") as fh:
        _PROD_SHA = hashlib.sha256(fh.read()).hexdigest()

database.init_db()
database.seed()

OFFICER = "qa-db-officer"
OFFICER_PW = "QA-db-Passw0rd-2026!"

with database.connection() as db:
    exam_auth.create_staff(OFFICER, "QA DB Officer", OFFICER_PW)
scanner_auth.create_scanner(username="qa-db-gate", display_name="QA DB Gate",
                             pin="739281", gate_ids=[3],
                             actor="phase39-fixture")
with database.connection() as db:
    DB_SCANNER_ID = db.execute(
        "SELECT id FROM scanner_users WHERE username = ?",
        ("qa-db-gate",)).fetchone()["id"]

app = create_app()
app.config.update(TESTING=True)
client = app.test_client()

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    if not cond:
        print("  FAIL %s  %r" % (name, detail))


def step(n, title):
    print("\n[%02d] %s" % (n, title))


def txt(r):
    return r.get_data(as_text=True)


def csrf_of(path):
    m = re.search(r'name="csrf_token" value="([^"]+)"', txt(client.get(path)))
    return m.group(1) if m else ""


def exam_login():
    tok = csrf_of("/exam/login")
    return client.post("/exam/login", data={"username": OFFICER,
                                            "password": OFFICER_PW,
                                            "csrf_token": tok})


def backup_tool(*args):
    p = subprocess.run([sys.executable, os.path.join("scripts",
                                                     "backup_db.py")] +
                       list(args),
                       cwd=APP_DIR, capture_output=True, text=True,
                       errors="replace", env=dict(os.environ))
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


# --------------------------------------------- connection tracking proxy
class _TrackedConn:
    """Delegating wrapper so a never-closed SQLite connection stays alive
    (and visible) instead of being silently GC-closed."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_closed", False)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_real"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_real"), name, value)

    def close(self):
        object.__setattr__(self, "_closed", True)
        return object.__getattribute__(self, "_real").close()

    @property
    def closed(self):
        return object.__getattribute__(self, "_closed")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def track_open():
    state = {"conns": []}
    orig = database.connect

    def wrapper(path=None):
        t = _TrackedConn(orig(path))
        state["conns"].append(t)
        return t

    database.connect = wrapper      # get_db() and connection() both funnel here
    return orig, state


def untracked_unclosed(state):
    return [c for c in state["conns"] if not c.closed]


def restore_connect(orig, state):
    database.connect = orig
    for c in state["conns"]:
        try:
            c.close()
        except Exception:  # noqa: BLE001 - cleanup must not mask results
            pass
    state["conns"].clear()


SCAN_SQL = ("INSERT INTO scans (qr_id, person_type, person_name, gate_id,"
            " mode, volunteer, scanned_at) VALUES (?,?,?,?,?,?,?)")


def put_scan(db, qr, mode, stamp, gate=7):
    db.execute(SCAN_SQL, (qr, "student", "QA DB Probe", gate, mode,
                          "phase39-db", stamp))


# ================================================= 01 migration chain
step(1, "Migration chain on a fresh disposable file")
chain = os.path.join(_TMP, "chain.db")
c = sqlite3.connect(chain)
c.executescript(database.SCHEMA)
ver = migrations.migrate(c)
latest = [v for v, _ in migrations.MIGRATIONS][-1]
check("fresh chain reaches latest migration", ver == latest,
      "v%s vs latest v%s" % (ver, latest))
check("this build expects schema v14", ver == 14, ver)
check("migrate() re-run is a no-op", migrations.migrate(c) == ver)
ic = c.execute("PRAGMA integrity_check").fetchone()[0]
check("fresh DB integrity ok", ic == "ok", ic)
tables = {r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
need = {"students", "guests", "scans", "gates", "convocations", "settings",
        "medalists", "staff_users", "student_accounts"}
check("required tables present", need <= tables, sorted(need - tables))
check("support table present", any("support" in t for t in tables))
fk = c.execute("PRAGMA foreign_key_check").fetchall()
check("no dangling FKs in fresh schema", not fk, len(fk))
c.close()

# ================================================= 02 backup / restore
step(2, "Backup, verification, restore (scripts/backup_db.py)")
b1 = os.path.join(_TMP, "b1.db")
rc, log = backup_tool("create", "--dest", b1)
check("backup create ok", rc == 0 and os.path.exists(b1), log[-200:])
rc, log = backup_tool("verify", b1)
check("backup verify ok", rc == 0, log[-200:])
# In-process refusal gate: backup.restore() must refuse a production dest
# BEFORE any write. The check runs against a sentinel path with
# is_production_db patched, so app/lgu.db is never even opened for writing.
sentinel = os.path.join(_TMP, "sentinel-never-written.db")
_orig_prod_guard = config.is_production_db
refusal = None
try:
    config.is_production_db = lambda p: True
    try:
        backup.restore(b1, sentinel)
    except ValueError as exc:
        refusal = str(exc)
finally:
    config.is_production_db = _orig_prod_guard
check("restore refuses a production-style destination", bool(refusal),
      refusal)
check("refusal happened before any write", not os.path.exists(sentinel))
with database.connection() as db:
    s0 = db.execute("SELECT COUNT(*) c FROM students").fetchone()["c"]
    db.execute("DELETE FROM students WHERE roll_no = 'LGU-2024-140'")
    db.commit()
r1 = os.path.join(_TMP, "restored.db")
rc, log = backup_tool("restore", b1, "--to", r1)
check("restore to a new file ok", rc == 0, log[-200:])
if os.path.exists(r1):
    ro = sqlite3.connect("file:%s?mode=ro" % r1.replace("\\", "/"), uri=True)
    s1 = ro.execute("SELECT COUNT(*) c FROM students").fetchone()[0]
    uv = ro.execute("PRAGMA user_version").fetchone()[0]
    ic = ro.execute("PRAGMA integrity_check").fetchone()[0]
    ro.close()
    check("restored row counts match pre-mutation", s1 == s0,
          "%s vs %s" % (s1, s0))
    check("restored DB integrity + version", ic == "ok" and uv == 14,
          "ic=%s uv=%s" % (ic, uv))
else:
    check("restored file exists", False, r1)

# ================================================= 03 FK + integrity live
step(3, "Declared FKs enforced + integrity on the live disposable DB")
with database.connection() as db:
    # Positive control: valid (scanner, gate) pair must insert.
    pos_err = None
    try:
        db.execute("INSERT INTO scanner_gates (scanner_id, gate_id)"
                   " VALUES (?, 1)", (DB_SCANNER_ID,))
        db.commit()
        db.execute("DELETE FROM scanner_gates WHERE scanner_id = ?"
                   " AND gate_id = 1", (DB_SCANNER_ID,))
        db.commit()
    except sqlite3.Error as exc:
        db.rollback()
        pos_err = repr(exc)
    # The probe: declared REFERENCES gates(id) must reject a bogus gate.
    try:
        db.execute("INSERT INTO scanner_gates (scanner_id, gate_id)"
                   " VALUES (?, 999999)", (DB_SCANNER_ID,))
        db.rollback()
        bad = None
    except sqlite3.IntegrityError as exc:
        db.rollback()
        bad = str(exc)
    ic = db.execute("PRAGMA integrity_check").fetchone()[0]
    dangling = db.execute("PRAGMA foreign_key_check").fetchall()
check("valid scanner_gates row inserts", pos_err is None, pos_err)
check("declared FK rejects bogus gate_id", bad is not None
      and "FOREIGN KEY" in bad, bad)
check("live disposable DB integrity ok", ic == "ok", ic)
check("no dangling FKs after probes", not dangling, len(dangling))
print("  NOTE: scans.gate_id carries no REFERENCES clause - orphan gate"
      " ids are rejected by the API layer only (design observation"
      " O-DB-1, schema unchanged).")

# ================================================= 04 unique constraints
step(4, "UNIQUE constraints (settings PK, one guest per host)")
u1 = u2 = None
with database.connection() as db:
    try:
        db.execute("INSERT INTO settings (key, value, updated_at)"
                   " VALUES ('convocation_name', 'dup', '2031-01-01')")
        db.rollback()
    except sqlite3.IntegrityError as exc:
        u1 = str(exc)
    try:
        db.execute("INSERT INTO guests (name, phone, host_roll_no, qr_id,"
                   " created_at) VALUES ('QA Dup', '0300 0000000',"
                   " 'LGU-2024-101', 'DBDUP001', '2031-01-01 00:00:00')")
        db.rollback()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        u2 = str(exc)
check("settings PK rejects duplicate key", u1 and "UNIQUE" in u1, u1)
check("idx_guests_host_once rejects 2nd guest", u2 and "UNIQUE" in u2, u2)

# ================================================= 05 rollback semantics
step(5, "Rollback: exception inside connection() leaves no partial row")
KEY = "phase39_rollback_probe"
try:
    with database.connection() as db:
        db.execute("INSERT INTO settings (key, value, updated_at)"
                   " VALUES (?, 'x', '2031-01-01 00:00:00')", (KEY,))
        raise RuntimeError("forced rollback probe")
except RuntimeError:
    pass
with database.connection() as db:
    row = db.execute("SELECT 1 FROM settings WHERE key = ?",
                     (KEY,)).fetchone()
check("uncommitted write rolled back", row is None)

# ================================================= 06 connection cleanup
step(6, "Connection cleanup: every code path closes what it opens")
orig, state = track_open()
try:
    for _ in range(20):
        with database.connection() as db:
            db.execute("SELECT 1").fetchone()
    try:
        with database.connection() as db:
            db.execute("SELECT 1").fetchone()
            raise RuntimeError("forced mid-transaction failure")
    except RuntimeError:
        pass
    for _ in range(5):
        d = database.get_db()
        d.execute("SELECT 1").fetchone()
        d.close()
    open_n = len(untracked_unclosed(state))
    check("all tracked connections closed", open_n == 0, "open=%d" % open_n)
finally:
    restore_connect(orig, state)

# ================================================= 07 Q-1 leak regression
step(7, "Q-1: medalist edit/publish/photo must not leak a connection")
r = exam_login()
check("exam staff login", r.status_code in (302, 200), r.status_code)
tok = csrf_of("/exam/medalists/new")
r = client.post("/exam/medalists/new", data={
    "csrf_token": tok, "department": "Database QA",
    "student_name": "QA DB Medalist", "award_category": "gold",
    "position": ""})
check("medalist fixture created", r.status_code == 302, r.status_code)
mid_m = re.search(r"/exam/medalists/(\d+)", r.headers.get("Location", ""))
check("medalist id parsed", bool(mid_m), r.headers.get("Location"))
mid = mid_m.group(1) if mid_m else "0"
orig, state = track_open()
try:
    tok = csrf_of("/exam/medalists/%s" % mid)
    r_edit = client.post("/exam/medalists/%s/edit" % mid, data={
        "csrf_token": tok, "department": "Database QA",
        "student_name": "QA DB Medalist", "award_category": "gold",
        "position": "1"})
    tok = csrf_of("/exam/medalists/%s" % mid)
    r_pub = client.post("/exam/medalists/%s/publish" % mid,
                        data={"csrf_token": tok})
    tok = csrf_of("/exam/medalists/%s" % mid)
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
           b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
           b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
           b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
    r_ph = client.post("/exam/medalists/%s/photo" % mid, data={
        "csrf_token": tok,
        "photo": (io.BytesIO(png), "qa.png")},
        content_type="multipart/form-data")
    for label, rr in (("edit", r_edit), ("publish", r_pub),
                      ("photo", r_ph)):
        check("medalist %s POST handled" % label,
              rr.status_code in (200, 400), rr.status_code)
    leaked = len(untracked_unclosed(state))
    check("Q-1: no connection leaked by edit/publish/photo", leaked == 0,
          "leaked=%d" % leaked)
finally:
    restore_connect(orig, state)

# ================================================= 08 concurrent guests
step(8, "Concurrent writes: same-host guest race -> exactly 1 winner")
race = []


def _race(i):
    try:
        gid, err = models.register_guest("QA Racer %d" % i,
                                         "0300 9998877", "LGU-2024-102",
                                         ids.generate_id)
        race.append((gid, err))
    except Exception as exc:  # noqa: BLE001 - record, never hide
        race.append((None, "EXC:%s" % exc))


threads = [threading.Thread(target=_race, args=(i,)) for i in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=30)
winners = [r for r in race if r[0]]
losers = [r for r in race if not r[0]]
check("same-host race: exactly 1 winner", len(winners) == 1, race)
check("all losers got the duplicate-host answer",
      len(losers) == 3 and all("already has a guest" in (e or "")
                               for _, e in losers), losers)
with database.connection() as db:
    rows = db.execute("SELECT COUNT(*) c FROM guests WHERE host_roll_no = ?",
                      ("LGU-2024-102",)).fetchone()["c"]
check("exactly one guest row for the host", rows == 1, rows)

# ================================================= 09 busy / lock retries
step(9, "Contended writes under the busy timeout (locking + retries)")
NB_THREADS, NB_EACH = 6, 20
werr = []


def _writer(t):
    try:
        for i in range(NB_EACH):
            with database.connection() as db:
                put_scan(db, "LOAD%01d%02d" % (t, i), "entry",
                         "2031-01-02 %02d:%02d:%02d" % (t, i % 60, i % 60))
                db.commit()
    except Exception as exc:  # noqa: BLE001
        werr.append(repr(exc))


t0 = time.time()
threads = [threading.Thread(target=_writer, args=(t,))
           for t in range(NB_THREADS)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=60)
dt_ms = int((time.time() - t0) * 1000)
with database.connection() as db:
    landed = db.execute(
        "SELECT COUNT(*) c FROM scans WHERE qr_id LIKE 'LOAD%'"
    ).fetchone()["c"]
expected = NB_THREADS * NB_EACH
check("all contended writes landed", landed == expected and not werr,
      "landed=%d/%d errs=%d %s" % (landed, expected, len(werr), werr[:2]))
print("  measured: %d writes from %d threads in %d ms (avg %.1f ms/write)"
      % (landed, NB_THREADS, dt_ms,
         (dt_ms / landed) if landed else 0))

# ================================================= 10 attendance aggregate
step(10, "Attendance aggregation: latest-scan-wins occupancy")
with database.connection() as db:
    q = [r["qr_id"] for r in db.execute(
        "SELECT qr_id FROM students WHERE roll_no IN"
        " ('LGU-2024-101','LGU-2024-103','LGU-2024-104') ORDER BY roll_no")]
check("three seeded students resolved", len(q) == 3, q)
before = models.dashboard_summary()["inside_total"] if len(q) == 3 else None
if len(q) == 3:
    q1, q2, q3 = q
    with database.connection() as db:
        put_scan(db, q1, "entry", "2031-01-03 08:00:00")   # re-enters twice
        put_scan(db, q1, "entry", "2031-01-03 08:00:01")
        put_scan(db, q2, "entry", "2031-01-03 08:00:02")
        put_scan(db, q2, "exit", "2031-01-03 08:00:03")    # ends outside
        put_scan(db, q3, "entry", "2031-01-03 08:00:04")   # stays inside
        db.commit()
    after = models.dashboard_summary()["inside_total"]
    delta = after - before
    with database.connection() as db:
        gross = db.execute(
            "SELECT COALESCE(SUM(mode = 'entry'), 0) -"
            " COALESCE(SUM(mode = 'exit'), 0) g FROM scans"
            " WHERE qr_id IN (?,?,?)", (q1, q2, q3)).fetchone()["g"]
    # gross event arithmetic: 4 entries - 1 exit = 3; occupancy must
    # dedupe to q1 in + q3 in = 2 (latest scan per person wins).
    check("inside_total counts people, not events (delta 2)", delta == 2,
          "delta=%s (before=%s after=%s)" % (delta, before, after))
    check("gross arithmetic gives 3 while occupancy gives 2",
          gross == 3 and delta == 2, "gross=%s delta=%s" % (gross, delta))
else:
    check("attendance probe ran", False, "students missing")

# ================================================= 11 prod DB isolation
step(11, "Production database isolation")
if _PROD_STAMP is None:
    check("production database remains absent", not os.path.exists(_PROD))
else:
    _s = os.stat(_PROD)
    check("prod size + mtime unchanged",
          (_s.st_size, _s.st_mtime_ns) == _PROD_STAMP)
    with open(_PROD, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    check("prod sha256 unchanged", digest == _PROD_SHA, digest)

# ================================================================== done
print("\nDisposable DB: %s" % os.environ["LGU_DB_PATH"])
failed = [n for n, ok in RESULTS if not ok]
print("\n%d checks, %d failures" % (len(RESULTS), len(failed)))
for n in failed:
    print("  FAILED: %s" % n)
sys.exit(1 if failed else 0)
