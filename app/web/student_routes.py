"""Student-facing JSON API (Phase 5): verification, sessions, profile.

Auth is a Bearer token in the Authorization header — no cookies, so there is
no ambient credential and no CSRF surface. Every response is JSON; every
private route resolves the session first. Email delivery fails closed: when
the provider is unavailable, verification and recovery answer HTTP 503 and
no account is ever created from an unverified address.
"""

import base64
import threading
import time
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request

import announcements as ann
import config
import convocation_events as ev
import convocation_history as hist
import convocation_pass as cp
import convocation_qr as cqr
import database
import emailer
import exam_registrations as reg
import medalists as med
import models
import readiness as rd
import student_auth as sa
import support_requests as sup
from exam_auth import validate_password
from exam_registrations import EMAIL_RE

bp = Blueprint("student_api", __name__, url_prefix="/api/student")

# Per-IP, in-process limits (same pattern as the exam/PIN limiters), read
# from config at request time so tests can tune them.
_HITS = {"send": [], "recovery": [], "login": [], "support": [], "readiness": [],
         "passissue": [], "confirm": []}
_HITS_LOCK = threading.Lock()

# Phase 18: each bucket uses its OWN documented window. Previously every
# bucket silently inherited STUDENT_RATE_WINDOW_SECONDS, so the support
# limiter ran on a 60s window instead of its intended 300s (allowing ~5x
# more requests over five minutes) and PASS_ISSUE_RATE_WINDOW_SECONDS was
# unreachable. A bucket that declares no window falls back to the shared
# student window; the attribute is resolved per call so tests can tune it.
_BUCKET_WINDOWS = {
    "send": "STUDENT_RATE_WINDOW_SECONDS",
    "recovery": "STUDENT_RATE_WINDOW_SECONDS",
    "login": "STUDENT_RATE_WINDOW_SECONDS",
    "confirm": "STUDENT_RATE_WINDOW_SECONDS",
    "support": "SUPPORT_RATE_WINDOW_SECONDS",
    "readiness": "READINESS_RATE_WINDOW_SECONDS",
    "passissue": "PASS_ISSUE_RATE_WINDOW_SECONDS",
}


def _bucket_window(bucket):
    """Validated window for a bucket; unusable config falls back to the default.

    A non-positive or non-integer value would otherwise mean "no limiting at
    all", so it degrades to the shared student window instead.
    """
    value = getattr(config, _BUCKET_WINDOWS.get(bucket, ""), None)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return config.STUDENT_RATE_WINDOW_SECONDS
    return value


def _limited(bucket, limit):
    now = time.time()
    window = _bucket_window(bucket)
    with _HITS_LOCK:
        hits = [t for t in _HITS[bucket] if now - t < window]
        if len(hits) >= limit:
            _HITS[bucket] = hits
            return True
        hits.append(now)
        _HITS[bucket] = hits
        return False


def _json():
    return request.get_json(silent=True) or {}


def _int_field(payload, name):
    try:
        value = int(payload.get(name) or 0)
    except (TypeError, ValueError):
        value = 0
    if value < 1:
        raise sa.StudentError(400, "missing_field", "%s is required." % name)
    return value


def _bearer():
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else ""


def current_account(db):
    account = sa.account_for_token(db, _bearer())
    if account is None:
        raise sa.StudentError(401, "auth", "Sign in to continue.")
    return account


def _send_email(to_email, code):
    try:
        emailer.send_verification(to_email, code)
    except emailer.EmailUnavailable:
        raise sa.StudentError(
            503, "email_unavailable",
            "Verification email could not be sent. Contact the Examination "
            "Department.")


def _expires_in(ts):
    try:
        moment = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return 0
    return max(0, int((moment - datetime.now(timezone.utc)).total_seconds()))


def _registration_payload(row):
    return {"registration_number": row["registration_number"],
            "roll_number": row["roll_number"],
            "student_name": row["student_name"],
            "department": row["department"], "status": row["status"],
            "convocation_id": row["convocation_id"]}


def _profile_payload(profile):
    return {"phone": profile["phone"],
            "photo": bool(profile["photo_file"]),
            "photo_updated_at": profile["photo_updated_at"]}


