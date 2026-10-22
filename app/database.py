"""SQLite setup: schema creation and seed data."""

import os
import re
import sqlite3
from contextlib import contextmanager

import config
import ids
import migrations

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    gender TEXT NOT NULL CHECK (gender IN ('Male', 'Female')),
    program TEXT NOT NULL,
    qr_id TEXT UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    host_roll_no TEXT NOT NULL,
    qr_id TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qr_id TEXT NOT NULL,
    person_type TEXT NOT NULL CHECK (person_type IN ('student', 'guest')),
    person_name TEXT NOT NULL,
    gate_id INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('entry', 'exit')),
    volunteer TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'online'
);
CREATE TABLE IF NOT EXISTS broadcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audience TEXT NOT NULL,
    message TEXT NOT NULL,
    sent_by TEXT NOT NULL,
    sent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scans_qr ON scans(qr_id);
CREATE INDEX IF NOT EXISTS idx_scans_gate ON scans(gate_id);
CREATE INDEX IF NOT EXISTS idx_scans_time ON scans(scanned_at);
CREATE INDEX IF NOT EXISTS idx_scans_gate_mode_time ON scans(gate_id, mode, scanned_at);
CREATE INDEX IF NOT EXISTS idx_scans_person_type ON scans(person_type);
CREATE INDEX IF NOT EXISTS idx_students_qr ON students(qr_id);
CREATE INDEX IF NOT EXISTS idx_guests_qr ON guests(qr_id);
"""

# The seven official convocation gates. Labels are the plain gate names so
# every surface (app, web, printable cards) shows the same wording.
GATE_LABELS = [
    ("G1", "Main Gate"),
    ("G2", "East Gate"),
    ("G3", "West Gate"),
    ("G4", "North Gate"),
    ("G5", "South Gate"),
    ("G6", "Auditorium Gate"),
    ("G7", "Sports Complex Gate"),
]

# Legacy seeds used a "Gate N: <name>" prefix. Anything matching this exact
# old pattern is upgraded to the clean name; genuine admin renames (which do
# not match the pattern) are left untouched.
_LEGACY_GATE_PREFIX = re.compile(r"^Gate\s*\d+\s*:\s*(.+)$")


def normalise_gate_labels(db):
    """Upgrade legacy 'Gate N: X' labels to the official clean gate names."""
    rows = db.execute("SELECT id, code, label FROM gates").fetchall()
    clean_by_code = {code: label for code, label in GATE_LABELS}
    for row in rows:
        match = _LEGACY_GATE_PREFIX.match((row["label"] or "").strip())
        clean = clean_by_code.get(row["code"])
        if match and clean:
            db.execute("UPDATE gates SET label = ? WHERE id = ?",
                       (clean, row["id"]))

SEED_STUDENTS = [
    ("LGU-2024-101", "Ayesha Khan", "Female", "BS Computer Science"),
    ("LGU-2024-102", "Muhammad Ahmed", "Male", "BS Computer Science"),
    ("LGU-2024-103", "Fatima Raza", "Female", "BS Software Engineering"),
    ("LGU-2024-104", "Ali Raza", "Male", "BS Software Engineering"),
    ("LGU-2024-105", "Zainab Tariq", "Female", "BS Business Administration"),
    ("LGU-2024-106", "Usman Khalid", "Male", "BS Business Administration"),
    ("LGU-2024-107", "Mahnoor Fatima", "Female", "BS English"),
    ("LGU-2024-108", "Bilal Hussain", "Male", "BS English"),
    ("LGU-2024-109", "Hira Shahid", "Female", "BS Psychology"),
    ("LGU-2024-110", "Danish Ali", "Male", "BS Psychology"),
    ("LGU-2024-111", "Sana Malik", "Female", "BS Mass Communication"),
    ("LGU-2024-112", "Hamza Sheikh", "Male", "BS Mass Communication"),
    ("LGU-2024-113", "Iqra Naveed", "Female", "BS Mathematics"),
    ("LGU-2024-114", "Fahad Iqbal", "Male", "BS Mathematics"),
    ("LGU-2024-115", "Maryam Aslam", "Female", "BS Computer Science"),
    ("LGU-2024-116", "Talha Mehmood", "Male", "BS Computer Science"),
    ("LGU-2024-117", "Areeba Anwar", "Female", "BS Software Engineering"),
    ("LGU-2024-118", "Saad Farooq", "Male", "BS Software Engineering"),
    ("LGU-2024-119", "Nimra Akram", "Female", "BS Business Administration"),
    ("LGU-2024-120", "Waqas Ahmad", "Male", "BS Business Administration"),
    ("LGU-2024-121", "Rabia Siddiqui", "Female", "BS English"),
    ("LGU-2024-122", "Imran Yousaf", "Male", "BS English"),
    ("LGU-2024-123", "Sadia Perveen", "Female", "BS Psychology"),
    ("LGU-2024-124", "Arslan Butt", "Male", "BS Psychology"),
    ("LGU-2024-125", "Kiran Shahzadi", "Female", "BS Mass Communication"),
    ("LGU-2024-126", "Noman Asghar", "Male", "BS Mass Communication"),
    ("LGU-2024-127", "Farah Naz", "Female", "BS Mathematics"),
    ("LGU-2024-128", "Junaid Akhtar", "Male", "BS Mathematics"),
    ("LGU-2024-129", "Amna Javed", "Female", "BS Computer Science"),
    ("LGU-2024-130", "Shahzaib Khan", "Male", "BS Computer Science"),
    ("LGU-2024-131", "Laiba Rehman", "Female", "BS Software Engineering"),
    ("LGU-2024-132", "Umar Farooq", "Male", "BS Software Engineering"),
    ("LGU-2024-133", "Mehwish Ali", "Female", "BS Business Administration"),
    ("LGU-2024-134", "Asad Mahmood", "Male", "BS Business Administration"),
    ("LGU-2024-135", "Tayyaba Noor", "Female", "BS English"),
    ("LGU-2024-136", "Kamran Shah", "Male", "BS English"),
    ("LGU-2024-137", "Saba Iqbal", "Female", "BS Psychology"),
    ("LGU-2024-138", "Rizwan Haider", "Male", "BS Psychology"),
    ("LGU-2024-139", "Anam Tariq", "Female", "BS Mass Communication"),
    ("LGU-2024-140", "Zeeshan Malik", "Male", "BS Mass Communication"),
]

SEED_GUESTS = [
    ("Nasir Khan", "0300 1112233", "LGU-2024-101"),
    ("Shazia Bibi", "0321 4455667", "LGU-2024-106"),
    ("Tariq Mehmood", "0333 7788990", "LGU-2024-112"),
]

# Event-level settings with their factory defaults. Seeded with INSERT OR
# IGNORE so existing values are never overwritten. expected_attendance is the
# administrator-configured target headcount for the convocation; "0" means
# unset, in which case dashboards show an explicit "not set" state — the
# student roster is a different count and never substitutes as the target
# (Phase 35K Part B).
SETTING_KEYS = (
    "convocation_name",
    "convocation_year",
    "convocation_datetime",
    "venue",
    "expected_attendance",
    "university_name",
)

DEFAULT_SETTINGS = [
    ("convocation_name", "LGU Smart Convocation 2026"),
    ("convocation_year", "2026"),
    # Placeholder until the user confirms the real date.
    ("convocation_datetime", "2026-12-12T09:00:00+05:00"),
    ("venue", "Lahore Garrison University, Lahore"),
    ("expected_attendance", "0"),
    ("university_name", "Lahore Garrison University"),
]


def seed_settings(db):
    """Insert default settings, leaving any existing keys untouched."""
    for key, value in DEFAULT_SETTINGS:
        db.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, _now()),
        )
    db.commit()


def get_settings():
    """Return a flat dict of the event settings."""
    db = get_db()
    try:
        placeholders = ", ".join("?" for _ in SETTING_KEYS)
        rows = db.execute(
            "SELECT key, value FROM settings WHERE key IN (%s)" % placeholders,
            SETTING_KEYS,
        ).fetchall()
    finally:
        # DB-003: a busy or failing read must not strand the handle.
        db.close()
    settings = {key: "" for key in SETTING_KEYS}
    for row in rows:
        settings[row["key"]] = row["value"]
    return settings


def update_settings(updates):
    """Update any subset of settings; stamps updated_at with current UTC time.

    Uses INSERT OR REPLACE so keys added after the initial seed (for example
    expected_attendance on a database created before it existed) can still be
    written through this path.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db = get_db()
    try:
        for key, value in updates.items():
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at)"
                " VALUES (?, ?, ?)",
                (key, value, now),
            )
        db.commit()
    finally:
        # DB-003: partial writes still close; commit ran only on success.
        db.close()


