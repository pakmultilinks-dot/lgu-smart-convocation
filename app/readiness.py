"""Student convocation readiness centre and personalized reminders (Phase 10).

Readiness is computed server-side from authoritative records the Examination
Department already owns — the claimed registration, profile completion, the
published event snapshot, published announcements and the student's own
support requests. The student app never keeps an editable copy of any of
those: it renders this response and refreshes it through the existing
freshness mechanism, so a staff change appears after the next fetch.

Two shapes come out of `readiness_for`:

* ``items``   — the checklist. Every row is a real, backend-verifiable state
  (a claimed registration, a stored photo, a published date, a live support
  request). Nothing is marked done because a screen was opened; nothing is
  invented — there are no deadlines, eligibility rules or tasks here that do
  not already exist as data.
* ``reminders`` — the personalized alerts. Each carries a stable key (so the
  same fact never re-alerts twice), a reason, a priority, a timestamp drawn
  from the source record, and a navigation action. Only informational
  reminders are dismissible; an unresolved registration or support issue is
  never dismissible, so a dismissal can never hide it.

Reminder read/dismiss state lives in student_reminder_state (migration v8),
keyed by (account, key), and is written only after the server has re-derived
the live reminder set and confirmed the key is present and dismissible — a
client cannot dismiss an arbitrary key.
"""

from datetime import datetime, timezone

import announcements as ann
import convocation_events as ev
import convocation_pass as cp
import exam_registrations as reg
import student_auth as sa
import support_requests as sup

# Stable navigation targets (expo-router paths) used by the mobile app. The
# backend only names the destination; the app owns how it renders.
ROUTE_HOME = "/(student)/home"
ROUTE_PROFILE = "/(student)/profile"
ROUTE_EVENT = "/(student)/event"
ROUTE_ANNOUNCEMENTS = "/(student)/announcements"
ROUTE_SUPPORT = "/(student)/support"
ROUTE_PASS = "/(student)/pass"


def _live_pass(db, conv_id, registration_id):
    """The latest ACTIVE, unexpired convocation entry pass, or None.

    Read-only. Mirrors convocation_qr.live_pass plus the scan-time TTL check,
    so readiness reports a pass only when the gate would actually accept it.
    An expired-but-still-'active' pass is treated as absent (a student must
    reissue), matching what convocation_qr.verify_scan enforces at the gate.
    """
    row = db.execute(
        "SELECT * FROM convocation_passes"
        " WHERE convocation_id = ? AND registration_id = ? AND status = 'active'"
        " ORDER BY id DESC LIMIT 1", (conv_id, registration_id)).fetchone()
    if row is None:
        return None
    if row["expires_at"]:
        try:
            now = datetime.now(timezone.utc)
            exp = datetime.fromisoformat(row["expires_at"])
            if exp.tzinfo is None:   # naive stamps are UTC
                exp = exp.replace(tzinfo=timezone.utc)
            if now >= exp:
                return None
        except (TypeError, ValueError):
            pass
    return row


