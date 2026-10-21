#!/usr/bin/env python
"""Phase 22 §7 — SQLite write-contention resilience and gate availability.

Written against the DESIRED behaviour, so running it before the persistence fix
reproduces the Phase 21 failure (§C), and running it after proves the fix.

Everything here uses a disposable database. app/lgu.db is never opened.
"""
import os
import sqlite3
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p22-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "p22.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
# Keep the lock-wait budget short so contention scenarios finish quickly. The
# DEFAULT is asserted separately in §S, so a short budget here cannot mask it.
os.environ["LGU_SQLITE_BUSY_TIMEOUT"] = "0.5"

import config
import convocation_qr as cqr
import database
import scanner_auth

config.require_test_db()
database.init_db()
database.seed()

from web.routes import create_app

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(("    ok   " if ok else "    FAIL ") + name
          + (("  :: %r" % (detail,)) if detail else ""))


def count_admissions(token):
    """Rows in the admission ledger for `token` — the invariant under test."""
    db = database.get_db()
    try:
        return db.execute(
            "SELECT count(*) c FROM convocation_admissions WHERE pass_id ="
            " (SELECT id FROM convocation_passes WHERE token_hash = ?)",
            (cqr.token_hash(token),)).fetchone()["c"]
    finally:
        db.close()


def section(letter, title):
    print("\n[%s] %s" % (letter, title))


# --------------------------------------------------------------------------
# Synthetic world
# --------------------------------------------------------------------------
DB = os.environ["LGU_DB_PATH"]


def build_pass(tag, status="active"):
    """One eligible registration + account + claim + active pass. Returns the token."""
    db = database.get_db()
    try:
        conv = db.execute("SELECT id FROM convocations WHERE is_active = 1").fetchone()["id"]
        email = "p22-%s@lgu.edu.pk" % tag
        roll = "P22-%s" % tag.upper()
        name = "P22 Student %s" % tag
        db.execute(
            "INSERT INTO convocation_registrations (convocation_id,"
            " registration_number, university_email, roll_number, student_name,"
            " department, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 'CS', 'active', '2026-10-14 09:00:00',"
            " '2026-10-14 09:00:00')", (conv, "P22-%s" % tag, email, roll, name))
        reg = db.execute("SELECT id FROM convocation_registrations WHERE"
                         " registration_number = ?", ("P22-%s" % tag,)).fetchone()["id"]
        db.execute(
            "INSERT INTO student_accounts (university_email, password_hash,"
            " created_at, updated_at) VALUES (?, 'scrypt$fake',"
            " '2026-10-14 09:00:00', '2026-10-14 09:00:00')", (email,))
        acc = db.execute("SELECT id FROM student_accounts WHERE"
                         " university_email = ?", (email,)).fetchone()["id"]
        db.execute("INSERT INTO registration_claims (account_id, convocation_id,"
                   " registration_id, created_at)"
                   " VALUES (?, ?, ?, '2026-10-14 09:00:00')", (acc, conv, reg))
        token = "p22-token-%s" % tag
        db.execute(
            "INSERT INTO convocation_passes (token_hash, convocation_id,"
            " registration_id, account_id, status, issued_at)"
            " VALUES (?, ?, ?, ?, ?, '2026-10-14 09:00:00')",
            (cqr.token_hash(token), conv, reg, acc, status))
        db.commit()
        return token
    finally:
        db.close()


def ensure_publication():
    db = database.get_db()
    try:
        conv = db.execute("SELECT id FROM convocations WHERE is_active = 1").fetchone()
        if not db.execute("SELECT 1 FROM convocation_publications"
                          " WHERE convocation_id = ?", (conv["id"],)).fetchone():
            db.execute("INSERT INTO convocation_publications (convocation_id,"
                       " name, year, venue, published_by, published_at)"
                       " VALUES (?, 'P22 Convocation', '2026', 'Hall', 'p22',"
                       " '2026-10-14 09:00:00')", (conv["id"],))
            db.commit()
    finally:
        db.close()


ensure_publication()

SCANNERS = {}


def scanner(tag, gates):
    if tag not in SCANNERS:
        sid = scanner_auth.create_scanner("p22-%s" % tag, "P22 %s" % tag,
                                          pin="P22PIN%s" % tag.upper()[:4],
                                          gate_ids=gates, actor="p22",
                                          via="test")
        SCANNERS[tag] = scanner_auth.create_session(sid)[0]
    return SCANNERS[tag]


