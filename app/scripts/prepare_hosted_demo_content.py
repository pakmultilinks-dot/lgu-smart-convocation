"""Explicit operator action on the known synthetic host; never runs at startup.

Adds a separate operational host fixture (not a registration/roster bridge)
and publishes a clearly marked provisional demonstration event. Existing
accounts, photos, guest passes, attendance and dashboard switches are retained.
"""
import argparse
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish-synthetic-demo", action="store_true", required=True)
    parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.pythonanywhere_preview_wsgi import PRIVATE_DB
    import config
    import database
    import convocation_events as events
    import ids
    config.require_test_db(PRIVATE_DB)
    with database.connection() as db:
        rows = db.execute("SELECT registration_number FROM convocation_registrations").fetchall()
        if len(rows) != 1 or rows[0]["registration_number"] != "PREVIEW-ONLY-001":
            raise RuntimeError("Refusing a database other than the single-record synthetic demo.")
        conv = events.active(db)
        if conv is None:
            raise RuntimeError("No active demo convocation.")
        details = events.clean_details({**events.details_of(conv),
            "name": "LGU Convocation 2026", "confirmed_date": "",
            "instructions": "Demonstration schedule for app testing only. This is not an official university event notice."})
        events.save_details(db, conv, details, "synthetic-demo-operator")
        events.publish(db, events.get(db, conv["id"]), "synthetic-demo-operator")
        db.execute("INSERT INTO students (roll_no,name,gender,program,qr_id,created_at) "
                   "VALUES (?,?,?,?,?,?) ON CONFLICT(roll_no) DO NOTHING",
                   ("DEMO-HOST-001", "Demo Guest Host", "Male", "Synthetic test roster",
                    ids.generate_id(), database._now()))
        db.commit()
    print("Synthetic demo event published as provisional. Search/guest host roll: DEMO-HOST-001.")
    print("Existing dashboard switch state, accounts and user uploads were retained.")


if __name__ == "__main__":
    main()