def _completion(profile, claimed):
    """Completion derived from ONE authoritative state.

    The three per-step flags and the count both come from this same `steps`
    list, so the header ("2 of 3") can never disagree with the step pills.
    The top-level booleans mirror the steps for the mobile client, which
    reads `completion.verified/claimed/photo` directly.
    """
    verified = True  # an account only exists after email verification
    steps = [("verified", "Email verified", bool(verified)),
             ("claimed", "Registration claimed", bool(claimed)),
             ("photo", "Profile photo", bool(profile["photo_file"]))]
    flags = {key: on for key, _, on in steps}
    done = sum(1 for _, _, on in steps if on)
    return {"steps": [{"key": key, "label": label, "done": on}
                      for key, label, on in steps],
            "verified": flags["verified"],
            "claimed": flags["claimed"],
            "photo": flags["photo"],
            "done": done, "total": len(steps), "percent": done * 100 // 3,
            "complete": done == 3}


def _me(db, account):
    profile = sa.ensure_profile(db, account["id"])
    conv = reg.active_convocation(db)
    claimed = sa.claimed_registration(db, account["id"], conv["id"]) \
        if conv else None
    return {"account": {"email": account["university_email"],
                        "created_at": account["created_at"],
                        "last_login_at": account["last_login_at"]},
            "profile": _profile_payload(profile),
            "registration": _registration_payload(claimed) if claimed else None,
            "claimed_at": claimed["claimed_at"] if claimed else None,
            "completion": _completion(profile, claimed)}


def _session_body(db, account, token, expires):
    body = {"ok": True, "token": token, "expires_at": expires}
    body.update(_me(db, account))
    return body


@bp.errorhandler(sa.StudentError)
def _student_error(exc):
    return jsonify({"ok": False, "code": exc.code, "error": exc.message}), \
        exc.status


@bp.route("/verify", methods=["POST"])
def verify():
    if _limited("send", config.STUDENT_RATE_MAX_VERIFY):
        raise sa.StudentError(429, "rate_limited",
                              "Too many attempts from this device. Try "
                              "again in a minute.")
    fields = sa.require_fields(_json(), [
        ("registration_number", sa.norm_ident),
        ("university_email", sa.norm_email),
        ("roll_number", sa.norm_ident),
        ("student_name", sa.norm_name)])
    email = fields["university_email"]
    if not EMAIL_RE.match(email) or len(email) > sa.EMAIL_LIMIT:
        raise sa.StudentError(400, "email",
                              "Enter a valid university email address.")
    db = database.get_db()
    try:
        conv = reg.active_convocation(db)
        if conv is None:
            raise sa.StudentError(409, "no_convocation",
                                  "No active convocation is configured yet.")
        row = db.execute(
            "SELECT * FROM convocation_registrations WHERE convocation_id = ?"
            " AND registration_number = ? AND university_email = ?"
            " AND roll_number = ?",
            (conv["id"], fields["registration_number"], email,
             fields["roll_number"])).fetchone()
        if row is None or not sa.names_match(row["student_name"],
                                             fields["student_name"]):
            raise sa.StudentError(
                404, "unmatched",
                "No registration matches those details. Check every field "
                "against your official registration.")
        if row["status"] != "active":
            raise sa.StudentError(
                410, row["status"],
                "That registration is %s and cannot be claimed."
                % row["status"])
        account = sa.get_account(db, email)
        if account is not None and sa.claim_for(db, account["id"], conv["id"]):
            raise sa.StudentError(409, "claimed",
                                  "This registration is already linked to a "
                                  "student account. Sign in instead.")
        taken = db.execute(
            "SELECT 1 FROM registration_claims WHERE convocation_id = ?"
            " AND registration_id = ?", (conv["id"], row["id"])).fetchone()
        if taken:
            raise sa.StudentError(409, "claimed",
                                  "This registration is already linked to a "
                                  "student account. Sign in instead.")
        pending = sa.active_challenge(db, "signup", email)
        if pending is None:
            code = sa.new_code()
            _send_email(email, code)  # fails closed BEFORE any row exists
            challenge_id = sa.create_challenge(db, "signup", email, code,
                                               conv["id"], row["id"])
            pending = sa.get_challenge(db, challenge_id, "signup")
            was_pending = False
        else:
            challenge_id, was_pending = pending["id"], True
        db.commit()
        return jsonify({"ok": True, "challenge_id": challenge_id,
                        "masked_email": sa.mask_email(email),
                        "account_exists": account is not None,
                        "pending": was_pending,
                        "resend_remaining": max(
                            0, config.CODE_MAX_SENDS - pending["sent_count"]),
                        "expires_in": _expires_in(pending["expires_at"])})
    finally:
        db.close()