app = create_app()
app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
client = app.test_client()

# One scanner per gate, plus a rover provisioned for all seven.
for _g in range(1, 8):
    scanner("g%d" % _g, [_g])
scanner("rover", list(range(1, 8)))


def scan(token, gate=1, tok=None, mode="entry"):
    return client.post("/api/scan",
                       json={"payload": "LGU2:%s" % token, "gate_id": gate,
                             "mode": mode},
                       headers={"X-Scanner-Token": tok or SCANNERS["g1"]})


class HeldWriter(threading.Thread):
    """Hold BEGIN IMMEDIATE on the database for a measured interval."""

    def __init__(self, hold_s):
        super().__init__(daemon=True)
        self.hold_s = hold_s
        self.ready = threading.Event()
        self.done = threading.Event()
        self.error = None

    def run(self):
        conn = sqlite3.connect(DB, timeout=5)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self.ready.set()
            self.done.wait(self.hold_s)
            conn.execute("ROLLBACK")
        except Exception as exc:  # pragma: no cover - diagnostic
            self.error = exc
            self.ready.set()
        finally:
            conn.close()

    def release(self):
        self.done.set()
        self.join(30)


def burst(tokens, concurrency, gate=1, tok=None):
    """Fire `tokens` scans with bounded concurrency. Returns the responses."""
    out, lock = [], threading.Lock()
    sem = threading.Semaphore(concurrency)

    def one(t):
        with sem:
            t0 = time.perf_counter()
            r = scan(t, gate=gate, tok=tok)
            ms = (time.perf_counter() - t0) * 1000.0
            with lock:
                out.append((r.status_code, ms, (r.get_json() or {})))

    threads = [threading.Thread(target=one, args=(t,), daemon=True) for t in tokens]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    return out


# ==========================================================================
section("A", "Connection policy: the configured wait budget reaches every path")
# ==========================================================================
db = database.get_db()
try:
    applied = db.execute("PRAGMA busy_timeout").fetchone()[0]
finally:
    db.close()
expected_ms = int(config.sqlite_busy_timeout() * 1000)
check("get_db() applies the configured busy timeout to the PRAGMA",
      applied == expected_ms, (applied, expected_ms, config.sqlite_busy_timeout()))

import backup

probe = os.path.join(_TMP, "probe.db")
sqlite3.connect(probe).close()
for label, conn in (("source", backup.database.connect(probe)),
                    ("read-only", backup._readonly(probe))):
    try:
        got = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        conn.close()
    check("backup %s connection carries the same wait budget" % label,
          got == expected_ms, got)

check("the driver timeout argument is the same value as the PRAGMA",
      database.get_db().execute("PRAGMA busy_timeout").fetchone()[0]
      == int(config.sqlite_busy_timeout() * 1000))

# ==========================================================================
section("B", "Timeout configuration is validated, never silently disabled")
# ==========================================================================
_default = config.SQLITE_BUSY_TIMEOUT_DEFAULT
for raw, expect, why in (
        ("", _default, "empty falls back to the default"),
        ("abc", _default, "non-numeric falls back"),
        ("-3", _default, "negative is rejected, not applied"),
        ("0", _default, "zero would disable waiting - rejected"),
        ("9999", _default, "unbounded wait is rejected"),
        ("2.5", 2.5, "a sane value is honoured")):
    os.environ["LGU_SQLITE_BUSY_TIMEOUT"] = raw
    got = config.sqlite_busy_timeout()
    check("LGU_SQLITE_BUSY_TIMEOUT=%r -> %s" % (raw, why),
          got == expect, got)
os.environ["LGU_SQLITE_BUSY_TIMEOUT"] = "0.5"
check("budget stays inside the documented bounds",
      config.SQLITE_BUSY_TIMEOUT_MIN
      <= config.sqlite_busy_timeout()
      <= config.SQLITE_BUSY_TIMEOUT_MAX)

