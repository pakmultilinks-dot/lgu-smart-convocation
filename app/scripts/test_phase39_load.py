"""Phase 39 STEP 7 — event load / performance against a REAL running server.

Mandate item 7 with ACTUAL measured results: concurrent scanners, duplicate
check-ins, dashboard viewers + polling, request spikes, database contention
at HTTP level, and client-abort (network interruption) resilience. Boots its
own disposable DB (temp dir) + ``python run.py`` on a free port, drives it
with parallel HTTP clients, prints measured latencies, then stops the server.

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase39_load.py
Exit code 1 if any check fails. NEVER touches production app/lgu.db.
"""

import json
import os
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_ROOT = tempfile.mkdtemp(prefix="lgu-p39load-")
DB_PATH = os.path.join(TEST_ROOT, "load.db")
sys.path.insert(0, APP_DIR)

os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = DB_PATH
os.environ["LGU_ALLOW_DEMO_SECRETS"] = "1"

import config  # noqa: E402

config.require_test_db()

import database  # noqa: E402
import ids  # noqa: E402
import scanner_auth  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    if not cond:
        print("  FAIL %s  %r" % (name, detail))


def step(n, title):
    print("\n[%02d] %s" % (n, title))


def stats(ms):
    if not ms:
        return "n=0"
    s = sorted(ms)
    p50 = s[int(0.50 * (len(s) - 1))]
    p95 = s[int(0.95 * (len(s) - 1))]
    return ("n=%d avg=%.0f p50=%d p95=%d max=%d ms"
            % (len(s), statistics.fmean(s), p50, p95, s[-1]))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method, path, body=None, headers=None, timeout=15):
    """One HTTP call; returns (status, parsed-or-text, elapsed_ms)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (PORT, path), data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    ms = (time.time() - t0) * 1000
    try:
        return status, json.loads(raw), ms
    except (ValueError, UnicodeDecodeError):
        return status, raw[:200], ms


# --------------------------------------------------------------- fixtures
database.init_db()
database.seed()
scanner_auth.create_scanner(username="qa-load-gate", display_name="QA Load",
                             pin="816253", gate_ids=[1],
                             actor="phase39-fixture")
with database.connection() as db:
    STUDENTS = [r["qr_id"] for r in db.execute(
        "SELECT qr_id FROM students ORDER BY roll_no LIMIT 40")]
PAYLOADS = [ids.make_payload(q) for q in STUDENTS]

PORT = free_port()
PROC = None


def start_server():
    global PROC
    env = dict(os.environ)
    env["LGU_PORT"] = str(PORT)
    env["LGU_DASHBOARD_POLL_MS"] = "2000"
    log = open(os.path.join(TEST_ROOT, "server.log"), "w")
    PROC = subprocess.Popen([sys.executable, "run.py"], cwd=APP_DIR, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            st, body, _ = http("GET", "/api/health", timeout=3)
            if st == 200:
                return True
        except Exception:  # noqa: BLE001 - server still booting
            time.sleep(0.25)
    return False


def stop_server():
    if PROC:
        PROC.terminate()
        try:
            PROC.wait(timeout=10)
        except subprocess.TimeoutExpired:
            PROC.kill()


def scans_rows():
    con = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"),
                          uri=True)
    n = con.execute("SELECT COUNT(*) c FROM scans").fetchone()[0]
    con.close()
    return n


def login_scanner():
    st, body, ms = http("POST", "/api/scanner/login",
                        {"username": "qa-load-gate", "pin": "816253"})
    return body["token"] if st == 200 and body.get("token") else None


# ============================================================ run scenarios
if not start_server():
    stop_server()
    print("FATAL: server did not become healthy")
    sys.exit(2)

try:
    # ---- server boot + baseline
    step(0, "Server booted; baseline health")
    t_boot = time.time()
    st, body, ms = http("GET", "/api/health")
    check("health 200", st == 200, st)
    print("  measured: health %s" % stats([ms]))

    token = login_scanner()
    check("scanner login", bool(token))
    HDRS = {"X-Scanner-Token": token}

    # ---- 1: concurrent scanners (incl. duplicate check-ins in flight)
    step(1, "Concurrent scanners: 6 sessions x 30 scans")
    shared = PAYLOADS[:12]              # overlap on purpose: dup protection
    lat, codes, lock = [], {}, threading.Lock()
    before = scans_rows()

    def worker():
        tl, my_codes = [], {}
        for i in range(30):
            st, body, ms = http(
                "POST", "/api/scan",
                {"payload": shared[i % len(shared)], "gate_id": 1,
                 "mode": "entry"}, headers=HDRS)
            tl.append(ms)
            my_codes[st] = my_codes.get(st, 0) + 1
        with lock:
            lat.extend(tl)
            for k, v in my_codes.items():
                codes[k] = codes.get(k, 0) + v

    t0 = time.time()
    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    wall = time.time() - t0
    after = scans_rows()
    added = after - before
    print("  measured: %s | wall=%.1fs | throughput=%.0f req/s"
          % (stats(lat), wall, 180 / wall if wall else 0))
    print("  codes: %s | rows added=%d (distinct persons=%d)"
          % (codes, added, len(shared)))
    check("no 5xx during scan load",
          not any(c >= 500 for c in codes), codes)
    check("statuses only 200/403/503 (busy)",
          set(codes) <= {200, 403, 503}, codes)
    check("no double-count under concurrency (rows <= persons)",
          0 < added <= len(shared), added)

    # ---- 2: sequential duplicate check-ins
    step(2, "Duplicate check-ins: same person x10")
    dup_payload = PAYLOADS[20]         # untouched by scenario 1
    before = scans_rows()
    titles, lat2 = [], []
    for _ in range(10):
        st, body, ms = http("POST", "/api/scan",
                            {"payload": dup_payload, "gate_id": 1,
                             "mode": "entry"}, headers=HDRS)
        lat2.append(ms)
        titles.append(body.get("title") if isinstance(body, dict) else None)
    added = scans_rows() - before
    print("  measured: %s | first=%s repeats=%s"
          % (stats(lat2), titles[0], sorted(set(titles[1:]))))
    check("first scan recorded an entry", titles[0] == "ENTRY RECORDED",
          titles[0])
    check("repeats answered ALREADY INSIDE",
          all(t == "ALREADY INSIDE" for t in titles[1:]), titles[1:])
    check("duplicates added exactly one row", added == 1, added)

    # ---- 3: dashboard viewers + polling
    step(3, "Dashboard viewers: 8 clients polling /api/dashboard for 6s")
    dlat, dcodes, first_poll = [], {}, []

    def viewer():
        tl, fc, myc = [], None, {}
        end = time.time() + 6
        while time.time() < end:
            st, body, ms = http("GET", "/api/dashboard")
            tl.append(ms)
            myc[st] = myc.get(st, 0) + 1
            if fc is None and isinstance(body, dict):
                fc = body.get("poll_interval_ms")
            time.sleep(2)          # honour the server-suggested cadence
        with lock:
            dlat.extend(tl)
            for k, v in myc.items():
                dcodes[k] = dcodes.get(k, 0) + v
            first_poll.append(fc)

    threads = [threading.Thread(target=viewer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    print("  measured: %s | codes=%s | poll_interval_ms=%s"
          % (stats(dlat), dcodes, sorted({p for p in first_poll})))
    check("all dashboard polls 200", set(dcodes) == {200}, dcodes)
    check("server advertises a poll interval",
          all(p in (1000, 2000) for p in first_poll if p is not None),
          first_poll)

    # ---- 4: request spike
    step(4, "Spike: 120 mixed read requests back-to-back")
    slat, scodes = [], {}
    spike_paths = ["/api/health", "/api/config", "/api/gates",
                   "/api/dashboard", "/api/broadcasts"]

    def spiker(k):
        tl, myc = [], {}
        for i in range(24):
            st, _, ms = http("GET", spike_paths[i % len(spike_paths)],
                             timeout=20)
            tl.append(ms)
            myc[st] = myc.get(st, 0) + 1
        with lock:
            slat.extend(tl)
            for a, b in myc.items():
                scodes[a] = scodes.get(a, 0) + b

    threads = [threading.Thread(target=spiker, args=(k,)) for k in range(5)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    print("  measured: %s | wall=%.1fs | codes=%s"
          % (stats(slat), time.time() - t0, scodes))
    check("spike: every request succeeded", set(scodes) == {200}, scodes)

    # ---- 5: client abort / network interruption mid-request
    step(5, "Client aborts: 20 sockets closed mid-request, server survives")
    for _ in range(20):
        s = socket.create_connection(("127.0.0.1", PORT), timeout=3)
        s.sendall(("GET /api/dashboard HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                   "Connection: close\r\n\r\n").encode())
        s.close()                       # vanish before the reply is read
    time.sleep(0.5)
    st, body, ms = http("GET", "/api/health")
    check("server healthy after 20 client aborts", st == 200, st)
    st, body, _ = http("GET", "/api/dashboard")
    check("dashboard still serves after aborts",
          st == 200 and isinstance(body, dict), st)

finally:
    stop_server()

# ================================================================== done
failed = [n for n, ok in RESULTS if not ok]
print("\n%d checks, %d failures" % (len(RESULTS), len(failed)))
for n in failed:
    print("  FAILED: %s" % n)
sys.exit(1 if failed else 0)
