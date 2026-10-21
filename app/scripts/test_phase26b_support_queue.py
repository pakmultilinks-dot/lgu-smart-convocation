"""Phase 26B: the Examination Department support queue must be COMPLETE when
filtered.

Defect proven here: ``exam_support_routes._queue_rows`` used to call
``support_requests.search`` WITHOUT a status filter (fetching only the most
recent ``PAGE*4 = 100`` rows) and then narrow by status in Python. With more
than 100 requests, a status-filtered view (e.g. "open") silently dropped
older matching requests while ``counts_by_status`` still counted them — the
queue under-reported the very rows the dashboard said were waiting.

This suite runs on ONE disposable temp database: it creates 120 open +
10 resolved requests for the active convocation, then asserts that the
"open" staff queue returns all 120 open rows (not a truncated window) and
that a category filter is applied in SQL alongside status. app/lgu.db is
never opened (stat-stamped before and after).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase26b_support_queue.py
"""

import os
import re
import sqlite3
import sys
import tempfile

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

PROD_DB = os.path.join(APP_DIR, "lgu.db")
if os.path.exists(PROD_DB):
    _s = os.stat(PROD_DB)
    PROD_STAMP = (_s.st_size, _s.st_mtime_ns)
else:
    PROD_STAMP = None

TMP = tempfile.mkdtemp(prefix="lgu-p26b-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "support.db")
os.environ["LGU_EMAIL_MODE"] = "fake"
os.environ["LGU_STUDENT_PHOTO_DIR"] = os.path.join(TMP, "student-photos")

import config  # noqa: E402
config.require_test_db()
import database  # noqa: E402
import student_auth as sa  # noqa: E402
import support_requests as sup  # noqa: E402

failures = 0
checks = 0


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


def raw(sql, args=()):
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        c.commit()
        return rows
    finally:
        c.close()


database.init_db()
database.seed()
db = database.get_db()
CONV = raw("SELECT id FROM convocations WHERE is_active = 1")[0]["id"]

# 120 OPEN (mixed categories) + 10 resolved. All belong to one account so we
# do not need student sign-ups to exercise the staff queue path.
ACCOUNT_ID = sa.create_account(db, "queue.probe@uni.edu.pk", "QueueProbe2026")

OPEN_N = 120
RESOLVED_N = 10
for i in range(OPEN_N + RESOLVED_N):
    category = "correction" if i % 2 == 0 else "general"
    sup.create(db, CONV, ACCOUNT_ID, None,
               {"category": category, "subject": "Open row %d" % i,
                "message": "Body for open row %d" % i})
# Resolve the last RESOLVED_N so they leave every open filter.
for row in db.execute("SELECT * FROM support_requests WHERE convocation_id = ?"
                      " ORDER BY id DESC LIMIT ?",
                      (CONV, RESOLVED_N)).fetchall():
    sup.set_status(db, row, "resolved", actor="officer", body="done")

total = raw("SELECT COUNT(*) AS n FROM support_requests"
            " WHERE convocation_id = ?", (CONV,))[0]["n"]
check("setup: 130 requests exist for the active convocation",
      total == OPEN_N + RESOLVED_N, total)

counts = sup.counts_by_status(db, CONV)
open_counted = sum(counts[s] for s in sup.OPEN_STATUSES)
check("counts: the dashboard counts %d open requests" % OPEN_N,
      open_counted == OPEN_N, counts)

# The route's own fetch: 'open' expands to every unresolved status and is now
# applied in SQL, so the LIMIT bounds matching rows only. Under the old
# Python-side filter the 100 most-recent rows (mixed statuses) were narrowed
# after the fetch, returning ~90 open rows; SQL filtering returns 100 open.
rows = sup.search(db, CONV, q="", status=sup.OPEN_STATUSES,
                  category="", limit=25 * 4, offset=0)
check("queue: the route's 100-row window is 100 OPEN rows (was ~90)",
      len(rows) == 100 and all(r["status"] in sup.OPEN_STATUSES for r in rows),
      len(rows))
# With a limit above the open count, every matching row comes back.
all_open = sup.search(db, CONV, q="", status=sup.OPEN_STATUSES,
                      category="", limit=25 * 8, offset=0)
check("queue: the 'open' filter returns every matching row (not a window)",
      len(all_open) == OPEN_N, len(all_open))
check("queue: no resolved request leaks into the 'open' view",
      all(r["status"] in sup.OPEN_STATUSES for r in all_open))

# Category + status together, in SQL.
crows = sup.search(db, CONV, q="", status=sup.OPEN_STATUSES,
                   category="correction", limit=25 * 8, offset=0)
expected_correction = sum(
    1 for i in range(OPEN_N) if i % 2 == 0)
check("queue: category filter narrows the open set correctly",
      len(crows) == expected_correction
      and all(r["category"] == "correction" for r in crows),
      len(crows))

# A single status string still works (back-compat).
srows = sup.search(db, CONV, q="", status="resolved", limit=25 * 4)
check("queue: a single status string still resolves in SQL",
      len(srows) == RESOLVED_N, len(srows))

# An unknown status in a tuple is rejected loudly.
try:
    sup.search(db, CONV, status=("submitted", "bogus"))
    check("queue: an unknown status filter is rejected", False)
except sup.SupportError:
    check("queue: an unknown status filter is rejected", True)

db.close()

# app/lgu.db untouched.
if PROD_STAMP is not None:
    _s = os.stat(PROD_DB)
    check("production lgu.db untouched",
          (_s.st_size, _s.st_mtime_ns) == PROD_STAMP,
          (_s.st_size, _s.st_mtime_ns))
else:
    check("production lgu.db untouched (absent stays absent)",
          not os.path.exists(PROD_DB))

print("\nRESULT: %d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
