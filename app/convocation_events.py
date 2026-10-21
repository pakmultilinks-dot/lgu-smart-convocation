"""Convocation event information (Phase 7, §1–§2).

The convocation row holds the working (draft) details the exam staff edit;
students only ever see the snapshot in convocation_publications, which is
written by an explicit publish action and attributed to the acting staff
member. The three date states — not_announced / expected / confirmed — are
derived from which date fields a record actually carries, so an expected
date can never be presented as confirmed.

Never touches app/lgu.db: the caller passes the request-scoped db handle.
"""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import config
from database import _now
from exam_registrations import utc_now

DETAIL_FIELDS = ("name", "year", "expected_date", "confirmed_date",
                 "ceremony_time", "rehearsal_date", "rehearsal_time",
                 "rehearsal_venue", "venue", "instructions")
MAX_NAME = 120
MAX_VENUE = 200
MAX_INSTRUCTIONS = 2000

STATE_LABELS = {
    "not_announced": "Not announced",
    "expected": "Expected (provisional)",
    "confirmed": "Officially confirmed",
}


class EventError(Exception):
    """Rejected event input — carries a message safe to show in the portal."""


def active(db):
    return db.execute(
        "SELECT * FROM convocations WHERE is_active = 1 ORDER BY id LIMIT 1"
    ).fetchone()


def get(db, conv_id):
    return db.execute("SELECT * FROM convocations WHERE id = ?",
                      (conv_id,)).fetchone()


def list_events(db):
    return db.execute("SELECT * FROM convocations ORDER BY id DESC").fetchall()


def date_state(row):
    """not_announced → expected → confirmed, strictly by populated fields."""
    if row is None:
        return "not_announced"
    if row["confirmed_date"]:
        return "confirmed"
    if row["expected_date"]:
        return "expected"
    return "not_announced"


def _bound(value, label, limit):
    value = (value or "").strip()
    if len(value) > limit:
        raise EventError(f"{label} is too long (limit {limit} characters).")
    return value


def _date_or_none(value, label):
    value = (value or "").strip()
    if not value:
        return None
    # Legacy seeding stored the full ISO datetime in expected_date; accept
    # (and normalize) any trailing time suffix instead of rejecting it.
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise EventError(f"{label} must be a valid date (YYYY-MM-DD).")


def _time_or_none(value, label):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time().isoformat(
            timespec="minutes")
    except ValueError:
        raise EventError(f"{label} must be a valid time (HH:MM).")


def clean_details(form):
    """Validate the edit form into a complete, bounded detail dict."""
    name = _bound(form.get("name"), "Event name", MAX_NAME)
    if not name:
        raise EventError("Event name is required.")
    year = _bound(form.get("year"), "Year", 20)
    if not year:
        raise EventError("Year is required.")
    details = {
        "name": name,
        "year": year,
        "expected_date": _date_or_none(form.get("expected_date"),
                                       "Expected date"),
        "confirmed_date": _date_or_none(form.get("confirmed_date"),
                                        "Confirmed date"),
        "ceremony_time": _time_or_none(form.get("ceremony_time"),
                                        "Ceremony time"),
        "rehearsal_date": _date_or_none(form.get("rehearsal_date"),
                                        "Rehearsal date"),
        "rehearsal_time": _time_or_none(form.get("rehearsal_time"),
                                        "Rehearsal time"),
        "rehearsal_venue": _bound(form.get("rehearsal_venue"),
                                  "Rehearsal venue", MAX_VENUE),
        "venue": _bound(form.get("venue"), "Venue", MAX_VENUE),
        "instructions": _bound(form.get("instructions"), "Instructions",
                               MAX_INSTRUCTIONS),
    }
    _check_order(details)
    return details


def _check_order(details):
    """The rehearsal must precede the main convocation (Phase 29 §2).

    ISO dates and HH:MM times compare correctly as strings. The ceremony
    side uses the confirmed date, falling back to the provisional expected
    date when that is all there is — a schedule that contradicts itself is
    rejected whether or not it has been confirmed yet."""
    ceremony = details["confirmed_date"] or details["expected_date"]
    rehearsal = details["rehearsal_date"]
    if not (ceremony and rehearsal):
        return
    if rehearsal > ceremony:
        raise EventError(
            "The rehearsal must be scheduled before the main convocation.")
    if rehearsal == ceremony:
        r_time, c_time = details["rehearsal_time"], details["ceremony_time"]
        if r_time and c_time and r_time >= c_time:
            raise EventError(
                "On the same day, the rehearsal must start before the main "
                "convocation starts.")