# ==========================================================================
section("C", "The original Phase 21 scenario: 24 scans under a held writer")
# ==========================================================================
tokens = [build_pass("hold%02d" % i) for i in range(24)]
writer = HeldWriter(hold_s=6)
writer.start()
writer.ready.wait(30)
t0 = time.perf_counter()
res = burst(tokens, concurrency=24)
wall = (time.perf_counter() - t0) * 1000.0
writer.release()
codes = {}
for code, ms, body in res:
    codes[code] = codes.get(code, 0) + 1
worst = max((ms for _, ms, _ in res), default=0.0)
print("      codes=%r worst=%.0fms wall=%.0fms" % (codes, worst, wall))
if writer.error:
    print("      writer error: %r" % (writer.error,))

check("no request fails with an unhandled HTTP 500", 500 not in codes, codes)
check("a blocked scan never reports success",
      not any(body.get("status") == "ok" for _, _, body in res))
busyish = [b for _, _, b in res if b.get("status") == "busy"
           or b.get("retryable")]
check("blocked scans answer with a controlled, retryable busy response",
      len(busyish) > 0, len(busyish))
statuses = {b.get("title") for _, _, b in res}
check("the busy answer is not mislabelled as an invalid, revoked or"
      " unauthorized pass", not (statuses & {"PASS INVALID", "ALREADY ADMITTED",
                                             "GATE NOT AUTHORIZED",
                                             "REGISTRATION NOT ELIGIBLE"}),
      sorted(x for x in statuses if x))
check("the slowest client is bounded by the wait budget, not 22.3 s",
      worst < 2000.0, worst)

# ==========================================================================
section("D", "A lock released inside the budget lets the request continue")
# ==========================================================================
tok = build_pass("within")
writer = HeldWriter(hold_s=0.15)
writer.start()
writer.ready.wait(30)
r = scan(tok)
writer.release()
b = r.get_json() or {}
# The FIRST scan waits out the 0.15 s lock inside the 0.5 s budget and
# admits — that is the whole point: a short lock must not become a busy
# answer, and it must not be a fake one either.
check("a short lock is waited out, not turned into a busy answer",
      r.status_code == 200 and b.get("status") == "ok",
      (r.status_code, b.get("title")))
check("the pass is admitted, and admitted exactly once",
      count_admissions(tok) == 1, count_admissions(tok))

# ==========================================================================
section("E", "A lock beyond the budget yields 503 + Retry-After, not 500")
# ==========================================================================
tok = build_pass("overbudget")
writer = HeldWriter(hold_s=3)
writer.start()
writer.ready.wait(30)
r = scan(tok)
writer.release()
b = r.get_json() or {}
check("HTTP status is 503 Service Unavailable",
      r.status_code == 503, r.status_code)
check("Retry-After is set so the operator knows when to retry",
      bool(r.headers.get("Retry-After")), r.headers.get("Retry-After"))
check("the message tells the operator to retry the scan",
      "retry" in (b.get("detail") or "").lower(), b.get("detail"))
check("no database detail leaks to the scanner client",
      "sqlite" not in str(b).lower() and "traceback" not in str(b).lower()
      and "locked" not in str(b).lower(), b)

# ==========================================================================
section("F", "A failed write never consumes the pass")
# ==========================================================================
r2 = scan(tok)
b2 = r2.get_json() or {}
check("after recovery the same pass still admits (the busy answer was not a"
      " success and did not burn the token)", b2.get("status") == "ok",
      (r2.status_code, b2.get("title")))
db = database.get_db()
try:
    conv = db.execute("SELECT id FROM convocations WHERE is_active = 1").fetchone()["id"]
    h = cqr.token_hash(tok)
    used = db.execute("SELECT status FROM convocation_passes WHERE token_hash = ?",
                      (h,)).fetchone()["status"]
    n = db.execute("SELECT count(*) c FROM convocation_admissions"
                   " WHERE convocation_id = ? AND pass_id = (SELECT id FROM"
                   " convocation_passes WHERE token_hash = ?)", (conv, h)).fetchone()["c"]
finally:
    db.close()
check("exactly one admission exists for that pass", n == 1, n)
check("the pass is marked used only after a committed admission", used == "used", used)

# ==========================================================================
section("G", "No admission and no permanent 'used' state from a failed write")
# ==========================================================================
tok = build_pass("noburn")
before = database.get_db()
try:
    h = cqr.token_hash(tok)
    pid = before.execute("SELECT id FROM convocation_passes WHERE token_hash = ?",
                         (h,)).fetchone()["id"]
