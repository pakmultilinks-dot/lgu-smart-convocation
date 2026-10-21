#!/usr/bin/env python
"""Phase 21 §3/§4 — SYNTHETIC event-day load benchmark and resilience probes.

Everything here runs against a disposable database built from scratch with
synthetic records. Nothing is derived from production and production is never
opened. This is a SYNTHETIC BENCHMARK: no institutional demand estimate or
approved SLA has been supplied, so the numbers below are measurements, not a
capacity commitment (see docs/OPERATIONS.md §9).

Acceptance thresholds are declared UP FRONT so results cannot be read to fit
the numbers:

  T1  ZERO unhandled exceptions (HTTP 500) and ZERO SQLite busy/locked errors
      at every tested concurrency. A 500 at a gate on event day stops a queue.
  T2  ZERO duplicate admissions: a pass is admitted exactly once, ever, no
      matter how many gates race it.
  T3  Latency and throughput are RECORDED, not judged — production-capacity
      approval is PENDING until an institutional demand estimate exists.

Run from app/:  ..\\..\\.venv\\Scripts\\python.exe scripts\\test_phase21_load_resilience.py
"""
import json
import logging
import os
import shutil
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p21load-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "load.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config  # noqa: E402
import convocation_pass as cp  # noqa: E402
import convocation_qr as cqr  # noqa: E402
import database  # noqa: E402
import scanner_auth  # noqa: E402
import student_auth as sa  # noqa: E402

config.require_test_db()

# This harness deliberately provokes 5xx responses and counts them. Flask's
# per-request traceback log would bury the report, so drop it to WARNING;
# run_load still records every unhandled exception in RESULTS.
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("flask.app").setLevel(logging.ERROR)

try:
    import psutil  # type: ignore
    _PROC = psutil.Process()
except Exception:  # pragma: no cover - optional measurement
    psutil = None
    _PROC = None

RESULTS = []
REPORT = {"environment": {}, "workloads": [], "resilience": {}}

# ---- declared BEFORE measuring (see module docstring) ----
T1_MAX_500 = 0
T1_MAX_DB_ERRORS = 0
T2_MAX_DUPLICATES = 0

DEPTS = ["Computer Science", "Software Engineering", "Business Administration",
         "English", "Psychology", "Mass Communication", "Mathematics",
         "Physics"]
N_REG = 3000
N_LEGACY_STUDENTS = 500
CONCURRENCIES = [1, 4, 8]


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    if not cond:
        print("  FAIL %s %s" % (name, detail))


def step(n, title):
    print("\n[%s] %s" % (n, title))


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------- fixtures
def build_world():
    """Synthetic event: N registrations, accounts, passes, scanners, roster."""
    database.init_db()
    database.seed()
    db = database.get_db()
    conv = db.execute("SELECT id FROM convocations WHERE is_active = 1").fetchone()["id"]
    stamp = now()
    try:
        for i in range(N_REG):
            db.execute(
                "INSERT INTO convocation_registrations (convocation_id,"
                " registration_number, university_email, roll_number,"
                " student_name, department, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (conv, "REG-%05d" % i, "bench%05d@lgu.edu.pk" % i,
                 "ROLL-%05d" % i, "Benchmark Student %05d" % i,
                 DEPTS[i % len(DEPTS)], stamp, stamp))
        db.commit()
        regs = db.execute("SELECT id, university_email FROM"
                          " convocation_registrations WHERE convocation_id = ?"
                          " ORDER BY id", (conv,)).fetchall()
        for r in regs:
            db.execute("INSERT INTO student_accounts (university_email,"
                       " password_hash, created_at, updated_at)"
                       " VALUES (?, 'scrypt$benchmark', ?, ?)",
                       (r["university_email"], stamp, stamp))
        db.commit()
        acc = {row["university_email"]: row["id"] for row in db.execute(
            "SELECT id, university_email FROM student_accounts").fetchall()}
        for r in regs:
            a = acc[r["university_email"]]
            db.execute("INSERT INTO registration_claims (account_id,"
                       " convocation_id, registration_id, created_at)"
                       " VALUES (?, ?, ?, ?)", (a, conv, r["id"], stamp))
            db.execute("INSERT INTO convocation_passes (token_hash,"
                       " convocation_id, registration_id, account_id, status,"
                       " issued_at) VALUES (?, ?, ?, ?, 'active', ?)",
                       ("pass-hash-%05d" % r["id"], conv, r["id"], a, stamp))
        # convocation_qr re-derives eligibility at scan time and refuses while
        # the event is unpublished, so the world needs a published snapshot.
        import convocation_events as ev
        ev.publish(db, db.execute("SELECT * FROM convocations WHERE id = ?",
                                  (conv,)).fetchone(), "bench")
        # Legacy operational roster for the /api/scan (LGU1) path.
        for i in range(N_LEGACY_STUDENTS):
            db.execute("INSERT INTO students (roll_no, name, gender, program,"
                       " qr_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                       ("BENCH-%05d" % i, "Roster Student %05d" % i,
                        "Male" if i % 2 else "Female", "BS Bench",
                        "BQR%07d" % i, stamp))
        db.commit()
    finally:
        db.close()
    return conv