def details_of(row):
    return {name: row[name] for name in DETAIL_FIELDS}


def _audit(db, conv_id, actor, action, before, after):
    db.execute(
        "INSERT INTO convocation_audit "
        "(convocation_id, actor, action, before_json, after_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conv_id, actor, action, json.dumps(before, sort_keys=True),
         json.dumps(after, sort_keys=True), utc_now()))


def save_details(db, conv, details, actor):
    """Draft-save the working details; returns the changed fields."""
    before = details_of(conv)
    changed = {k: v for k, v in details.items() if before[k] != v}
    if changed:
        db.execute(
            "UPDATE convocations SET name = :name, year = :year, "
            "expected_date = :expected_date, confirmed_date = :confirmed_date, "
            "ceremony_time = :ceremony_time, "
            "rehearsal_date = :rehearsal_date, "
            "rehearsal_time = :rehearsal_time, "
            "rehearsal_venue = :rehearsal_venue, venue = :venue, "
            "instructions = :instructions, updated_at = :updated_at "
            "WHERE id = :id",
            {**details, "updated_at": _now(), "id": conv["id"]})
        _audit(db, conv["id"], actor, "save",
               {k: before[k] for k in changed},
               {k: changed[k] for k in changed})
    return changed


def create_event(db, details, actor):
    """Add a separate convocation event. Never steals active status."""
    now = _now()
    cur = db.execute(
        "INSERT INTO convocations "
        "(name, year, status, expected_date, confirmed_date, ceremony_time, "
        " rehearsal_date, rehearsal_time, rehearsal_venue, venue, "
        " instructions, is_active, created_at, updated_at) "
        "VALUES (?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (details["name"], details["year"], details["expected_date"],
         details["confirmed_date"], details["ceremony_time"],
         details["rehearsal_date"], details["rehearsal_time"],
         details["rehearsal_venue"], details["venue"],
         details["instructions"], now, now))
    conv_id = cur.lastrowid
    _audit(db, conv_id, actor, "create", {}, details)
    return conv_id


def set_active(db, conv_id, actor):
    """Make one event active and only that one (partial UNIQUE index backs it)."""
    db.execute("BEGIN IMMEDIATE")
    previous = active(db)
    db.execute("UPDATE convocations SET is_active = 0, updated_at = ? "
               "WHERE is_active = 1", (_now(),))
    if conv_id is not None:
        db.execute("UPDATE convocations SET is_active = 1, updated_at = ? "
                   "WHERE id = ?", (_now(), conv_id))
    _audit(db, conv_id if conv_id is not None else (previous["id"]
                                                    if previous else 0),
           actor, "activate",
           {"was_active": previous["id"] if previous else None},
           {"is_active": conv_id})
    return previous


def publication(db, conv_id):
    return db.execute("SELECT * FROM convocation_publications "
                      "WHERE convocation_id = ?", (conv_id,)).fetchone()


def publish(db, conv, actor):
    """Copy the working details into the published snapshot students see."""
    details = details_of(conv)
    now = utc_now()
    previous = publication(db, conv["id"])
    db.execute(
        "INSERT INTO convocation_publications "
        "(convocation_id, name, year, expected_date, confirmed_date, "
        " ceremony_time, rehearsal_date, rehearsal_time, rehearsal_venue, "
        " venue, instructions, published_by, published_at) "
        "VALUES (:convocation_id, :name, :year, :expected_date, "
        " :confirmed_date, :ceremony_time, :rehearsal_date, "
        " :rehearsal_time, :rehearsal_venue, :venue, :instructions, "
        " :published_by, :published_at) "
        "ON CONFLICT(convocation_id) DO UPDATE SET "
        " name = excluded.name, year = excluded.year, "
        " expected_date = excluded.expected_date, "
        " confirmed_date = excluded.confirmed_date, "
        " ceremony_time = excluded.ceremony_time, "
        " rehearsal_date = excluded.rehearsal_date, "
        " rehearsal_time = excluded.rehearsal_time, "
        " rehearsal_venue = excluded.rehearsal_venue, "
        " venue = excluded.venue, instructions = excluded.instructions, "
        " published_by = excluded.published_by, "
        " published_at = excluded.published_at",
        {**details, "convocation_id": conv["id"], "published_by": actor,
         "published_at": now})
    _audit(db, conv["id"], actor, "publish",
           details_of(previous) if previous else {},
           {**details, "published_by": actor, "published_at": now})
    return publication(db, conv["id"])


