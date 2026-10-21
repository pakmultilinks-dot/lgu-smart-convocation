"""Student convocation history (Phase 11, §1–§2).

A read-only ledger of every convocation this student's verified official
records touch, built from the ``registration_claims`` the account actually
owns. Nothing here is stored or edited by the client, and only the
requesting account's own records are ever returned — one student's history
never mixes with another's, and no operational check-in data leaks in.

Each entry pairs the claimed registration with the convocation's PUBLISHED
event snapshot (expected is never shown as confirmed) and any PUBLISHED
honours whose reference matches the registration's official identifiers.
The convocation the student is currently claimed for is flagged ``active``.

Phase 27 (D3): the active/past bucket is DERIVED from the event's real
state rather than from ``convocations.status`` alone. That column is written
once at insert as ``'planned'`` and no route in the product ever updates it,
so every convocation — including one whose date had passed — was reported as
still active. Derivation is a pure read: a history request never changes
state.
"""

import config
import convocation_events as ev

# A staff-declared terminal status is authoritative and always wins over the
# dates below. ('planned'/'confirmed'/'live' are the in-progress states the
# insert/check constraint define; they never imply "past" on their own.)
TERMINAL_STATUSES = ("completed", "archived")


def lifecycle(status, pub):
    """(bucket, phase) for one convocation — pure, and deliberately never a write.

    - ``completed`` / ``archived``: staff declared the record terminal.
    - Otherwise the event has ENDED only when the PUBLISHED snapshot carries a
      date before today **in the portal timezone** (``ev.days_until``); a date
      of today still counts as running, and only the announced convocation
      date counts — a rehearsal alone does not prove the event is over.
    - No usable date (never announced, unpublished, legacy or malformed): we
      cannot say. The entry reports ``undated`` and stays ``active`` instead
      of being falsely called past, so the uncertainty is exposed rather than
      guessed at.
    """
    if status in TERMINAL_STATUSES:
        return "past", status
    days = ev.days_until((pub["confirmed_date"] or pub["expected_date"])
                         if pub is not None else None)
    if days is None:
        return "active", "undated"
    return ("past", "ended") if days < 0 else ("active", "upcoming")


def _honours_for(db, conv_id, registration):
    """Published medals whose reference matches this registration's official
    identifiers (case-insensitive). Draft records never appear here."""
    ref_number = registration["registration_number"]
    roll = registration["roll_number"]
    rows = db.execute(
        "SELECT department, student_name, award_category, position, photo_file"
        " FROM medalists"
        " WHERE convocation_id = ? AND publication = 'published'"
        " AND reference_number IN (?, ?)"
        " ORDER BY award_category, position, id",
        (conv_id, ref_number, roll)).fetchall()
    return [{"department": r["department"], "student_name": r["student_name"],
             "award_category": r["award_category"], "position": r["position"],
             "has_photo": bool(r["photo_file"])} for r in rows]


def _entry(db, claim, active_conv_id):
    conv_id = claim["convocation_id"]
    conv_status = claim["conv_status"]
    is_active = conv_id == active_conv_id
    pub = ev.publication(db, conv_id)
    bucket, phase = lifecycle(conv_status, pub)
    event = None
    if pub is not None:
        state = ev.date_state(pub)
        rehearsal = ({"date": pub["rehearsal_date"],
                      "time": pub["rehearsal_time"],
                      "venue": pub["rehearsal_venue"] or pub["venue"]}
                     if pub["rehearsal_date"] else None)
        event = {"name": pub["name"], "year": pub["year"],
                 "date_state": state, "date_state_label": ev.STATE_LABELS[state],
                 "confirmed_date": pub["confirmed_date"],
                 "expected_date": pub["expected_date"],
                 "ceremony_time": pub["ceremony_time"],
                 "venue": pub["venue"], "rehearsal": rehearsal,
                 "published_at": pub["published_at"],
                 "occasions": ev.occasions(pub), "portal_tz": config.DISPLAY_TZ}
    return {
        "convocation": {"id": conv_id, "name": claim["conv_name"],
                        "year": claim["conv_year"], "status": conv_status,
                        "is_active": is_active, "lifecycle": phase,
                        "bucket": bucket},
        "registration": {"status": claim["reg_status"],
                         "student_name": claim["reg_name"],
                         "registration_number": claim["reg_number"],
                         "roll_number": claim["roll_number"],
                         "department": claim["department"],
                         "claimed_at": claim["claimed_at"]},
        "event": event,
        "honours": _honours_for(db, conv_id, {
            "registration_number": claim["reg_number"],
            "roll_number": claim["roll_number"]}),
    }


def history_for_account(db, account, active_conv_id=None):
    """Newest-first history of the convocations this account claimed.

    Isolation: only rows in ``registration_claims`` owned by this account.
    Read-only: derived from committed records, never a roster or scanner
    source. The active convocation (if any) sorts first, then newest year.
    """
    rows = db.execute(
        "SELECT c.convocation_id, c.created_at AS claimed_at,"
        "       v.name AS conv_name, v.year AS conv_year,"
        "       v.status AS conv_status,"
        "       r.status AS reg_status, r.student_name AS reg_name,"
        "       r.registration_number AS reg_number, r.roll_number,"
        "       r.department"
        " FROM registration_claims c"
        " JOIN convocations v ON v.id = c.convocation_id"
        " JOIN convocation_registrations r ON r.id = c.registration_id"
        " WHERE c.account_id = ?"
        " ORDER BY v.year DESC, c.convocation_id DESC, c.id DESC",
        (account["id"],)).fetchall()
    entries = [_entry(db, row, active_conv_id) for row in rows]
    entries.sort(key=lambda e: (0 if e["convocation"]["is_active"] else 1,))
    return entries