def pass_tokens(conv, limit):
    """Plaintext pass tokens are never stored, so rewrite each row's hash to a
    known synthetic token. One connection, one pass — 2500 separate open/close
    cycles would measure the fixture, not the application."""
    db = database.get_db()
    out = []
    try:
        ids = [r["id"] for r in db.execute(
            "SELECT id FROM convocation_passes WHERE convocation_id = ?"
            " AND status = 'active' ORDER BY id LIMIT ?", (conv, limit))]
        for pid in ids:
            token = "bench-pass-token-%05d" % pid
            db.execute("UPDATE convocation_passes SET token_hash = ? WHERE id = ?",
                       (cqr.token_hash(token), pid))
            out.append("LGU2:" + token)
        db.commit()
    finally:
        db.close()
    return out


def scanners():
    """One scanner per gate, plus sessions. Returns [(token, gates, label)]."""
    out = []
    for i in range(1, 8):
        sid = scanner_auth.create_scanner(
            "bench-gate-%d" % i, "Gate %d Volunteer" % i,
            pin="BENCHPIN%d" % i, gate_ids=[i], actor="bench", via="test")
        token, _ = scanner_auth.create_session(sid)
        out.append((token, [i], "Gate %d" % i))
    sid = scanner_auth.create_scanner("bench-rover", "Rover Volunteer",
                                      pin="BENCHPIN9", gate_ids=list(range(1, 8)),
                                      actor="bench", via="test")
    token, _ = scanner_auth.create_session(sid)
    out.append((token, list(range(1, 8)), "Rover"))
    return out


# ------------------------------------------------------------- the runner
DB_ERROR_MARKERS = ("database is locked", "database is busy", "locking protocol",
                    "disk i/o error", "database table is locked", "attempt to")


def run_load(app, label, threads, per_thread, call, payload_mix=None):
    """Drive `call(client, i)` from `threads` workers, `per_thread` each."""
    lat, codes, db_errs, unhandled = [], [], [], []

    def worker(wid):
        client = app.test_client()
        for i in range(per_thread):
            t0 = time.perf_counter()
            try:
                r = call(client, wid, i)
                codes.append(r.status_code)
                if r.status_code >= 500:
                    unhandled.append((r.status_code, r.data[:120]))
            except sqlite3.OperationalError as exc:
                db_errs.append(str(exc))
            except Exception as exc:  # noqa: BLE001 - counted, not swallowed
                unhandled.append((type(exc).__name__, str(exc)[:120]))
            lat.append((time.perf_counter() - t0) * 1000.0)

    wall = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(worker, range(threads)))
    wall = time.perf_counter() - wall

    total = threads * per_thread
    ok = sum(1 for c in codes if 200 <= c < 400)
    client_err = sum(1 for c in codes if 400 <= c < 500)
    lat_sorted = sorted(lat)
    rec = {
        "workload": label, "concurrency": threads, "requests": total,
        "ok": ok, "client_4xx": client_err, "unhandled_5xx_or_exc": len(unhandled),
        "sqlite_errors": len(db_errs), "sqlite_error_samples": sorted(set(db_errs))[:3],
        "duration_s": round(wall, 3),
        "throughput_rps": round(total / wall, 1) if wall else 0,
        "p50_ms": round(statistics.median(lat), 2) if lat else 0,
        "p95_ms": round(lat_sorted[int(len(lat_sorted) * 0.95) - 1], 2) if lat else 0,
        "max_ms": round(max(lat), 2) if lat else 0,
    }
    REPORT["workloads"].append(rec)
    print("    %-34s c=%d n=%-5d %6.1f rps  p50=%6.2fms p95=%7.2fms"
          "  4xx=%-4d 5xx=%-3d dberr=%-3d"
          % (label, threads, total, rec["throughput_rps"], rec["p50_ms"],
             rec["p95_ms"], client_err, rec["unhandled_5xx_or_exc"],
             rec["sqlite_errors"]))
    if unhandled:
        print("      sample unhandled: %s" % (unhandled[:2],))
    return rec


