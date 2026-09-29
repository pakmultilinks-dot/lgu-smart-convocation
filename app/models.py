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
    rows = db.execute(
        "SELECT g.*, CASE WHEN u.qr_id IS NULL THEN 0 ELSE 1 END AS used"
        " FROM guests g LEFT JOIN"
        " (SELECT DISTINCT qr_id FROM scans WHERE person_type = 'guest') u"
        " ON u.qr_id = g.qr_id ORDER BY g.id DESC").fetchall()
    db.close()
    out = []
    for r in rows:
        d = dict(r)
        d["used"] = bool(d["used"])
        out.append(d)
    return out


def first_outside_student():
    """First roster student whose latest scan is not an entry (demo helper)."""
    db = get_db()
    r = db.execute(
        "SELECT * FROM students WHERE qr_id IS NOT NULL"
        " AND COALESCE((SELECT s.mode FROM scans s WHERE s.qr_id = students.qr_id"
        " ORDER BY s.id DESC LIMIT 1), '') != 'entry'"
        " ORDER BY roll_no LIMIT 1").fetchone()
    db.close()
    return dict(r) if r else None


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


def _expected(db):
    """Roster totals. Real data only: zeros when no roster is uploaded."""
    r = db.execute(
        "SELECT COUNT(*) c,"
        " COALESCE(SUM(gender = 'Male'), 0) m,"
        " COALESCE(SUM(gender = 'Female'), 0) f"
        " FROM students").fetchone()
    guests = db.execute("SELECT COUNT(*) c FROM guests").fetchone()["c"]
    return {"total": r["c"], "male": r["m"], "female": r["f"],
            "guests": guests}


def _inside_by_gender(db):
    """Students whose latest scan is an entry, grouped by gender.

    One aggregate query using idx_scans_qr, no per-student round trips.
    """
    rows = db.execute(
        "SELECT st.gender AS gender, COUNT(*) AS c FROM students st"
        " WHERE st.qr_id IS NOT NULL"
        " AND (SELECT s.mode FROM scans s WHERE s.qr_id = st.qr_id"
        "      ORDER BY s.id DESC LIMIT 1) = 'entry'"
        " GROUP BY st.gender").fetchall()
    out = {"Male": 0, "Female": 0}
    for r in rows:
        if r["gender"] in out:
            out[r["gender"]] = r["c"]
    return out


def _guests_inside(db):
    # Guest passes are single-use entry only, so any scan means inside.
    return db.execute(
        "SELECT COUNT(*) c FROM guests WHERE qr_id IN"
        " (SELECT DISTINCT qr_id FROM scans WHERE person_type = 'guest')"
    ).fetchone()["c"]


def _throughput_map(db, cutoff):
    rows = db.execute(
        "SELECT gate_id, COUNT(*) c FROM scans"
        " WHERE mode = 'entry' AND scanned_at >= ? GROUP BY gate_id",
        (cutoff,)).fetchall()
    return {r["gate_id"]: r["c"] for r in rows}


def _busiest_gate_label(db, gate_by_id):
    today = datetime.now(ZoneInfo(config.DISPLAY_TZ)).strftime("%Y-%m-%d")
    r = db.execute(
        "SELECT gate_id, COUNT(*) c FROM scans WHERE mode = 'entry'"
        " AND date(scanned_at) = ? GROUP BY gate_id"
        " ORDER BY c DESC LIMIT 1", (today,)).fetchone()
    if r:
        return gate_by_id.get(r["gate_id"], {}).get("label")
    return None


def _sync_status(db, gate_list):
    rows = db.execute(
        "SELECT gate_id, MAX(scanned_at) m, COUNT(*) c FROM scans"
        " GROUP BY gate_id").fetchall()
    by_gate = {r["gate_id"]: r for r in rows}
    return [{"gate": g,
             "last": by_gate[g["id"]]["m"] if g["id"] in by_gate else None,
             "count": by_gate[g["id"]]["c"] if g["id"] in by_gate else 0}
            for g in gate_list]


def _arrival_pct(inside_total, expected_total):
    if expected_total <= 0:
        return 0
    return min(100, round(100 * inside_total / expected_total))


def dashboard_summary():
    """Lightweight one-round-trip summary for the mobile KPI cards.

    Expected totals come from the real roster; when the roster is empty
    every expected value is 0 and the app labels it "No roster uploaded yet".
    """
    db = get_db()
    exp = _expected(db)
    inside = _inside_by_gender(db)
    inside_total = inside["Male"] + inside["Female"]
    guests_inside = _guests_inside(db)
    gate_list = [dict(r) for r in
                 db.execute("SELECT * FROM gates ORDER BY id").fetchall()]
    gate_by_id = {g["id"]: g for g in gate_list}
    cutoff = (datetime.now(ZoneInfo(config.DISPLAY_TZ)) - timedelta(minutes=15)
              ).strftime("%Y-%m-%d %H:%M:%S")
    throughput_map = _throughput_map(db, cutoff)
    busiest = _busiest_gate_label(db, gate_by_id)
    db.close()
    return {
        "expected_total": exp["total"],
        "expected_male": exp["male"],
        "expected_female": exp["female"],
        "expected_guests": exp["guests"],
        "inside_total": inside_total,
        "male": inside["Male"],
        "female": inside["Female"],
        "guests_inside": guests_inside,
        "arrival_pct": _arrival_pct(inside_total, exp["total"]),
        "busiest_gate": busiest or "No scans yet",
        "throughput": [{"gate": g, "count": throughput_map.get(g["id"], 0)}
                       for g in gate_list],
        "generated_at": now_str(),
    }


def dashboard():
    """Everything the dashboard needs, in one call. Aggregate queries only,
    no per-row round trips."""
    db = get_db()
    exp = _expected(db)
    inside = _inside_by_gender(db)
    inside_total = inside["Male"] + inside["Female"]
    guests_inside = _guests_inside(db)

    gate_list = [dict(r) for r in
                 db.execute("SELECT * FROM gates ORDER BY id").fetchall()]
    gate_by_id = {g["id"]: g for g in gate_list}

    cutoff = (datetime.now(ZoneInfo(config.DISPLAY_TZ)) - timedelta(minutes=15)
              ).strftime("%Y-%m-%d %H:%M:%S")
    throughput_map = _throughput_map(db, cutoff)
    busiest = _busiest_gate_label(db, gate_by_id)
    sync = _sync_status(db, gate_list)

    feed = [dict(r) for r in db.execute(
        "SELECT sc.*, g.label AS gate_label FROM scans sc"
        " JOIN gates g ON g.id = sc.gate_id ORDER BY sc.id DESC LIMIT 20")]

    db.close()
    return {
        "expected_total": exp["total"],
        "expected_male": exp["male"],
        "expected_female": exp["female"],
        "expected_guests": exp["guests"],
        "inside_total": inside_total,
        "male": inside["Male"],
        "female": inside["Female"],
        "guests_inside": guests_inside,
        "arrival_pct": _arrival_pct(inside_total, exp["total"]),
        "busiest_gate": busiest or "No scans yet",
        "throughput": [{"gate": g, "count": throughput_map.get(g["id"], 0)}
                       for g in gate_list],
        "sync": sync,
        "feed": feed,
        "generated_at": now_str(),
    }
