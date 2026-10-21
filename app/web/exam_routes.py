"""Examination Department portal: login, logout and protected dashboard shell.

Separate blueprint and session key from the volunteer PIN unlock (lgu_admin).
"""

import functools
import hmac
import json
import secrets
import threading
import time

from flask import (Blueprint, abort, redirect, render_template, request,
                   session, url_for)

import config
import database
import exam_auth
import exam_registrations as reg
import scanner_auth

bp = Blueprint("exam", __name__, url_prefix="/exam")

CSRF_KEY = "exam_csrf"

# Phase 19: prefix of every scanner-administration route. Kept here so the
# CSRF guard below and the management module share one definition.
MGMT_PATH = "/exam/scanners"

# Per client IP, in-process. 5 wrong logins per 60 s -> 429 (tunable via
# LGU_EXAM_MAX_FAILS / LGU_EXAM_WINDOW). Separate from the PIN limiter in
# routes.py so the two surfaces cannot throttle each other.
_EXAM_FAILS = {}
_EXAM_FAILS_LOCK = threading.Lock()


def _client_ip():
    return request.remote_addr or "unknown"


def _rate_limited():
    now = time.time()
    window = config.EXAM_RATE_WINDOW_SECONDS
    ip = _client_ip()
    with _EXAM_FAILS_LOCK:
        fails = [t for t in _EXAM_FAILS.get(ip, []) if now - t < window]
        if fails:
            _EXAM_FAILS[ip] = fails
        else:
            _EXAM_FAILS.pop(ip, None)
        return len(fails) >= config.EXAM_RATE_MAX_FAILS


def _record_failure():
    with _EXAM_FAILS_LOCK:
        _EXAM_FAILS.setdefault(_client_ip(), []).append(time.time())


# Phase 19: bounded in-process guard for management denial auditing. A
# rejected scanner-management attempt is worth recording, but an
# unauthenticated client must not be able to grow audit_log without limit.
_DENY_WINDOW_SECONDS = 300
_DENY_MAX_PER_WINDOW = 20
_DENIED = {}
_DENIED_LOCK = threading.Lock()


def _audit_mgmt_denied(path, reason):
    """Record a rejected scanner-management attempt.

    Bounded per client so an anonymous flood cannot fill the audit trail; the
    bound is generous enough that a genuine probe is always captured.
    """
    now = time.time()
    ip = _client_ip()
    with _DENIED_LOCK:
        hits = [t for t in _DENIED.get(ip, [])
                if now - t < _DENY_WINDOW_SECONDS]
        if len(hits) >= _DENY_MAX_PER_WINDOW:
            _DENIED[ip] = hits
            return
        hits.append(now)
        _DENIED[ip] = hits
    db = database.get_db()
    try:
        exam_auth.audit(db, scanner_auth.UNKNOWN_ACTOR, "scanner_mgmt_denied",
                        "via=portal route=%s reason=%s" % (path[:120], reason))
        db.commit()
    finally:
        db.close()


def _csrf_token():
    if CSRF_KEY not in session:
        session[CSRF_KEY] = secrets.token_urlsafe(32)
    return session[CSRF_KEY]


@bp.app_context_processor
def _inject_csrf():
    return {"exam_csrf_token": _csrf_token}


@bp.before_app_request
def _csrf_guard():
    """Reject state-changing requests to the exam surfaces without a valid token.

    Covers both the exam blueprint and the Phase 6 medalists blueprint: both
    live behind the same staff session and token.
    """
    if request.blueprint not in ("exam", "medalists") or request.method != "POST":
        return None
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get(CSRF_KEY)
    # An empty expected token must never compare equal to an empty sent
    # token: a sessionless POST would otherwise pass the guard.
    if not expected or not hmac.compare_digest(sent, expected):
        # Phase 19: a rejected POST to the scanner-management surface is a
        # management attempt worth recording, not just a 403.
        if request.path.startswith(MGMT_PATH):
            _audit_mgmt_denied(request.path, "csrf_or_unauthenticated")
        abort(403)
    return None


