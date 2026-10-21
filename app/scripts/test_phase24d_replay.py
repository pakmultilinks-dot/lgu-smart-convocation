"""Phase 24D — convocation queued-scan replay idempotency.

Reproduces the confirmed defect: a queued LGU2 convocation scan that was
already admitted by an earlier sync is answered `ALREADY ADMITTED` (red),
which the mobile offline queue does NOT treat as a permanent rejection —
so the item is retried forever and the volunteer sees a red failure for an
operation that actually succeeded. The roster path already solves this with
models.queued_scan_exists → `ALREADY SYNCED` (amber, permanent). This test
proves the convocation path lacked the equivalent, then asserts the fix.

Uses a disposable database; the production DB is never touched.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p24d-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "p24d.db")
os.environ["LGU_EMAIL_MODE"] = "fake"

import config                      # noqa: E402
import convocation_qr as cqr       # noqa: E402
import database                    # noqa: E402
import scanner_auth                # noqa: E402
from web.routes import create_app  # noqa: E402

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


def build_pass(tag):
    """Seed a registration + claimed account + active convocation pass."""
    db = database.get_db()
    try:
        conv = db.execute(
            "SELECT id FROM convocations WHERE is_active = 1").fetchone()["id"]
        email = "p24d-%s@lgu.edu.pk" % tag
        db.execute(
            "INSERT INTO convocation_registrations (convocation_id,"
            " registration_number, university_email, roll_number, student_name,"
            " department, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 'CS', 'active', '2026-10-14 09:00:00',"
            " '2026-10-14 09:00:00')",
            (conv, "P24D-%s" % tag, email, "P24D-%s" % tag.upper(),
             "P24D Student %s" % tag))
        reg = db.execute(
            "SELECT id FROM convocation_registrations WHERE registration_number"
            " = ?", ("P24D-%s" % tag,)).fetchone()["id"]
        db.execute(
            "INSERT INTO student_accounts (university_email, password_hash,"
            " created_at, updated_at) VALUES (?, 'scrypt$fake',"
            " '2026-10-14 09:00:00', '2026-10-14 09:00:00')", (email,))
        acc = db.execute(
            "SELECT id FROM student_accounts WHERE university_email = ?",
            (email,)).fetchone()["id"]
        db.execute(
            "INSERT INTO registration_claims (account_id, convocation_id,"
            " registration_id, created_at) VALUES (?, ?, ?,"
            " '2026-10-14 09:00:00')", (acc, conv, reg))
        token = "p24d-token-%s" % tag
        db.execute(
            "INSERT INTO convocation_passes (token_hash, convocation_id,"
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
        conv = db.execute(
            "SELECT id FROM convocations WHERE is_active = 1").fetchone()["id"]
        if not db.execute(
                "SELECT 1 FROM convocation_publications WHERE convocation_id"
                " = ?", (conv,)).fetchone():
            db.execute(
                "INSERT INTO convocation_publications (convocation_id, name,"
                " year, venue, published_by, published_at)"
                " VALUES (?, 'P24D Convocation', '2026', 'Hall', 'p24d',"
                " '2026-10-14 09:00:00')", (conv,))
            db.commit()
    finally:
        db.close()


ensure_publication()

SID = scanner_auth.create_scanner("p24d-main", "P24D Main", pin="P24DPIN1",
                                  gate_ids=[1, 2], actor="p24d", via="test")
TOKEN = scanner_auth.create_session(SID)[0]
HDRS = {"X-Scanner-Token": TOKEN}

app = create_app()
app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
CLIENT = app.test_client()


def sync(items):
    return CLIENT.post("/api/sync", json={"items": items}, headers=HDRS)


def count_admissions(token):
    db = database.get_db()
    try:
        return db.execute(
            "SELECT count(*) c FROM convocation_admissions WHERE pass_id ="
            " (SELECT id FROM convocation_passes WHERE token_hash = ?)",
            (cqr.token_hash(token),)).fetchone()["c"]
    finally:
        db.close()


# The exact PERMANENT_REJECTIONS set in mobile/src/store/offlineQueue.ts.
# Kept in sync by the mobile-side test; asserted here so the backend title
# chosen for a replay is one the client actually drops. Phase 24D added
# ALREADY ADMITTED and GATE NOT AUTHORIZED — both permanent, both previously
# missing, which made those outcomes retry forever.
CLIENT_PERMANENT_REJECTIONS = {
    "ALREADY INSIDE", "ALREADY USED", "ALREADY SYNCED", "ALREADY ADMITTED",
    "GATE NOT AUTHORIZED", "NOT INSIDE",
    "INVALID CODE", "UNKNOWN CODE", "NO GATE SELECTED", "NO MODE SELECTED",
    "UNKNOWN GATE", "GUEST PASS IS ENTRY ONLY",
}

print("=" * 66)
print("Phase 24D — convocation queued-scan replay idempotency")
print("disposable DB:", os.environ["LGU_DB_PATH"])
print("=" * 66)

# ---------------------------------------------------------------- scenario 1
# An offline-queued convocation scan is synced for the first time: recorded.
TOKEN_A = build_pass("alpha")
item = {"payload": "LGU2:%s" % TOKEN_A, "gate_id": 1, "mode": "entry",
        "scanned_at": "2026-10-15 10:00:00"}
r1 = sync([item])
b1 = r1.get_json()
check("1. first queued sync records the admission",
      r1.status_code == 200 and b1["synced"] == 1
      and b1["results"][0]["result"]["status"] == "ok", b1)
check("1. exactly one admission row exists",
      count_admissions(TOKEN_A) == 1, count_admissions(TOKEN_A))

# ---------------------------------------------------------------- scenario 2
# THE DEFECT: the response is lost, so the client re-sends the SAME queued
# item. The server must answer with a title the client drops as permanent —
# NOT a transient retry, and never a second admission.
r2 = sync([item])
b2 = r2.get_json()
title2 = b2["results"][0]["result"]["title"]
check("2. replay never creates a second admission",
      count_admissions(TOKEN_A) == 1, count_admissions(TOKEN_A))
check("2. replay answers a PERMANENT title the client drops",
      title2 in CLIENT_PERMANENT_REJECTIONS,
      (title2, "not in client PERMANENT_REJECTIONS -> infinite retry"))
check("2. replay is not reported as a fresh success",
      b2["results"][0]["result"]["status"] != "ok"
      and b2["synced"] == 0, b2)
check("2. replay title is idempotent-replay (amber), not a red failure",
      b2["results"][0]["result"]["title"] == "ALREADY SYNCED"
      and b2["results"][0]["result"]["level"] == "amber", b2)

# ---------------------------------------------------------------- scenario 3
# A GENUINE duplicate from another device/gate is still a real duplicate:
# it must be refused and must never be converted into a second admission.
TOKEN_B = build_pass("beta")
r3a = sync([{"payload": "LGU2:%s" % TOKEN_B, "gate_id": 1, "mode": "entry",
             "scanned_at": "2026-10-15 11:00:00"}])
b3a = r3a.get_json()
check("3. the genuine first scan of B succeeds",
      b3a["synced"] == 1, b3a)
r3b = sync([{"payload": "LGU2:%s" % TOKEN_B, "gate_id": 2, "mode": "entry",
             "scanned_at": "2026-10-15 11:05:00"}])
b3b = r3b.get_json()
title3 = b3b["results"][0]["result"]["title"]
check("3. a second scan of the same registration is refused",
      b3b["results"][0]["result"]["status"] != "ok", b3b)
check("3. genuine duplicate title is one the client drops",
      title3 in CLIENT_PERMANENT_REJECTIONS, title3)
check("3. genuine duplicate never becomes a second admission",
      count_admissions(TOKEN_B) == 1, count_admissions(TOKEN_B))

# ---------------------------------------------------------------- scenario 4
# Mixed outcomes in one batch: each result must align positionally, and only
# the transient failure stays queued (permanent drops + successes removed).
TOKEN_C = build_pass("gamma")
TOKEN_D = build_pass("delta")
mixed = [
    {"payload": "LGU2:%s" % TOKEN_C, "gate_id": 1, "mode": "entry",
     "scanned_at": "2026-10-15 12:00:00"},        # 0 -> ok (fresh)
    {"payload": "LGU2:%s" % TOKEN_A, "gate_id": 1, "mode": "entry",
     "scanned_at": "2026-10-15 10:00:00"},        # 1 -> replay (permanent)
    {"payload": "LGU2:%s" % TOKEN_D, "gate_id": 99, "mode": "entry",
     "scanned_at": "2026-10-15 12:00:00"},        # 2 -> unknown gate (perm.)
    {"payload": "", "gate_id": 1, "mode": "entry",
     "scanned_at": "2026-10-15 12:00:00"},        # 3 -> malformed (permanent)
]
r4 = sync(mixed)
b4 = r4.get_json()
res = b4["results"]
check("4. results are positional (one result per item, in order)",
      len(res) == 4
      and all(res[i]["payload"] == mixed[i]["payload"] for i in range(4)), b4)
check("4. item0 fresh scan -> ok",
      res[0]["result"]["status"] == "ok", res[0])
check("4. item1 replay -> permanent, not transient",
      res[1]["result"]["title"] in CLIENT_PERMANENT_REJECTIONS
      and res[1]["result"]["status"] != "ok", res[1])
check("4. item2 unknown gate -> GATE NOT AUTHORIZED (permanent)",
      res[2]["result"]["title"] in CLIENT_PERMANENT_REJECTIONS, res[2])
check("4. item3 malformed -> INVALID CODE (permanent)",
      res[3]["result"]["title"] in CLIENT_PERMANENT_REJECTIONS, res[3])
check("4. only the fresh scan counts as synced",
      b4["synced"] == 1, b4)

print("-" * 66)
print("%d checks, %d failures" % (PASS, FAIL))
print("PROD_DB untouched (never opened by this test)")
raise SystemExit(1 if FAIL else 0)