# ================================================================== build
step("A", "Build a synthetic event world (disposable database)")
conv = build_world()
tokens = pass_tokens(conv, 2500)
SCANNERS = scanners()
import convocation_qr as cqr  # noqa: E402
from web.routes import create_app  # noqa: E402

config.DB_PATH = os.environ["LGU_DB_PATH"]
APP = create_app()
APP.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
dbx = database.get_db()
try:
    check("world: registrations loaded",
          dbx.execute("SELECT COUNT(*) FROM convocation_registrations"
                      ).fetchone()[0] == N_REG)
finally:
    dbx.close()
check("world: active passes minted", len(tokens) >= 2000, len(tokens))
check("world: one scanner per gate plus a rover", len(SCANNERS) == 8)

size_before = os.path.getsize(config.DB_PATH)
REPORT["environment"] = {
    "python": sys.version.split()[0], "platform": sys.platform,
    "logical_cpus": os.cpu_count(),
    "registrations": N_REG, "legacy_roster": N_LEGACY_STUDENTS,
    "passes_minted": len(tokens), "gates": 7,
    "journal_mode": "rollback (SQLite default — no PRAGMA journal_mode set)",
    "sqlite_python_default_timeout_s": sqlite3.connect(":memory:").execute(
        "PRAGMA busy_timeout").fetchone()[0] / 1000.0,
    "db_bytes_before": size_before,
    "harness": "Flask test client (in-process WSGI, no socket/TLS overhead)",
    "measured_cpu_time_s": None, "peak_rss_mb": None,
}
print("    world: %d registrations, %d passes, %d scanners, db=%d bytes"
      % (N_REG, len(tokens), len(SCANNERS), size_before))

# ============================================================= S1..S5 reads
step("B", "Ordinary convocation traffic (reads)")
ROVER_TOKEN, ROVER_GATES, _ = SCANNERS[-1]


def api_reads(client, wid, i):
    return [client.get("/api/health"), client.get("/api/gates"),
            client.get("/api/config"), client.get("/api/dashboard"),
            client.get("/api/dashboard/summary")][i % 5]


for c in CONCURRENCIES:
    run_load(APP, "reads: health/gates/config/dashboard", c, 100, api_reads)


def student_reads(client, wid, i):
    """Each request mints a fresh session (the real signup/login cost) then
    reads the four student surfaces that run on event day."""
    dbx = database.get_db()
    try:
        row = dbx.execute("SELECT id FROM student_accounts ORDER BY id LIMIT 1"
                          " OFFSET ?", (wid * 3 + (i % 3),)).fetchone()
        token, _ = sa.issue_session(dbx, row["id"])
        dbx.commit()
    finally:
        dbx.close()
    h = {"Authorization": "Bearer %s" % token}
    return [client.get("/api/student/me", headers=h),
            client.get("/api/student/event", headers=h),
            client.get("/api/student/announcements", headers=h),
            client.get("/api/student/readiness", headers=h),
            client.get("/api/student/medalists", headers=h)][i % 5]


for c in CONCURRENCIES:
    run_load(APP, "reads: student event/readiness/feed", c, 60, student_reads)


def search_reads(client, wid, i):
    # Phase 34: /api/search now rides the scanner session (it carries guest
    # PII + once leaked the qr_id credential), so the workload authenticates
    # with a real scanner token to keep measuring actual lookup latency.
    dept = DEPTS[i % len(DEPTS)].split()[0]
    return client.get("/api/search?q=%s" % dept,
                      headers={"X-Scanner-Token": SCANNERS[0][0]})


for c in CONCURRENCIES:
    run_load(APP, "reads: registration search", c, 100, search_reads)

# ============================================================ S2 scan writes
step("C", "Gate admission traffic (writes, single scanner)")


def make_scanner_call(token, gate):
    def call(client, wid, i):
        idx = (wid * 50 + i) % len(tokens)
        return client.post("/api/scan",
                           json={"payload": tokens[idx], "gate_id": gate,
                                 "mode": "entry"},
                           headers={"X-Scanner-Token": token})
    return call