@bp.route("/resend", methods=["POST"])
def resend():
    if _limited("send", config.STUDENT_RATE_MAX_VERIFY):
        raise sa.StudentError(429, "rate_limited",
                              "Too many attempts from this device. Try "
                              "again in a minute.")
    challenge_id = _int_field(_json(), "challenge_id")
    db = database.get_db()
    try:
        row = sa.get_challenge(db, challenge_id, "signup")
        if row["consumed_at"]:
            raise sa.StudentError(410, "challenge",
                                  "That verification code has already been "
                                  "used.")
        if row["sent_count"] >= config.CODE_MAX_SENDS:
            raise sa.StudentError(429, "send_limit",
                                  "This code has reached its resend limit. "
                                  "Start the sign-up again.")
        code = sa.new_code()
        _send_email(row["university_email"], code)
        sa.resend_challenge(db, row, code)
        refreshed = sa.get_challenge(db, row["id"], "signup")
        db.commit()
        return jsonify({"ok": True, "challenge_id": row["id"],
                        "resend_remaining": max(
                            0, config.CODE_MAX_SENDS - refreshed["sent_count"]),
                        "expires_in": _expires_in(refreshed["expires_at"])})
    finally:
        db.close()


@bp.route("/complete", methods=["POST"])
def complete():
    # Code entry is guessable, so it carries its own per-IP budget on top
    # of the per-challenge attempt cap (a wrong code can only consume the
    # challenge, this bounds how fast a new challenge can be requested).
    if _limited("confirm", config.STUDENT_RATE_MAX_CONFIRM):
        raise sa.StudentError(429, "rate_limited",
                              "Too many attempts from this device. Try "
                              "again in a minute.")
    payload = _json()
    challenge_id = _int_field(payload, "challenge_id")
    code = (payload.get("code") or "").strip()
    if not code:
        raise sa.StudentError(400, "missing_field", "code is required.")
    password = payload.get("password") or ""
    db = database.get_db()
    try:
        row = sa.get_challenge(db, challenge_id, "signup")
        account = sa.get_account(db, row["university_email"])
        if account is None:
            # a brand-new account must be secured BEFORE the code is consumed
            if not password:
                raise sa.StudentError(
                    400, "password",
                    "Create a password (at least 12 characters) to finish.")
            error = validate_password(password)
            if error:
                raise sa.StudentError(400, "password", error)
        sa.verify_challenge(db, row, code)  # single use — consumes
        if account is None:
            account_id = sa.create_account(db, row["university_email"],
                                           password)
        else:
            account_id = account["id"]
        sa.claim_registration(db, account_id, row["convocation_id"],
                              row["registration_id"])
        sa.ensure_profile(db, account_id)
        db.execute("UPDATE student_accounts SET last_login_at = ?,"
                   " updated_at = ? WHERE id = ?",
                   (sa.utc_now(), sa.utc_now(), account_id))
        sa.audit(db, "student:%s" % row["university_email"],
                 "registration_claimed",
                 "convocation=%s registration=%s"
                 % (row["convocation_id"], row["registration_id"]))
        token, expires = sa.issue_session(db, account_id)
        db.commit()
        account = sa.get_account(db, row["university_email"])
        return jsonify(_session_body(db, account, token, expires))
    finally:
        db.close()


@bp.route("/login", methods=["POST"])
def login():
    if _limited("login", config.STUDENT_RATE_MAX_LOGIN):
        raise sa.StudentError(429, "rate_limited",
                              "Too many attempts from this device. Try "
                              "again in a minute.")
    payload = _json()
    email = sa.norm_email(payload.get("email", ""))
    if not email:
        raise sa.StudentError(400, "missing_field", "email is required.")
    db = database.get_db()
    try:
        account = sa.login(db, email, payload.get("password") or "")
        token, expires = sa.issue_session(db, account["id"])
        db.commit()
        return jsonify(_session_body(db, account, token, expires))
    finally:
        db.close()


@bp.route("/logout", methods=["POST"])
def logout():
    token = _bearer()
    if token:
        db = database.get_db()
        try:
            sa.revoke_token(db, token)
            db.commit()
        finally:
            db.close()
    return jsonify({"ok": True})


