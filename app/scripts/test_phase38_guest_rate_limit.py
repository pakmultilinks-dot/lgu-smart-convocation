"""Phase 38 — BE-003: guest self-registration rate limiting.

The only anonymous endpoint that mints a bearer QR credential now carries:
- a shared per-IP windowed bucket (form + JSON — one budget, not two), and
- a table-derived daily cap (restart-proof, counts every mint).

Checks run against a disposable database via the real Flask test client:
1. valid registrations succeed while under budget;
2. the Nth attempt in the window is refused with HTTP 429 + message;
3. the FORM path rides the same bucket as the JSON path;
4. an exhausted bucket pre-empts input validation (blocked = 429, not 400);
5. the daily cap refuses minting when the guests table is at capacity;
6. GET /guests and other buckets are unaffected;
7. production DB re-stamped read-only (sha256/size/user_version untouched).
"""
import hashlib
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LGU_TESTING"] = "1"
_TMP = tempfile.mkdtemp(prefix="lgu-p38rl-")
os.environ["LGU_DB_PATH"] = os.path.join(_TMP, "p38rl.db")
os.environ["LGU_ALLOW_DEMO_SECRETS"] = "1"
# Read at call time by routes, but set BEFORE import so intent is explicit.
os.environ["LGU_GUEST_WINDOW"] = "60"
os.environ["LGU_GUEST_MAX_ATTEMPTS"] = "3"

from _production_boundary import production_stamp
_PRODUCTION_BEFORE = production_stamp()

import config                      # noqa: E402
import database                    # noqa: E402
import models                      # noqa: E402
from web import routes             # noqa: E402
from web.routes import create_app  # noqa: E402

config.require_test_db()
assert config.GUEST_RATE_MAX_ATTEMPTS == 3, config.GUEST_RATE_MAX_ATTEMPTS
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


def host_pool(n):
    """n roster hosts that currently hold no guest (fresh disposable DB)."""
    db = database.connect()
    rows = db.execute(
        "SELECT roll_no FROM students WHERE qr_id IS NOT NULL"
        " AND roll_no NOT IN (SELECT host_roll_no FROM guests)"
        " ORDER BY roll_no LIMIT ?", (n,)).fetchall()
    db.close()
    return [r["roll_no"] for r in rows]


app = create_app()
client = app.test_client()
client.environ_base["HTTP_X_ADMIN_PIN"] = str(config.ADMIN_PIN)
with client.session_transaction() as sess:
    sess["lgu_admin"] = True
H = host_pool(10)
assert len(H) >= 8, "seed did not provide enough guest-free hosts"


def post_json(host, name="P38 RL Guest"):
    # phone derived per host: the twin (name+phone) rule rejects identical
    # identities, which would mask what this test measures (the limiter).
    return client.post("/api/guests", json={
        "name": name, "phone": "0300" + host, "host_roll_no": host,
        "payment_reference": "PAY-" + host, "payment_verified": True})


def reset_bucket():
    routes._GUEST_REG_ATTEMPTS.clear()


print("=" * 70)
print("Phase 38 — BE-003 guest registration rate limiting")
print("disposable DB:", os.environ["LGU_DB_PATH"])
print("=" * 70)

print("\n[1] Under budget: three registrations succeed, fourth is 429")
reset_bucket()
codes = [post_json(h).status_code for h in H[:3]]
r4 = post_json(H[3])
check("first three JSON registrations accepted", codes == [200, 200, 200],
      codes)
check("fourth attempt refused with 429", r4.status_code == 429,
      r4.status_code)
check("429 carries the limiter message",
      (r4.get_json() or {}).get("error") == routes._GUEST_REG_MSG,
      r4.get_json())

print("\n[2] Form path shares the SAME bucket (one budget)")
reset_bucket()
j1 = post_json(H[3], "P38 D").status_code      # attempt 1 (fresh host)
j2 = post_json(H[4], "P38 E").status_code      # attempt 2
f1 = client.post("/guests", data={"name": "P38 F", "phone": "0300 6",
                                  "host_roll_no": H[5], "payment_reference": "FORM-5", "payment_verified": "on"})   # attempt 3
f2 = client.post("/guests", data={"name": "P38 G", "phone": "0300 7",
                                  "host_roll_no": H[6], "payment_reference": "FORM-6", "payment_verified": "on"})   # attempt 4 -> block
check("attempts 1-2 (JSON) accepted", j1 == 200 and j2 == 200, (j1, j2))
check("attempt 3 (form) within budget -> 302 redirect",
      f1.status_code == 302, f1.status_code)
check("attempt 4 (form) blocked by the shared bucket",
      f2.status_code == 200 and routes._GUEST_REG_MSG
      in (f2.get_data(as_text=True) or ""),
      (f2.status_code, (f2.get_data(as_text=True) or "")[:160]))

print("\n[3] Exhausted bucket pre-empts validation (429, not 400)")
reset_bucket()
for i, h in enumerate(H[:3]):
    post_json(h, "P38 Dup %d" % i)             # counted; mostly 400s
r_block = client.post("/api/guests", json={})   # would be 400 if open
check("malformed body while limited -> 429",
      r_block.status_code == 429, r_block.status_code)

print("\n[4] Daily cap refuses minting when the table is at capacity")
reset_bucket()
saved_cap = config.GUEST_DAILY_CAP
config.GUEST_DAILY_CAP = models.guests_created_today()   # already at cap
r_cap = post_json(H[7])
check("at-cap attempt refused with 429", r_cap.status_code == 429,
      r_cap.status_code)
check("cap message is the daily-capacity reply",
      (r_cap.get_json() or {}).get("error") == routes._GUEST_CAP_MSG,
      r_cap.get_json())
config.GUEST_DAILY_CAP = saved_cap
reset_bucket()
r_ok = post_json(H[7], "P38 Cap Pass")
check("registration works again below the cap",
      r_ok.status_code == 200, (r_ok.status_code, r_ok.get_json()))

print("\n[5] GET /guests unaffected by the limiter")
reset_bucket()
codes_get = [client.get("/guests").status_code for _ in range(6)]
check("repeated GET /guests all 200", codes_get == [200] * 6, codes_get)

print("\n[6] Production database untouched (read-only re-stamp)")
PROD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "lgu.db")
check("production database unchanged or remains absent",
      production_stamp() == _PRODUCTION_BEFORE)

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)