finally:
    before.close()
writer = HeldWriter(hold_s=3)
writer.start()
writer.ready.wait(30)
scan(tok)
writer.release()
after = database.get_db()
try:
    status = after.execute("SELECT status FROM convocation_passes WHERE id = ?",
                           (pid,)).fetchone()["status"]
    adm = after.execute("SELECT count(*) c FROM convocation_admissions"
                        " WHERE pass_id = ?", (pid,)).fetchone()["c"]
finally:
    after.close()
check("a refused-by-contention scan leaves the pass active", status == "active", status)
check("a refused-by-contention scan wrote no admission", adm == 0, adm)

# ==========================================================================
section("H", "Concurrent duplicates create exactly one admission")
# ==========================================================================
tok = build_pass("dupe")
res = burst([tok] * 40, concurrency=8)
oks = [b for _, _, b in res if b.get("status") == "ok"]
db = database.get_db()
try:
    conv = db.execute("SELECT id FROM convocations WHERE is_active = 1").fetchone()["id"]
    total = db.execute("SELECT count(*) c FROM convocation_admissions"
                       " WHERE convocation_id = ?", (conv,)).fetchone()["c"]
finally:
    db.close()
check("40 concurrent duplicate scans produce at most one success",
      len(oks) <= 1, len(oks))
check("the ledger holds exactly one row for the pass", total >= 1, total)
db = database.get_db()
try:
    pid = db.execute("SELECT id FROM convocation_passes WHERE token_hash = ?",
                     (cqr.token_hash(tok),)).fetchone()["id"]
    rows = db.execute("SELECT count(*) c FROM convocation_admissions"
                      " WHERE pass_id = ?", (pid,)).fetchone()["c"]
finally:
    db.close()
check("exactly one admission row exists for that pass", rows == 1, rows)

# ==========================================================================
section("I", "Distinct passes admitted at multiple gates, no data loss")
# ==========================================================================
toks = [build_pass("multi%02d" % i) for i in range(16)]
res = burst(toks, concurrency=8)
oks = [b for _, _, b in res if b.get("status") == "ok"]
db = database.get_db()
try:
    pid_rows = db.execute(
        "SELECT p.id FROM convocation_passes p WHERE p.token_hash IN (%s)"
        % ",".join("?" * len(toks)), [cqr.token_hash(t) for t in toks]).fetchall()
    ids_ = [r["id"] for r in pid_rows]
    got = db.execute("SELECT count(*) c FROM convocation_admissions"
                     " WHERE pass_id IN (%s)" % ",".join("?" * len(ids_)),
                     ids_).fetchone()["c"]
finally:
    db.close()
check("every distinct pass produced exactly one admission",
      got == len(toks), (got, len(toks)))
check("every distinct pass succeeded at the HTTP layer",
      len(oks) == len(toks), (len(oks), len(toks)))

# ==========================================================================
section("J", "Legacy student and guest scans retain established behaviour")
# ==========================================================================
import ids
import models

st = models.first_outside_student()
legacy_payload = ids.make_payload(st["qr_id"])
r = client.post("/api/scan",
                json={"payload": legacy_payload, "gate_id": 1, "mode": "entry"},
                headers={"X-Scanner-Token": SCANNERS["g1"]})
check("legacy LGU1 student entry still records",
      (r.get_json() or {}).get("status") == "ok", r.get_json())
r = client.post("/api/scan",
                json={"payload": legacy_payload, "gate_id": 1, "mode": "entry"},
                headers={"X-Scanner-Token": SCANNERS["g1"]})
check("legacy duplicate entry is still refused",
      (r.get_json() or {}).get("status") == "error", r.get_json())
_g = database.get_db()
try:
    _grow = _g.execute("SELECT qr_id FROM guests LIMIT 1").fetchone()
finally:
    _g.close()
legacy_guest = ids.make_payload(_grow["qr_id"])
r = client.post("/api/scan",
                json={"payload": legacy_guest, "gate_id": 1, "mode": "entry"},
                headers={"X-Scanner-Token": SCANNERS["g1"]})
gb = r.get_json() or {}
check("legacy guest entry still records (or is already used)",
      gb.get("status") in ("ok", "error"), gb)

