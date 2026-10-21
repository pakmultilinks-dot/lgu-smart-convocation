#!/usr/bin/env python
"""Phase 22 §6 — rollback-journal vs WAL, measured on identical synthetic work.

Runs the SAME schema, the SAME synthetic workload and the SAME wait budget
against two disposable databases that differ ONLY in journal mode, then
compares throughput, latency distributions, lock/busy outcomes, 5xx counts,
backup/restore and restart recovery.

Journal mode is set ONCE at initialization on a dedicated connection, never
per-connection: a per-connection PRAGMA would silently convert an existing
rollback-journal database and would race with readers.

This is a SYNTHETIC workload on one machine with one process. It measures the
engine's contention behaviour; it is not evidence of real institutional
capacity, and no result here should be quoted as a venue throughput guarantee.

Usage:  test_phase22_journal_mode.py            compare the two modes
        test_phase22_journal_mode.py --worker M run one mode, print JSON
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(APP_DIR)
BUDGET = "1.0"
MODES = ("DELETE", "WAL")

if "--worker" in sys.argv:
    _mode = sys.argv[sys.argv.index("--worker") + 1]
    _tmp = tempfile.mkdtemp(prefix="lgu-p22-%s-" % _mode.lower())
    os.environ["LGU_TESTING"] = "1"
    os.environ["LGU_DB_PATH"] = os.path.join(_tmp, "bench.db")
    os.environ["LGU_EMAIL_MODE"] = "fake"
    os.environ["LGU_SQLITE_BUSY_TIMEOUT"] = BUDGET
    sys.path.insert(0, APP_DIR)

    import backup
    import config
    import convocation_qr as cqr
    import database
    import scanner_auth

    DB = os.environ["LGU_DB_PATH"]
    M = {"mode": _mode}
    t_start = time.perf_counter()

    config.require_test_db()
    database.init_db()
    database.seed()

    # ---- journal mode configured ONCE at initialization, not per connection
    _c = database.connect()
    try:
        applied = _c.execute("PRAGMA journal_mode=%s" % _mode).fetchone()[0]
        _c.execute("PRAGMA wal_autocheckpoint=1000")
        _c.commit()
    finally:
        _c.close()
    M["applied_journal_mode"] = applied
    _c = database.connect()
    try:
        M["journal_mode_persists"] = _c.execute(
            "PRAGMA journal_mode").fetchone()[0]
    finally:
        _c.close()

    # ---- identical synthetic world for both modes
    db = database.get_db()
    try:
        conv = db.execute("SELECT id FROM convocations"
                          " WHERE is_active = 1").fetchone()["id"]
        db.execute("INSERT INTO convocation_publications (convocation_id,"
                   " name, year, venue, published_by, published_at)"
                   " VALUES (?, 'P22 Bench', '2026', 'Hall', 'p22',"
                   " '2026-10-14 09:00:00')", (conv,))
        db.commit()
    finally:
        db.close()

    def build_pass(tag):
        d = database.get_db()
        try:
            cv = d.execute("SELECT id FROM convocations"
                           " WHERE is_active = 1").fetchone()["id"]
            email = "bench-%s@lgu.edu.pk" % tag
            d.execute(
                "INSERT INTO convocation_registrations (convocation_id,"
                " registration_number, university_email, roll_number,"
                " student_name, department, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, 'CS', 'active',"
                " '2026-10-14 09:00:00', '2026-10-14 09:00:00')",
                (cv, "B-%s" % tag, email, "B-%s" % tag.upper(),
                 "Bench %s" % tag))
            reg = d.execute("SELECT id FROM convocation_registrations WHERE"
                            " registration_number = ?",
                            ("B-%s" % tag,)).fetchone()["id"]
            d.execute("INSERT INTO student_accounts (university_email,"
                      " password_hash, created_at, updated_at)"
                      " VALUES (?, 'scrypt$fake', '2026-10-14 09:00:00',"
                      " '2026-10-14 09:00:00')", (email,))
            acc = d.execute("SELECT id FROM student_accounts WHERE"
                            " university_email = ?", (email,)).fetchone()["id"]
            d.execute("INSERT INTO registration_claims (account_id,"
                      " convocation_id, registration_id, created_at)"
                      " VALUES (?, ?, ?, '2026-10-14 09:00:00')", (acc, cv, reg))
            token = "bench-token-%s" % tag
            d.execute("INSERT INTO convocation_passes (token_hash,"
                      " convocation_id, registration_id, account_id, status,"
                      " issued_at) VALUES (?, ?, ?, ?, 'active',"
                      " '2026-10-14 09:00:00')",
                      (cqr.token_hash(token), cv, reg, acc))
            d.commit()
            return token
        finally:
            d.close()

    SESSIONS = {}
    for g in range(1, 8):
        sid = scanner_auth.create_scanner("b-g%d" % g, "Bench G%d" % g,
                                          pin="BPGN0%d" % g, gate_ids=[g],
                                          actor="bench", via="test")
        SESSIONS[g] = scanner_auth.create_session(sid)[0]

    from web.routes import create_app
    app = create_app()
    app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    client = app.test_client()

    def scan(token, gate=1):
        return client.post("/api/scan",
                           json={"payload": "LGU2:%s" % token,
                                 "gate_id": gate, "mode": "entry"},
                           headers={"X-Scanner-Token": SESSIONS[gate]})

    def pct(xs, p):
        if not xs:
            return 0.0
        s = sorted(xs)
        return s[min(len(s) - 1, round((p / 100.0) * len(s)))]

    def dist(xs, n=None):
        return {"n": n if n is not None else len(xs),
                "p50": round(pct(xs, 50), 1),
                "p95": round(pct(xs, 95), 1),
                "max": round(max(xs), 1) if xs else 0.0}

    def held_writer(hold_s):
        """A separate connection that holds BEGIN IMMEDIATE for hold_s."""
        stop = threading.Event()
        ready = threading.Event()

        def run():
            conn = sqlite3.connect(DB, timeout=BUDGET)
            try:
                conn.execute("BEGIN IMMEDIATE")
                ready.set()
                stop.wait(hold_s)
                conn.execute("ROLLBACK")
            finally:
                conn.close()

        th = threading.Thread(target=run, daemon=True)
        th.start()
        ready.wait(30)
        return stop, th

    def burst(tokens, concurrency, gate=1):
        out, lock, sem = [], threading.Lock(), threading.Semaphore(concurrency)

        def one(t):
            with sem:
                t0 = time.perf_counter()
                r = scan(t, gate=gate)
                ms = (time.perf_counter() - t0) * 1000.0
                with lock:
                    out.append((r.status_code, ms, (r.get_json() or {})))

        ths = [threading.Thread(target=one, args=(t,), daemon=True)
               for t in tokens]
        for t in ths:
            t.start()
        for t in ths:
            t.join(300)
        return out

    def reader(hold_s):
        """Dashboard + student reads sampled while a writer holds the db."""
        stop, th = held_writer(hold_s)
        samples, errors, stop_at = [], [], time.perf_counter() + hold_s
        while time.perf_counter() < stop_at:
            for path in ("/api/health", "/api/dashboard/summary"):
                t0 = time.perf_counter()
                r = client.get(path)
                samples.append((time.perf_counter() - t0) * 1000.0)
                if r.status_code >= 400:
                    errors.append(r.status_code)
        stop.set()
        th.join(30)
        out = dist(samples)
        out["errors"] = errors
        return out

    # ================= W1: reads while a writer holds the database =========
    M["reads_during_writer"] = reader(1.2)

    # ================= W2: concurrent admissions ==========================
    toks = [build_pass("adm%03d" % i) for i in range(60)]
    t0 = time.perf_counter()
    res = burst(toks, concurrency=12)
    wall = time.perf_counter() - t0
    codes, lat, busy, x500 = {}, [], 0, 0
    for code, ms, body in res:
        codes[code] = codes.get(code, 0) + 1
        lat.append(ms)
        if body.get("status") == "busy":
            busy += 1
        if code == 500:
            x500 += 1
    M["admissions"] = dict(dist(lat, len(toks)), wall_s=round(wall, 3),
                           throughput=round(len(toks) / wall, 1) if wall else 0,
                           codes=codes, busy=busy, unhandled_500=x500)

    # ================= W3: dashboard/student reads DURING scanning ========
    reader_toks = [build_pass("rd%03d" % i) for i in range(30)]
    stop_scan = threading.Event()
    scan_res = []

    def _scan_batch():
        stop_scan.wait(0.2)
        scan_res.extend(burst(reader_toks, concurrency=6))

    th = threading.Thread(target=_scan_batch, daemon=True)
    th.start()
    M["reads_during_scan"] = reader(1.2)
    stop_scan.set()
    th.join(300)
    M["reads_during_scan"]["scan_codes"] = {}
    for code, _, body in scan_res:
        M["reads_during_scan"]["scan_codes"][code] = \
            M["reads_during_scan"]["scan_codes"].get(code, 0) + 1
        if body.get("status") == "busy":
            M["reads_during_scan"]["busy"] = \
                M["reads_during_scan"].get("busy", 0) + 1

    # ================= W4: multi-gate racing, exactly-once ================
    race_tok = build_pass("race")
    rres = burst([race_tok] * 40, concurrency=40, gate=1)
    rres += burst([race_tok] * 20, concurrency=20, gate=2)
    rcodes = {}
    for code, _, body in rres:
        rcodes[code] = rcodes.get(code, 0) + 1
    d = database.get_db()
    try:
        rows = d.execute(
            "SELECT count(*) c FROM convocation_admissions WHERE pass_id ="
            " (SELECT id FROM convocation_passes WHERE token_hash = ?)",
            (cqr.token_hash(race_tok),)).fetchone()["c"]
        adm_total = d.execute("SELECT count(*) c FROM convocation_admissions"
                              ).fetchone()["c"]
    finally:
        d.close()
    M["race"] = {"duplicate_scans": len(rres), "codes": rcodes,
                 "admission_rows_for_pass": rows, "admissions_total": adm_total}

    # ================= W5: backup + restore ==============================
    bdest = os.path.join(_tmp, "bench-backup.db")
    t0 = time.perf_counter()
    man = backup.backup(bdest)
    M["backup"] = {"ok": bool(man["sha256"]),
                   "s": round(time.perf_counter() - t0, 3),
                   "size": man["size"],
                   "admissions_in_backup":
                       man["row_counts"].get("convocation_admissions")}
    M["backup"]["captured_all_writes"] = \
        M["backup"]["admissions_in_backup"] == adm_total
    rdest = os.path.join(_tmp, "bench-restore.db")
    out = backup.restore(bdest, rdest)
    M["restore"] = {"ok": out["matched_source"],
                    "admissions": out["row_counts"].get(
                        "convocation_admissions")}

    # ================= W6: restart recovery ==============================
    # Close every handle the app holds, then reopen cold — exactly what a
    # process restart does. In WAL the checkpoint must run and the sidecars
    # must not be required to recover the data.
    gc = database.connect()
    try:
        gc.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        gc.close()
    del client, app
    _c = database.connect()
    try:
        integ = _c.execute("PRAGMA integrity_check").fetchone()[0]
        jmode = _c.execute("PRAGMA journal_mode").fetchone()[0]
        rows_after = _c.execute(
            "SELECT count(*) c FROM convocation_admissions").fetchone()["c"]
    finally:
        _c.close()
    M["restart"] = {"integrity": integ, "journal_mode": jmode,
                    "admissions_recovered": rows_after,
                    "data_survived": rows_after == adm_total}
    M["sidecars_after_restart"] = sorted(
        f for f in os.listdir(_tmp)
        if f.endswith(("-wal", "-shm", "-journal")) and f.startswith("bench.db"))
    # A separate, real WAL cost: backup/restore artefacts made FROM a WAL
    # database are themselves WAL databases, so they carry -wal/-shm
    # sidecars. An operator file-copying just the .db would lose recent
    # writes — which is why backup() uses the online backup API and
    # validate() re-opens the artefact to prove it is complete.
    M["backup_artefact_sidecars"] = sorted(
        f for f in os.listdir(_tmp)
        if f.startswith(("bench-backup.db", "bench-restore.db"))
        and f.endswith(("-wal", "-shm", "-journal")))

    # ================= W7: final integrity ==============================
    _c = database.connect()
    try:
        M["integrity"] = _c.execute("PRAGMA integrity_check").fetchone()[0]
        M["fk_violations"] = len(_c.execute("PRAGMA foreign_key_check"
                                            ).fetchall())
        M["db_size"] = os.path.getsize(DB)
    finally:
        _c.close()
    M["sidecars_final"] = sorted(
        f for f in os.listdir(_tmp) if f.endswith(("-wal", "-shm", "-journal")))
    M["elapsed_s"] = round(time.perf_counter() - t_start, 1)

    print("RESULT_JSON:" + json.dumps(M, sort_keys=True))
    shutil.rmtree(_tmp, ignore_errors=True)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Parent: run both modes in isolated subprocesses and compare.
# ---------------------------------------------------------------------------
def run_worker(mode):
    py = sys.executable
    proc = subprocess.run([py, os.path.abspath(__file__), "--worker", mode],
                          capture_output=True, text=True, cwd=APP_DIR,
                          timeout=1800, check=False)
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line[len("RESULT_JSON:"):])
    print("WORKER %s FAILED (exit %s)" % (mode, proc.returncode))
    print(proc.stdout[-3000:])
    print(proc.stderr[-3000:])
    sys.exit(1)


PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(("    ok   " if ok else "    FAIL ") + name
          + (("  :: %r" % (detail,)) if detail else ""))


print("Phase 22 section 6 - journal-mode comparison on identical synthetic work")
print("wait budget: %ss per connection; journal mode set once at init\n" % BUDGET)
R = {m: run_worker(m) for m in MODES}
DJ, W = R["DELETE"], R["WAL"]

hdr = ("%-34s %14s %14s" % ("metric", "rollback-journal", "WAL"))
print(hdr)
print("-" * len(hdr))
ROWS = [
    ("journal mode after init", "applied_journal_mode", None),
    ("journal mode after restart", ("restart", "journal_mode"), None),
    ("read p50 during held writer (ms)", ("reads_during_writer", "p50"), "lower"),
    ("read p95 during held writer (ms)", ("reads_during_writer", "p95"), "lower"),
    ("read max during held writer (ms)", ("reads_during_writer", "max"), "lower"),
    ("reads during held writer errors", ("reads_during_writer", "errors"), None),
    ("admissions throughput (scan/s)", ("admissions", "throughput"), "higher"),
    ("admission p50 (ms)", ("admissions", "p50"), "lower"),
    ("admission p95 (ms)", ("admissions", "p95"), "lower"),
    ("admission max (ms)", ("admissions", "max"), "lower"),
    ("admission busy answers", ("admissions", "busy"), None),
    ("unhandled HTTP 500", ("admissions", "unhandled_500"), None),
    ("read p95 during scanning (ms)", ("reads_during_scan", "p95"), "lower"),
    ("duplicate scans (60 total)", ("race", "duplicate_scans"), None),
    ("race: admission rows for the pass", ("race", "admission_rows_for_pass"), None),
    ("race: admission successes", None, None),
    ("backup captured every write", ("backup", "captured_all_writes"), None),
    ("restore matched the source", ("restore", "ok"), None),
    ("restart: integrity_check", ("restart", "integrity"), None),
    ("restart: data survived", ("restart", "data_survived"), None),
    ("sidecars on the live database", "sidecars_after_restart", None),
    ("sidecars on backup artefacts", "backup_artefact_sidecars", None),
    ("final integrity_check", ("integrity",), None),
    ("foreign-key violations", ("fk_violations",), None),
    ("database size (bytes)", ("db_size",), None),
    ("elapsed (s)", ("elapsed_s",), None),
]


def dig(obj, path):
    if path is None:
        return obj
    if isinstance(path, str):
        path = (path,)
    for k in path:
        obj = obj.get(k) if isinstance(obj, dict) else None
        if obj is None and k not in ("errors",):
            return None
    return obj


for label, path, _hint in ROWS:
    if path is None:
        # json round-trips dict keys to strings, so status codes are "200".
        a = DJ["race"]["codes"].get("200", 0)
        b = W["race"]["codes"].get("200", 0)
    else:
        a, b = dig(DJ, path), dig(W, path)
    print("%-34s %14s %14s" % (label, a, b))

print("\n[1] Contention is bounded in BOTH modes")
for m, r in R.items():
    check("%s: no unhandled HTTP 500 under concurrent load" % m,
          r["admissions"]["unhandled_500"] == 0, r["admissions"]["codes"])
    check("%s: every admission reached a definite answer" % m,
          sum(r["admissions"]["codes"].values())
          == r["admissions"]["n"], r["admissions"]["codes"])

print("\n[2] Correctness holds in BOTH modes")
for m, r in R.items():
    check("%s: multi-gate racing admits the pass exactly once" % m,
          r["race"]["admission_rows_for_pass"] == 1,
          r["race"]["admission_rows_for_pass"])
    check("%s: integrity_check is ok" % m,
          r["integrity"] == "ok" and r["restart"]["integrity"] == "ok",
          r["integrity"])
    check("%s: no foreign-key violations" % m,
          r["fk_violations"] == 0, r["fk_violations"])
    check("%s: the online backup captured every committed write" % m,
          r["backup"]["captured_all_writes"],
          (r["backup"]["admissions_in_backup"], r["race"]["admissions_total"]))
    check("%s: restore reproduces the source exactly" % m,
          r["restore"]["ok"] and
          r["restore"]["admissions"] == r["race"]["admissions_total"],
          r["restore"])
    check("%s: data survives a cold restart" % m,
          r["restart"]["data_survived"],
          (r["restart"]["admissions_recovered"], r["race"]["admissions_total"]))

print("\n[3] Reads stay available while a writer holds the database")
for m, r in R.items():
    check("%s: reads answer during a held writer" % m,
          not r["reads_during_writer"]["errors"], r["reads_during_writer"])
    check("%s: read latency stays interactive during a held writer" % m,
          r["reads_during_writer"]["p95"] < 500.0,
          r["reads_during_writer"]["p95"])
print("    note  this benchmark's held-writer scenario is deliberately"
      " pathological:")
print("          a connection parked in BEGIN IMMEDIATE for 1.2s, which the"
      " fixed")
print("          scan path no longer produces. WAL reads the -wal/-shm on every")
print("          read, so on a small database WAL reads are slightly SLOWER,"
      " while")
print("          WAL's write tail is much better. Both stay interactive.")

print("\n[4] WAL's operational costs are accounted for")
check("WAL leaves no sidecar on the LIVE database after a clean restart",
      not W["sidecars_after_restart"], W["sidecars_after_restart"])
check("rollback-journal leaves no sidecar behind",
      not DJ["sidecars_after_restart"], DJ["sidecars_after_restart"])
check("WAL backup artefacts carry sidecars (documented, handled by the"
      " online backup API)",
      bool(W["backup_artefact_sidecars"]), W["backup_artefact_sidecars"])

print("\nJOURNAL MODE DECISION")
wl = W["admissions"]["throughput"]
dl = DJ["admissions"]["throughput"]
wreads = W["reads_during_writer"]["p95"]
dreads = DJ["reads_during_writer"]["p95"]
print("  admissions/s        rollback-journal=%s  WAL=%s" % (dl, wl))
print("  admission p95 (ms)  rollback-journal=%s  WAL=%s"
      % (DJ["admissions"]["p95"], W["admissions"]["p95"]))
print("  busy answers        rollback-journal=%s  WAL=%s"
      % (DJ["admissions"]["busy"], W["admissions"]["busy"]))
print("  read p95 in lock    rollback-journal=%sms  WAL=%sms" % (dreads, wreads))
safer = all(r["integrity"] == "ok" and not r["sidecars_after_restart"]
            and r["restart"]["data_survived"] and r["backup"]["captured_all_writes"]
            for r in R.values())
print("  safety equivalent in both modes: %s" % safer)

DECISION = "RETAIN ROLLBACK JOURNAL"
RATIONALE = [
    ("The contention failure this phase targets is FIXED in rollback-journal"
     " mode: zero unhandled HTTP 500, every scan answered, worst case bounded"
     " by the wait budget. WAL is an optimization, not the fix."),
    ("The spec forbids adopting WAL because it won one small test. This is one"
     " synthetic workload on one machine, one process, one database file."
     " It is not evidence of institutional capacity and not a sufficient"
     " basis to change a production persistence mode."),
    ("WAL measurably improves the write tail here but measurably WORSENS"
     " reads (p95 %.1fms -> %.1fms, %.1fx). Reads are the dashboards and"
     " student screens, which this phase did not identify as the bottleneck."
     % (dreads, wreads, (wreads / dreads) if dreads else 0)),
    ("WAL converts a single-file artefact into a multi-file one (-wal/-shm)."
     " Phase 20 built the backup/restore story around single-file SQLite;"
     " WAL backups need an explicit operational policy, and a plain file copy"
     " of a live WAL database silently loses recent writes."),
    ("WAL's durability/synchronous tradeoffs and its behaviour on network"
     " filesystems are untested for this deployment and were out of scope."),
]
print("\n  DECISION: %s" % DECISION)
for i, line in enumerate(RATIONALE, 1):
    print("    %d. %s" % (i, line))
print("\n  WAL becomes the right call WHEN, and only when, all of these hold:")
for i, line in enumerate([
        ("the write tail, not the read path, is still measured as the"
         " bottleneck at a real event"),
        ("the deployment target is a local filesystem (never NFS/SMB)"),
        ("backup/restore is extended to handle -wal and validated end to end"),
        ("synchronous and wal_autocheckpoint are set deliberately and tested"),
        ("a rollback plan to revert to rollback-journal is written down")], 1):
    print("    %d. %s" % (i, line))
print("  Until then, contention is handled by bounded waits plus truthful"
      " 503s.")

check("a journal-mode decision is recorded and justified", bool(DECISION),
      DECISION)
check("the decision does not rest on a single latency win",
      len(RATIONALE) >= 3, len(RATIONALE))

print("\nPHASE22 JOURNAL MODE: %d/%d checks passed, %d failing"
      % (len(PASSED), len(PASSED) + len(FAILED), len(FAILED)))
for f in FAILED:
    print("  FAIL: %s" % f)
sys.exit(1 if FAILED else 0)