def get_db():
    return connect()


def connect(path=None):
    """Open a connection carrying the repository's SQLite policy (Phase 22 §3).

    The single place timeout, row factory and PRAGMAs are configured, so every
    connection the application opens — the live database, a backup source, a
    backup destination — waits under the SAME bounded budget. `timeout=` sets
    SQLite's own busy handler and the PRAGMA is issued to match, so there is
    exactly one wait budget rather than two that can disagree.
    """
    budget = config.sqlite_busy_timeout()
    conn = sqlite3.connect(path or config.DB_PATH, timeout=budget)
    conn.row_factory = sqlite3.Row
    # Issued out of band: a PRAGMA before any statement starts no transaction.
    conn.execute("PRAGMA busy_timeout = %d" % int(budget * 1000))
    # Phase 38 (DB-002): declared REFERENCES must actually bind. SQLite
    # enforces foreign keys per connection, so the check lives here — the
    # single place every application connection is opened.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection(path=None):
    """Open a connection that is ALWAYS closed (Phase 38 DB-003).

    try/finally at every call site leaked connections the moment an execute
    raised mid-function; this wrapper makes the close unconditional.
    """
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def is_busy_error(exc):
    """True when `exc` is a bounded-lock-wait timeout, not corruption.

    A busy/locked database is a TRANSIENT, EXPECTED condition under a
    single-writer engine. It must never be reported as an invalid QR, a
    revoked pass or an unauthorized gate, and it must never be reported as a
    success — the caller turns it into a retryable answer instead.
    """
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    text = str(exc).lower()
    return "locked" in text or "busy" in text


