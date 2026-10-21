"""Examination Department support-request review queue (Phase 9, §2).

Routes attach to the existing exam blueprint, so the Phase 3 CSRF guard and
the staff_required decorator cover every one of them with no extra wiring.

Staff can search and filter the queue, open a request alongside the official
registration record, change its status, ask for information, record an
internal note, and answer with a student-visible response or a decision.
A request NEVER mutates an official registration: where a correction is
needed, staff follow the link to the existing registration-correction
screen (exam.registration_correct). Internal notes (student_visible = 0)
stay inside this portal.
"""

import re

from flask import redirect, render_template, request, url_for

import config
import exam_registrations as reg
import support_requests as sup
from database import get_db
from web.exam_routes import bp, staff_required

PAGE = 25

# Query-string status filter -> the queue heading, so a dashboard metric can
# deep-link straight to the list it counts.
FILTER_LABELS = {
    "open": "Awaiting review",
    "info_required": "Awaiting student information",
    "resolved_recent": "Recently resolved",
    "stale": "Older, unresolved",
}

DONE = {
    "status": "Status updated. The student sees the new status and any "
              "response you wrote.",
    "respond": "Response recorded. The student can read it in the app.",
    "note": "Internal note saved. Only Examination Department staff can "
            "see it.",
}


def _done(request_args):
    return DONE.get(request_args.get("done"))


def _status_filter_arg():
    """Map the dashboard's named queues onto concrete status filters.

    'open' means any unresolved request; 'resolved_recent' and 'stale' are
    cross-status dashboard concepts, so they resolve to the terminal and
    open sets respectively and the caller narrows further in Python where a
    date window is needed.
    """
    raw = request.args.get("status", "").strip()
    if raw == "open":
        return "open"
    if raw in sup.STATUSES:
        return raw
    return ""


def _queue_rows(db, conv_id, q, status, category):
    """Fetch the filtered queue. 'open' expands to every unresolved status.

    The status filter is applied in SQL so the LIMIT bounds the matching
    rows — filtering in Python after a capped fetch would silently drop
    older matching requests from the queue while the counts still include
    them (26B: a filtered staff view must show every row it counts)."""
    statuses = sup.OPEN_STATUSES if status == "open" else \
        ((status,) if status else ())
    return sup.search(db, conv_id, q=q, status=statuses, category=category,
                      limit=PAGE * 4, offset=0)


def _render_queue(staff, error=None, done=None):
    db = get_db()
    conv = reg.active_convocation(db)
    q = request.args.get("q", "").strip()[:80]
    category = request.args.get("category", "").strip()
    status = _status_filter_arg()
    if category and category not in sup.CATEGORIES:
        category = ""
    rows, conv_id = [], conv["id"] if conv else None
    if conv_id is not None:
        try:
            rows = _queue_rows(db, conv_id, q, status, category)
        except sup.SupportError as exc:
            error = str(exc)
    counts = sup.counts_by_status(db, conv_id) if conv_id else None
    out = render_template(
        "exam/support.html", staff=staff, error=error, done=done, conv=conv,
        rows=rows, q=q, status=status, category=category, counts=counts,
        categories=sup.CATEGORIES, category_labels=sup.CATEGORY_LABELS,
        status_labels=sup.STATUS_LABELS,
        filter_label=FILTER_LABELS.get(status),
        page_size=PAGE)
    db.close()
    return out


def _render_detail(staff, request_id, error=None, done=None, form=None):
    db = get_db()
    row = sup.get(db, request_id)
    if row is None:
        db.close()
        return _render_queue(staff, "That support request no longer exists.")
    # The associated official record, when the student had a claimed
    # registration at the time they opened the request. Read-only here —
    # corrections go through the existing registration workflow.
    registration = None
    if row["registration_id"]:
        registration = reg.get(db, row["registration_id"])
    trail = sup.history(db, request_id)
    account = db.execute(
        "SELECT university_email FROM student_accounts WHERE id = ?",
        (row["account_id"],)).fetchone()
    out = render_template(
        "exam/support_detail.html", staff=staff, item=row, error=error,
        done=done, form=form, trail=trail,
        registration=dict(registration) if registration else None,
        account_email=account["university_email"] if account else "",
        statuses=sup.STATUSES, status_labels=sup.STATUS_LABELS,
        transitions=sup.TRANSITIONS.get(row["status"], ()),
        categories=sup.CATEGORIES, category_labels=sup.CATEGORY_LABELS,
        registration_detail_url=(
            url_for("exam.registration_detail", reg_id=row["registration_id"])
            if row["registration_id"] else None),
        message_max=config.SUPPORT_MESSAGE_MAX)
    db.close()
    return out


@bp.route("/support")
@staff_required
def support_queue(staff):
    return _render_queue(staff, done=_done(request.args))


@bp.route("/support/<int:request_id>")
@staff_required
def support_detail(staff, request_id):
    return _render_detail(staff, request_id, done=_done(request.args))


@bp.route("/support/<int:request_id>/status", methods=["POST"])
@staff_required
def support_status(staff, request_id):
    db = get_db()
    row = sup.get(db, request_id)
    if row is None:
        db.close()
        return _render_queue(staff, "That support request no longer exists.")
    target = (request.form.get("status") or "").strip()
    try:
        sup.set_status(db, row, target, staff["username"])
    except sup.SupportError as exc:
        db.close()
        return _render_detail(staff, request_id, str(exc))
    db.close()
    return redirect(url_for("exam.support_detail", request_id=request_id,
                            done="status"))


@bp.route("/support/<int:request_id>/respond", methods=["POST"])
@staff_required
def support_respond(staff, request_id):
    """One handler for a staff reply, an information request, a decision and
    an internal note. The visible flag separates student-readable text from
    portal-only notes; an explicit status is honoured, otherwise a reply to a
    submitted request moves it under review."""
    db = get_db()
    row = sup.get(db, request_id)
    if row is None:
        db.close()
        return _render_queue(staff, "That support request no longer exists.")
    body = request.form.get("message") or ""
    target = (request.form.get("status") or "").strip() or None
    internal = request.form.get("internal") == "1"
    try:
        sup.respond(db, row, staff["username"], body,
                    status=target, visible=not internal)
    except sup.SupportError as exc:
        db.close()
        return _render_detail(staff, request_id, str(exc))
    db.close()
    return redirect(url_for("exam.support_detail", request_id=request_id,
                            done="note" if internal else "respond"))


@bp.route("/support/registration/<int:reg_id>")
@staff_required
def support_registration(staff, reg_id):
    """Honest alias: the review screen links to the official record through
    the existing registration detail page, never a second mutation path."""
    return redirect(url_for("exam.registration_detail", reg_id=reg_id))
