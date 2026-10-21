"""Student support requests and the Examination Department review queue (Phase 9).

A request is owned by exactly one student account and bound to one
convocation. Students open a request and read the staff response; Examination
Department staff move it through the review queue, ask for information and
record a decision. This module NEVER mutates an official registration — when a
request results in a correction, staff use the existing registration-correction
workflow (exam_registrations.correct), linked by registration_id when the
student has a claimed registration.

History is a single append-only stream (support_events). Rows with
student_visible = 0 are internal staff notes and never leave the portal;
everything else is shown to the owning student. Text is validated and bounded
server-side; the reference is a random, human-quotable code unique per request.
"""

import secrets
from datetime import datetime, timezone

import config


def _stamp():
    """One UTC timestamp in SQLite's 'YYYY-MM-DD HH:MM:SS' form.

    Every column and every metric comparison in this module uses this, so
    date math against sqlite ``datetime('now')`` (UTC) is exact — mixing a
    local-time column in would silently skew the stale/recent windows.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

CATEGORIES = ("missing_registration", "correction", "cancellation",
              "account_claim", "general")
CATEGORY_LABELS = {
    "missing_registration": "Missing / mismatched registration",
    "correction": "Correct my details",
    "cancellation": "Cancellation or account claim",
    "account_claim": "Account / registration claim",
    "general": "Convocation question",
}
# Open statuses count against a student's open-request limit and toward the
# staff "awaiting review" queues. Resolved and rejected are terminal.
OPEN_STATUSES = ("submitted", "under_review", "info_required")
STATUSES = OPEN_STATUSES + ("resolved", "rejected")
STATUS_LABELS = {
    "submitted": "Submitted",
    "under_review": "Under review",
    "info_required": "Information required",
    "resolved": "Resolved",
    "rejected": "Rejected",
}
# Statuses a staff member may move a request to from its current status.
# Reopening a resolved/rejected request is allowed only back to under_review
# so a decision is never silently reversed; a student can always file a new
# request if a resolved issue recurs.
TRANSITIONS = {
    "submitted": ("under_review", "resolved", "rejected"),
    "under_review": ("submitted", "info_required", "resolved", "rejected"),
    "info_required": ("under_review", "resolved", "rejected"),
    "resolved": ("under_review",),
    "rejected": ("under_review",),
}
# The default next step when a staff member "responds" without picking a
# status explicitly: an unanswered request moves under review.
RESPONSE_DEFAULT_STATUS = "under_review"


class SupportError(Exception):
    """Rejected support input — message is safe to show to the caller."""


def clean_text(name, value, limit):
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    text = " ".join(text.split()).strip()
    if not text:
        raise SupportError("%s is required." % name.capitalize())
    if len(text) > limit:
        raise SupportError("%s is too long (limit %d characters)."
                           % (name.capitalize(), limit))
    if any(ord(c) < 32 for c in text):
        raise SupportError("%s contains control characters." % name.capitalize())
    return text


def clean_category(value):
    category = (value or "").strip()
    if category not in CATEGORIES:
        raise SupportError("Choose a request category.")
    return category


def new_reference():
    """Human-quotable code, alphabet without 0/O/1/I to survive a phone call."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "SUP-" + "".join(secrets.choice(alphabet) for _ in range(6))


def _state(row):
    return {"status": row["status"], "handled_by": row["handled_by"],
            "resolved_at": row["resolved_at"]}


def _audit(db, req, actor, role, action, body, before, after, visible=True):
    db.execute(
        "INSERT INTO support_events"
        " (support_request_id, actor, actor_role, action, student_visible,"
        "  body, before_status, after_status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (req["id"], str(actor or "")[:64], role, action,
         1 if visible else 0, (body or "")[:4000], before or "", after or "",
         _stamp()))


def get(db, request_id):
    return db.execute("SELECT * FROM support_requests WHERE id = ?",
                      (request_id,)).fetchone()


def get_by_reference(db, reference):
    return db.execute("SELECT * FROM support_requests WHERE reference = ?",
                      (reference,)).fetchone()


def open_count(db, account_id, conv_id):
    """How many requests this account still holds open for this convocation."""
    placeholders = ",".join("?" for _ in OPEN_STATUSES)
    return db.execute(
        "SELECT COUNT(*) FROM support_requests"
        " WHERE account_id = ? AND convocation_id = ?"
        " AND status IN (%s)" % placeholders,
        (account_id, conv_id, *OPEN_STATUSES)).fetchone()[0]


def validate_form(form, subject_max=None, message_max=None):
    """Validate a submitted request into a clean dict (no ids/times)."""
    category = clean_category(form.get("category"))
    subject = clean_text("subject", form.get("subject"),
                         subject_max or config.SUPPORT_SUBJECT_MAX)
    message = clean_text("message", form.get("message"),
                         message_max or config.SUPPORT_MESSAGE_MAX)
    return {"category": category, "subject": subject, "message": message}