BUSY_STATUS = "busy"       # response status for a bounded lock-wait timeout
BUSY_RETRY_AFTER = 2       # seconds; HTTP Retry-After paired with BUSY_STATUS


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()
    migrations.migrate(db)
    db.close()


def seed_convocation(db):
    """Create the initial convocation from legacy settings, once, as the active event.

    The legacy datetime is an unconfirmed placeholder, so it is stored as
    expected_date only when no confirmed date exists; confirmed_date stays NULL.
    """
    if db.execute("SELECT 1 FROM convocations LIMIT 1").fetchone():
        return
    settings = {k: v for k, v in db.execute("SELECT key, value FROM settings").fetchall()}
    now = _now()
    db.execute(
        "INSERT INTO convocations (name, year, status, expected_date, venue, is_active, created_at, updated_at)"
        " VALUES (?, ?, 'planned', ?, ?, 1, ?, ?)",
        (settings.get("convocation_name") or "LGU Smart Convocation",
         settings.get("convocation_year") or "",
         settings.get("convocation_datetime") or None,
         settings.get("venue") or "", now, now),
    )
    db.commit()


def _now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(config.DISPLAY_TZ)).strftime("%Y-%m-%d %H:%M:%S")


def seed():
    db = get_db()
    # Settings defaults are idempotent: existing values are never overwritten.
    seed_settings(db)
    seed_convocation(db)
    already = db.execute("SELECT COUNT(*) c FROM gates").fetchone()["c"]
    if already:
        # Upgrade any legacy "Gate N: X" labels to the official clean names.
        normalise_gate_labels(db)
        db.commit()
        db.close()
        return False
    for code, label in GATE_LABELS:
        db.execute("INSERT INTO gates (code, label) VALUES (?, ?)", (code, label))

    # Demo people receive genuine signed QR IDs; they must never be created
    # implicitly on a fresh live database. Keep gates and general settings
    # available without polluting the real student/guest registers.
    environment = os.environ.get("LGU_APP_ENV", "").strip().lower()
    demo_allowed = (
        environment != "production"
        and not config.is_production_db()
        and (
            os.environ.get("LGU_TESTING") == "1"
            or (
                environment in ("", "test", "development")
                and os.environ.get("LGU_ALLOW_DEMO_SECRETS") == "1"
            )
        )
    )
    if not demo_allowed:
        db.commit()
        db.close()
        return True

    used = set()
    for roll_no, name, gender, program in SEED_STUDENTS:
        qr_id = ids.generate_id()
        while qr_id in used:
            qr_id = ids.generate_id()
        used.add(qr_id)
        db.execute(
            "INSERT INTO students (roll_no, name, gender, program, qr_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (roll_no, name, gender, program, qr_id, _now()),
        )
    for name, phone, host_roll_no in SEED_GUESTS:
        qr_id = ids.generate_id()
        while qr_id in used:
            qr_id = ids.generate_id()
        used.add(qr_id)
        db.execute(
            "INSERT INTO guests (name, phone, host_roll_no, qr_id, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, phone, host_roll_no, qr_id, _now()),
        )
    db.commit()
    db.close()
    return True
