#!/usr/bin/env python3
"""Make a brand-new, PRIVATE, synthetic three-role mobile preview database.

This helper NEVER opens app/lgu.db or any existing database. It must be run
locally by an authorized tester; never inside a public service request.
"""
import argparse
import os
from pathlib import Path
import secrets
import sys


def provision(output_dir):
    root = Path(output_dir).expanduser().absolute().resolve()
    repository = Path(__file__).resolve().parents[2]
    if root == repository or repository in root.parents:
        raise ValueError("Choose a private directory OUTSIDE the Git repository.")
    if root.exists():
        raise ValueError("Output already exists. Refusing to overwrite any data.")
    if os.environ.get("LGU_APP_ENV", "").strip().lower() == "production":
        raise ValueError("Never run demo provisioning from a production environment.")
    # No SQLite files, backups, photos or credentials can be read from an
    # existing location. The new directory is the only write destination.
    root.mkdir(parents=True, exist_ok=False)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    db_file = root / "lgu-preview.sqlite3"
    session_secret = secrets.token_urlsafe(48)
    hmac_secret = secrets.token_urlsafe(48)
    admin_pin = "".join(secrets.choice("23456789") for _ in range(8))
    student_password = secrets.token_urlsafe(18)
    scanner_pin = "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
                          for _ in range(8))
    os.environ.update({
        "LGU_DB_PATH": str(db_file),
        "LGU_APP_ENV": "development",
        "LGU_TESTING": "",
        "LGU_ALLOW_DEMO_SECRETS": "",
        "LGU_SECRET_KEY": session_secret,
        "LGU_HMAC_SECRET": hmac_secret,
        "LGU_ADMIN_PIN": admin_pin,
        "LGU_EMAIL_MODE": "disabled",
        "LGU_COOKIE_SECURE": "1",
        "LGU_STUDENT_PHOTO_DIR": str(root / "photos"),
        "LGU_MEDALIST_PHOTO_DIR": str(root / "medalist-photos"),
    })
    # Delay imports until the synthetic path and freshly generated secrets are
    # installed: config.py reads these environment variables on import.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import config
    import database
    import exam_registrations
    import scanner_auth
    import student_auth

    config.require_test_db(db_file)
    database.init_db()
    database.seed()  # creates gates and event, no demo student auto-seeding
    email = "preview.student@example.invalid"
    with database.connection() as db:
        account_id = student_auth.create_account(db, email, student_password)
        convocation = exam_registrations.active_convocation(db)
        if convocation is None:
            raise RuntimeError("No synthetic convocation created.")
        now = exam_registrations.utc_now()
        cur = db.execute(
            "INSERT INTO convocation_registrations "
            "(convocation_id, registration_number, university_email, "
            "roll_number, student_name, department, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (convocation["id"], "PREVIEW-ONLY-001", email,
             "SYNTHETIC-0001", "Preview Test Student", "Test Department",
             "active", now, now),
        )
        student_auth.claim_registration(
            db, account_id, convocation["id"], cur.lastrowid
        )
        db.commit()
    scanner_auth.create_scanner(
        "preview-scanner", "Preview Test Volunteer", scanner_pin, [1],
        actor="preview-provisioner", via=scanner_auth.VIA_TEST,
    )
    credentials = root / "TEST-LOGIN-DETAILS.txt"
    credentials.write_text(
        "SYNTHETIC DEMO ONLY. Never use with real university data.\n"
        "These accounts work ONLY on the preview backend using this database.\n\n"
        "Student email: " + email + "\n"
        "Student password: " + student_password + "\n\n"
        "Scanner username: preview-scanner\n"
        "Scanner PIN: " + scanner_pin + "\n"
        "Scanner permitted gate: 1\n\n"
        "Admin PIN: " + admin_pin + "\n"
        "No shared production credentials exist.\n",
        encoding="utf-8",
    )
    runtime = root / "PRIVATE-BACKEND-ENV.txt"
    runtime.write_text(
        "# PRIVATE ONLY: copy these as environment variables on the HTTPS "
        "synthetic staging host. NEVER commit, screenshot, or upload this file.\n"
        "# Change LGU_DB_PATH to the actual location of the new preview DB "
        "on that host. The app does not auto-load .env files.\n"
        "LGU_APP_ENV=production\nLGU_COOKIE_SECURE=1\n"
        "LGU_EMAIL_MODE=disabled\nLGU_ALLOW_DEMO_SECRETS=0\n"
        "LGU_DB_PATH=" + str(db_file) + "\n"
        "LGU_SECRET_KEY=" + session_secret + "\n"
        "LGU_HMAC_SECRET=" + hmac_secret + "\n"
        "LGU_ADMIN_PIN=" + admin_pin + "\n",
        encoding="utf-8",
    )
    for file in (credentials, runtime):
        try:
            file.chmod(0o600)
        except OSError:
            pass
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True,
                        help="new private directory, outside the repository")
    args = parser.parse_args()
    try:
        root = provision(args.output_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, "ERROR: %s\n" % exc)
    print("Created synthetic-only database and THREE demo login accounts.")
    print("Private directory:", root)
    print("Read TEST-LOGIN-DETAILS.txt locally. Do NOT upload it to GitHub.")
    print("No server was launched: configure a separate HTTPS demo backend.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