def _stamp():
    """UTC timestamp in SQLite's 'YYYY-MM-DD HH:MM:SS' form (module-local,
    same rule as support_requests — see that docstring for why)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _route_support_detail(request_id):
    return f"{ROUTE_SUPPORT}-detail?id={request_id}"


# ---------------------------------------------------------------- reminders

def reminder_state_map(db, account_id):
    rows = db.execute(
        "SELECT reminder_key, state FROM student_reminder_state"
        " WHERE account_id = ?", (account_id,)).fetchall()
    return {r["reminder_key"]: r["state"] for r in rows}


def set_reminder_state(db, account_id, key, state):
    db.execute(
        "INSERT INTO student_reminder_state"
        " (account_id, reminder_key, state, updated_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(account_id, reminder_key)"
        " DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
        (account_id, key, state, _stamp()))
    db.commit()


# --------------------------------------------------------------- checklist

def _item(key, kind, status, title, detail, action=None, source="", at=None):
    return {"key": key, "kind": kind, "status": status, "title": title,
            "detail": detail, "action": action, "source": source, "at": at}


def _reminder(key, priority, title, reason, at, action, dismissible):
    return {"key": key, "priority": priority, "title": title, "reason": reason,
            "at": at, "action": action, "dismissible": dismissible}


def readiness_for(db, account):
    """Combine every authoritative signal into checklist + reminders.

    Pure read: no row is written here (state changes happen only through the
    reminder endpoint). Every sub-query is scoped to this account or to
    published/public data, so nothing leaks across students.
    """
    conv = reg.active_convocation(db)
    claim = sa.claimed_registration(db, account["id"], conv["id"]) if conv else None
    profile = sa.ensure_profile(db, account["id"])
    event = ev.student_payload(db)
    announcements = ann.feed(db, conv["id"]) if conv else []
    requests = sup.list_for_account(db, account["id"], conv["id"]) if conv else []

    items = []
    reminders = []

    # --- registration ---------------------------------------------------
    if conv is None:
        items.append(_item(
            "registration", "info", "todo",
            "No convocation is open yet",
            "Registration details appear once the Examination Department "
            "opens a convocation.", None, "registration"))
    elif claim is None:
        items.append(_item(
            "registration", "required", "todo",
            "Claim your registration",
            "Link your official registration to this account to see your "
            "convocation status.",
            {"label": "Claim registration", "route": ROUTE_HOME},
            "registration"))
        reminders.append(_reminder(
            "registration:%s:unclaimed" % conv["id"], "high",
            "Your registration is not claimed yet",
            "You have not linked an official registration to this account.",
            None, {"label": "Open home", "route": ROUTE_HOME}, False))
    elif claim["status"] != "active":
        items.append(_item(
            "registration", "required", "attention",
            "Registration needs review",
            "Your registration is currently marked '%s'. The Examination "
            "Department must review it before convocation." % claim["status"],
            {"label": "Open support", "route": ROUTE_SUPPORT},
            "registration", claim["updated_at"]))
        reminders.append(_reminder(
            "registration:%s:%s" % (conv["id"], claim["status"]), "high",
            "Registration requires attention",
            "Your registration is marked '%s'." % claim["status"],
            claim["updated_at"],
            {"label": "Open support", "route": ROUTE_SUPPORT}, False))
    else:
        items.append(_item(
            "registration", "required", "done",
            "Registration confirmed",
            "Your registration is active for %s." % conv["name"],
            {"label": "Open home", "route": ROUTE_HOME},
            "registration", claim["claimed_at"]))

    # --- entry pass (Phase 26A): readiness must never claim "ready" without
    # a live, gate-acceptable convocation QR. Profile completion and an active
    # registration are NOT entry eligibility — the pass is the authoritative
    # entry credential, so it is a REQUIRED item derived from the same
    # invitation state the pass screen and the gate verify against. --------
    if conv is not None and claim is not None and claim["status"] == "active":
        invitation = cp.pass_for_account(db, account, conv)
        live = _live_pass(db, conv["id"], claim["id"])
        if live is not None:
            items.append(_item(
                "entry_pass", "required", "done",
                "Entry pass issued",
                "Your convocation entry QR is issued and valid for %s."
                % conv["name"],
                {"label": "Open invitation", "route": ROUTE_PASS},
                "pass", live["issued_at"]))
        elif invitation["state"] == "eligible":
            items.append(_item(
                "entry_pass", "required", "todo",
                "Issue your entry pass",
                "Your registration is eligible, but no entry QR has been "
                "issued yet. Open your invitation to issue the pass you will "
                "scan at the gate.",
                {"label": "Open invitation", "route": ROUTE_PASS},
                "pass"))
            reminders.append(_reminder(
                "pass:%s:unissued" % conv["id"], "high",
                "Your entry pass is not issued yet",
                "You need a convocation entry QR before you can be admitted.",
                None, {"label": "Open invitation", "route": ROUTE_PASS},
                False))
        else:
            items.append(_item(
                "entry_pass", "required", "attention",
                "Entry pass not available",
                invitation["detail"] or
                "An entry pass cannot be issued for your registration yet.",
                {"label": "Open invitation", "route": ROUTE_PASS},
                "pass"))

    # --- profile completion (photo is the required field the app stores) --
    if profile["photo_file"]:
        items.append(_item(
            "profile_photo", "required", "done",
            "Profile photo added",
            "Your profile includes a photo.",
            {"label": "Manage profile", "route": ROUTE_PROFILE},
            "profile", profile["photo_updated_at"]))
    else:
        items.append(_item(
            "profile_photo", "required", "todo",
            "Add a profile photo",
            "A profile photo is required so staff can identify you at "
            "convocation.",
            {"label": "Add photo", "route": ROUTE_PROFILE}, "profile"))
        reminders.append(_reminder(
            "profile:photo", "normal", "Add a profile photo",
            "Your profile is missing a photo.", None,
            {"label": "Add photo", "route": ROUTE_PROFILE}, True))

    # --- published event date and rehearsal (provisional vs confirmed) ----
    event_info = event.get("event")
    if event_info is None:
        items.append(_item(
            "event_date", "info", "todo",
            "Event details not published",
            "The convocation date has not been published yet.",
            {"label": "Open event", "route": ROUTE_EVENT}, "event"))
    else:
        state = event_info["date_state"]
        if state == "confirmed":
            items.append(_item(
                "event_date", "required", "done",
                "Convocation date confirmed",
                "The convocation date is officially confirmed for %s."
                % event_info["confirmed_date"],
                {"label": "Open event", "route": ROUTE_EVENT},
                "event", event_info["published_at"]))
            reminders.append(_reminder(
                "event:%s:date" % event["convocation"]["id"], "normal",
                "Convocation date confirmed",
                "The convocation date is officially confirmed for %s."
                % event_info["confirmed_date"],
                event_info["published_at"],
                {"label": "Open event", "route": ROUTE_EVENT}, True))
        elif state == "expected":
            items.append(_item(
                "event_date", "info", "todo",
                "Expected convocation date published",
                "An expected (provisional) date of %s is shown — it is not "
                "yet officially confirmed." % event_info["expected_date"],
                {"label": "Open event", "route": ROUTE_EVENT},
                "event", event_info["published_at"]))
            reminders.append(_reminder(
                "event:%s:date" % event["convocation"]["id"], "normal",
                "Expected convocation date published",
                "A provisional date of %s is shown. It is not officially "
                "confirmed." % event_info["expected_date"],
                event_info["published_at"],
                {"label": "Open event", "route": ROUTE_EVENT}, True))
        rehearsal = event_info.get("rehearsal")
        if rehearsal and rehearsal.get("date"):
            items.append(_item(
                "rehearsal", "info", "todo",
                "Rehearsal schedule published",
                "Rehearsal is scheduled for %s%s."
                % (rehearsal["date"],
                   (" at %s" % rehearsal["time"]) if rehearsal.get("time")
                   else ""),
                {"label": "Open event", "route": ROUTE_EVENT},
                "event", event_info["published_at"]))
            reminders.append(_reminder(
                "event:%s:rehearsal" % event["convocation"]["id"], "normal",
                "Rehearsal schedule published",
                "Rehearsal is scheduled for %s." % rehearsal["date"],
                event_info["published_at"],
                {"label": "Open event", "route": ROUTE_EVENT}, True))

    # --- published announcements (important ones become reminders) --------
    if announcements:
        items.append(_item(
            "announcements", "info", "todo",
            "Review convocation announcements",
            "%d published announcement%s to review."
            % (len(announcements), "" if len(announcements) == 1 else "s"),
            {"label": "Open announcements", "route": ROUTE_ANNOUNCEMENTS},
            "announcements", announcements[0]["published_at"]))
        for row in announcements:
            if not row["is_important"]:
                continue
            reminders.append(_reminder(
                "announcement:%s" % row["id"], "normal",
                row["title"],
                "An important announcement was published.",
                row["published_at"] or row["created_at"],
                {"label": "Read announcement", "route": ROUTE_ANNOUNCEMENTS},
                True))

    # --- support requests that require the student to act ----------------
    for row in requests:
        if row["status"] == "info_required":
            items.append(_item(
                "support:%s" % row["id"], "required", "attention",
                "Staff requested more information",
                "A staff member asked for more information about your "
                "request '%s'." % row["subject"],
                {"label": "Open request", "route": _route_support_detail(row["id"])},
                "support", row["updated_at"]))
            reminders.append(_reminder(
                "support:%s:info_required" % row["id"], "high",
                "A staff member requested more information",
                "Your request '%s' is waiting on a reply from you."
                % row["subject"],
                row["updated_at"],
                {"label": "Open request", "route": _route_support_detail(row["id"])},
                False))
        elif row["status"] in sup.OPEN_STATUSES:
            items.append(_item(
                "support:%s" % row["id"], "info", "todo",
                "Support request under review",
                "Your request '%s' is with the Examination Department."
                % row["subject"],
                {"label": "Open request", "route": _route_support_detail(row["id"])},
                "support", row["updated_at"]))

    # --- reminders: apply stored read/dismiss state, drop dismissed -------
    states = reminder_state_map(db, account["id"])
    for reminder in reminders:
        reminder["state"] = states.get(reminder["key"], "new")
    active = [r for r in reminders if not (
        r["state"] == "dismissed" and r["dismissible"])]
    # Highest priority first; stable order within a priority (by key) so the
    # list never reshuffles between refreshes.
    active.sort(key=lambda r: (0 if r["priority"] == "high" else 1, r["key"]))

    required = [i for i in items if i["kind"] == "required"]
    required_done = sum(1 for i in required if i["status"] == "done")
    summary = {
        "required_total": len(required),
        "required_done": required_done,
        "percent": (required_done * 100 // len(required)) if required else 100,
        "outstanding": sum(1 for i in required if i["status"] != "done"),
        "reminders_new": sum(1 for r in active if r["state"] == "new"),
    }

    return {
        "convocation": ({"name": conv["name"], "year": conv["year"]}
                        if conv else None),
        "generated_at": _stamp(),
        "summary": summary,
        "items": items,
        "reminders": active,
    }


def mark_reminder(db, account, key, action):
    """Persist a read/dismiss after re-deriving the live reminder set.

    The key must be a reminder this student currently has AND, for a dismiss,
    it must be dismissible. Returns the stored state. Raises ValueError on
    any invalid target so the route can answer 400/404 without touching data.
    """
    if action not in ("read", "dismiss"):
        raise ValueError("Unknown reminder action.")
    data = readiness_for(db, account)
    match = next((r for r in data["reminders"] if r["key"] == key), None)
    if match is None:
        raise ValueError("That reminder is not on your list.")
    if action == "dismiss" and not match["dismissible"]:
        raise ValueError("This reminder cannot be dismissed.")
    state = "dismissed" if action == "dismiss" else "read"
    set_reminder_state(db, account["id"], key, state)
    return state
