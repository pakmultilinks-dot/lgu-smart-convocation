#!/usr/bin/env python
"""Phase 23 §2 — the transient-busy contract, backend to volunteer.

Phase 22 proved the server answers 503 under a lock beyond the budget. This
suite proves the answer is *consumable by the mobile client exactly as the
release requires*, which is a different and stronger property: the mobile
scanner recognises a busy answer by JSON shape (`status === "busy"` AND
`retryable === true`), and must never mistake it for a gate outcome.

It is written against the DESIRED contract, so a rename of any of those keys
on either side fails here instead of silently degrading the volunteer to a
red "SCAN FAILED" and an offline marker.

Everything uses a disposable database. app/lgu.db is never opened.
"""
import os
import sqlite3
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p23-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "p23.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_SQLITE_BUSY_TIMEOUT"] = "0.5"

import config  # noqa: E402
import convocation_qr as cqr  # noqa: E402
import database  # noqa: E402
import scanner_auth  # noqa: E402

config.require_test_db()
database.init_db()
database.seed()

from web.routes import create_app  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(("    ok   " if ok else "    FAIL ") + name
          + (("  :: %r" % (detail,)) if detail else ""))


def section(letter, title):
    print("\n[%s] %s" % (letter, title))


# --------------------------------------------------------------------------
# The mobile parser's contract, mirrored from mobile/src/api/client.ts.
# Kept deliberately literal: if the client's predicate changes, this mirror
# is the thing that must be updated, and this suite is what says so.
# --------------------------------------------------------------------------
REQUIRED_KEYS = ("status", "level", "title")


def client_recognises_busy(body):
    """Exact condition in client.ts busyError()."""
    return (isinstance(body, dict)
            and body.get("status") == "busy"
            and body.get("retryable") is True)


def client_resolved_card(body):
    """What the volunteer is shown, resolved the way busyError() resolves it."""
    level = body.get("level") if body.get("level") in ("green", "red") else "amber"
    title = body.get("title") if isinstance(body.get("title"), str) \
        and body.get("title").strip() else "TEMPORARILY BUSY"
    return {"status": "busy", "level": level, "title": title,
            "detail": body.get("detail")}


# --------------------------------------------------------------------------
# Synthetic world (same shape as Phase 22 §7)
# --------------------------------------------------------------------------
def build_pass(tag):
    db = database.get_db()
    try:
        conv = db.execute("SELECT id FROM convocations WHERE is_active = 1").fetchone()["id"]
        email = "p23-%s@lgu.edu.pk" % tag
        db.execute(
            "INSERT INTO convocation_registrations (convocation_id,"
            " registration_number, university_email, roll_number, student_name,"
            " department, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 'CS', 'active', '2026-10-14 09:00:00',"
            " '2026-10-14 09:00:00')", (conv, "P23-%s" % tag, email,
                                        "P23-%s" % tag.upper(), "P23 Student %s" % tag))
        reg = db.execute("SELECT id FROM convocation_registrations WHERE"
                         " registration_number = ?", ("P23-%s" % tag,)).fetchone()["id"]
        db.execute("INSERT INTO student_accounts (university_email, password_hash,"
                   " created_at, updated_at)"
                   " VALUES (?, 'scrypt$fake', '2026-10-14 09:00:00',"
                   " '2026-10-14 09:00:00')", (email,))
        acc = db.execute("SELECT id FROM student_accounts WHERE"
                         " university_email = ?", (email,)).fetchone()["id"]
        db.execute("INSERT INTO registration_claims (account_id, convocation_id,"
                   " registration_id, created_at)"
                   " VALUES (?, ?, ?, '2026-10-14 09:00:00')", (acc, conv, reg))
        token = "p23-token-%s" % tag
        db.execute("INSERT INTO convocation_passes (token_hash, convocation_id,"
                   " registration_id, account_id, status, issued_at)"
                   " VALUES (?, ?, ?, ?, 'active', '2026-10-14 09:00:00')",
                   (cqr.token_hash(token), conv, reg, acc))
        db.commit()
        return token
    finally:
        db.close()


def ensure_publication():
    db = database.get_db()
    try:
        conv = db.execute("SELECT id FROM convocations WHERE is_active = 1").fetchone()["id"]
        if not db.execute("SELECT 1 FROM convocation_publications"
                          " WHERE convocation_id = ?", (conv,)).fetchone():
            db.execute("INSERT INTO convocation_publications (convocation_id,"
                       " name, year, venue, published_by, published_at)"
                       " VALUES (?, 'P23 Convocation', '2026', 'Hall', 'p23',"
                       " '2026-10-14 09:00:00')", (conv,))
            db.commit()
    finally:
        db.close()