def staff_required(view):
    """Redirect unauthenticated requests to the exam login page."""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        staff = exam_auth.current_staff()
        if staff is None:
            session.pop(exam_auth.SESSION_KEY, None)
            return redirect(url_for("exam.login"))
        return view(staff, *args, **kwargs)
    return wrapper


@bp.route("/login", methods=["GET", "POST"])
def login():
    error, status = None, 200
    if request.method == "POST":
        if _rate_limited():
            error = "Too many attempts. Try again in a minute."
            status = 429
        else:
            staff = exam_auth.authenticate(request.form.get("username"),
                                           request.form.get("password"))
            if staff:
                session.clear()
                session[exam_auth.SESSION_KEY] = staff["id"]
                session[CSRF_KEY] = secrets.token_urlsafe(32)
                return redirect(url_for("exam.dashboard"))
            _record_failure()
            error = "Invalid username or password, or the account is temporarily locked."
            status = 401
    return render_template("exam_login.html", error=error), status


@bp.route("/logout", methods=["POST"])
def logout():
    staff = exam_auth.current_staff()
    if staff:
        db = database.get_db()
        exam_auth.audit(db, staff["username"], "logout")
        db.commit()
        db.close()
    session.clear()
    return redirect(url_for("exam.login"))


def dashboard_metrics(db):
    """Phase 5: real, per-request metrics for the active convocation.

    Read-only — computing a dashboard never mutates data. Every issue links
    to the authorized screen that resolves it; numbers count records only
    (no emails, registration numbers or photos on the dashboard).
    """
    conv = reg.active_convocation(db)
    out = {"conv": dict(conv) if conv else None, "totals": None,
           "claimed": 0, "unclaimed": 0, "incomplete_profiles": 0,
           "ceremony_admitted": 0, "rehearsal_admitted": 0,
           "latest_import": None, "medalists": None, "issues": []}
    if conv is None:
        out["issues"].append({
            "level": "warn",
            "text": "No active convocation is configured, so nothing can be "
                    "registered or counted yet.",
            "href": url_for("exam.dashboard"), "label": "Reload dashboard"})
        return out
    conv_id = conv["id"]
    totals = reg.count_status(db, conv_id)
    total = sum(totals.values())
    out["totals"] = {**totals, "total": total}
    out["claimed"] = db.execute(
        "SELECT COUNT(*) FROM registration_claims c"
        " JOIN convocation_registrations r ON r.id = c.registration_id"
        " WHERE c.convocation_id = ?", (conv_id,)).fetchone()[0]
    out["unclaimed"] = max(0, total - out["claimed"])
    out["incomplete_profiles"] = db.execute(
        "SELECT COUNT(*) FROM registration_claims c"
        " LEFT JOIN student_profiles p ON p.account_id = c.account_id"
        " WHERE c.convocation_id = ? AND COALESCE(p.photo_file, '') = ''",
        (conv_id,)).fetchone()[0]
    # Phase 29: the two occasions of the annual cycle admit separately —
    # rehearsal check-ins never inflate the main-ceremony count.
    occ = {r["occasion"]: r["n"] for r in db.execute(
        "SELECT occasion, COUNT(*) AS n FROM convocation_admissions"
        " WHERE convocation_id = ? GROUP BY occasion", (conv_id,))}
    out["ceremony_admitted"] = occ.get("ceremony", 0)
    out["rehearsal_admitted"] = occ.get("rehearsal", 0)

    batch = db.execute(
        "SELECT * FROM import_batches WHERE convocation_id = ?"
        " ORDER BY id DESC LIMIT 1", (conv_id,)).fetchone()
    if batch is not None:
        out["latest_import"] = {
            **dict(batch),
            "result": (json.loads(batch["result_json"])
                       if batch["result_json"] else None)}

    issues = []
    if total == 0:
        issues.append({"level": "warn",
                       "text": "No registrations yet for this convocation. "
                               "Upload the official Excel list to begin.",
                       "href": url_for("exam.import_upload"),
                       "label": "Import registrations"})
    pending = db.execute(
        "SELECT id FROM import_batches WHERE convocation_id = ?"
        " AND status = 'preview' ORDER BY id LIMIT 1", (conv_id,)).fetchone()
    if pending is not None:
        issues.append({"level": "warn",
                       "text": "An uploaded import is waiting for review and "
                               "has not been committed.",
                       "href": url_for("exam.import_review",
                                       batch_id=pending["id"]),
                       "label": "Review the pending import"})
    failed = db.execute(
        "SELECT COUNT(*) FROM import_batches WHERE convocation_id = ?"
        " AND status = 'failed'", (conv_id,)).fetchone()[0]
    if failed:
        issues.append({"level": "bad",
                       "text": "%d import attempt%s failed and rolled back — "
                               "no registrations were changed. Re-upload the "
                               "file." % (failed, "" if failed == 1 else "s"),
                       "href": url_for("exam.import_history"),
                       "label": "Open import history"})
    last_done = db.execute(
        "SELECT * FROM import_batches WHERE convocation_id = ?"
        " AND status = 'committed' ORDER BY id DESC LIMIT 1",
        (conv_id,)).fetchone()
    if last_done is not None and last_done["result_json"]:
        result = json.loads(last_done["result_json"])
        skipped = sum(result.get(k, 0) for k in
                      ("skipped_invalid", "skipped_duplicate",
                       "skipped_conflict"))
        if skipped:
            issues.append({
                "level": "warn",
                "text": "The latest committed import skipped %d row%s "
                        "(invalid, duplicate or conflicting) — those "
                        "registrations were NOT added."
                        % (skipped, "" if skipped == 1 else "s"),
                "href": url_for("exam.import_review", batch_id=last_done["id"]),
                "label": "Review the skipped rows"})
    stale_claims = db.execute(
        "SELECT COUNT(*) FROM registration_claims c"
        " JOIN convocation_registrations r ON r.id = c.registration_id"
        " WHERE c.convocation_id = ? AND r.status != 'active'",
        (conv_id,)).fetchone()[0]
    if stale_claims:
        issues.append({"level": "warn",
                       "text": "%d student account%s hold a claimed "
                               "registration that is no longer active."
                               % (stale_claims,
                                  "" if stale_claims == 1 else "s"),
                       "href": url_for("exam.registrations"),
                       "label": "Open registrations"})

    # Phase 6: medalist records for the same convocation. Every number is
    # a real COUNT from medalists.py; every warning links to the record
    # list that resolves it. Missing coverage compares each department
    # against the categories actually in use (gold/silver/bronze only
    # when present in the data).
    import medalists as med
    med_counts = med.counts(db, conv_id)
    out["medalists"] = {**med_counts, "coverage_missing": 0}
    if med_counts["total"] == 0:
        issues.append({"level": "warn",
                       "text": "No medalist records yet for this "
                               "convocation. Add records one by one or "
                               "import the Excel list.",
                       "href": url_for("medalists.list_view"),
                       "label": "Open the medalist board"})
    else:
        _, _, missing = med.coverage(db, conv_id)
        out["medalists"]["coverage_missing"] = sum(
            len(m["missing"]) for m in missing)
        if missing:
            first = missing[0]
            issues.append({
                "level": "warn",
                "text": "%d department%s missing %d award coverage "
                        "slot%s (e.g. %s has no %s)."
                % (len(missing), "" if len(missing) == 1 else "s",
                   out["medalists"]["coverage_missing"],
                   "" if out["medalists"]["coverage_missing"] == 1 else "s",
                   first["department"], ", ".join(first["missing"])),
                "href": url_for("medalists.list_view",
                                department=first["department"]),
                "label": "Review %s" % first["department"]})
        if med_counts["draft"]:
            issues.append({"level": "warn",
                           "text": "%d medalist record%s still "
                                   "unpublished — the student board "
                                   "only shows published records."
                           % (med_counts["draft"],
                              "" if med_counts["draft"] == 1 else "s"),
                           "href": url_for("medalists.list_view",
                                           publication="draft"),
                           "label": "Review unpublished records"})
        issues.extend(med.data_quality(db, conv_id))

    # Phase 7: event information + announcements. Every value is a real
    # record: the date state derives from populated fields (expected can
    # never read as confirmed), counts come from the announcements table
    # and "recently published" from the audit trails. Issues are only
    # genuine gaps — provisional state and milestones are indicators on
    # the event card, not invented urgency.
    import announcements as ann
    import convocation_events as ev
    pub = ev.publication(db, conv_id)
    counts = ann.counts(db, conv_id)
    recent = db.execute(
        "SELECT actor, action, created_at FROM ("
        " SELECT id AS rid, actor, action, created_at FROM convocation_audit"
        "  WHERE convocation_id = ?"
        " UNION ALL SELECT id AS rid, actor, action, created_at"
        "  FROM announcement_audit WHERE convocation_id = ?)"
        " WHERE action IN ('publish', 'unpublish')"
        " ORDER BY created_at DESC, rid DESC LIMIT 5",
        (conv_id, conv_id)).fetchall()
    milestones = []
    for label, date_text in (("Convocation",
                              conv["confirmed_date"] or conv["expected_date"]),
                             ("Rehearsal", conv["rehearsal_date"])):
        days = ev.days_until(date_text)
        if days is not None and days >= 0:
            milestones.append({"label": label, "date": date_text,
                               "days": days})
    out["event"] = {
        "state": ev.date_state(conv),
        "label": ev.STATE_LABELS[ev.date_state(conv)],
        "published": pub is not None,
        "dirty": ev.is_dirty(db, conv),
        "announcements": counts,
        "recent": [dict(r) for r in recent],
        "milestones": milestones,
    }
    if out["event"]["state"] == "not_announced":
        issues.append({"level": "warn",
                       "text": "No convocation date has been announced yet — "
                               "students see no date at all.",
                       "href": url_for("exam.event_page"),
                       "label": "Open event details"})
    if out["event"]["dirty"]:
        issues.append({"level": "warn",
                       "text": "Event details changed since the last publish "
                               "— students still see the previous published "
                               "version.",
                       "href": url_for("exam.event_page"),
                       "label": "Review unpublished changes"})
    if not conv["venue"]:
        issues.append({"level": "warn",
                       "text": "No venue is recorded for this convocation.",
                       "href": url_for("exam.event_page"),
                       "label": "Set the venue"})
    if conv["rehearsal_date"] and not conv["rehearsal_time"]:
        issues.append({"level": "warn",
                       "text": "A rehearsal date is set but its time is "
                               "missing.",
                       "href": url_for("exam.event_page"),
                       "label": "Complete rehearsal details"})
    if counts["draft"]:
        issues.append({"level": "warn",
                       "text": "%d announcement draft%s not published — "
                               "students cannot see %s."
                       % (counts["draft"],
                          "" if counts["draft"] == 1 else "s",
                          "it" if counts["draft"] == 1 else "them"),
                       "href": url_for("exam.announcements_page"),
                       "label": "Review announcement drafts"})

    # Phase 9: student support metrics. Every number is a real COUNT from
    # support_requests.metrics over the active convocation, and every
    # warning links to the filtered queue that resolves it. Nothing here
    # mutates a registration — a resulting correction always goes through
    # the existing registration workflow from the request screen.
    import support_requests as sup
    sm = sup.metrics(db, conv_id)
    out["support"] = sm
    if sm["open"]:
        issues.append({
            "level": "warn",
            "text": "%d support request%s awaiting review."
                    % (sm["open"], "" if sm["open"] == 1 else "s"),
            "href": url_for("exam.support_queue", status="open"),
            "label": "Open the support queue"})
    if sm["info_required"]:
        issues.append({
            "level": "warn",
            "text": "%d request%s waiting on information from the student."
                    % (sm["info_required"],
                       "" if sm["info_required"] == 1 else "s"),
            "href": url_for("exam.support_queue", status="info_required"),
            "label": "Review requests needing information"})
    if sm["stale"]:
        issues.append({
            "level": "warn",
            "text": "%d support request%s open for more than %d days and "
                    "may need attention."
                    % (sm["stale"], "" if sm["stale"] == 1 else "s",
                       config.SUPPORT_STALE_DAYS),
            "href": url_for("exam.support_queue", status="open"),
            "label": "Review older requests"})

    # Phase 11: digital invitation passes. Real COUNTs over the active
    # convocation's registrations and claims, plus the operational-QR
    # prerequisite check. Nothing here grants eligibility or links a roster.
    # Phase 12 adds real COUNTs of issued convocation QR passes and recorded
    # admissions — still read-only reporting, never a grant of eligibility.
    import convocation_pass as cp
    active_total = totals.get("active", 0)
    claimed_active = db.execute(
        "SELECT COUNT(*) FROM registration_claims c"
        " JOIN convocation_registrations r ON r.id = c.registration_id"
        " WHERE c.convocation_id = ? AND r.status = 'active'",
        (conv_id,)).fetchone()[0]
    pending_review = db.execute(
        "SELECT COUNT(DISTINCT c.account_id) FROM registration_claims c"
        " JOIN convocation_registrations r ON r.id = c.registration_id"
        " JOIN support_requests s ON s.account_id = c.account_id"
        "  AND s.convocation_id = c.convocation_id"
        " WHERE c.convocation_id = ? AND r.status = 'active'"
        " AND s.category IN (%s) AND s.status IN (%s)"
        % (",".join("?" for _ in cp.BLOCKING_CATEGORIES),
           ",".join("?" for _ in sup.OPEN_STATUSES)),
        (conv_id, *cp.BLOCKING_CATEGORIES, *sup.OPEN_STATUSES)).fetchone()[0]
    out["invitations"] = {
        "active": active_total,
        "claimed": claimed_active,
        "pending_review": pending_review,
        "event_published": pub is not None,
        "qr_prerequisite": cp.qr_prerequisite(db, conv),
        # Phase 17: a pass only counts as "live" while its registration is
        # still active. Cancelling or revoking a registration stops the pass
        # admitting at the gate (convocation_qr re-checks eligibility on every
        # scan) but left the dashboard advertising it as a live entry pass.
        "passes_issued_active": db.execute(
            "SELECT COUNT(*) FROM convocation_passes p"
            " JOIN convocation_registrations r ON r.id = p.registration_id"
            " WHERE p.convocation_id = ? AND p.status = 'active'"
            " AND r.status = 'active'",
            (conv_id,)).fetchone()[0],
        "passes_issued_total": db.execute(
            "SELECT COUNT(*) FROM convocation_passes"
            " WHERE convocation_id = ?", (conv_id,)).fetchone()[0],
        "admitted": db.execute(
            "SELECT COUNT(*) FROM convocation_admissions"
            " WHERE convocation_id = ?", (conv_id,)).fetchone()[0],
    }
    out["invitations"]["qr_active"] = (
        out["invitations"]["passes_issued_active"] > 0)
    out["issues"] = issues
    return out


@bp.route("/")
@bp.route("/dashboard")
@staff_required
def dashboard(staff):
    db = database.get_db()
    try:
        metrics = dashboard_metrics(db)
    finally:
        db.close()
    return render_template("exam_dashboard.html", staff=staff,
                           metrics=metrics)
