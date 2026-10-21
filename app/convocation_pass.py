"""Digital convocation invitation pass (Phase 11, §1–§2; Phase 12, §3A).

The pass is an INFORMATIONAL, read-only invitation computed by the backend
from authoritative records — the claimed registration, its status, the
student's open support requests and the PUBLISHED event snapshot. The client
never stores or edits any of it, and this module never mutates a roster.

QR SCOPE: the volunteer scanner's LEGACY path resolves a QR payload to an
OPERATIONAL roster row via ``models.find_person(qr_id)`` → the ``students``
table. A convocation registration carries no ``qr_id`` and shares no key with
that roster — the two identifier spaces remain separate by design and there is
still no approved roster-synchronization workflow bridging them. Inventing
that link (by matching roll numbers, or by inserting a roster row when a pass
is opened) is exactly what the brief forbids: it could reuse or substitute
another student's identity and would bypass roster/registration-eligibility
rules. So THIS module still never issues a QR and never renders one; GET
/pass stays a read-only invitation.

Phase 12 adds a separate, non-roster path in ``convocation_qr``: while the
invitation state is ``eligible``, the student may mint a scannable convocation
QR (POST /api/student/pass/issue) that the gate verifies against the
authoritative registration/account ledger instead of the roster — solving the
§2 blocker without weakening separation or touching the legacy scanner.
"""

import config
import convocation_events as ev
import student_auth as sa
import support_requests as sup

# Pass states an account can be in for the active convocation.
STATE_LABELS = {
    "no_convocation": "No convocation is open",
    "registration_missing": "No confirmed registration",
    "registration_cancelled": "Registration cancelled",
    "registration_revoked": "Registration revoked",
    "pending_review": "Registration under review",
    "event_unpublished": "Event details not published",
    "eligible": "Invitation available",
}

# A registration is "under unresolved review" — and therefore not a valid
# pass — while the student holds an OPEN request in one of these
# registration-affecting categories. A general question never blocks a pass.
BLOCKING_CATEGORIES = ("missing_registration", "correction", "cancellation",
                       "account_claim")

# The real, structural reason a scannable QR cannot be issued yet. Shown to
# staff (admin portal) and summarised for the student.
# Why the LEGACY operational-QR prerequisite (roster sync) is still unmet —
# reported by qr_prerequisite. Registrations still cannot be resolved by the
# roster scanner; convocation entry instead uses the separately issued QR in
# convocation_qr, verified against the registration ledger.
ROSTER_BLOCKER = (
    "The operational-QR prerequisite is not met: convocation registrations "
    "are still not linked to the operational check-in roster (the students "
    "table the legacy scanner reads), and no approved roster-synchronization "
    "workflow exists to connect them. The legacy scanner therefore cannot "
    "resolve a registration by roster code; convocation entry uses a "
    "separately issued QR verified against the registration ledger instead."
)

# What the invitation itself says about QR issuance (GET /pass embeds none).
QR_BLOCKER = (
    "Your convocation entry QR is issued separately from this invitation. "
    "Convocation registrations are still not linked to the operational "
    "check-in roster, so the legacy roster scanner cannot resolve them — "
    "but while your registration is eligible you can issue a scannable "
    "convocation QR from this screen, and the gate verifies it against your "
    "registration record. The QR carries no personal data."
)


def _base(state, title, detail):
    return {"state": state, "state_label": STATE_LABELS[state],
            "title": title, "detail": detail,
            "convocation": None, "registration": None, "event": None,
            "qr_available": False, "qr": None, "qr_blocker": QR_BLOCKER}


def qr_prerequisite(db, conv):
    """Real diagnostic: has the LEGACY operational-QR prerequisite been met?

    ``satisfied`` is structurally False today — there is no authoritative key
    or approved sync between registrations and the operational roster, so the
    legacy scanner still cannot resolve a registration. This is unchanged by
    Phase 12: the separately issued convocation QR (convocation_qr) verifies
    against the registration ledger and does not make the roster prerequisite
    true. ``roster_overlap`` is a READ-ONLY count of active registrations
    whose roll_number happens to also appear in the operational roster; it is
    a diagnostic for staff planning a future sync, never a validated link and
    never a grant of eligibility.
    """
    if conv is None:
        return {"satisfied": False, "reason": ROSTER_BLOCKER,
                "roster_overlap": 0, "roster_size": 0}
    conv_id = conv["id"]
    roster_size = db.execute(
        "SELECT COUNT(*) FROM students WHERE qr_id IS NOT NULL").fetchone()[0]
    overlap = db.execute(
        "SELECT COUNT(*) FROM convocation_registrations r"
        " WHERE r.convocation_id = ? AND r.status = 'active'"
        " AND EXISTS (SELECT 1 FROM students s"
        "             WHERE s.roll_no = r.roll_number"
        "             AND s.qr_id IS NOT NULL)",
        (conv_id,)).fetchone()[0]
    return {"satisfied": False, "reason": ROSTER_BLOCKER,
            "roster_overlap": overlap, "roster_size": roster_size}