def create(db, conv_id, account_id, registration_id, data, subject_max=None,
           message_max=None):
    """Open a request owned by the account, with the initial audit event."""
    now = _stamp()
    reference = new_reference()
    # A colliding reference is astronomically unlikely but must never reuse
    # an existing code; regenerate a handful of times before failing loudly.
    for _ in range(8):
        clash = get_by_reference(db, reference)
        if clash is None:
            break
        reference = new_reference()
    else:
        raise SupportError("Could not allocate a unique reference. Try again.")
    cur = db.execute(
        "INSERT INTO support_requests"
        " (reference, convocation_id, account_id, registration_id, category,"
        "  subject, message, status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted', ?, ?)",
        (reference, conv_id, account_id, registration_id, data["category"],
         data["subject"], data["message"], now, now))
    req = get(db, cur.lastrowid)
    _audit(db, req, "student", "student", "create", data["message"],
           "", "submitted", visible=True)
    db.commit()
    return get(db, req["id"])


def list_for_account(db, account_id, conv_id):
    """Newest-first requests owned by this account, with the latest staff
    response attached so the list can show it without a second query."""
    rows = db.execute(
        "SELECT * FROM support_requests"
        " WHERE account_id = ? AND convocation_id = ?"
        " ORDER BY id DESC", (account_id, conv_id)).fetchall()
    return [dict(row, latest_response=latest_response(db, row["id"]))
            for row in rows]


def latest_response(db, request_id):
    """The newest student-visible staff reply (internal notes never surface)."""
    row = db.execute(
        "SELECT * FROM support_events"
        " WHERE support_request_id = ? AND actor_role = 'staff'"
        " AND student_visible = 1 AND body != ''"
        " ORDER BY id DESC LIMIT 1", (request_id,)).fetchone()
    return dict(row) if row else None


def history(db, request_id, include_internal=True):
    """Full update stream, oldest-first. Internal notes are portal-only."""
    sql = "SELECT * FROM support_events WHERE support_request_id = ?"
    if not include_internal:
        sql += " AND student_visible = 1"
    rows = db.execute(sql + " ORDER BY id ASC", (request_id,)).fetchall()
    return [dict(row) for row in rows]


def can_transition(current, target):
    return target in TRANSITIONS.get(current, ())


def set_status(db, req, target, actor, body="", visible=True):
    """Move a request to a new status with an audit event. Commits on success.

    A terminal status sets resolved_at so the dashboard can count "recently
    resolved"; returning to review clears it. The official registration is
    never touched here.
    """
    current = req["status"]
    if target not in STATUSES:
        raise SupportError("Unknown status.")
    if target == current:
        raise SupportError("This request is already %s."
                           % STATUS_LABELS.get(target, target))
    if not can_transition(current, target):
        raise SupportError("Cannot move a %s request directly to %s."
                           % (STATUS_LABELS.get(current, current),
                              STATUS_LABELS.get(target, target)))
    now = _stamp()
    resolved = now if target in ("resolved", "rejected") else None
    db.execute(
        "UPDATE support_requests SET status = ?, handled_by = ?,"
        " updated_at = ?, resolved_at = ? WHERE id = ?",
        (target, str(actor or "")[:64], now, resolved, req["id"]))
    updated = get(db, req["id"])
    _audit(db, updated, actor, "staff",
           "status" if not body else "response", body, current, target,
           visible=visible)
    db.commit()
    return updated


def respond(db, req, actor, body, status=None, visible=True):
    """Record a staff message and optionally move status in one audit step.

    status=None leaves the request in its current status (a pure reply or an
    internal note). A staff reply without an explicit status defaults to
    under_review so an answered request leaves the "submitted" queue.
    """
    text = clean_text("message", body, 4000)
    current = req["status"]
    now = _stamp()
    new_status = status or (RESPONSE_DEFAULT_STATUS
                            if current == "submitted" else current)
    if new_status != current and not can_transition(current, new_status):
        raise SupportError("Cannot move a %s request directly to %s."
                           % (STATUS_LABELS.get(current, current),
                              STATUS_LABELS.get(new_status, new_status)))
    resolved = now if new_status in ("resolved", "rejected") else None
    db.execute(
        "UPDATE support_requests SET status = ?, handled_by = ?,"
        " updated_at = ?, resolved_at = ? WHERE id = ?",
        (new_status, str(actor or "")[:64], now, resolved, req["id"]))
    updated = get(db, req["id"])
    _audit(db, updated, actor, "staff",
           "resolve" if new_status in ("resolved", "rejected")
           else "info_request" if new_status == "info_required"
           else "reply",
           text, current, new_status, visible=visible)
    db.commit()
    return updated