first_token, _, _ = SCANNERS[0]
for c in CONCURRENCIES:
    run_load(APP, "scan: gate 1 traffic (fresh + repeat scans)", c, 120,
             make_scanner_call(first_token, 1))

# ================================================ S3 duplicate-admission race
step("D", "Concurrent duplicate scans — the same pass at several gates")

# Section C only ever touches tokens[0:500], so the race starts from a slice
# that is still completely un-admitted: one pass for the pre-flight, then two
# disjoint 60-pass slices, one per racing concurrency level.
RACE_TOKENS = tokens[2000:2121]
DUP_TOKENS = RACE_TOKENS[:1]

# Non-vacuity proof: one synchronous scan must actually admit. Without this the
# race below would "pass" for the wrong reason (nothing ever admitting).
# Section C already wrote to the ledger, so measure the delta, not the total.
_dbP = database.get_db()
try:
    ledger_before = _dbP.execute(
        "SELECT COUNT(*) FROM convocation_admissions").fetchone()[0]
finally:
    _dbP.close()
probe = APP.test_client().post(
    "/api/scan", json={"payload": DUP_TOKENS[0], "gate_id": 1, "mode": "entry"},
    headers={"X-Scanner-Token": first_token})
dbpx = database.get_db()
try:
    probe_rows = dbpx.execute(
        "SELECT COUNT(*) FROM convocation_admissions").fetchone()[0]
    prow = dbpx.execute(
        "SELECT account_id, registration_id, convocation_id"
        " FROM convocation_passes WHERE token_hash = ?",
        (cqr.token_hash(DUP_TOKENS[0][len("LGU2:"):]),)).fetchone()
    pacc = dbpx.execute("SELECT * FROM student_accounts WHERE id = ?",
                        (prow["account_id"],)).fetchone() if prow else None
    pconv = dbpx.execute(
        "SELECT * FROM convocations WHERE id = ? AND is_active = 1",
        (prow["convocation_id"],)).fetchone() if prow else None
    pstate = (cp.pass_for_account(dbpx, pacc, pconv)["state"]
              if pacc and pconv else "no-account-or-conv")
finally:
    dbpx.close()
check("T2: a synchronous eligible scan is admitted and reaches the ledger",
      probe.status_code == 200 and probe.is_json
      and probe.get_json().get("status") == "ok"
      and probe_rows == ledger_before + 1 and pstate == "eligible",
      (probe.status_code, probe.get_json() if probe.is_json else probe.data[:160],
       ledger_before, probe_rows, pstate))
print("    pre-flight admission: status=%s title=%r ledger %d -> %d"
      " derived=%s"
      % (probe.get_json().get("status"), probe.get_json().get("title"),
         ledger_before, probe_rows, pstate))

# The race itself runs over the remaining 59 passes, all still un-admitted.
DUP_TOKENS = DUP_TOKENS[1:]
dup_outcomes = []
dup_lock = threading.Lock()


def dup_call(client, wid, i):
    tok = DUP_TOKENS[i % len(DUP_TOKENS)]
    gate = (wid % 7) + 1
    tok_scanner, _, _ = SCANNERS[gate - 1]
    r = client.post("/api/scan",
                    json={"payload": tok, "gate_id": gate, "mode": "entry"},
                    headers={"X-Scanner-Token": tok_scanner})
    with dup_lock:
        dup_outcomes.append((tok, gate, r.status_code,
                             r.get_json().get("status") if r.is_json else None))
    return r