def open_blocking_requests(db, account_id, conv_id):
    """Open registration-affecting requests = the registration is under
    unresolved review (the brief's "pending registration review" state)."""
    return db.execute(
        "SELECT COUNT(*) FROM support_requests"
        " WHERE account_id = ? AND convocation_id = ?"
        " AND category IN (%s)"
        " AND status IN (%s)"
        % (",".join("?" for _ in BLOCKING_CATEGORIES),
           ",".join("?" for _ in sup.OPEN_STATUSES)),
        (account_id, conv_id, *BLOCKING_CATEGORIES,
         *sup.OPEN_STATUSES)).fetchone()[0]


def _event_snapshot(db, conv_id):
    """Published-only event info; expected is never labelled confirmed."""
    pub = ev.publication(db, conv_id)
    if pub is None:
        return None
    state = ev.date_state(pub)
    rehearsal = None
    if pub["rehearsal_date"]:
        rehearsal = {"date": pub["rehearsal_date"],
                     "time": pub["rehearsal_time"],
                     "venue": pub["rehearsal_venue"] or pub["venue"]}
    return {"name": pub["name"], "year": pub["year"],
            "date_state": state, "date_state_label": ev.STATE_LABELS[state],
            "confirmed_date": pub["confirmed_date"],
            "expected_date": pub["expected_date"],
            "ceremony_time": pub["ceremony_time"], "venue": pub["venue"],
            "rehearsal": rehearsal, "instructions": pub["instructions"],
            "published_at": pub["published_at"],
            "occasions": ev.occasions(pub), "portal_tz": config.DISPLAY_TZ}


def _registration_view(row):
    return {"status": row["status"], "student_name": row["student_name"],
            "registration_number": row["registration_number"],
            "roll_number": row["roll_number"],
            "department": row["department"]}


def pass_for_account(db, account, conv):
    """The student's digital invitation for the active convocation.

    State is derived here, server-side, from the authoritative record; the
    screen only renders it. An ineligible student never receives event
    details or a scannable code — only a clear reason.
    """
    if conv is None:
        return _base(
            "no_convocation", "No convocation is open",
            "There is no active convocation to invite you to yet.")
    conv_id = conv["id"]
    row = sa.claimed_registration(db, account["id"], conv_id)
    conv_view = {"id": conv_id, "name": conv["name"], "year": conv["year"]}

    if row is None:
        out = _base(
            "registration_missing", "No confirmed registration",
            "You do not have a confirmed registration for this convocation "
            "yet. Contact the Examination Department if you expect one.")
        out["convocation"] = conv_view
        return out
    if row["status"] == "cancelled":
        out = _base(
            "registration_cancelled", "Registration cancelled",
            "Your registration for this convocation has been cancelled, so "
            "no invitation is issued. Open Help & corrections to ask about "
            "it.")
        out["convocation"] = conv_view
        out["registration"] = _registration_view(row)
        return out
    if row["status"] == "revoked":
        out = _base(
            "registration_revoked", "Registration revoked",
            "Your registration for this convocation has been revoked, so no "
            "invitation is issued. Open Help & corrections to ask about it.")
        out["convocation"] = conv_view
        out["registration"] = _registration_view(row)
        return out

    # Registration is active from here on.
    if open_blocking_requests(db, account["id"], conv_id):
        out = _base(
            "pending_review", "Registration under review",
            "You have an open request the Examination Department is still "
            "reviewing, so your invitation is not final yet. It will appear "
            "here once the review is resolved.")
        out["convocation"] = conv_view
        out["registration"] = _registration_view(row)
        return out

    event = _event_snapshot(db, conv_id)
    if event is None:
        out = _base(
            "event_unpublished", "Event details not published",
            "Your registration is confirmed, but the official convocation "
            "details have not been published yet. The invitation appears "
            "here once they are published.")
        out["convocation"] = conv_view
        out["registration"] = _registration_view(row)
        return out

    out = _base(
        "eligible", "Invitation available",
        "This is your official convocation invitation, based on your "
        "confirmed registration and the published event details.")
    out["convocation"] = conv_view
    out["registration"] = _registration_view(row)
    out["event"] = event
    return out
