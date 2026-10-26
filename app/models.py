"""Small data-access helpers. All queries live here, not in the routes."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
import database
from database import get_db


def now_str():
    return datetime.now(ZoneInfo(config.DISPLAY_TZ)).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def _db():
    """Connection that is always closed, even when a statement raises
    (Phase 38 DB-003 — leaked handles under a live event are a stall risk)."""
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


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
    with _db() as db:
        s = db.execute("SELECT * FROM students WHERE qr_id = ?", (qr_id,)).fetchone()
        if s:
            return "student", dict(s)
        g = db.execute("SELECT * FROM guests WHERE qr_id = ?", (qr_id,)).fetchone()
        return ("guest", dict(g)) if g else (None, None)


def last_scan(qr_id):
    with _db() as db:
        r = db.execute(
            "SELECT * FROM scans WHERE qr_id = ? ORDER BY id DESC LIMIT 1", (qr_id,)
        ).fetchone()
    return dict(r) if r else None


def student_inside(qr_id):
    ls = last_scan(qr_id)
    return bool(ls and ls["mode"] == "entry")


def guest_used(qr_id):
    with _db() as db:
        c = db.execute("SELECT COUNT(*) c FROM scans WHERE qr_id = ?", (qr_id,)).fetchone()["c"]
    return c > 0


def record_scan(qr_id, person_type, person_name, gate_id, mode, volunteer,
                scanned_at=None, source="online"):
    """Record an admission only if its pass state is still valid.

    The authoritative duplicate check happens *after* BEGIN IMMEDIATE, which
    serializes all writers on this SQLite database. Route-level checks remain
    useful for immediate feedback, but cannot by themselves prevent races.
    Returns True if recorded, False if another request already changed state.
    """
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        if person_type == "guest":
            already_used = db.execute(
                "SELECT 1 FROM scans WHERE qr_id = ? LIMIT 1", (qr_id,)
            ).fetchone()
            if already_used or mode != "entry":
                db.rollback()
                return False
        elif person_type == "student":
            latest = db.execute(
                "SELECT mode FROM scans WHERE qr_id = ?"
                " ORDER BY id DESC LIMIT 1", (qr_id,)
            ).fetchone()
            inside = bool(latest and latest["mode"] == "entry")
            if (mode == "entry" and inside) or (mode == "exit" and not inside):
                db.rollback()
                return False

        db.execute(
            "INSERT INTO scans (qr_id, person_type, person_name, gate_id, mode,"
            " volunteer, scanned_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (qr_id, person_type, person_name, gate_id, mode, volunteer,
             scanned_at or now_str(), source),
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
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
    added, skipped = 0, 0
    with _db() as db:
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
    return added, skipped


def register_guest(name, phone, host_roll_no, generate, *, payment_reference=None, actor=None):
    with _db() as db:
        # Serialize eligibility, identity checks and issuance even before v14.
        db.execute("BEGIN IMMEDIATE")
        if payment_reference:
            # BEGIN IMMEDIATE serializes receipt reuse checks with issuance.
            receipt = payment_reference.strip().upper()
            duplicate = db.execute(
                "SELECT 1 FROM audit_log WHERE action = 'paid_guest_issued' "
                "AND json_extract(detail, '$.payment_reference') = ? LIMIT 1",
                (receipt,)).fetchone()
            if duplicate:
                return None, "This payment reference already issued a guest pass."
        host = db.execute("SELECT * FROM students WHERE roll_no = ?",
                          (host_roll_no.strip(),)).fetchone()
        if not host:
            return None, "No student found with roll number %s." % host_roll_no
        # Duplicate identity is rejected at intake — the "one
        # guest per host limit is retained independently of paid issuance: one
        # live pass per host roll, and no twin (same name + phone) holding a
        # second pass under another host. The phone compare is SPACED-FORMAT
        # tolerant — stored numbers appear both as "0300 1112233" and
        # "03001112233", and the same person must not slip through on format.
        # Phase 38 (DB-002): the host rule is also a UNIQUE index, so a
        # concurrent registration that slips past these reads still loses at
        # INSERT time — see the IntegrityError below.
        existing = db.execute(
            "SELECT id FROM guests WHERE host_roll_no = ? LIMIT 1",
            (host_roll_no.strip(),)).fetchone()
        if existing:
            return None, "This student already has a guest registered."
        twin = db.execute(
            "SELECT id FROM guests WHERE name = ?"
            " AND REPLACE(phone, ' ', '') = REPLACE(?, ' ', '') LIMIT 1",
            (name.strip(), phone.strip())).fetchone()
        if twin:
            return None, "A guest with this name and phone is already registered."
        used = {r["qr_id"] for r in db.execute("SELECT qr_id FROM students").fetchall()}
        used |= {r["qr_id"] for r in db.execute("SELECT qr_id FROM guests").fetchall()}
        qr_id = generate()
        while qr_id in used:
            qr_id = generate()
        try:
            cur = db.execute(
                "INSERT INTO guests (name, phone, host_roll_no, qr_id, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (name.strip(), phone.strip(), host_roll_no.strip(), qr_id, now_str()),
            )
        except sqlite3.IntegrityError as exc:
            db.rollback()
            if "host_roll_no" not in str(exc):
                raise  # qr_id collision etc. is not this rule's error
            return None, "This student already has a guest registered."
        gid = cur.lastrowid
        if payment_reference:
            db.execute("INSERT INTO audit_log (actor,action,detail,created_at) VALUES (?,?,?,?)",
                       (actor or "administrator", "paid_guest_issued",
                        json.dumps({"guest_id": gid, "payment_reference": receipt,
                                    "verification": "administrator_attested"}), now_str()))
        db.commit()
        return gid, None


def guests_created_today():
    """Rows minted on the current local date — the restart-proof input to
    the BE-003 daily cap (counted from the table, never from memory)."""
    today = now_str()[:10]
    with _db() as db:
        return db.execute(
            "SELECT COUNT(*) c FROM guests WHERE substr(created_at, 1, 10) = ?",
            (today,)).fetchone()["c"]


def guest_by_id(gid):
    db = get_db()
    # 33-QA (I23): carry the HOST'S NAME alongside the roll — a roll
    # number alone means nothing to a volunteer at the gate.
    r = db.execute(
        "SELECT g.*, st.name AS host_name FROM guests g"
        " LEFT JOIN students st ON st.roll_no = g.host_roll_no"
        " WHERE g.id = ?", (gid,)).fetchone()
    db.close()
    return dict(r) if r else None


def revoke_guest(gid, *, actor=None):
    """Phase 34 (Part C): revoke an unused guest pass.

    Only an ACTIVE pass can be revoked — a used pass keeps its terminal
    'used' meaning and a pass already revoked is idempotent. Returns True
    when this call performed the transition. The pass payload is a bearer
    credential, so revocation is the lifecycle step that invalidates a lost
    or compromised pass BEFORE it is ever scanned; the gate refuses a
    revoked pass (routes._process_scan)."""
    db = get_db()
    cur = db.execute(
        "UPDATE guests SET status = 'revoked'"
        " WHERE id = ? AND status = 'active' AND NOT EXISTS "
        "(SELECT 1 FROM scans WHERE qr_id=guests.qr_id AND person_type='guest')", (gid,))
    changed = cur.rowcount > 0
    if changed and actor:
        db.execute("INSERT INTO audit_log (actor,action,detail,created_at) VALUES (?,?,?,?)",
                   (actor, "guest_pass_revoked", json.dumps({"guest_id": gid}), now_str()))
    db.commit()
    db.close()
    return changed


def all_guests():
    """All guests with single-use state + latest entry details (Phase 35H)."""
    db = get_db()
    rows = db.execute(
        "SELECT g.*, st.name AS host_name,"
        " CASE WHEN u.qr_id IS NULL THEN 0 ELSE 1 END AS used,"
        " u.scanned_at AS used_at, gt.label AS used_gate"
        " FROM guests g LEFT JOIN"
        " (SELECT s.qr_id, s.scanned_at, s.gate_id FROM scans s"
        "  JOIN (SELECT qr_id, MAX(id) AS mid FROM scans"
        "        WHERE person_type = 'guest' GROUP BY qr_id) m ON m.mid = s.id) u"
        " ON u.qr_id = g.qr_id LEFT JOIN gates gt ON gt.id = u.gate_id"
        " LEFT JOIN students st ON st.roll_no = g.host_roll_no"
        " ORDER BY g.id DESC").fetchall()
    db.close()
    out = []
    for r in rows:
        d = dict(r)
        d["used"] = bool(d["used"])
        d["used_at"] = d.get("used_at")
        d["used_gate"] = d.get("used_gate")
        out.append(d)
    return out


def guest_directory():
    """Minimum-field guest roster for the scanner kiosk and the staff page.

    Selects only what the guest desk renders: id, name, phone, host roll +
    roster name, and live pass state. Deliberately omits ``qr_id`` — the
    HMAC-signed bearer credential ``ids.make_payload`` signs — and
    ``created_at``.

    Phase 27 (C2): this is now the ONLY roster projection any route serves.
    ``all_guests()`` still returns full ``g.*`` rows (with ``qr_id``) but has
    no route caller — re-exposing it would put the credential back in page
    source, which is exactly what C2 closed.
    """
    db = get_db()
    rows = db.execute(
        "SELECT g.id, g.name, g.phone, g.host_roll_no, g.status,"
        " st.name AS host_name,"
        " CASE WHEN u.qr_id IS NULL THEN 0 ELSE 1 END AS used,"
        " u.scanned_at AS used_at, gt.label AS used_gate"
        " FROM guests g LEFT JOIN"
        " (SELECT s.qr_id, s.scanned_at, s.gate_id FROM scans s"
        "  JOIN (SELECT qr_id, MAX(id) AS mid FROM scans"
        "        WHERE person_type = 'guest' GROUP BY qr_id) m ON m.mid = s.id) u"
        " ON u.qr_id = g.qr_id LEFT JOIN gates gt ON gt.id = u.gate_id"
        " LEFT JOIN students st ON st.roll_no = g.host_roll_no"
        " ORDER BY g.id DESC").fetchall()
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
    """Roster totals (student + guest REGISTRATIONS — row counts).

    These are counts of roster rows, NOT the event attendance target.
    The target is the administrator-configured expected_attendance in
    settings — a distinct concept that never silently substitutes for the
    roster and vice versa (Phase 35K Parts A/B). Real data only: zeros
    when no roster is uploaded.
    """
    r = db.execute(
        "SELECT COUNT(*) c,"
        " COALESCE(SUM(gender = 'Male'), 0) m,"
        " COALESCE(SUM(gender = 'Female'), 0) f"
        " FROM students").fetchone()
    guests = db.execute("SELECT COUNT(*) c FROM guests").fetchone()["c"]
    return {"total": r["c"], "male": r["m"], "female": r["f"],
            "guests": guests}


def _announcement_audience(db, gate_ids=None):
    """Announcement audience count on an open connection (Phase 35K Part I).

    Rules:
    - all students: every student in the roster (default broadcast audience).
    - by selected gates: students whose LATEST scan is an ENTRY at one of
      the selected gates — i.e. students currently inside those gates.
      The scan history is the only real gate↔student association in the
      schema (no gate assignment table exists), so the count is derived
      from real data, never fabricated.
    """
    if not gate_ids:
        return db.execute(
            "SELECT COUNT(*) c FROM students").fetchone()["c"]
    placeholders = ", ".join("?" for _ in gate_ids)
    row = db.execute(
        "SELECT COUNT(*) c FROM students st"
        " WHERE st.qr_id IS NOT NULL"
        " AND (SELECT s.gate_id FROM scans s WHERE s.qr_id = st.qr_id"
        "      ORDER BY s.id DESC LIMIT 1) IN (%s)"
        " AND (SELECT s.mode FROM scans s WHERE s.qr_id = st.qr_id"
        "      ORDER BY s.id DESC LIMIT 1) = 'entry'" % placeholders,
        tuple(gate_ids),
    ).fetchone()
    return row["c"]


def broadcast_audience(gate_ids=None):
    """Announcement audience for the broadcast composer (/api/broadcast/audience).

    Returns {"count": int, "basis": str, "per_gate": [...]} — the basis
    string states the rule that produced the count so the UI never
    overclaims. The audience is roster-derived and deliberately distinct
    from expected_attendance (the event target) and from
    student_roster_count when gates narrow it. When gate ids are given,
    per_gate carries each selected gate's own inside count ordered by
    size (largest first, ties by label) so the composer can show WHERE
    the audience sits before sending (33-QA I15); without gates the
    breakdown is an empty list — there is no per-gate story to tell.
    """
    db = get_db()
    count = _announcement_audience(db, gate_ids)
    per_gate = []
    if gate_ids:
        labels = {
            r["id"]: r["label"]
            for r in db.execute(
                "SELECT id, label FROM gates WHERE id IN (%s)"
                % ", ".join("?" for _ in gate_ids), tuple(gate_ids)
            ).fetchall()
        }
        per_gate = [
            {"id": gid, "label": labels.get(gid, str(gid)),
             "count": _announcement_audience(db, [gid])}
            for gid in gate_ids
        ]
        # Largest audience first; ties broken by label so the order is
        # stable across refreshes (33-QA I15).
        per_gate.sort(key=lambda g: (-g["count"], g["label"]))
    db.close()
    basis = ("all students in the roster" if not gate_ids
             else "students currently inside at the selected gates")
    return {"count": count, "basis": basis, "per_gate": per_gate}


def queued_scan_exists(qr_id, gate_id, mode, scanned_at, volunteer):
    """True when an identical offline-queued scan was already recorded
    (Phase 35K Part O — sync idempotency).

    Matched on the business identity of the queued row: qr, gate, mode,
    the device-stamped original timestamp and volunteer, restricted to
    source='queued'. Re-sending the same batch (retry after a flaky
    network, duplicate device) must not double-count entries — the
    client treats "ALREADY SYNCED" as a permanent outcome and drops it.
    """
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM scans WHERE qr_id = ? AND gate_id = ? AND mode = ?"
        " AND scanned_at = ? AND volunteer = ? AND source = 'queued' LIMIT 1",
        (qr_id, gate_id, mode, scanned_at, volunteer),
    ).fetchone()
    db.close()
    return row is not None


def dashboard_access(settings=None):
    settings = settings if settings is not None else database.get_settings()
    return {"student": True,
            "volunteer": settings["volunteer_enabled"] == "true",
            "liveboard": settings["liveboard_enabled"] == "true"}


def app_config_payload():
    """Authoritative app configuration for GET /api/config (Phase 35K).

    One round trip: event identity (from settings), population counts
    (roster vs audience vs target — distinct concepts), gate list and
    operational config (broadcast mode, gate-activity window, message
    limit). Consumed by the mobile app; the hardcoded landing strings in
    mobile/src/config.ts are isolated startup fallbacks only.
    """
    settings = database.get_settings()
    gate_list = gates()
    db = get_db()
    roster = _expected(db)
    audience_count = _announcement_audience(db)
    db.close()
    expected = _expected_attendance()
    return {
        "app_name": config.APP_NAME,
        "dashboard_access": dashboard_access(settings),
        "university": settings.get("university_name") or config.UNIVERSITY,
        "motto": config.MOTTO,
        "event": {
            "name": settings.get("convocation_name") or "",
            "year": settings.get("convocation_year") or "",
            "datetime": settings.get("convocation_datetime") or "",
            "venue": settings.get("venue") or "",
        },
        "expected_attendance": expected,
        "attendance_set": expected > 0,
        "student_roster_count": roster["total"],
        "announcement_audience_count": audience_count,
        "guest_registrations": roster["guests"],
        "gates": [{"id": g["id"], "code": g["code"], "label": g["label"]}
                  for g in gate_list],
        "broadcast_mode": config.BROADCAST_MODE,
        "gate_activity_window_minutes": config.GATE_ACTIVITY_WINDOW_MINUTES,
        "message_char_limit": config.MESSAGE_CHAR_LIMIT,
    }


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
    """Per-gate scan activity for the dashboard gate grid.

    Adds entry/exit splits so the mobile dashboard can show direction
    counts per gate without extra requests.
    """
    rows = db.execute(
        "SELECT gate_id, MAX(scanned_at) m, COUNT(*) c,"
        " COALESCE(SUM(mode = 'entry'), 0) en,"
        " COALESCE(SUM(mode = 'exit'), 0) ex"
        " FROM scans GROUP BY gate_id").fetchall()
    by_gate = {r["gate_id"]: r for r in rows}
    return [{"gate": g,
             "last": by_gate[g["id"]]["m"] if g["id"] in by_gate else None,
             "count": by_gate[g["id"]]["c"] if g["id"] in by_gate else 0,
             "entries": by_gate[g["id"]]["en"] if g["id"] in by_gate else 0,
             "exits": by_gate[g["id"]]["ex"] if g["id"] in by_gate else 0}
            for g in gate_list]


# ---------------------------------------------------------------------------
# Deterministic Test Scan records (demo tooling, clearly separated from
# operational data). Fixed roll numbers from the seeded roster + one seeded
# guest so the mobile Test Scan feature always exercises the same real
# backend flow: entry -> duplicate -> exit, repeatable via reset.
# ---------------------------------------------------------------------------
TEST_ROLLS = (("male", "LGU-2024-102"), ("female", "LGU-2024-101"))
TEST_GUEST_ID = 1


def test_records():
    """Deterministic demo records for the mobile Test Scan feature."""
    import ids as idgen

    db = get_db()
    records = []
    for key, roll in TEST_ROLLS:
        r = db.execute("SELECT * FROM students WHERE roll_no = ?",
                       (roll,)).fetchone()
        if r and r["qr_id"]:
            records.append({
                "key": key,
                "kind": "student",
                "label": "%s (%s)" % (r["name"], r["roll_no"]),
                "payload": idgen.make_payload(r["qr_id"]),
            })
    g = db.execute("SELECT * FROM guests WHERE id = ?",
                   (TEST_GUEST_ID,)).fetchone()
    if g:
        records.append({
            "key": "guest",
            "kind": "guest",
            "label": "%s (guest pass)" % g["name"],
            "payload": idgen.make_payload(g["qr_id"]),
        })
    db.close()
    return records


def reset_test_scans():
    """TEST TOOL: clear scans recorded by the deterministic test records so
    Entry/Exit/duplicate scenarios can be re-run. Returns rows removed."""
    db = get_db()
    qr_ids = []
    for _key, roll in TEST_ROLLS:
        r = db.execute("SELECT qr_id FROM students WHERE roll_no = ?",
                       (roll,)).fetchone()
        if r and r["qr_id"]:
            qr_ids.append(r["qr_id"])
    g = db.execute("SELECT qr_id FROM guests WHERE id = ?",
                   (TEST_GUEST_ID,)).fetchone()
    if g:
        qr_ids.append(g["qr_id"])
    removed = 0
    for q in qr_ids:
        cur = db.execute("DELETE FROM scans WHERE qr_id = ?", (q,))
        removed += cur.rowcount
    db.commit()
    db.close()
    return removed


def _arrival_pct(inside_total, expected_total):
    if expected_total <= 0:
        return 0
    return min(100, round(100 * inside_total / expected_total))


def _expected_attendance():
    """Administrator-configured expected headcount from settings.

    Returns 0 when unset or invalid — dashboards then show an explicit
    "Expected attendance not set" state. The roster total is a different
    count and never silently substitutes for the target (Phase 35K Part B).
    """
    raw = database.get_settings().get("expected_attendance", "0")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    return value if 0 <= value <= 1_000_000 else 0


def _admitted_by_occasion(db):
    """(ceremony, rehearsal) admission counts for the ACTIVE convocation.

    Phase 29: the two occasions of the annual cycle count separately. Only
    convocation_admissions rows count — the legacy roster scans are
    operational check-ins with no occasion and never mix into these totals.
    """
    row = db.execute("SELECT id FROM convocations WHERE is_active = 1"
                     " ORDER BY id LIMIT 1").fetchone()
    if row is None:
        return 0, 0
    counts = {r["occasion"]: r["n"] for r in db.execute(
        "SELECT occasion, COUNT(*) AS n FROM convocation_admissions"
        " WHERE convocation_id = ? GROUP BY occasion", (row["id"],))}
    return counts.get("ceremony", 0), counts.get("rehearsal", 0)


# --------------------------------------------- Phase 38: shared analytics
# The same credential counted twice answers one of these — the duplicate
# subset of rejected scans. Everything else refused at a gate (bad code,
# expired pass, wrong gate, not eligible...) is rejected but not duplicate.
DUPLICATE_TITLES = frozenset({
    "ALREADY INSIDE", "ALREADY USED", "ALREADY ADMITTED", "ALREADY SYNCED",
})


def record_scan_rejection(gate_id, mode, occasion, title, source="online"):
    """Persist one refused scan verdict (Phase 38).

    Best-effort BY DESIGN: a busy or failing log write must never delay or
    fail the verdict it describes — a gate that admits people beats a gate
    that stalls on bookkeeping, and an under-counted log stays honest while
    a stalled scan does not. This log counts what happened; it never
    replaces, doubles, or rewrites the authoritative admission records.
    """
    try:
        with _db() as db:
            db.execute(
                "INSERT INTO scan_rejections"
                " (occurred_at, gate_id, mode, occasion, title, is_duplicate,"
                "  source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now_str(),
                 gate_id if isinstance(gate_id, int) else None,
                 mode if isinstance(mode, str) else None,
                 occasion if isinstance(occasion, str) else None,
                 title if isinstance(title, str) else "",
                 1 if title in DUPLICATE_TITLES else 0,
                 source))
            db.commit()
    except sqlite3.OperationalError:
        # Lock contention, or a database that predates the v14 log table:
        # the verdict already stands on its authoritative records.
        pass


def _rejection_counts(db, today):
    """(rejected, duplicates) recorded TODAY. duplicate ⊆ rejected by
    construction — one flag on one row, so the pair can never disagree."""
    try:
        row = db.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(is_duplicate), 0) d"
            " FROM scan_rejections WHERE substr(occurred_at, 1, 10) = ?",
            (today,)).fetchone()
        return int(row["c"]), int(row["d"])
    except sqlite3.OperationalError:
        # scan_rejections arrives with migration v14. A database that has
        # never seen it has never recorded a rejection — zero is the truth,
        # not a fallback fiction.
        return 0, 0


def _trend_map(db, today):
    """Hourly entry/exit activity for `today`, chronological.

    cumulative_entries is the running total of entries — the arrival curve.
    Semantics: occupancy DEDUPLICATES a person (latest scan wins,
    V-RACE-01); a trend counts EVENTS from the same scans table. Both
    describe what was recorded — neither invents what wasn't.
    """
    rows = db.execute(
        "SELECT substr(scanned_at, 12, 2) AS h, COUNT(*) AS n,"
        " COALESCE(SUM(mode = 'entry'), 0) AS en,"
        " COALESCE(SUM(mode = 'exit'), 0) AS ex"
        " FROM scans WHERE substr(scanned_at, 1, 10) = ?"
        " GROUP BY h ORDER BY h", (today,)).fetchall()
    out, cumulative = [], 0
    for row in rows:
        cumulative += row["en"]
        out.append({"hour": row["h"], "entries": row["en"],
                    "exits": row["ex"], "cumulative_entries": cumulative})
    return out


def _poll_interval_ms():
    """Server-suggested polling period, clamped to a sane band."""
    return max(2000, min(30000, config.DASHBOARD_POLL_MS))


def _analytics_block(db, today, expected, inside_total):
    """Phase 38 dashboard additions — authoritative records only, all
    ADDITIVE to the existing payload (PHASE37 shared analytics design §7)."""
    rejected, duplicates = _rejection_counts(db, today)
    return {
        "remaining_attendance": (max(0, expected - inside_total)
                                 if expected > 0 else None),
        "rejected_count": rejected,
        "duplicate_count": duplicates,
        "trends": _trend_map(db, today),
        "poll_interval_ms": _poll_interval_ms(),
    }


def student_attendance():
    """Privacy-safe attendance aggregate for the student portal (Phase 38).

    Same population semantics as the dashboard — registered = roster rows,
    verified = people currently inside, percentage against the admin target.
    Nothing administrative crosses the boundary: no names, no gates, no
    feed, no throughput, no gender split, no rejection detail, no broadcast
    audience. Students see their event's progress, not the office's ops.
    """
    with _db() as db:
        registered = db.execute(
            "SELECT COUNT(*) c FROM students").fetchone()["c"]
        inside = _inside_by_gender(db)
        verified = inside["Male"] + inside["Female"]
    expected = _expected_attendance()
    return {
        "registered": registered,
        "verified": verified,
        "remaining": (max(0, expected - verified) if expected > 0 else None),
        "percentage": _arrival_pct(verified, expected),
        "expected": expected,
        "attendance_set": expected > 0,
        "generated_at": now_str(),
    }


def dashboard_summary():
    """Lightweight one-round-trip summary for the mobile KPI cards.

    Population semantics (Phase 35K Part A/B) — five distinct values:
    - student_roster_count        — roster rows (registrations).
    - expected_attendance         — admin event target (0 = unset).
    - announcement_audience_count — default broadcast audience (roster).
    - guests_inside               — guest passes with any scan.
    - inside_total                — students whose latest scan is entry.
    Arrival progress is measured ONLY against expected_attendance; when
    unset the clients show an explicit not-set state.
    Phase 38 (additive): remaining_attendance / rejected_count /
    duplicate_count / trends / poll_interval_ms / admissions_by_occasion
    join the payload without changing any existing key.
    """
    expected_attendance = _expected_attendance()
    with _db() as db:
        exp = _expected(db)
        inside = _inside_by_gender(db)
        inside_total = inside["Male"] + inside["Female"]
        guests_inside = _guests_inside(db)
        ceremony_admitted, rehearsal_admitted = _admitted_by_occasion(db)
        gate_list = [dict(r) for r in
                     db.execute("SELECT * FROM gates ORDER BY id").fetchall()]
        gate_by_id = {g["id"]: g for g in gate_list}
        cutoff = (datetime.now(ZoneInfo(config.DISPLAY_TZ))
                  - timedelta(minutes=config.GATE_ACTIVITY_WINDOW_MINUTES)
                  ).strftime("%Y-%m-%d %H:%M:%S")
        throughput_map = _throughput_map(db, cutoff)
        busiest = _busiest_gate_label(db, gate_by_id)
        audience_count = _announcement_audience(db)
        analytics = _analytics_block(db, now_str()[:10], expected_attendance,
                                     inside_total)
    return {
        "student_roster_count": exp["total"],
        "expected_attendance": expected_attendance,
        "attendance_set": expected_attendance > 0,
        "announcement_audience_count": audience_count,
        "roster_male": exp["male"],
        "roster_female": exp["female"],
        "guest_registrations": exp["guests"],
        "inside_total": inside_total,
        "male": inside["Male"],
        "female": inside["Female"],
        "guests_inside": guests_inside,
        "ceremony_admitted": ceremony_admitted,
        "rehearsal_admitted": rehearsal_admitted,
        "arrival_pct": _arrival_pct(inside_total, expected_attendance),
        "busiest_gate": busiest or "No scans yet",
        "throughput": [{"gate": g, "count": throughput_map.get(g["id"], 0)}
                       for g in gate_list],
        "window_minutes": config.GATE_ACTIVITY_WINDOW_MINUTES,
        "generated_at": now_str(),
        **analytics,
        "admissions_by_occasion": {"ceremony": ceremony_admitted,
                                   "rehearsal": rehearsal_admitted},
    }


def dashboard():
    """Everything the dashboard needs, in one call. Aggregate queries only,
    no per-row round trips. Same population semantics as
    dashboard_summary() (Phase 35K) plus the web-only sync/feed feed.
    Phase 38 (additive): same analytics block as dashboard_summary()."""
    expected_attendance = _expected_attendance()
    with _db() as db:
        exp = _expected(db)
        inside = _inside_by_gender(db)
        inside_total = inside["Male"] + inside["Female"]
        guests_inside = _guests_inside(db)
        ceremony_admitted, rehearsal_admitted = _admitted_by_occasion(db)

        gate_list = [dict(r) for r in
                     db.execute("SELECT * FROM gates ORDER BY id").fetchall()]
        gate_by_id = {g["id"]: g for g in gate_list}

        cutoff = (datetime.now(ZoneInfo(config.DISPLAY_TZ))
                  - timedelta(minutes=config.GATE_ACTIVITY_WINDOW_MINUTES)
                  ).strftime("%Y-%m-%d %H:%M:%S")
        throughput_map = _throughput_map(db, cutoff)
        busiest = _busiest_gate_label(db, gate_by_id)
        sync = _sync_status(db, gate_list)

        feed = [dict(r) for r in db.execute(
            "SELECT sc.*, g.label AS gate_label FROM scans sc"
            " JOIN gates g ON g.id = sc.gate_id ORDER BY sc.id DESC LIMIT 20")]

        audience_count = _announcement_audience(db)
        analytics = _analytics_block(db, now_str()[:10], expected_attendance,
                                     inside_total)
    return {
        "student_roster_count": exp["total"],
        "expected_attendance": expected_attendance,
        "attendance_set": expected_attendance > 0,
        "announcement_audience_count": audience_count,
        "roster_male": exp["male"],
        "roster_female": exp["female"],
        "guest_registrations": exp["guests"],
        "inside_total": inside_total,
        "male": inside["Male"],
        "female": inside["Female"],
        "guests_inside": guests_inside,
        "ceremony_admitted": ceremony_admitted,
        "rehearsal_admitted": rehearsal_admitted,
        "arrival_pct": _arrival_pct(inside_total, expected_attendance),
        "busiest_gate": busiest or "No scans yet",
        "throughput": [{"gate": g, "count": throughput_map.get(g["id"], 0)}
                       for g in gate_list],
        "window_minutes": config.GATE_ACTIVITY_WINDOW_MINUTES,
        "sync": sync,
        "feed": feed,
        "generated_at": now_str(),
        **analytics,
        "admissions_by_occasion": {"ceremony": ceremony_admitted,
                                   "rehearsal": rehearsal_admitted},
    }