for c in (4, 8):
    # Each concurrency level races its own still-un-admitted passes; reusing a
    # slice would make the second race measure "already admitted" rejections.
    DUP_TOKENS = RACE_TOKENS[1:61] if c == 4 else RACE_TOKENS[61:121]
    dup_outcomes.clear()
    _dbB = database.get_db()
    try:
        rows_before = _dbB.execute(
            "SELECT COUNT(*) FROM convocation_admissions").fetchone()[0]
    finally:
        _dbB.close()
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=c) as pool:
        list(pool.map(lambda w: [dup_call(APP.test_client(), w, i)
                                 for i in range(len(DUP_TOKENS))], range(c)))
    wall = time.perf_counter() - t0
    admitted = {}
    for tok, gate, code, status in dup_outcomes:
        if status == "ok":
            admitted.setdefault(tok, []).append(gate)
    dup_admits = {k: v for k, v in admitted.items() if len(v) > 1}
    rows = 0
    dbx = database.get_db()
    try:
        rows = dbx.execute("SELECT COUNT(*) FROM convocation_admissions").fetchone()[0]
    finally:
        dbx.close()
    print("    c=%d  %d duplicate attempts over %d passes in %.2fs ->"
          " %d passes admitted, %d admitted MORE THAN ONCE, ledger=%d rows"
          % (c, len(dup_outcomes), len(DUP_TOKENS), wall, len(admitted),
             len(dup_admits), rows))
    check("T2: c=%d no pass admitted twice" % c, not dup_admits,
          sorted(dup_admits)[:3])
    check("T2: c=%d every racing pass admitted exactly once"
          % c, rows == rows_before + len(admitted)
          and len(admitted) == len(DUP_TOKENS),
          (rows_before, rows, len(admitted), len(DUP_TOKENS)))

# ================================================== S4 bursts: invalid + auth
step("E", "Bursts of invalid payloads, unauthorized and expired sessions")
invalid_payloads = ["", "nonsense", "LGU2:", "LGU2:short", "A" * 4096,
                    "LGU1:deadbeef", "'; DROP TABLE scans;--", "LGU2:" + "x" * 200]

_dbE = database.get_db()
try:
    adm_before = _dbE.execute("SELECT COUNT(*) FROM convocation_admissions").fetchone()[0]
    used_before = _dbE.execute("SELECT COUNT(*) FROM convocation_passes"
                               " WHERE status = 'used'").fetchone()[0]
finally:
    _dbE.close()


def invalid_call(client, wid, i):
    return client.post("/api/scan",
                       json={"payload": invalid_payloads[i % len(invalid_payloads)],
                             "gate_id": 1, "mode": "entry"},
                       headers={"X-Scanner-Token": first_token})


for c in CONCURRENCIES:
    rec = run_load(APP, "scan: invalid/forged payloads", c, 100, invalid_call)


revoked_token, _, _ = SCANNERS[0]
dbx = database.get_db()
try:
    scanner_auth.revoke_session(revoked_token)
finally:
    dbx.close()


def unauthorized_call(client, wid, i):
    kinds = [
        {},
        {"X-Scanner-Token": "not-a-real-token"},
        {"X-Scanner-Token": revoked_token},
    ]
    return client.post("/api/scan",
                       json={"payload": tokens[i % len(tokens)],
                             "gate_id": (i % 7) + 1, "mode": "entry"},
                       headers=kinds[i % 3])


rec = run_load(APP, "scan: unauthenticated/expired/revoked", 4, 150,
               unauthorized_call)
check("T1: unauthorized scans never return 2xx", rec["ok"] == 0, rec["ok"])
check("T1: unauthorized scans never 500", rec["unhandled_5xx_or_exc"] == 0)

# scanner login throughput (real scrypt hashing — the expensive path)
def login_call(client, wid, i):
    return client.post("/api/scanner/login",
                       json={"username": "bench-gate-1", "pin": "BENCHPIN1"})


rec = run_load(APP, "auth: scanner login (scrypt verify)", 4, 20, login_call)
REPORT["resilience"]["login_rps"] = rec["throughput_rps"]

# unauthorized gate attempt
def wrong_gate_call(client, wid, i):
    # SCANNERS[2] is provisioned for gate 3 only; gate 7 must be refused.
    return client.post("/api/scan",
                       json={"payload": tokens[i % len(tokens)], "gate_id": 7,
                             "mode": "entry"},
                       headers={"X-Scanner-Token": SCANNERS[2][0]})


rec = run_load(APP, "scan: gate the scanner is not authorized for", 4, 60,
               wrong_gate_call)
check("T1: cross-gate attempts are all refused", rec["ok"] == 0, rec["ok"])

# Every refused scan above must have written nothing: compare the ledger and
# pass states against the snapshot taken before the bursts started.
dbfx = database.get_db()
try:
    f_adm = dbfx.execute("SELECT COUNT(*) FROM convocation_admissions").fetchone()[0]
    f_used = dbfx.execute("SELECT COUNT(*) FROM convocation_passes"
                          " WHERE status = 'used'").fetchone()[0]
finally:
    dbfx.close()
print("    refused bursts changed nothing: admissions %d -> %d, used"
      " passes %d -> %d" % (adm_before, f_adm, used_before, f_used))