# ------------------------------------------------------------- staff queue

def search(db, conv_id, q="", status="", category="", limit=25, offset=0):
    """Staff queue: filter by status and category, search text across the
    reference, subject, message and the owning account's email.

    ``status`` may be a single status word or an iterable of them (the
    review queue expands "open" to every unresolved status). The filter runs
    in SQL so the caller's LIMIT bounds the *matching* rows, not an arbitrary
    recent window that is then narrowed in Python."""
    sql = ("SELECT r.*, a.university_email AS account_email"
           " FROM support_requests r"
           " JOIN student_accounts a ON a.id = r.account_id"
           " WHERE r.convocation_id = ?")
    args = [conv_id]
    if status:
        wanted = (status,) if isinstance(status, str) else tuple(status)
        for s in wanted:
            if s not in STATUSES:
                raise SupportError("Unknown status filter.")
        sql += " AND r.status IN (%s)" % ",".join("?" for _ in wanted)
        args.extend(wanted)
    if category:
        if category not in CATEGORIES:
            raise SupportError("Unknown category filter.")
        sql += " AND r.category = ?"
        args.append(category)
    if q:
        sql += (" AND (r.reference LIKE ? OR r.subject LIKE ?"
                " OR r.message LIKE ? OR a.university_email LIKE ?)")
        like = "%" + q + "%"
        args.extend([like, like, like, like])
    sql += " ORDER BY r.updated_at DESC, r.id DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    return db.execute(sql, args).fetchall()


def counts_by_status(db, conv_id):
    rows = db.execute(
        "SELECT status, COUNT(*) AS n FROM support_requests"
        " WHERE convocation_id = ? GROUP BY status", (conv_id,)).fetchall()
    out = {s: 0 for s in STATUSES}
    out.update({r["status"]: r["n"] for r in rows})
    return out


def metrics(db, conv_id, stale_days=7, recent_days=7):
    """Real, database-backed support metrics for the staff dashboard.

    Every number is a COUNT over the active convocation. Open and
    info_required drive the review queues; resolved_recent counts decisions
    made in the last recent_days; stale counts requests still open (not
    resolved or rejected) that were last touched more than stale_days ago.
    No count here ever mutates a registration.
    """
    stale_days = stale_days or config.SUPPORT_STALE_DAYS
    recent_days = recent_days or config.SUPPORT_RECENT_DAYS
    counts = counts_by_status(db, conv_id)
    open_ = sum(counts[s] for s in OPEN_STATUSES)
    info_required = counts["info_required"]
    resolved_recent = db.execute(
        "SELECT COUNT(*) FROM support_requests"
        " WHERE convocation_id = ? AND status IN ('resolved', 'rejected')"
        " AND resolved_at >= datetime('now', ?)",
        (conv_id, "-%d days" % recent_days)).fetchone()[0]
    stale = db.execute(
        "SELECT COUNT(*) FROM support_requests"
        " WHERE convocation_id = ? AND status IN (%s)"
        " AND updated_at < datetime('now', ?)"
        % ",".join("?" for _ in OPEN_STATUSES),
        (conv_id, *OPEN_STATUSES, "-%d days" % stale_days)).fetchone()[0]
    placeholders = ",".join("?" for _ in OPEN_STATUSES)
    open_args = (conv_id, *OPEN_STATUSES)
    # Age of open work, in whole days, from created_at (all UTC stamps).
    avg_age, = db.execute(
        "SELECT COALESCE(AVG(julianday('now') - julianday(created_at)), 0)"
        " FROM support_requests"
        " WHERE convocation_id = ? AND status IN (%s)" % placeholders,
        open_args).fetchone()
    oldest_age, = db.execute(
        "SELECT COALESCE(MAX(julianday('now') - julianday(created_at)), 0)"
        " FROM support_requests"
        " WHERE convocation_id = ? AND status IN (%s)" % placeholders,
        open_args).fetchone()
    new_today = db.execute(
        "SELECT COUNT(*) FROM support_requests"
        " WHERE convocation_id = ? AND date(created_at) = date('now')",
        (conv_id,)).fetchone()[0]
    cat_rows = db.execute(
        "SELECT category, COUNT(*) AS n FROM support_requests"
        " WHERE convocation_id = ? GROUP BY category", (conv_id,)).fetchall()
    by_category = {c: 0 for c in CATEGORIES}
    by_category.update({r["category"]: r["n"] for r in cat_rows})
    return {"counts": counts, "open": open_, "info_required": info_required,
            "resolved_recent": resolved_recent, "stale": stale,
            "total": sum(counts.values()),
            "active": open_, "new_today": new_today,
            "avg_age_days": round(avg_age or 0.0, 1),
            "oldest_age_days": int(oldest_age or 0),
            "by_category": by_category}
