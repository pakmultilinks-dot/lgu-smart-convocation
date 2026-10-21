"""Remove development test-fixture data from the event database.

Phase 35A (bug 4): smoke/test runs created guests named "Phase Test Guest",
"Smoke Test Guest" and "Phase34B Guest" (plus their scan records). Phase 35E:
the mobile api-test suite creates "Test Guest {tag}" fixtures the same way.
These are fixtures, not event data, and must not appear in the production
guest list or dashboard counts.

Phase 35G: the mobile api-test suite posts demo broadcasts (sent_by
"ApiTest"/"PhaseTest", message "API test <stamp>", "Phase test broadcast",
"Phase34B smoke") — fixtures, not announcements. They are removed here the
same way, by exact known patterns only.

Phase 35I: api-test.mjs now runs against an isolated test database and can
no longer touch production. This utility remains the MANUAL, pre-event
production cleaner (never wired into app startup). It also removes scan
records stamped with the known test volunteer names — those come from
historical smoke runs against the production file. Scans whose volunteer is
a real operator name (e.g. "Volunteer") are never touched.

This script is deliberately NOT wired into app startup. Run it manually
(before an event, or after a testing session):

    .venv\\Scripts\\python.exe app\\scripts\\cleanup_test_fixtures.py

Safety:
- Idempotent (safe to re-run).
- Deletes ONLY guests whose name matches the known test fixtures above or the
  api-test "Test Guest ..." pattern — the seeded demo roster (Nasir Khan,
  Shazia Bibi, Tariq Mehmood) and any user-registered guest are never touched.
- Deletes only scan records whose person_name matches those fixtures or whose
  volunteer is one of the known test senders.
- Deletes only broadcasts sent by the known test senders or carrying the
  known test messages — a real announcement is never touched.
"""

import sqlite3
import sys
from pathlib import Path

TEST_GUEST_NAMES = ("Phase Test Guest", "Smoke Test Guest", "Phase34B Guest")
# api-test.mjs fixture prefix: "Test Guest {tag}" — no real guest uses it.
TEST_GUEST_PREFIX = "Test Guest %"
# Phase 35G broadcast fixtures: api-test + smoke sends + endpoint probes.
# Real announcements (volunteer/admin entries in the app UI) never match.
TEST_BROADCAST_SENDERS = ("ApiTest", "PhaseTest", "Probe", "Phase35G Visual")
# Scan records stamped by the same test senders are fixtures too (35I).
TEST_SCAN_VOLUNTEERS = TEST_BROADCAST_SENDERS
TEST_BROADCAST_MESSAGES = (
    "Phase test broadcast",
    "Phase34B smoke",
    # Phase 35G visual pass (browser + urllib probes).
    "Convocation gates open at 9:00 AM at the Main Gate.",
    "Visual pass probe",
)

DB_PATH = Path(__file__).resolve().parents[1] / "lgu.db"


def main() -> int:
    if not DB_PATH.exists():
        print("Database not found: %s" % DB_PATH)
        return 1
    conn = sqlite3.connect(DB_PATH)
    try:
        placeholders = ",".join("?" for _ in TEST_GUEST_NAMES)
        params = (*TEST_GUEST_NAMES, TEST_GUEST_PREFIX)
        scans = conn.execute(
            "DELETE FROM scans WHERE person_type='guest' AND "
            "(person_name IN (%s) OR person_name LIKE ?)" % placeholders,
            params,
        ).rowcount
        scans += conn.execute(
            "DELETE FROM scans WHERE volunteer IN (%s)"
            % ",".join("?" for _ in TEST_SCAN_VOLUNTEERS),
            TEST_SCAN_VOLUNTEERS,
        ).rowcount
        guests = conn.execute(
            "DELETE FROM guests WHERE (name IN (%s) OR name LIKE ?)" % placeholders,
            params,
        ).rowcount
        sender_placeholders = ",".join("?" for _ in TEST_BROADCAST_SENDERS)
        msg_placeholders = ",".join("?" for _ in TEST_BROADCAST_MESSAGES)
        broadcasts = conn.execute(
            "DELETE FROM broadcasts WHERE (sent_by IN (%s) OR "
            "message LIKE 'API test %%' OR message IN (%s))"
            % (sender_placeholders, msg_placeholders),
            (*TEST_BROADCAST_SENDERS, *TEST_BROADCAST_MESSAGES),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    print("Removed %d test guest(s), %d test scan(s), %d test broadcast(s)."
          % (guests, scans, broadcasts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
