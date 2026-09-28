"""Small data-access helpers. All queries live here, not in the routes."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from database import get_db


def now_str():
    return datetime.now(ZoneInfo(config.DISPLAY_TZ)).strftime("%Y-%m-%d %H:%M:%S")


def gates():
    db = get_db()
    rows = db.execute("SELECT * FROM gates ORDER BY id").fetchall()
    db.close()
    return [dict(r) for r in rows]


def rename_gate(gate_id, label):
    db = get_db()
    db.execute("UPDATE gates SET label = ? WHERE id = ?", (label.strip(), gate_id))
    db.commit()
    db.close()


def find_person(qr_id):
    """Return (person_type, record) for a QR id, or (None, None)."""
    db = get_db()
    s = db.execute("SELECT * FROM students WHERE qr_id = ?", (qr_id,)).fetchone()
    if s:
        db.close()
        return "student", dict(s)
    g = db.execute("SELECT * FROM guests WHERE qr_id = ?", (qr_id,)).fetchone()
    db.close()
    if g:
        return "guest", dict(g)
    return None, None


def last_scan(qr_id):
    db = get_db()
    r = db.execute(
        "SELECT * FROM scans WHERE qr_id = ? ORDER BY id DESC LIMIT 1", (qr_id,)
    ).fetchone()
    db.close()
    return dict(r) if r else None


def student_inside(qr_id):
    ls = last_scan(qr_id)
    return bool(ls and ls["mode"] == "entry")


def guest_used(qr_id):
    db = get_db()
    c = db.execute("SELECT COUNT(*) c FROM scans WHERE qr_id = ?", (qr_id,)).fetchone()["c"]
    db.close()
    return c > 0


def record_scan(qr_id, person_type, person_name, gate_id, mode, volunteer,
                scanned_at=None, source="online"):
    db = get_db()
    db.execute(
        "INSERT INTO scans (qr_id, person_type, person_name, gate_id, mode,"
        " volunteer, scanned_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (qr_id, person_type, person_name, gate_id, mode, volunteer,
         scanned_at or now_str(), source),
    )
    db.commit()
    db.close()


def students_missing_ids():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM students WHERE qr_id IS NULL ORDER BY roll_no").fetchall()
    db.close()
    return [dict(r) for r in rows]


def all_students():
    db = get_db()
    rows = db.execute("SELECT * FROM students ORDER BY roll_no").fetchall()
    db.close()
    return [dict(r) for r in rows]


def students_with_ids():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM students WHERE qr_id IS NOT NULL ORDER BY roll_no").fetchall()
    db.close()
    return [dict(r) for r in rows]


def assign_ids(students, generate):
    """Give each student in the list a fresh unique id using generate()."""
    import ids as ids_mod
    db = get_db()
    used = {r["qr_id"] for r in db.execute("SELECT qr_id FROM students").fetchall()}
    used |= {r["qr_id"] for r in db.execute("SELECT qr_id FROM guests").fetchall()}
    count = 0
    for st in students:
        qr_id = generate()
        while qr_id in used:
            qr_id = generate()
        used.add(qr_id)
        db.execute("UPDATE students SET qr_id = ? WHERE id = ?", (qr_id, st["id"]))
        count += 1
    db.commit()
    db.close()
    return count


def add_students(rows):
    """rows: list of (roll_no, name, gender, program). Returns (added, skipped)."""
    db = get_db()
    added, skipped = 0, 0
    for roll_no, name, gender, program in rows:
        try:
            db.execute(
                "INSERT INTO students (roll_no, name, gender, program, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (roll_no.strip(), name.strip(), gender.strip(), program.strip(), now_str()),
            )
            added += 1
        except Exception:
            skipped += 1
    db.commit()
    db.close()
    return added, skipped


def register_guest(name, phone, host_roll_no, generate):
    import ids as ids_mod
    db = get_db()
    host = db.execute("SELECT * FROM students WHERE roll_no = ?",
                      (host_roll_no.strip(),)).fetchone()
    if not host:
        db.close()
        return None, "No student found with roll number %s." % host_roll_no
    used = {r["qr_id"] for r in db.execute("SELECT qr_id FROM students").fetchall()}
    used |= {r["qr_id"] for r in db.execute("SELECT qr_id FROM guests").fetchall()}
    qr_id = generate()
    while qr_id in used:
        qr_id = generate()
    cur = db.execute(
        "INSERT INTO guests (name, phone, host_roll_no, qr_id, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (name.strip(), phone.strip(), host_roll_no.strip(), qr_id, now_str()),
    )
    gid = cur.lastrowid
    db.commit()
    db.close()
    return gid, None


def guest_by_id(gid):
    db = get_db()
    r = db.execute("SELECT * FROM guests WHERE id = ?", (gid,)).fetchone()
    db.close()
    return dict(r) if r else None


def all_guests():
    db = get_db()
    rows = db.execute("SELECT * FROM guests ORDER BY id DESC").fetchall()
    db.close()
    out = []
    for r in rows:
        d = dict(r)
        d["used"] = guest_used(d["qr_id"])
        out.append(d)
    return out


def add_broadcast(audience, message, sent_by):
    db = get_db()
    db.execute(
        "INSERT INTO broadcasts (audience, message, sent_by, sent_at)"
        " VALUES (?, ?, ?, ?)",
        (audience, message.strip(), sent_by.strip() or "Admin", now_str()),
    )
    db.commit()
    db.close()


def recent_broadcasts(limit=20):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM broadcasts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    db.close()
    return [dict(r) for r in rows]


def recent_scans(limit=20):
    db = get_db()
    rows = db.execute(
        "SELECT sc.*, g.label AS gate_label FROM scans sc"
        " JOIN gates g ON g.id = sc.gate_id"
        " ORDER BY sc.id DESC LIMIT ?", (limit,)).fetchall()
    db.close()
    return [dict(r) for r in rows]


def dashboard():
    """Everything the dashboard needs, in one call."""
    db = get_db()
    students = [dict(r) for r in db.execute("SELECT * FROM students").fetchall()]
    gate_list = [dict(r) for r in db.execute("SELECT * FROM gates ORDER BY id").fetchall()]
    gate_by_id = {g["id"]: g for g in gate_list}

    inside = []
    for st in students:
        ls = db.execute(
            "SELECT * FROM scans WHERE qr_id = ? ORDER BY id DESC LIMIT 1",
            (st["qr_id"],)).fetchone() if st["qr_id"] else None
        if ls and ls["mode"] == "entry":
            inside.append(st)

    male = sum(1 for s in inside if s["gender"] == "Male")
    female = sum(1 for s in inside if s["gender"] == "Female")

    guests_inside = db.execute(
        "SELECT COUNT(*) c FROM guests WHERE qr_id IN"
        " (SELECT DISTINCT qr_id FROM scans WHERE person_type = 'guest')").fetchone()["c"]

    cutoff = (datetime.now(ZoneInfo(config.DISPLAY_TZ)) - timedelta(minutes=15)
              ).strftime("%Y-%m-%d %H:%M:%S")
    throughput = {g["id"]: 0 for g in gate_list}
    for r in db.execute(
            "SELECT gate_id, COUNT(*) c FROM scans"
            " WHERE mode = 'entry' AND scanned_at >= ? GROUP BY gate_id", (cutoff,)):
        throughput[r["gate_id"]] = r["c"]

    today = datetime.now(ZoneInfo(config.DISPLAY_TZ)).strftime("%Y-%m-%d")
    entries_today = db.execute(
        "SELECT gate_id, COUNT(*) c FROM scans WHERE mode = 'entry'"
        " AND date(scanned_at) = ? GROUP BY gate_id", (today,)).fetchall()
    busiest = None
    best = -1
    for r in entries_today:
        if r["c"] > best:
            best = r["c"]
            busiest = gate_by_id.get(r["gate_id"], {}).get("label")

    sync = []
    for g in gate_list:
        r = db.execute(
            "SELECT MAX(scanned_at) m, COUNT(*) c FROM scans WHERE gate_id = ?",
            (g["id"],)).fetchone()
        sync.append({"gate": g, "last": r["m"], "count": r["c"]})

    feed = [dict(r) for r in db.execute(
        "SELECT sc.*, g.label AS gate_label FROM scans sc"
        " JOIN gates g ON g.id = sc.gate_id ORDER BY sc.id DESC LIMIT 20")]

    db.close()
    return {
        "inside_total": len(inside),
        "male": male,
        "female": female,
        "guests_inside": guests_inside,
        "busiest_gate": busiest or "No scans yet",
        "throughput": [{"gate": gate_by_id[gid], "count": c}
                       for gid, c in throughput.items()],
        "sync": sync,
        "feed": feed,
        "generated_at": now_str(),
    }
