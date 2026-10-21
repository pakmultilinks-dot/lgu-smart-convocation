"""Phase 27 — D3: convocation lifecycle bucketing in student history.

D3: ``convocations.status`` is written ONCE, at insert, as ``'planned'``; no
route in the product ever updates it, and the history bucket was derived from
that column alone. Every convocation therefore stayed bucket ``active``
forever — including one whose published date had passed months earlier, and
including ``completed``/``archived`` rows the schema already allows.

The bucket is now DERIVED on every read from the two authoritative signals
that do exist (a staff-declared terminal status, then the published date in
the portal timezone), and the entry carries an explicit ``lifecycle`` value so
a consumer can tell WHY it bucketed that way: ``undated`` means "we cannot
say" instead of a guessed past/active.

Proves on one disposable temp database:
  * future / today / yesterday published dates land in the right bucket
  * completed + archived are past whatever the dates say (terminal wins)
  * a never-announced or never-published event is NOT asserted past
  * confirmed beats expected; a rehearsal alone never ends the convocation
  * legacy full-ISO and malformed date values neither crash nor lie
  * reading history changes NOTHING — convocation rows, audit rows,
    ``user_version`` and the database file bytes are all identical
  * every existing claim is still returned, with its registration intact

Synthetic records only; app/lgu.db is never opened (stat-stamped before and
after to prove it).

Run from app/:  ..\\.venv\\Scripts\\python.exe scripts\\test_phase27_convocation_lifecycle.py
"""

import hashlib
import os
import sys
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

# Stat-stamp the production database BEFORE anything runs: the boundary check
# at the end proves this suite never opened or mutated it.
PROD_DB = os.path.join(APP_DIR, "lgu.db")
if os.path.exists(PROD_DB):
    _prod_stat = os.stat(PROD_DB)
    PROD_STAMP = (_prod_stat.st_size, _prod_stat.st_mtime_ns)
else:
    PROD_STAMP = None

TMP = tempfile.mkdtemp(prefix="lgu-p27lifecycle-")
os.environ["LGU_TESTING"] = "1"
os.environ["LGU_DB_PATH"] = os.path.join(TMP, "lifecycle.db")

import config  # noqa: E402
config.require_test_db()
import convocation_events as ev  # noqa: E402
import convocation_history as hist  # noqa: E402
import database  # noqa: E402

failures = 0
checks = 0

# All date maths is anchored to the portal timezone the product publishes
# with (DISPLAY_TZ) — the same clock ev.days_until() compares against.
TODAY = datetime.now(ZoneInfo(config.DISPLAY_TZ)).date()


