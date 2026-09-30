"""SQLite setup: schema creation and seed data."""

import sqlite3

import config
import ids

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

GATE_LABELS = [
    ("G1", "Gate 1: Main Gate"),
    ("G2", "Gate 2: East Gate"),
    ("G3", "Gate 3: West Gate"),
    ("G4", "Gate 4: North Gate"),
    ("G5", "Gate 5: South Gate"),
    ("G6", "Gate 6: Auditorium Gate"),
    ("G7", "Gate 7: Sports Complex Gate"),
]

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
# IGNORE so existing values are never overwritten.
SETTING_KEYS = ("convocation_name", "convocation_year", "convocation_datetime", "venue")

DEFAULT_SETTINGS = [
    ("convocation_name", "LGU Convocation 2026"),
    ("convocation_year", "2026"),
    # Placeholder until the user confirms the real date.
    ("convocation_datetime", "2026-12-12T09:00:00+05:00"),
    ("venue", "Lahore Garrison University, Lahore"),
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
    """Return a flat dict of the four event settings."""
    db = get_db()
    rows = db.execute(
        "SELECT key, value FROM settings WHERE key IN (?, ?, ?, ?)", SETTING_KEYS
    ).fetchall()
    db.close()
    settings = {key: "" for key in SETTING_KEYS}
    for row in rows:
        settings[row["key"]] = row["value"]
    return settings


def update_settings(updates):
    """Update any subset of settings; stamps updated_at with current UTC time."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db = get_db()
    for key, value in updates.items():
        db.execute(
            "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
            (value, now, key),
        )
    db.commit()
    db.close()


def get_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()
    db.close()


def _now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(config.DISPLAY_TZ)).strftime("%Y-%m-%d %H:%M:%S")


def seed():
    db = get_db()
    # Settings defaults are idempotent: existing values are never overwritten.
    seed_settings(db)
    already = db.execute("SELECT COUNT(*) c FROM gates").fetchone()["c"]
    if already:
        db.close()
        return False
    for code, label in GATE_LABELS:
        db.execute("INSERT INTO gates (code, label) VALUES (?, ?)", (code, label))
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
