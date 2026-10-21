"""Create an Examination Department staff account (no public signup).

Run from app/:  python scripts/manage_exam_staff.py --username NAME --display "Full Name"
The password is read with a hidden prompt; it is never accepted as an argument.
"""

import argparse
import getpass
import os
import sys

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP_DIR)

import database  # noqa: E402
import exam_auth  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username", required=True)
    parser.add_argument("--display", required=True)
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.")
        return 1
    database.init_db()
    try:
        exam_auth.create_staff(args.username, args.display, password)
    except ValueError as exc:
        print("Error: %s" % exc)
        return 1
    print("Created staff account: %s" % args.username)
    return 0


if __name__ == "__main__":
    sys.exit(main())