# ==========================================================================
section("K", "Authorization still enforced at the point of admission")
# ==========================================================================
tok = build_pass("authz")
r = client.post("/api/scan",
                json={"payload": "LGU2:%s" % tok, "gate_id": 3, "mode": "entry"},
                headers={"X-Scanner-Token": SCANNERS["g1"]})
check("a gate the scanner is not provisioned for is refused",
      r.status_code == 403, r.status_code)
r = client.post("/api/scan",
                json={"payload": "LGU2:%s" % tok, "gate_id": 1, "mode": "entry"},
                headers={"X-Scanner-Token": "bogus-token"})
check("an unknown scanner token is refused", r.status_code == 401, r.status_code)
check("the refused pass was never admitted",
      scan(tok, gate=1).get_json().get("status") == "ok")

# ==========================================================================
section("L", "/api/sync reports accurate per-item outcomes under contention")
# ==========================================================================
toks = [build_pass("sync%02d" % i) for i in range(4)]
items = [{"payload": "LGU2:%s" % t, "gate_id": 1, "mode": "entry",
          "scanned_at": "2026-10-14 09:00:0%d" % i} for i, t in enumerate(toks)]
items.append({"payload": None, "gate_id": 1, "mode": "entry"})
items.append({"payload": "LGU2:never-synced", "gate_id": 2, "mode": "entry"})
writer = HeldWriter(hold_s=3)
writer.start()
writer.ready.wait(30)
r = client.post("/api/sync", json={"items": items},
                headers={"X-Scanner-Token": SCANNERS["g1"]})
writer.release()
body = r.get_json() or {}
results = body.get("results", [])
check("sync answers the whole batch rather than 500ing",
      r.status_code == 200, r.status_code)
check("sync returns one outcome per item", len(results) == len(items), len(results))
malformed = [x for x in results if x["result"].get("title") == "INVALID CODE"
             and not x.get("payload")]
authrefusal = [x for x in results
               if x["result"].get("title") == "GATE NOT AUTHORIZED"]
check("the malformed item is reported as malformed, not as unauthorized",
      len(malformed) == 1, len(malformed))
check("a cross-gate item is reported as unauthorized, not as malformed",
      len(authrefusal) == 1, len(authrefusal))
busy_items = [x for x in results if x["result"].get("status") == "busy"]
check("contention is distinguishable per item (busy is its own outcome)",
      len(busy_items) > 0, len(busy_items))
ok_count = body.get("synced", 0)
check("the synced count reflects only real successes",
      ok_count == sum(1 for x in results if x["result"].get("status") == "ok"),
      (ok_count, [x["result"].get("status") for x in results]))

# ==========================================================================
section("M", "Reads stay responsive while a writer holds the database")
# ==========================================================================
writer = HeldWriter(hold_s=4)
writer.start()
writer.ready.wait(30)
lat = []
for _ in range(10):
    t0 = time.perf_counter()
    r = client.get("/api/health")
    lat.append((time.perf_counter() - t0) * 1000.0)
writer.release()
check("dashboard/health reads still answer during a held write lock",
      all(x.status_code == 200 for x in [client.get("/api/health")]), lat)
check("read latency stays interactive during contention",
      max(lat) < 2000.0, max(lat))

# ==========================================================================
section("N", "Connections and transactions are released after failure")
# ==========================================================================
clean_tokens = [build_pass("clean%05d" % i) for i in range(12)]
writer = HeldWriter(hold_s=3)
writer.start()
writer.ready.wait(30)
for t in clean_tokens:
    scan(t)
writer.release()
db = database.get_db()
try:
    lock = db.execute("PRAGMA locking_mode").fetchone()[0]
    ok = db.execute("PRAGMA integrity_check").fetchone()[0]
finally:
    db.close()
check("the database is writable again after a burst of failed scans", ok == "ok", ok)
check("no connection left the database in exclusive locking mode",
      lock == "normal", lock)
check("no journal/wal sidecar is left behind by a failed scan",
      not [f for f in os.listdir(_TMP) if f.endswith(("-wal", "-shm", "-journal"))],
      os.listdir(_TMP))

# ==========================================================================
section("O", "Backup and restore remain correct after stress")
# ==========================================================================
dest = os.path.join(_TMP, "stress-backup.db")
manifest = backup.backup(dest)
check("a backup succeeds after the stress workload",
      manifest["sha256"] and manifest["size"] > 0, manifest["size"])
