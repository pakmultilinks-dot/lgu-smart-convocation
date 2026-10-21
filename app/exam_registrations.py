"""Convocation registration records for the Examination Department portal.

Registrations belong to one convocation and are deliberately separate from the
volunteer check-in student roster. Every identifier is TEXT so leading zeros
("04550") round-trip exactly. Uniqueness is enforced per convocation for
registration_number, roll_number and university_email even after cancellation
or revocation, so an identifier is never silently reused.

Every mutation writes a registration_audit row (actor, action, before/after
JSON). SQLite foreign keys are not enforced at runtime, so callers always pass
an explicit convocation_id.
"""

import json
import re
import sqlite3
from datetime import datetime, timezone

import database

CANONICAL_COLUMNS = ("registration_number", "university_email",
                     "roll_number", "student_name", "department")
REQUIRED_FIELDS = ("registration_number", "university_email",
                   "roll_number", "student_name")
FIELD_LIMITS = {"registration_number": 64, "university_email": 254,
                "roll_number": 32, "student_name": 120, "department": 120}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
REG_FIELDS = ("registration_number", "university_email", "roll_number",
              "student_name", "department")
STATUSES = ("active", "cancelled", "revoked")
# status transitions: action -> allowed current statuses
ACTIONS = {"cancel": ("active",), "revoke": ("active", "cancelled"),
           "reinstate": ("cancelled",)}
ACTION_TO_STATUS = {"cancel": "cancelled", "revoke": "revoked",
                    "reinstate": "active"}
ACTION_LABELS = {"cancel": "Cancel", "revoke": "Revoke",
                 "reinstate": "Reinstate"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_field(name, value):
    """Clean one canonical field. Returns (clean_value, error_or_None)."""
    text = value.strip() if isinstance(value, str) else ("" if value is None else str(value).strip())
    limit = FIELD_LIMITS[name]
    if name in REQUIRED_FIELDS and not text:
        return text, f"{name} is required."
    if len(text) > limit:
        return text, f"{name} is longer than {limit} characters."
    if any(ord(c) < 32 for c in text):
        return text, f"{name} contains control characters."
    if name == "university_email" and text:
        text = text.lower()
        if len(text) > limit or not EMAIL_RE.match(text):
            return text, "university_email must be a valid email address (e.g. name@university.edu.pk)."
    return text, None


def clean_row(raw):
    """Validate a dict of canonical fields -> (clean dict, error list)."""
    clean, errors = {}, []
    for name in raw:
        if name not in FIELD_LIMITS:
            errors.append(f"{name}: unknown column.")
            continue
        value, err = validate_field(name, raw[name])
        clean[name] = value
        if err:
            errors.append(f"{name}: {err}")
    return clean, errors


def audit(db, registration_id, convocation_id, actor, action, before,
          after, batch_id=None):
    db.execute(
        "INSERT INTO registration_audit"
        " (registration_id, convocation_id, batch_id, actor, action,"
        "  before_json, after_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (registration_id, convocation_id, batch_id, str(actor or "")[:64],
         action,
         json.dumps(before, ensure_ascii=False, sort_keys=True) if before else "",
         json.dumps(after, ensure_ascii=False, sort_keys=True) if after else "",
         utc_now()))


def active_convocation(db):
    return db.execute(
        "SELECT * FROM convocations WHERE is_active = 1 ORDER BY id LIMIT 1"
    ).fetchone()


def get(db, registration_id):
    return db.execute(
        "SELECT * FROM convocation_registrations WHERE id = ?",
        (registration_id,)).fetchone()


def count_status(db, convocation_id):
    out = {s: 0 for s in STATUSES}
    for row in db.execute(
            "SELECT status, COUNT(*) AS n FROM convocation_registrations"
            " WHERE convocation_id = ? GROUP BY status", (convocation_id,)):
        out[row["status"]] = row["n"]
    return out


def search(db, convocation_id, query, status, limit, offset):
    sql = "SELECT * FROM convocation_registrations WHERE convocation_id = ?"
    args = [convocation_id]
    if status in STATUSES:
        sql += " AND status = ?"
        args.append(status)
    if query:
        like = "%" + (query.replace("\\", "\\\\").replace("%", "\\%")
                      .replace("_", "\\_")) + "%"
        sql += (" AND (registration_number LIKE ? ESCAPE '\\'"
                " OR roll_number LIKE ? ESCAPE '\\'"
                " OR student_name LIKE ? ESCAPE '\\'"
                " OR university_email LIKE ? ESCAPE '\\')")
        args += [like] * 4
    sql += " ORDER BY registration_number LIMIT ? OFFSET ?"
    args += [limit, offset]
    return db.execute(sql, args).fetchall()


def insert(db, convocation_id, clean, batch_id, actor):
    """Insert one clean registration row and audit it. Caller commits."""
    now = utc_now()
    cur = db.execute(
        "INSERT INTO convocation_registrations"
        " (convocation_id, registration_number, university_email, roll_number,"
        "  student_name, department, status, import_batch_id, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
        (convocation_id, clean["registration_number"],
         clean["university_email"], clean["roll_number"],
         clean["student_name"], clean["department"], batch_id, now, now))
    audit(db, cur.lastrowid, convocation_id, actor, "import_insert", None,
          {k: clean[k] for k in REG_FIELDS}, batch_id)
    return cur.lastrowid


def correct(db, registration, fields, actor):
    """Apply a staff correction with before/after audit. Commits on success."""
    clean, errors = clean_row(fields)
    if errors:
        raise ValueError(" ".join(errors))
    changed = {k: clean[k] for k in clean if clean[k] != registration[k]}
    if not changed:
        raise ValueError("Nothing changed - all values are already correct.")
    try:
        db.execute(
            "UPDATE convocation_registrations SET"
            f" {', '.join(f'{k} = ?' for k in changed)}, updated_at = ?"
            " WHERE id = ?",
            (*changed.values(), utc_now(), registration["id"]))
    except sqlite3.IntegrityError:
        db.rollback()
        raise ValueError(
            "roll_number or university_email already belongs to another registration.")
    audit(db, registration["id"], registration["convocation_id"], actor,
          "correct", {k: registration[k] for k in changed}, changed)
    db.commit()
    return {**registration, **changed}


def set_status(db, registration, action, actor):
    """Apply a validated status transition with audit. Commits on success."""
    allowed = ACTIONS.get(action)
    if allowed is None:
        raise ValueError("Unknown action.")
    if registration["status"] not in allowed:
        raise ValueError(
            f"Cannot {action} a registration that is {registration['status']}.")
    new_status = ACTION_TO_STATUS[action]
    db.execute("UPDATE convocation_registrations SET status = ?, updated_at = ?"
               " WHERE id = ?", (new_status, utc_now(), registration["id"]))
    audit(db, registration["id"], registration["convocation_id"], actor,
          action, {"status": registration["status"]}, {"status": new_status})
    db.commit()
    return new_status


def audit_trail(db, registration_id, limit=100):
    """Newest-first audit rows with parsed before/after diffs for templates."""
    rows = db.execute(
        "SELECT * FROM registration_audit WHERE registration_id = ?"
        " ORDER BY id DESC LIMIT ?", (registration_id, limit)).fetchall()
    out = []
    for row in rows:
        entry = dict(row)
        before = json.loads(entry["before_json"]) if entry["before_json"] else {}
        after = json.loads(entry["after_json"]) if entry["after_json"] else {}
        entry["changes"] = [(k, str(before.get(k, "-")), str(after.get(k, "-")))
                            for k in sorted(set(before) | set(after))]
        out.append(entry)
    return out