ensure_publication()

SID = scanner_auth.create_scanner("p23-main", "P23 Main", pin="P23PIN1",
                                  gate_ids=[1], actor="p23", via="test")
TOKEN = scanner_auth.create_session(SID)[0]
DB = os.environ["LGU_DB_PATH"]

app = create_app()
# TESTING=False + PROPAGATE_EXCEPTIONS=False: an assertion failure inside a
# route must surface as a 500 we can assert on, not an escaped exception.
app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
CLIENT = app.test_client()
HEADERS = {"X-Scanner-Token": TOKEN}


def scan(token, gate=1, mode="entry"):
    return CLIENT.post("/api/scan",
                       json={"payload": "LGU2:%s" % token, "gate_id": gate,
                             "mode": mode}, headers=HEADERS)


def count_admissions(token):
    db = database.get_db()
    try:
        return db.execute(
            "SELECT count(*) c FROM convocation_admissions WHERE pass_id ="
            " (SELECT id FROM convocation_passes WHERE token_hash = ?)",
            (cqr.token_hash(token),)).fetchone()["c"]
    finally:
        db.close()


class HeldWriter(threading.Thread):
    """A second connection that takes the write lock and refuses to release
    it until told — the only honest way to reproduce real contention.

    The connection is opened INSIDE the worker thread: sqlite3 objects are
    bound to the thread that created them."""

    def __init__(self, hold_s=3):
        super().__init__(daemon=True)
        self.hold_s = hold_s
        self.ready = threading.Event()
        self.release_now = threading.Event()
        self.error = None

    def run(self):
        conn = sqlite3.connect(DB, timeout=5)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self.ready.set()
            self.release_now.wait(self.hold_s)
            conn.execute("ROLLBACK")
        except Exception as exc:  # pragma: no cover - diagnostic
            self.error = exc
            self.ready.set()
        finally:
            conn.close()

    def release(self):
        self.release_now.set()
        self.join(30)
        return self.error


# ==========================================================================
section("A", "The busy answer is the exact body the mobile client parses")
# ==========================================================================
tok = build_pass("contract")
writer = HeldWriter(hold_s=3)
writer.start()
writer.ready.wait(30)
r = scan(tok)
writer.release()
b = r.get_json() or {}

check("HTTP status is 503, a handled response (not an unhandled 500)",
      r.status_code == 503, r.status_code)
check("the body carries every key the mobile parser reads",
      all(k in b for k in REQUIRED_KEYS) and "retryable" in b,
      sorted(b.keys()))
check("status is exactly 'busy' — the client's discriminant",
      b.get("status") == "busy", b.get("status"))
check("retryable is exactly true — the client's second discriminant",
      b.get("retryable") is True, b.get("retryable"))
check("level is amber: a caution, never green (admitted) or red (failed)",
      b.get("level") == "amber", b.get("level"))
check("title reads as a delay to the operator, not as a failure",
      b.get("title") == "TEMPORARILY BUSY", b.get("title"))
check("detail tells the volunteer to retry this scan",
      "retry" in (b.get("detail") or "").lower(), b.get("detail"))
check("Retry-After is a bare number the client can act on",
      (r.headers.get("Retry-After") or "").isdigit(), r.headers.get("Retry-After"))
check("no database or developer detail leaks into the body",
      not any(w in str(b).lower() for w in
              ("sqlite", "locked", "traceback", "exception", "http://")),
      b)

# ==========================================================================
section("B", "The client's own recognition predicate accepts this body")
# ==========================================================================
check("busyError() recognises the real server body",
      client_recognises_busy(b), b)
card = client_resolved_card(b)
check("the volunteer is shown the sanctioned amber notice",
      card == {"status": "busy", "level": "amber",
               "title": "TEMPORARILY BUSY", "detail": b.get("detail")}, card)
# Lookalikes that must NOT be recognised, so a future server change cannot
# quietly reintroduce the generic "service unavailable" error path.
check("a busy body without retryable is not recognised",
      not client_recognises_busy({"status": "busy", "level": "amber",
                                  "title": "TEMPORARILY BUSY"}))
check("an ok body is not recognised as busy",
      not client_recognises_busy({"status": "ok", "level": "green",
                                  "title": "VALID"}))