check("T1: refused scans produced no new admission records",
      f_adm == adm_before, (adm_before, f_adm))
check("T1: refused scans left no extra pass marked used",
      f_used == used_before, (used_before, f_used))

# ================================================== S5 dashboard summary load
step("F", "Examination dashboard and attendance summaries under load")


def dash_call(client, wid, i):
    return client.get("/api/dashboard/summary")


for c in CONCURRENCIES:
    run_load(APP, "dashboard: attendance summary", c, 100, dash_call)

# =============================================================== resilience
step("G", "Resilience: lock contention, interruption, recovery")
dbx = database.get_db()
try:
    adm_total = dbx.execute("SELECT COUNT(*) FROM convocation_admissions").fetchone()[0]
    pass_used = dbx.execute("SELECT COUNT(*) FROM convocation_passes"
                            " WHERE status = 'used'").fetchone()[0]
finally:
    dbx.close()
check("T1: zero unhandled exceptions across every workload",
      all(w["unhandled_5xx_or_exc"] == 0 for w in REPORT["workloads"]),
      [w["workload"] for w in REPORT["workloads"]
       if w["unhandled_5xx_or_exc"]][:3])
check("T1: zero SQLite busy/locked errors across every workload",
      all(w["sqlite_errors"] == 0 for w in REPORT["workloads"]),
      [(w["workload"], w["sqlite_error_samples"]) for w in REPORT["workloads"]
       if w["sqlite_errors"]][:3])

# A writer holding an exclusive lock while readers/writers hammer the file.
# Fresh tokens per attempt so every request is a genuine admission attempt,
# plus a latency record — the question is whether clients see errors, stalls,
# or clean service.
lock_probe = {"busy": 0, "ok": 0, "other_4xx": 0, "5xx": 0, "max_ms": 0.0}
_lock_lock = threading.Lock()


def contend(i):
    client = APP.test_client()
    tok = tokens[1200 + (i % 60)]
    t0 = time.perf_counter()
    try:
        r = client.post("/api/scan",
                        json={"payload": tok, "gate_id": 2, "mode": "entry"},
                        headers={"X-Scanner-Token": SCANNERS[1][0]})
    except sqlite3.OperationalError:
        with _lock_lock:
            lock_probe["busy"] += 1
        return
    ms = (time.perf_counter() - t0) * 1000.0
    with _lock_lock:
        lock_probe["max_ms"] = max(lock_probe["max_ms"], ms)
        if r.status_code == 200 and r.is_json and r.get_json().get("status") == "ok":
            lock_probe["ok"] += 1
        elif r.status_code >= 500:
            lock_probe["5xx"] += 1
        else:
            lock_probe["other_4xx"] += 1


holder = database.get_db()
holder.execute("BEGIN IMMEDIATE")
try:
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(contend, range(24)))
    REPORT["resilience"]["under_exclusive_lock"] = dict(lock_probe)
    print("    during a held IMMEDIATE lock: admitted=%d refused=%d"
          " busy/locked=%d 5xx=%d slowest=%.1fms"
          % (lock_probe["ok"], lock_probe["other_4xx"], lock_probe["busy"],
             lock_probe["5xx"], lock_probe["max_ms"]))
finally:
    try:
        holder.rollback()
    finally:
        holder.close()

# Integrity under contention is the hard requirement. Availability under a
# held write lock is a recorded operational finding (see the report).
dbic = database.get_db()
try:
    ic_adm = dbic.execute("SELECT COUNT(*) FROM convocation_admissions").fetchone()[0]
    ic_dist = dbic.execute(
        "SELECT COUNT(DISTINCT convocation_id || ':' || registration_id)"
        " FROM convocation_admissions").fetchone()[0]
    ic_used = dbic.execute(
        "SELECT COUNT(*) FROM convocation_passes WHERE status = 'used'").fetchone()[0]
finally:
    dbic.close()
check("T3: the database stayed consistent through the contention burst"
      " (no duplicated admission)",
      ic_adm == ic_dist, (ic_adm, ic_dist))
check("T3: no pass was left marked used without an admission row",
      ic_used <= ic_adm, (ic_used, ic_adm))