@bp.route("/me")
def me():
    db = database.get_db()
    try:
        account = current_account(db)
        return jsonify({"ok": True, **_me(db, account)})
    finally:
        db.close()


@bp.route("/profile", methods=["POST"])
def profile():
    db = database.get_db()
    try:
        account = current_account(db)
        payload = _json()
        if "phone" not in payload:
            raise sa.StudentError(400, "missing_field", "phone is required.")
        phone = " ".join(str(payload["phone"]).split())
        if len(phone) > sa.PHONE_LIMIT:
            raise sa.StudentError(400, "profile",
                                  "The phone number must be %d characters "
                                  "or fewer." % sa.PHONE_LIMIT)
        # Ensure the row exists BEFORE the UPDATE — otherwise the student's
        # number is silently discarded while the route still answers 200.
        sa.ensure_profile(db, account["id"])
        db.execute("UPDATE student_profiles SET phone = ?, updated_at = ?"
                   " WHERE account_id = ?", (phone, sa.utc_now(),
                                             account["id"]))
        db.commit()
        row = sa.ensure_profile(db, account["id"])
        conv = reg.active_convocation(db)
        claimed = sa.claimed_registration(db, account["id"], conv["id"]) \
            if conv else None
        return jsonify({"ok": True, "profile": _profile_payload(row),
                        "completion": _completion(row, claimed)})
    finally:
        db.close()


@bp.route("/profile/photo", methods=["POST"])
def upload_photo():
    db = database.get_db()
    try:
        account = current_account(db)
        data = str(_json().get("data") or "")
        if not data:
            raise sa.StudentError(400, "missing_field", "data is required.")
        try:
            raw = base64.b64decode(data, validate=True)
        except Exception:
            raise sa.StudentError(400, "photo",
                                  "The photo could not be read. Choose a "
                                  "JPEG, PNG, or WebP image.")
        row = sa.store_photo(db, account["id"], raw)
        db.commit()
        conv = reg.active_convocation(db)
        claimed = sa.claimed_registration(db, account["id"], conv["id"]) \
            if conv else None
        return jsonify({"ok": True, "profile": _profile_payload(row),
                        "completion": _completion(row, claimed)})
    finally:
        db.close()


@bp.route("/profile/photo", methods=["GET"])
def download_photo():
    db = database.get_db()
    try:
        account = current_account(db)
        data, mime = sa.read_photo(db, account["id"])
    finally:
        db.close()
    response = Response(data, content_type=mime)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.route("/recovery/request", methods=["POST"])
def recovery_request():
    # Fail closed BEFORE any lookup: an unconfigured provider must never
    # reveal whether an address has an account.
    if not emailer.available():
        raise sa.StudentError(503, "email_unavailable",
                              "Password recovery is not configured on this "
                              "server. Contact the Examination Department.")
    if _limited("recovery", config.STUDENT_RATE_MAX_RECOVERY):
        raise sa.StudentError(429, "rate_limited",
                              "Too many recovery requests. Try again in a "
                              "few minutes.")
    email = sa.norm_email(_json().get("email", ""))
    if not EMAIL_RE.match(email) or len(email) > sa.EMAIL_LIMIT:
        raise sa.StudentError(400, "email",
                              "Enter a valid university email address.")
    db = database.get_db()
    try:
        account = sa.get_account(db, email)
        if account is not None:
            pending = sa.active_challenge(db, "recovery", email)
            if pending is None:
                code = sa.new_code()
                _send_email(email, code)
                sa.create_challenge(db, "recovery", email, code)
            elif pending["sent_count"] < config.CODE_MAX_SENDS:
                code = sa.new_code()
                _send_email(email, code)
                sa.resend_challenge(db, pending, code)
            db.commit()
        # unknown email: nothing is sent, same 200 — no enumeration
    finally:
        db.close()
    return jsonify({"ok": True,
                    "message": "If that email has an account, a recovery "
                               "code is on its way."})