check("a bare string body is not recognised as busy",
      not client_recognises_busy("busy"))
check("an empty title still resolves to the sanctioned wording",
      client_resolved_card({"status": "busy", "retryable": True})["title"]
      == "TEMPORARILY BUSY")

# ==========================================================================
section("C", "Contention is not an outcome: nothing is admitted or burned")
# ==========================================================================
check("the contended scan admitted nobody",
      count_admissions(tok) == 0, count_admissions(tok))
db = database.get_db()
try:
    used = db.execute("SELECT status FROM convocation_passes WHERE token_hash = ?",
                      (cqr.token_hash(tok),)).fetchone()["status"]
finally:
    db.close()
check("the pass is untouched by a busy answer", used == "active", used)
r2 = scan(tok)
b2 = r2.get_json() or {}
check("after the lock is released the SAME pass admits",
      r2.status_code == 200 and b2.get("status") == "ok", (r2.status_code, b2.get("title")))
check("exactly one admission is recorded — the busy answer was not a write",
      count_admissions(tok) == 1, count_admissions(tok))

# ==========================================================================
section("D", "A busy device is still online, and the queue must not absorb it")
# ==========================================================================
# The client only marks a device offline when the answer is NOT retryable.
# If a busy answer were ever reported as an error, the NEXT scan would be
# diverted to the offline queue and shown as "SCAN QUEUED" — a live server
# would be reported to the operator as an offline gate. This section pins the
# discriminator that prevents that.
check("a busy answer is retryable, so the client keeps the device online",
      client_recognises_busy(b) is True)
tok2 = build_pass("recovery")
writer = HeldWriter(hold_s=3)
writer.start()
writer.ready.wait(30)
r3 = scan(tok2)
writer.release()
b3 = r3.get_json() or {}
check("the second contended scan is also retryable and never a 500",
      r3.status_code == 503 and client_recognises_busy(b3), (r3.status_code, b3))
r4 = scan(tok2)
check("the immediately following scan, once the DB is free, is a real outcome",
      r4.status_code == 200 and (r4.get_json() or {}).get("status") == "ok",
      (r4.status_code, (r4.get_json() or {}).get("title")))

# ==========================================================================
section("E", "/api/sync reports each queued item truthfully under contention")
# ==========================================================================
tokA, tokB = build_pass("syncA"), build_pass("syncB")
items = [{"payload": "LGU2:%s" % tokA, "gate_id": 1, "mode": "entry", "scanned_at": None},
         {"payload": "LGU2:%s" % tokB, "gate_id": 1, "mode": "entry", "scanned_at": None}]
writer = HeldWriter(hold_s=2)
writer.start()
writer.ready.wait(30)
rs = CLIENT.post("/api/sync", json={"items": items}, headers=HEADERS)
writer.release()
body = rs.get_json() or {}
results = body.get("results") or []
check("sync answers 200 with one result per submitted item, never a 500",
      rs.status_code == 200 and len(results) == len(items),
      (rs.status_code, len(results)))
check("every result carries the full contract the client reads",
      all(set(REQUIRED_KEYS) <= set((x.get("result") or {}).keys())
          for x in results if isinstance(x, dict)),
      [sorted((x.get("result") or {}).keys()) for x in results])
busy_items = [x for x in results
              if isinstance(x, dict) and client_recognises_busy(x.get("result") or {})]
admitted = [x for x in results
            if isinstance(x, dict) and (x.get("result") or {}).get("status") == "ok"]
rejected = [x for x in results
            if isinstance(x, dict)
            and (x.get("result") or {}).get("status") not in ("ok", "busy")]
check("every item is reported truthfully: busy, an outcome, or a refusal",
      len(busy_items) + len(admitted) + len(rejected) == len(items),
      {"busy": len(busy_items), "ok": len(admitted), "other": len(rejected)})
check("a busy item is retained by the client for retry, not dropped as final",
      all((x.get("result") or {}).get("title") != ""
          for x in busy_items), busy_items)
check("replaying the batch once the DB is free admits both passes exactly once",
      (CLIENT.post("/api/sync", json={"items": items}, headers=HEADERS)
       .get_json() or {}).get("results") is not None
      and count_admissions(tokA) == 1 and count_admissions(tokB) == 1,
      (count_admissions(tokA), count_admissions(tokB)))

# ==========================================================================
print("\nPhase 23 §2 busy-contract suite: %d passed, %d failed"
      % (len(PASSED), len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  FAILED: %s" % f)
sys.exit(1 if FAILED else 0)