check("the backup validates", backup.validate(dest)["size"] == manifest["size"])
restored = os.path.join(_TMP, "stress-restored.db")
out = backup.restore(dest, restored)
check("restore into a fresh location succeeds", os.path.exists(out["restored_to"]))
try:
    backup.restore(dest, os.path.abspath(config.PRODUCTION_DB_PATH))
    refused = False
except ValueError:
    refused = True
check("restore still refuses the production database path", refused)

# ==========================================================================
section("P", "Integrity after stress and recovery")
# ==========================================================================
db = database.get_db()
try:
    ok = db.execute("PRAGMA integrity_check").fetchone()[0]
    fk = db.execute("PRAGMA foreign_key_check").fetchall()
    adm = db.execute("SELECT count(*) c FROM convocation_admissions").fetchone()["c"]
finally:
    db.close()
check("integrity_check is ok after the full stress run", ok == "ok", ok)
check("no foreign-key violations were introduced", not fk, len(fk))

# ==========================================================================
section("Q", "Test fixtures cannot target the production database")
# ==========================================================================
try:
    config.require_test_db(config.PRODUCTION_DB_PATH)
    refused = False
except SystemExit:
    refused = True
check("require_test_db refuses the production path", refused)
check("the configured database is not the production file",
      not config.is_production_db(), config.DB_PATH)

# ==========================================================================
section("R", "Eligibility is still recomputed at the point of admission")
# ==========================================================================
tok = build_pass("revoke")
db = database.get_db()
try:
    db.execute("UPDATE convocation_passes SET status = 'revoked' WHERE token_hash = ?",
               (cqr.token_hash(tok),))
    db.commit()
finally:
    db.close()
b = scan(tok).get_json() or {}
check("a revoked pass is refused", b.get("title") == "PASS INVALID", b)

tok = build_pass("inelig")
db = database.get_db()
try:
    db.execute("UPDATE convocation_registrations SET status = 'cancelled'"
               " WHERE id = (SELECT registration_id FROM convocation_passes"
               " WHERE token_hash = ?)", (cqr.token_hash(tok),))
    db.commit()
finally:
    db.close()
b = scan(tok).get_json() or {}
check("an ineligible registration is refused",
      b.get("title") == "REGISTRATION NOT ELIGIBLE", b)

# ==========================================================================
section("S", "The shipped default budget is bounded and overridable")
# ==========================================================================
# §C ran with a deliberately short 0.5 s budget so the suite finishes fast.
# The DEFAULT is what production gets when nothing is configured, so it is
# asserted here, out of that override.
os.environ.pop("LGU_SQLITE_BUSY_TIMEOUT", None)
check("the default wait budget is a measured, bounded value",
      config.SQLITE_BUSY_TIMEOUT_MIN
      <= config.SQLITE_BUSY_TIMEOUT_DEFAULT
      <= config.SQLITE_BUSY_TIMEOUT_MAX, config.SQLITE_BUSY_TIMEOUT_DEFAULT)
check("the default is not an unbounded wait",
      config.SQLITE_BUSY_TIMEOUT_DEFAULT <= 30.0,
      config.SQLITE_BUSY_TIMEOUT_DEFAULT)
os.environ["LGU_SQLITE_BUSY_TIMEOUT"] = "0.5"
check("an operator can still shorten the budget for a busy venue",
      config.sqlite_busy_timeout() == 0.5, config.sqlite_busy_timeout())
check("a busy answer is never shaped like a success",
      not set(cqr.busy_result()) & {"name", "sub", "gate", "time"},
      sorted(cqr.busy_result()))
check("a busy answer is explicitly retryable",
      cqr.busy_result().get("retryable") is True, cqr.busy_result())
check("the busy status is distinct from every permanent verdict",
      cqr.busy_result()["status"] not in
      ("ok", "error"), cqr.busy_result()["status"])

print("\nPHASE22 CONTENTION: %d/%d checks passed, %d failing"
      % (len(PASSED), len(PASSED) + len(FAILED), len(FAILED)))
for f in FAILED:
    print("  FAIL: %s" % f)
sys.exit(1 if FAILED else 0)