def day(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def check(label, cond, detail=""):
    global failures, checks
    checks += 1
    if cond:
        print("ok   " + label)
    else:
        failures += 1
        print("FAIL " + label + (" - " + str(detail) if detail else ""))


print("Phase 27 convocation lifecycle (isolated temp database, production untouched)\n")

database.init_db()
database.seed()
c = database.connect()
# Phase 38 (DB-002): foreign keys are now enforced, so the claims this
# script writes need the account they reference to actually exist.
# AUTOINCREMENT starts at 1 and seed() creates no accounts -> id 1.
c.execute("INSERT INTO student_accounts (university_email, password_hash,"
          " created_at, updated_at) VALUES ('p27-lifecycle@uni.edu.pk', 'x',"
          " ?, ?)", (database._now(), database._now()))
c.commit()
ACCOUNT = {"id": 1}
_seq = [0]


def add_conv(status, dates, name):
    """One convocation + its claimed registration, optionally published."""
    _seq[0] += 1
    n = _seq[0]
    now = database._now()
    cid = c.execute(
        "INSERT INTO convocations (name, year, status, expected_date,"
        " confirmed_date, rehearsal_date, rehearsal_time, venue, instructions,"
        " is_active, created_at, updated_at)"
        " VALUES (?, '2026', ?, ?, ?, ?, '10:00', 'Main Hall', '', 0, ?, ?)",
        (name, status, dates.get("expected"), dates.get("confirmed"),
         dates.get("rehearsal"), now, now)).lastrowid
    rid = c.execute(
        "INSERT INTO convocation_registrations (convocation_id,"
        " registration_number, university_email, roll_number, student_name,"
        " department, status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'Lifecycle Student', 'CS', 'active', ?, ?)",
        (cid, "REG-L%04d" % cid, "l%d@uni.edu.pk" % cid, "09L%04d" % cid,
         now, now)).lastrowid
    c.execute("INSERT INTO registration_claims (account_id, convocation_id,"
              " registration_id, created_at) VALUES (1, ?, ?, ?)",
              (cid, rid, now))
    if dates.get("published"):
        ev.publish(c, ev.get(c, cid), "phase27-test")
    c.commit()
    return cid


def conv_of(cid, active=None):
    for e in hist.history_for_account(c, ACCOUNT, active):
        if e["convocation"]["id"] == cid:
            return e
    return None


def state(cid, active=None):
    e = conv_of(cid, active)
    return None if e is None else (e["convocation"]["bucket"],
                                   e["convocation"]["lifecycle"])


# ------------------------------------------------------------------ A. dates
future = add_conv("planned", {"expected": day(1), "published": True},
                  "Future expected")
today = add_conv("planned", {"expected": day(0), "published": True},
                 "Dated today")
past = add_conv("planned", {"expected": day(-3), "published": True},
                "Dated three days ago")
check("future published date stays in the ACTIVE bucket",
      state(future) == ("active", "upcoming"), state(future))
check("an event dated today still counts as running (date boundary)",
      state(today) == ("active", "upcoming"), state(today))
check("a published date that has passed lands in the PAST bucket",
      state(past) == ("past", "ended"), state(past))

# ------------------------------------------------------- B. terminal status
done = add_conv("completed", {"expected": day(30), "published": True},
                "Completed, future date")
arch = add_conv("archived", {}, "Archived, never dated")
check("completed is past even with a future date (staff declaration wins)",
      state(done) == ("past", "completed"), state(done))
check("archived is past with no publication at all",
      state(arch) == ("past", "archived"), state(arch))
check("completed still reports its stored status for the record",
      conv_of(done)["convocation"]["status"] == "completed",
      conv_of(done)["convocation"])

# ------------------------------------------------------------- C. no dates
undated = add_conv("planned", {}, "Never announced")
unpub = add_conv("planned", {"expected": day(-30)}, "Past draft, never published")
rehearsal_only = add_conv("planned", {"rehearsal": day(-30), "published": True},
                          "Rehearsal only")
legacy = add_conv("planned", {"expected": day(45) + "T09:00:00+05:00",
                              "published": True}, "Legacy full-ISO expected")
malformed = add_conv("planned", {"expected": "not-a-date", "published": True},
                     "Malformed date")
check("an event nobody has announced is NOT asserted past (uncertainty shown)",
      state(undated) == ("active", "undated"), state(undated))
check("an unpublished past draft stays active — students only ever see "
      "the published snapshot", state(unpub) == ("active", "undated"),
      state(unpub))
check("a rehearsal alone never proves the convocation is over",
      state(rehearsal_only) == ("active", "undated"), state(rehearsal_only))
check("legacy full-ISO expected_date is read as a date, not as junk",
      state(legacy) == ("active", "upcoming"), state(legacy))
check("a malformed date degrades to 'undated' instead of crashing or lying",
      state(malformed) == ("active", "undated"), state(malformed))

# ------------------------------------------------------------- D. precedence
mixed = add_conv("planned", {"expected": day(-30), "confirmed": day(5),
                             "published": True}, "Expected past, confirmed future")
check("the confirmed date beats the expected date",
      state(mixed) == ("active", "upcoming"), state(mixed))
noconf = add_conv("planned", {"expected": day(-30), "confirmed": "",
                              "published": True}, "Confirmed cleared")
check("clearing the confirmed date exposes the expected one again",
      state(noconf) == ("past", "ended"), state(noconf))

# --------------------------------------------------------- E. is_active row
designated = future
e = conv_of(designated, designated)
check("an explicitly designated convocation is still flagged is_active",
      e["convocation"]["is_active"] is True, e["convocation"])
check("bucket and lifecycle are independent of that designation",
      (e["convocation"]["bucket"], e["convocation"]["lifecycle"]) ==
      ("active", "upcoming"), e["convocation"])

# ------------------------------------------------- F. records are preserved
entries = hist.history_for_account(c, ACCOUNT)
want = c.execute("SELECT COUNT(*) n FROM registration_claims"
                 " WHERE account_id = 1").fetchone()["n"]
check("every existing claim is still returned", len(entries) == want,
      (len(entries), want))
check("entries keep their registration payload",
      all(x["registration"]["student_name"] == "Lifecycle Student" and
          x["registration"]["roll_number"] for x in entries), entries[:1])
check("entries keep the published event snapshot where one exists",
      conv_of(past)["event"]["date_state"] in
      ("not_announced", "expected", "confirmed"), conv_of(past)["event"])

# -------------------------------------------- G. a read NEVER writes (D3 law)
def db_bytes():
    c.commit()
    with open(config.DB_PATH, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def rows_of(sql):
    return [tuple(r) for r in c.execute(sql).fetchall()]


CONV_SQL = ("SELECT id, name, year, status, expected_date, confirmed_date,"
            " rehearsal_date, rehearsal_time, venue, instructions, is_active,"
            " created_at, updated_at FROM convocations ORDER BY id")
before_rows = rows_of(CONV_SQL)
before_audit = c.execute("SELECT COUNT(*) n FROM convocation_audit").fetchone()["n"]
before_ver = c.execute("PRAGMA user_version").fetchone()[0]
before_hash = db_bytes()
hist.history_for_account(c, ACCOUNT, designated)
hist.history_for_account(c, ACCOUNT)
after_rows = rows_of(CONV_SQL)
after_audit = c.execute("SELECT COUNT(*) n FROM convocation_audit").fetchone()["n"]
after_ver = c.execute("PRAGMA user_version").fetchone()[0]
after_hash = db_bytes()
check("reading history never rewrites a convocation row",
      before_rows == after_rows, (len(before_rows), len(after_rows)))
check("reading history never advances the stored status",
      [r[3] for r in after_rows] == [b[3] for b in before_rows]
      and any(b[3] == "planned" for b in before_rows),
      [r[3] for r in after_rows])
check("reading history writes no audit trail",
      before_audit == after_audit, (before_audit, after_audit))
check("reading history runs no migration", before_ver == after_ver,
      (before_ver, after_ver))
check("the database file is byte-identical across history reads",
      before_hash == after_hash, (before_hash, after_hash))

# --------------------------------------------------------- H. TZ anchoring
check("today is computed in the portal timezone, not UTC",
      database._now()[:10] == TODAY.isoformat(),
      (database._now(), TODAY.isoformat()))
check("days_until counts the portal-today boundary as 0 (still running)",
      ev.days_until(day(0)) == 0, ev.days_until(day(0)))
check("days_until puts the portal-yesterday squarely in the past",
      ev.days_until(day(-1)) == -1, ev.days_until(day(-1)))

# ------------------------------------------------- I. boundary: production
c.close()
if PROD_STAMP is not None:
    _stat = os.stat(PROD_DB)
    check("production database was never opened",
          (_stat.st_size, _stat.st_mtime_ns) == PROD_STAMP,
          (_stat.st_size, _stat.st_mtime_ns, PROD_STAMP))
else:
    check("production database still absent", not os.path.exists(PROD_DB))

print("\n%d checks, %d failures" % (checks, failures))
sys.exit(1 if failures else 0)
