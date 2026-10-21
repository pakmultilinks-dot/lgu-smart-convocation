"""Examination Department staff accounts: hashing, login lockout and audit log.

Kept separate from the volunteer PIN (config.ADMIN_PIN / session["lgu_admin"]).
"""

from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

import database

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
MIN_PASSWORD_LENGTH = 12
SESSION_KEY = "exam_staff_id"


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def audit(db, actor, action, detail=""):
    db.execute("INSERT INTO audit_log (actor, action, detail, created_at) VALUES (?, ?, ?, ?)",
               (actor, action, detail, _iso(_utcnow())))


def hash_password(password):
    return generate_password_hash(password, method="scrypt")


def validate_password(password):
    """Return an error message, or None when the password meets policy."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return "Password must be at least %d characters." % MIN_PASSWORD_LENGTH
    if len(password) > 256:
        return "Password must be at most 256 characters."
    return None


def create_staff(username, display_name, password):
    """Create an active staff account. Raises ValueError on invalid input or duplicates."""
    username = (username or "").strip()
    display_name = (display_name or "").strip()
    if not username or len(username) > 64:
        raise ValueError("Username is required (max 64 characters).")
    if not display_name or len(display_name) > 120:
        raise ValueError("Display name is required (max 120 characters).")
    error = validate_password(password)
    if error:
        raise ValueError(error)
    now = _iso(_utcnow())
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO staff_users (username, display_name, password_hash, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (username, display_name, hash_password(password), now, now))
        audit(db, username, "staff_created")
        db.commit()
    except Exception as exc:
        db.rollback()
        if "UNIQUE" in str(exc):
            raise ValueError("That username already exists.") from exc
        raise
    finally:
        db.close()


def authenticate(username, password):
    """Verify credentials. Returns the staff row dict on success, else None.

    Unknown users and wrong passwords return the same result. Repeated
    failures lock the account for LOCK_MINUTES. Usernames longer than the
    64-char creation cap can never match an account, and passwords longer
    than the 256-char policy cap can never be valid; both are rejected
    without a lookup/verify and only a bounded prefix reaches the audit log.
    """
    raw = (username or "").strip()
    name = raw[:64]
    password = password or ""
    db = database.get_db()
    try:
        row = None
        if len(raw) <= 64:
            row = db.execute("SELECT * FROM staff_users WHERE username = ?", (name,)).fetchone()
        now = _utcnow()
        if row is None:
            # Burn comparable time so unknown usernames are not distinguishable by latency.
            check_password_hash(hash_password("x" * MIN_PASSWORD_LENGTH), password[:256])
            audit(db, name or "?", "login_failed", "unknown user")
            db.commit()
            return None
        locked = row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > now
        if not row["is_active"] or locked:
            audit(db, name, "login_blocked", "inactive" if not row["is_active"] else "locked")
            db.commit()
            return None
        if len(password) <= 256 and check_password_hash(row["password_hash"], password):
            db.execute("UPDATE staff_users SET failed_attempts = 0, locked_until = NULL,"
                       " last_login_at = ? WHERE id = ?", (_iso(now), row["id"]))
            audit(db, name, "login_ok")
            db.commit()
            return dict(row)
        fails = row["failed_attempts"] + 1
        locked_until = _iso(now + timedelta(minutes=LOCK_MINUTES)) if fails >= MAX_FAILED_ATTEMPTS else None
        db.execute("UPDATE staff_users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                   (0 if locked_until else fails, locked_until, row["id"]))
        audit(db, name, "login_failed", "wrong password")
        db.commit()
        return None
    finally:
        db.close()


def current_staff():
    """Return the logged-in active staff row for the request session, or None."""
    from flask import session
    staff_id = session.get(SESSION_KEY)
    if not staff_id:
        return None
    db = database.get_db()
    try:
        row = db.execute("SELECT * FROM staff_users WHERE id = ? AND is_active = 1", (staff_id,)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()