REPORT["resilience"]["lock_contention_availability"] = dict(lock_probe)
if lock_probe["5xx"] or lock_probe["busy"]:
    print("    !! FINDING: while a writer held the database, %d of 24 scans"
          " failed (%d x 5xx, %d x SQLite busy) and the slowest client waited"
          " %.1f s. database.get_db() uses the SQLite default 5s busy timeout"
          " and a rollback journal, so a blocked writer multiplies into"
          " multi-second stalls." % (lock_probe["5xx"] + lock_probe["busy"],
                                     lock_probe["5xx"], lock_probe["busy"],
                                     lock_probe["max_ms"] / 1000.0))

# backup + restore of the post-workload database
import backup  # noqa: E402
dest = os.path.join(_TMP, "after-load.db")
man = backup.backup(dest)
check("backup: online backup of the worked-on database succeeds", os.path.exists(dest))
check("backup: manifest written", os.path.exists(man.get("path", "") or ""))
v = backup.validate(dest)
check("backup: the post-workload backup validates", isinstance(v, dict), v)
refused = False
try:
    backup.restore(dest, config.PRODUCTION_DB_PATH)
except ValueError as exc:
    refused = "production" in str(exc).lower()
check("backup: restore refuses to write the production database", refused)

# interruption: kill mid-transaction on a disposable copy, then reopen
INT = os.path.join(_TMP, "interrupted.db")
shutil.copyfile(config.DB_PATH, INT)
killer = sqlite3.connect(INT)
killer.execute("BEGIN IMMEDIATE")
killer.execute("INSERT INTO broadcasts (audience, message, sent_by, sent_at)"
               " VALUES ('students', 'partial', 'bench', ?)", (now(),))
killer.close()  # no commit -> simulates a process killed mid-write
recovered = sqlite3.connect(INT)
integ = recovered.execute("PRAGMA integrity_check").fetchone()[0]
pending = recovered.execute("SELECT COUNT(*) FROM broadcasts"
                            " WHERE message = 'partial'").fetchone()[0]
recovered.close()
check("recovery: interrupted write left the database consistent",
      integ == "ok", integ)
check("recovery: uncommitted row was rolled back", pending == 0, pending)

# restart the application against the same database
APP2 = create_app()
APP2.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
c2 = APP2.test_client()
r = c2.get("/api/health")
check("recovery: app restarts and serves /api/health", r.status_code == 200)
r = c2.get("/api/dashboard/summary")
check("recovery: dashboard summary recomputes after restart",
      r.status_code == 200)
dbx = database.get_db()
try:
    after_adm = dbx.execute("SELECT COUNT(*) FROM convocation_admissions").fetchone()[0]
    after_used = dbx.execute("SELECT COUNT(*) FROM convocation_passes"
                             " WHERE status = 'used'").fetchone()[0]
    distinct_adm = dbx.execute("SELECT COUNT(DISTINCT convocation_id || ':' ||"
                               " registration_id) FROM convocation_admissions"
                               ).fetchone()[0]
finally:
    dbx.close()
check("recovery: admission ledger still has no duplicate registration",
      after_adm == distinct_adm, (after_adm, distinct_adm))
print("    post-recovery: admissions=%d used_passes=%d distinct=%d"
      % (after_adm, after_used, distinct_adm))

size_after = os.path.getsize(config.DB_PATH)
REPORT["environment"]["db_bytes_after"] = size_after
REPORT["environment"]["admissions_recorded"] = after_adm
REPORT["environment"]["passes_used"] = after_used
print("    db size: %d -> %d bytes (+%d)"
      % (size_before, size_after, size_after - size_before))
if psutil and _PROC:
    REPORT["environment"]["peak_rss_mb"] = round(_PROC.memory_info().rss / 1e6, 1)

with open(os.path.join(_TMP, "summary.json"), "w", encoding="utf-8") as fh:
    json.dump(REPORT, fh, indent=2)
try:
    print("\n---- measured workloads (SYNTHETIC BENCHMARK) ----")
    print(json.dumps(REPORT["workloads"], indent=2))
    print("---- environment ----")
    print(json.dumps(REPORT["environment"], indent=2))
except Exception:
    pass

passed = sum(1 for _, ok, _ in RESULTS if ok)
print("\nPHASE21 LOAD/RESILIENCE: %d/%d checks passed, %d failing"
      % (passed, len(RESULTS), len(RESULTS) - passed))
for name, ok, detail in RESULTS:
    if not ok:
        print("  FAIL: %s %s" % (name, detail))
shutil.rmtree(_TMP, ignore_errors=True)
sys.exit(1 if passed != len(RESULTS) else 0)