@bp.route("/recovery/complete", methods=["POST"])
def recovery_complete():
    if _limited("confirm", config.STUDENT_RATE_MAX_CONFIRM):
        raise sa.StudentError(429, "rate_limited",
                              "Too many attempts from this device. Try "
                              "again in a minute.")
    payload = _json()
    code = (payload.get("code") or "").strip()
    password = payload.get("password") or ""
    if not code:
        raise sa.StudentError(400, "missing_field", "code is required.")
    if not password:
        raise sa.StudentError(400, "missing_field", "password is required.")
    db = database.get_db()
    try:
        # Clients may address the step by id (test/tools) or by email —
        # /recovery/request never exposes ids, so no account oracle.
        if "challenge_id" in payload:
            row = sa.get_challenge(db, _int_field(payload, "challenge_id"),
                                   "recovery")
        else:
            email = sa.norm_email(payload.get("email", ""))
            if not email:
                raise sa.StudentError(400, "missing_field",
                                      "email is required.")
            row = sa.active_challenge(db, "recovery", email)
            if row is None:
                raise sa.StudentError(404, "challenge",
                                      "This recovery step no longer exists.")
        account = sa.get_account(db, row["university_email"])
        if account is None:
            raise sa.StudentError(404, "challenge",
                                  "This recovery step no longer exists.")
        error = validate_password(password)
        if error:  # validate BEFORE consuming the single-use code
            raise sa.StudentError(400, "password", error)
        sa.verify_challenge(db, row, code)
        sa.set_password(db, account["id"], password)
        sa.revoke_all_sessions(db, account["id"])
        sa.audit(db, "student:%s" % account["university_email"],
                 "password_reset", "all sessions revoked")
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


# ------------------------------------------------------------ Phase 6 board

@bp.route("/medalists")
def medalist_board():
    """Public medalist board for the active convocation.

    Published records only; the payload comes from med.public_payload so
    private fields (reference numbers, publication state, timestamps) can
    never leak. No student session is required - this is public display data.
    """
    department = request.args.get("department", "").strip()[:120]
    category = request.args.get("category", "").strip()[:60]
    db = database.get_db()
    try:
        conv = reg.active_convocation(db)
        if conv is None:
            return jsonify({"convocation": None, "total": 0,
                            "departments": [], "categories": [],
                            "medalists": []})
        items = med.public_payload(db, conv["id"])
        if department:
            items = [m for m in items
                     if m["department"].lower() == department.lower()]
        if category:
            items = [m for m in items
                     if m["award_category"].lower() == category.lower()]
        return jsonify({
            "convocation": {"name": conv["name"], "year": conv["year"]},
            "total": len(items),
            "departments": med.list_departments(db, conv["id"], True),
            "categories": med.list_categories(db, conv["id"], True),
            "medalists": items})
    finally:
        db.close()


@bp.route("/medalists/photo/<int:medalist_id>")
def medalist_photo(medalist_id):
    """Controlled public image route. Published records only - drafts and
    missing files answer the same 404 so nothing leaks existence."""
    db = database.get_db()
    try:
        try:
            data, mime = med.read_photo(db, medalist_id)
        except med.MedalistError:
            return jsonify({"ok": False,
                            "error": "No published picture exists."}), 404
        response = Response(data, mimetype=mime)
        response.headers["Cache-Control"] = "public, max-age=300"
        return response
    finally:
        db.close()


# ------------------------------------------- Phase 7 event info + feed

@bp.route("/event")
def event_info():
    """Published event information for the active convocation.

    Public and read-only, same rule as the medalist board: the payload
    comes only from the publication snapshot (ev.student_payload), so
    working drafts and unpublished changes can never appear here. Never
    announced, expected (provisional) and confirmed dates stay distinct
    via date_state.
    """
    db = database.get_db()
    try:
        return jsonify(ev.student_payload(db))
    finally:
        db.close()


@bp.route("/announcements")
def announcements_feed():
    """Official announcements feed for the active convocation.

    Published rows with the students audience only (ann.feed is the sole
    query behind this route); drafts, staff-only and archived rows never
    leave the exam portal. Announcements publish independently of the
    event-information snapshot, so the active convocation label comes
    from reg.active_convocation (same rule as the medalist board).
    Phase 33: each row carries its audience verbatim so the student app
    can state who an announcement was addressed to; the feed query
    already guarantees it is 'students'.
    """
    db = database.get_db()
    try:
        conv = reg.active_convocation(db)
        rows = ann.feed(db, conv["id"]) if conv else []
        return jsonify({
            "convocation": ({"name": conv["name"], "year": conv["year"]}
                            if conv else None),
            "total": len(rows),
            "announcements": [
                {"id": r["id"], "title": r["title"], "body": r["body"],
                 "audience": r["audience"],
                 "is_important": bool(r["is_important"]),
                 "created_at": r["created_at"],
                 "updated_at": r["updated_at"],
                 "published_at": r["published_at"]} for r in rows]})
    finally:
        db.close()