def is_dirty(db, conv):
    """True when working details differ from the published snapshot."""
    pub = publication(db, conv["id"])
    if pub is None:
        return False
    return any(pub[name] != conv[name] for name in DETAIL_FIELDS)


def days_until(date_text):
    """Whole days from today (portal timezone) to a date value."""
    if not date_text:
        return None
    try:
        target = datetime.strptime(date_text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    today = datetime.strptime(_now()[:10], "%Y-%m-%d").date()
    return (target - today).days


def audit_trail(db, conv_id, limit=20):
    return db.execute(
        "SELECT * FROM convocation_audit WHERE convocation_id = ? "
        "ORDER BY id DESC LIMIT ?", (conv_id, limit)).fetchall()


def _utc_start(date_text, time_text):
    """ISO-8601 UTC instant of a portal-local date+time, or None when the
    date is unusable or the START TIME was never announced — a countdown
    clock must never claim a time nobody published."""
    if not date_text or not time_text:
        return None
    try:
        moment = datetime.combine(
            datetime.strptime(date_text[:10], "%Y-%m-%d").date(),
            datetime.strptime(time_text[:5], "%H:%M").time(),
            tzinfo=ZoneInfo(config.DISPLAY_TZ))
    except (TypeError, ValueError):
        return None
    return moment.astimezone(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _occasion(label, key, date_text, time_text, venue, state):
    """One occasion's published schedule with a server-authoritative phase.

    - phase: upcoming → live (the date is TODAY in the portal timezone) →
      completed (the date has passed). None while unannounced.
    - days_until: signed days from today (portal timezone); None when the
      date is unusable.
    - starts_at: UTC instant, present only when date AND time are known.
    """
    phase, days = None, None
    if date_text:
        try:
            day = datetime.strptime(date_text[:10], "%Y-%m-%d").date()
            today = datetime.strptime(_now()[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            day = None
        if day is not None:
            days = (day - today).days
            phase = ("completed" if days < 0 else
                     "live" if days == 0 else "upcoming")
    return {"key": key, "label": label, "date": date_text, "time": time_text,
            "venue": venue or None, "state": state, "phase": phase,
            "days_until": days, "starts_at": _utc_start(date_text, time_text)}


def occasions(pub):
    """The annual cycle's two occasions, in chronological order (Phase 29).

    The ceremony keeps the publication's own date_state, so an expected
    (provisional) date is never labelled confirmed; the rehearsal becomes
    'announced' once a date exists, because publishing is itself the staff
    act that confirms it. A rehearsal venue falls back to the main venue
    when none was set separately."""
    if pub is None:
        return []
    return [
        _occasion("Convocation rehearsal", "rehearsal", pub["rehearsal_date"],
                  pub["rehearsal_time"],
                  pub["rehearsal_venue"] or pub["venue"],
                  "announced" if pub["rehearsal_date"] else "not_announced"),
        _occasion("Main convocation", "ceremony",
                  pub["confirmed_date"] or pub["expected_date"],
                  pub["ceremony_time"], pub["venue"], date_state(pub)),
    ]


def student_payload(db):
    """Published-only event info for the active convocation (§3/§5 law)."""
    conv = active(db)
    pub = publication(db, conv["id"]) if conv else None
    if pub is None:
        return {"convocation": None, "event": None}
    state = date_state(pub)
    rehearsal = None
    if pub["rehearsal_date"]:
        rehearsal = {"date": pub["rehearsal_date"],
                     "time": pub["rehearsal_time"],
                     "venue": pub["rehearsal_venue"] or pub["venue"]}
    return {
        "convocation": {"id": conv["id"], "name": pub["name"],
                        "year": pub["year"]},
        "event": {
            "date_state": state,
            "date_state_label": STATE_LABELS[state],
            "expected_date": pub["expected_date"],
            "confirmed_date": pub["confirmed_date"],
            "ceremony_time": pub["ceremony_time"],
            "rehearsal": rehearsal,
            "venue": pub["venue"],
            "instructions": pub["instructions"],
            "published_at": pub["published_at"],
            "occasions": occasions(pub),
            "portal_tz": config.DISPLAY_TZ,
        },
    }