# -------------------------------------------------- Phase 9: student support

def _support_payload(row, latest=None):
    """One request as the owning student sees it. Staff-only audit rows are
    never included — the status, subject, message and any student-visible
    staff response are the whole surface."""
    return {
        "id": row["id"],
        "reference": row["reference"],
        "category": row["category"],
        "category_label": sup.CATEGORY_LABELS.get(row["category"],
                                                  row["category"]),
        "subject": row["subject"],
        "message": row["message"],
        "status": row["status"],
        "status_label": sup.STATUS_LABELS.get(row["status"], row["status"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "resolved_at": row["resolved_at"],
        "latest_response": (
            {"body": latest["body"], "at": latest["created_at"]}
            if latest else None),
    }


def _support_detail(row, events, latest):
    out = _support_payload(row, latest)
    out["history"] = [
        {"action": e["action"], "actor_role": e["actor_role"],
         "body": e["body"], "at": e["created_at"],
         "before_status": e["before_status"], "after_status": e["after_status"]}
        for e in events]
    return out


def _active_conv_or_none(db):
    return reg.active_convocation(db)


@bp.route("/support", methods=["POST"])
def support_create():
    """Open a new support request owned by the signed-in account.

    Bound to the active convocation and the account's claimed registration
    (when one exists) so staff can open the official record. Never mutates
    the registration itself.
    """
    payload = _json()
    db = database.get_db()
    try:
        account = current_account(db)
        if _limited("support", config.SUPPORT_RATE_MAX_CREATE):
            raise sa.StudentError(
                429, "rate_limited",
                "Too many support requests. Please wait a few minutes.")
        conv = _active_conv_or_none(db)
        if conv is None:
            raise sa.StudentError(409, "no_convocation",
                                  "No active convocation is configured.")
        claim = sa.claimed_registration(db, account["id"], conv["id"])
        if sup.open_count(db, account["id"], conv["id"]) >= \
                config.SUPPORT_MAX_OPEN:
            raise sa.StudentError(
                429, "too_many_open",
                "You already have %d open requests. Please wait for a "
                "response before opening more." % config.SUPPORT_MAX_OPEN)
        try:
            data = sup.validate_form(payload)
        except sup.SupportError as exc:
            raise sa.StudentError(400, "validation", str(exc))
        try:
            row = sup.create(db, conv["id"], account["id"],
                             claim["id"] if claim else None, data)
        except sup.SupportError as exc:
            raise sa.StudentError(400, "validation", str(exc))
        latest = sup.latest_response(db, row["id"])
        return jsonify({"ok": True, "request": _support_payload(row, latest)})
    finally:
        db.close()


@bp.route("/support")
def support_list():
    """Every request owned by the signed-in account, newest first."""
    db = database.get_db()
    try:
        account = current_account(db)
        conv = _active_conv_or_none(db)
        if conv is None:
            return jsonify({"convocation": None, "total": 0, "requests": []})
        rows = sup.list_for_account(db, account["id"], conv["id"])
        return jsonify({
            "convocation": {"name": conv["name"], "year": conv["year"]},
            "total": len(rows),
            "requests": [_support_payload(r, r["latest_response"])
                         for r in rows]})
    finally:
        db.close()


@bp.route("/support/<int:request_id>")
def support_detail(request_id):
    """One owned request with its student-visible history.

    A request owned by another account is indistinguishable from a missing
    one (404) so ids can never be probed across students.
    """
    db = database.get_db()
    try:
        account = current_account(db)
        row = sup.get(db, request_id)
        if row is None or row["account_id"] != account["id"]:
            raise sa.StudentError(404, "not_found",
                                  "This request could not be found.")
        events = sup.history(db, request_id, include_internal=False)
        return jsonify({"ok": True,
                        "request": _support_detail(
                            row, events, sup.latest_response(db, request_id))})
    finally:
        db.close()


# ------------------------------------------------- Phase 10: readiness centre

@bp.route("/readiness")
def readiness():
    """The signed-in student's personalized readiness checklist + reminders.

    Computed server-side from authoritative records (registration, profile,
    published event, announcements, support requests). Scoped to this account
    only; nothing another student holds can appear here. Read-only — the
    checklist reflects backend state, never a local acknowledgement.
    """
    db = database.get_db()
    try:
        account = current_account(db)
        return jsonify({"ok": True,
                        "readiness": rd.readiness_for(db, account)})
    finally:
        db.close()


@bp.route("/attendance")
def attendance():
    """Aggregate event attendance for the signed-in student (Phase 38).

    Read-only COUNTS with the dashboard's population semantics — registered
    (roster rows), verified (people currently inside), remaining and
    percentage against the admin target. Nothing administrative crosses
    this boundary: no names, gates, feed, throughput, gender split,
    rejection detail or broadcast audience ever appears in a student-facing
    payload. Any valid student token may read it; anonymous is 401.
    """
    db = database.get_db()
    try:
        current_account(db)  # 401 for anonymous, expired or invalid tokens
        return jsonify({"ok": True,
                        "attendance": models.student_attendance()})
    finally:
        db.close()


@bp.route("/readiness/reminders", methods=["POST"])
def readiness_reminder():
    """Mark one of this student's reminders read or dismissed.

    The key is re-validated against the freshly derived reminder set, so a
    client can only act on a reminder it actually holds — and only an
    informational (dismissible) one can be dismissed. A required reminder
    (registration issue, staff awaiting information) is never removable, so
    a dismissal can never hide an unresolved problem or erase official data.
    """
    if _limited("readiness", config.READINESS_RATE_MAX_MARK):
        raise sa.StudentError(429, "rate_limited",
                              "Too many updates. Try again in a minute.")
    # Authenticate before touching the payload: an anonymous caller must be
    # told to sign in (401), never a payload-validation error that reveals
    # this route exists and how it is shaped.
    db = database.get_db()
    try:
        account = current_account(db)
        payload = _json()
        key = (payload.get("key") or "").strip()
        action = (payload.get("action") or "").strip()
        if not key:
            raise sa.StudentError(400, "validation",
                                  "A reminder key is required.")
        try:
            state = rd.mark_reminder(db, account, key, action)
        except ValueError as exc:
            raise sa.StudentError(400, "validation", str(exc))
        return jsonify({"ok": True, "key": key, "state": state})
    finally:
        db.close()


# -------------------------------------------- Phase 11: pass + history

@bp.route("/pass")
def student_pass():
    """The signed-in student's digital convocation invitation.

    Read-only, backend-computed from the claimed registration, its status,
    open support requests and the published event. No QR is ever issued:
    convocation registrations are not linked to the operational check-in
    roster, so a pass QR would not validate at the gate (§2 blocker,
    reported via qr_blocker). The client cannot grant eligibility — state
    is derived here on every request.
    """
    db = database.get_db()
    try:
        account = current_account(db)
        conv = reg.active_convocation(db)
        return jsonify({"ok": True, "pass": cp.pass_for_account(db, account, conv)})
    finally:
        db.close()


@bp.route("/history")
def student_history():
    """The signed-in student's convocation history.

    Read-only ledger of every convocation this account's verified official
    records (registration_claims) touch, newest first, with published event
    details and published honours. Scoped to this account only; another
    student's registrations can never appear here.
    """
    db = database.get_db()
    try:
        account = current_account(db)
        conv = reg.active_convocation(db)
        entries = hist.history_for_account(
            db, account, conv["id"] if conv else None)
        return jsonify({"ok": True, "total": len(entries), "history": entries})
    finally:
        db.close()


@bp.route("/pass/issue", methods=["POST"])
def student_pass_issue():
    """Issue (or reissue) the signed-in student's convocation entry QR (Phase 12).

    Separate from the read-only GET /pass invitation: this is the only
    endpoint that mints a bearer token. Eligibility is recomputed from
    authoritative records on every call; reissue revokes the previous token so
    a lost or replaced QR stops validating at the gate. The QR carries no
    personal data — only a high-entropy token the gate verifies server-side.
    The client cannot grant eligibility or pick a registration.
    """
    if _limited("passissue", config.PASS_ISSUE_RATE_MAX):
        raise sa.StudentError(429, "rate_limited",
                              "Too many pass requests. Try again in a minute.")
    db = database.get_db()
    try:
        account = current_account(db)
        conv = reg.active_convocation(db)
        try:
            issued = cqr.issue_pass(db, account, conv)
        except cqr.PassError as exc:
            raise sa.StudentError(exc.status, exc.code, exc.message)
        return jsonify({"ok": True, "pass": issued})
    finally:
        db.close()
