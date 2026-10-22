"""All HTTP routes: pages, scanner API, dashboard API, admin, guests, broadcast."""

import csv
import hmac
import io
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.parse
from datetime import datetime

from flask import (Blueprint, Flask, Response, jsonify, redirect,
                   render_template, request, session, url_for)

import config
import convocation_qr as convqr
import database
import ids
import models
import qrgen
import scanner_auth

bp = Blueprint("main", __name__)

# --- Master audit: scan atomicity (V-RACE-01/02/03) -----------------------
# The person-state check and the scan insert must be atomic per process:
# concurrent scans of the same person must not both pass the "already
# inside / already used" check before either insert lands. RLock because
# api_sync holds the same lock around queued-check + process_scan.
_SCAN_LOCK = threading.RLock()

# --- Master audit: PIN attempt rate limiting (V-AUTH-01/02) ---------------
# In-memory per client IP. 5 wrong attempts per 60 s → 429 (tunable via
# LGU_PIN_MAX_FAILS / LGU_PIN_WINDOW for isolated test backends).
_PIN_FAILS = {}
_PIN_FAILS_LOCK = threading.Lock()

# --- Master audit: input length caps (V-INP-01..04) ----------------------
_SETTING_LEN_CAPS = {"convocation_name": 120, "university_name": 120,
                     "venue": 120}
_NAME_CAP = 120
_PHONE_CAP = 32
_ROLL_CAP = 32
_VOLUNTEER_CAP = 64
_AUDIENCE_CAP = 64

# Origins allowed for cross-browser reads (CORS allowlist, V-CORS-01).
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _client_ip():
    return request.remote_addr or "unknown"


def _pin_rate_limited():
    now = time.time()
    window = config.PIN_RATE_WINDOW_SECONDS
    ip = _client_ip()
    with _PIN_FAILS_LOCK:
        fails = [t for t in _PIN_FAILS.get(ip, []) if now - t < window]
        _PIN_FAILS[ip] = fails
        return len(fails) >= config.PIN_RATE_MAX_FAILS


def _pin_record_failure():
    with _PIN_FAILS_LOCK:
        _PIN_FAILS.setdefault(_client_ip(), []).append(time.time())


# --- Phase 14: scanner login rate limiting (per client IP) ----------------
# A dedicated bucket so scanner logins never throttle the admin PIN limiter
# (or vice versa). Repeats the _PIN_FAILS pattern with its own config knobs;
# this runs alongside the per-account lockout enforced in scanner_auth.
_SCAN_LOGIN_FAILS = {}
_SCAN_LOGIN_FAILS_LOCK = threading.Lock()


def _scan_login_rate_limited():
    now = time.time()
    window = config.SCANNER_RATE_WINDOW_SECONDS
    ip = _client_ip()
    with _SCAN_LOGIN_FAILS_LOCK:
        fails = [t for t in _SCAN_LOGIN_FAILS.get(ip, []) if now - t < window]
        _SCAN_LOGIN_FAILS[ip] = fails
        return len(fails) >= config.SCANNER_RATE_MAX_FAILS


def _scan_login_record_failure():
    with _SCAN_LOGIN_FAILS_LOCK:
        _SCAN_LOGIN_FAILS.setdefault(_client_ip(), []).append(time.time())


def _origin_allowed(origin, request_host):
    """CORS allowlist: same host, loopback dev origins, or the LAN host
    this server is reached through. Native mobile fetch sends no Origin
    and is unaffected."""
    try:
        host = urllib.parse.urlsplit(origin or "").netloc.lower()
    except ValueError:
        return False
    if not host:
        return False
    hostname = host.rsplit("@", 1)[-1]
    if hostname.startswith("["):
        hostname = hostname[1:hostname.find("]")] if "]" in hostname else hostname
    else:
        hostname = hostname.split(":")[0]
    req = (request_host or "").lower()
    if host == req:
        return True
    if hostname in _LOOPBACK_HOSTS:
        return True
    req_hostname = req.split(":")[0]
    return hostname == req_hostname


def _test_tool_guard():
    """Expose dangerous QA endpoints only in explicitly isolated test runs.

    A database stored on a cloud volume or a custom LGU_DB_PATH is not
    automatically a *test* database. Never mint scanner sessions, disclose
    signed test passes, or reset attendance solely based on its filename.
    """
    if (
        os.environ.get("LGU_TESTING") != "1"
        or os.environ.get("LGU_APP_ENV", "").strip().lower() == "production"
        or config.is_production_db()
    ):
        return jsonify({"ok": False, "error": "Not found."}), 404
    return None


def _require_web_admin():
    """PIN-gate the browser admin surfaces (master audit V-AUTH-03/04).

    Unlock is per browser session (Flask session cookie). Wrong PINs share
    the per-IP rate limiter with the JSON API."""
    if session.get("lgu_admin") is True:
        return None
    if _pin_rate_limited():
        return (render_template("unlock.html", next_url=request.path,
                                error="Too many attempts. Try again in a minute."),
                429)
    pin = (request.form.get("admin_pin") or "").strip()
    error = None
    if pin:
        if _pin_ok(pin):
            session["lgu_admin"] = True
            return None
        _pin_record_failure()
        error = "Incorrect administrator PIN. Try again."
    return (render_template("unlock.html", next_url=request.path,
                            error=error), 401)


def _gates():
    return models.gates()


# --- Phase 14: scanner authorization --------------------------------------
def _scanner_token():
    return (request.headers.get("X-Scanner-Token") or "").strip()


def _require_scanner():
    """Resolve the X-Scanner-Token bearer to an authenticated scanner session.

    Returns the scanner dict {id, username, display_name, gates} on success,
    or an (response, status) error tuple the caller must return. Both LGU1 and
    LGU2 admissions route through this — there is no unauthenticated path to
    process_scan. The gates list is read server-side from scanner_gates, never
    from client request data."""
    token = _scanner_token()
    info = scanner_auth.resolve_session(token) if token else None
    if not info:
        return (jsonify({"ok": False, "code": "scanner_auth_required",
                         "error": "Scanner sign-in required."}), 401)
    return info


def _guest_print_allowed(gid):
    """Authorise viewing ONE guest's pass artefact (Phase 27 C3).

    The signed pass payload is a bearer credential, so an enumerable integer
    ``gid`` alone must never mint one. Accepted, in order:

    * a guest print capability — minted at self-registration and carried in
      the signed session cookie (browser) or the ``X-Print-Token`` header
      (API). It never appears in a URL, so it cannot reach an access log,
      and it is bound to this guest id + purpose + expiry, so it cannot be
      replayed for another guest or fabricated by editing the id;
    * the staff portal session, so authorised operators keep reprinting;
    * a live scanner session, so the volunteer desk keeps printing.

    The capability deliberately grants no directory or admin access."""
    if ids.verify_print_token(session.get("guest_print", ""), gid):
        return True
    if ids.verify_print_token(request.headers.get("X-Print-Token", ""), gid):
        return True
    if session.get("lgu_admin") is True:
        return True
    return isinstance(_require_scanner(), dict)


def _coerce_gate(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_occasion(value):
    """The occasion this scan records, or None when the request is invalid.

    Absent/empty means the main convocation — every scanner build before
    Phase 29 sent nothing, and a legacy queued record must replay as the
    single occasion that existed then. Anything else must be a known
    occasion; a made-up value is never silently accepted."""
    if value is None or value == "":
        return convqr.DEFAULT_OCCASION
    if isinstance(value, str) and value in convqr.OCCASIONS:
        return value
    return None


# Client clocks send "%Y-%m-%d %H:%M:%S" (mobile localTimestamp), the same
# value with a "," separator (Intl en-CA), or ISO-8601 with a "T".
_SCANNED_AT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})([ ,T]) ?(\d{2}:\d{2}:\d{2})$")


def _valid_scanned_at(value):
    """Canonical timestamp for the scans table, or None to use server time.

    A malformed client timestamp must never be stored: the dashboard windows
    compare scanned_at as TEXT, so junk like "zzz" sorts after every real date
    and would count in every window forever. The "," separator some Intl
    locales emit is normalised to " " so it sorts the same way as rows written
    by the server clock; a "T" separator is kept as sent (it never mis-sorts
    against a different date, and feeds slice the time out of the raw string).
    """
    if not isinstance(value, str) or not value or len(value) > 32:
        return None
    m = _SCANNED_AT_RE.match(value.strip())
    if m is None:
        return None
    try:
        datetime.strptime("%s %s" % (m.group(1), m.group(3)),
                           "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return "%s%s%s" % (m.group(1), " " if m.group(2) in ", " else m.group(2),
                       m.group(3))


def _normalise_gender(value):
    """Accept M/F, male/female, any case; return Male/Female or the raw value."""
    v = (value or "").strip().lower()
    if v in ("m", "male", "boy", "men"):
        return "Male"
    if v in ("f", "female", "girl", "women"):
        return "Female"
    return (value or "").strip()


def _parse_roster(rows):
    """Parse roster CSV rows into (roll_no, name, gender, program) tuples.

    If the first row is a header, columns are mapped by name so any column
    order works; otherwise roll_no, name, gender, program order is assumed.
    Returns (parsed_rows, error_message_or_None).
    """
    if not rows:
        return [], None
    header_map = {
        "roll_no": "roll_no", "roll no": "roll_no", "rollno": "roll_no",
        "rollnumber": "roll_no", "roll number": "roll_no",
        "name": "name", "student name": "name", "fullname": "name",
        "full name": "name",
        "gender": "gender", "sex": "gender",
        "program": "program", "programme": "program", "degree": "program",
    }
    first = [c.strip().lower() for c in rows[0]]
    if any(c in header_map for c in first):
        idx = {}
        for i, c in enumerate(first):
            key = header_map.get(c)
            if key and key not in idx:
                idx[key] = i
        missing = [k for k in ("roll_no", "name", "gender", "program") if k not in idx]
        if missing:
            return [], ("Roster header is missing columns: %s. Expected "
                        "roll_no, name, gender, program." % ", ".join(missing))
        data = rows[1:]
        parsed = [
            (r[idx["roll_no"]].strip(), r[idx["name"]].strip(),
             _normalise_gender(r[idx["gender"]]), r[idx["program"]].strip())
            for r in data if len(r) > max(idx.values())
        ]
        return parsed, None
    parsed = [
        (r[0].strip(), r[1].strip(), _normalise_gender(r[2]), r[3].strip())
        for r in rows if len(r) >= 4
    ]
    return parsed, None


# ---------------------------------------------------------------- home
@bp.route("/")
def index():
    return render_template("index.html", gates=_gates())


# ---------------------------------------------------------------- dashboard
@bp.route("/dashboard")
def dashboard():
    # Phase 35K (J): the template's "last N minutes" label and stale check
    # consume the same server value as the backend queries — one source.
    return render_template("dashboard.html", gates=_gates(),
                           window_minutes=config.GATE_ACTIVITY_WINDOW_MINUTES)


@bp.route("/api/dashboard")
def api_dashboard():
    return _scoped_dashboard(models.dashboard)


@bp.route("/api/dashboard/summary")
def api_dashboard_summary():
    """Lightweight KPI summary: roster counts, admin target, live counts."""
    return _scoped_dashboard(models.dashboard_summary)


def _scoped_dashboard(build):
    """Phase 38 event-specific filtering: ?occasion= appends the validated
    echo plus that occasion's scoped admission count. Without the param the
    payload is untouched; a bad value is a 400, never a silent pass."""
    payload = build()
    occasion = (request.args.get("occasion") or "").strip()
    if not occasion:
        return jsonify(payload), 200
    if occasion not in convqr.OCCASIONS:
        return jsonify({"ok": False,
                        "error": "occasion must be one of %s."
                                 % ", ".join(convqr.OCCASIONS)}), 400
    payload["occasion_filter"] = occasion
    payload["occasion_admitted"] = payload["admissions_by_occasion"][occasion]
    return jsonify(payload), 200


# ---------------------------------------------------------------- config
# Phase 35K (F/J/K/G): authoritative runtime configuration for the mobile
# app — event identity, population counts, gate list and shared limits.
@bp.route("/api/config")
def api_config():
    return jsonify(models.app_config_payload())


# ---------------------------------------------------------------- settings
# Event-level settings (convocation name/year/datetime/venue/university),
# editable via the mobile Admin screen. Administrator PIN required (35K T):
# these values drive event-wide display and progress denominators.
#
# Phase 28: the READ side now carries the same gate as the write side.
# PUT accepts any key in database.SETTING_KEYS, so an ungated GET served
# every one of them to an anonymous caller — including any operational key
# added later, which would have become public the moment it was written.
# This is NOT about a secret in the current payload (name/year/datetime/
# venue/university and the attendance target are already published at
# GET /api/config, which stays public for the kiosk, the landing page and
# mobile connectivity discovery). It is about the resource's contract:
# reading an administrator's settings is an administrator's action, and the
# least-privilege default for a key nobody has classified yet is "protected".


def _pin_ok(candidate):
    """Constant-time ADMIN_PIN comparison (Phase 37 SEC-002).

    utf-8 bytes keep hmac.compare_digest total for any attacker-supplied
    string (the C implementation rejects non-ASCII str). PIN length is not
    secret; byte equality must not leak through short-circuit timing."""
    return hmac.compare_digest(str(candidate or "").strip().encode("utf-8"),
                               str(config.ADMIN_PIN).encode("utf-8"))


def _require_admin_pin(denied_message="Administrator access required."):
    """Shared PIN gate for administrator mutations (Phase 35K T).

    Master audit V-AUTH-01/02: wrong attempts are rate limited per client
    IP (config.PIN_RATE_MAX_FAILS per window → 429). The mobile client
    lockout remains UX-only; this is the server-side enforcement.
    Phase 37 BE-001: EVERY admin mutation routes through this gate — the
    broadcast composer included — so the comparison and the limiter can no
    longer drift apart. Callers may pass their own denial text because
    response wording is pinned by source regression tests."""
    if _pin_rate_limited():
        return jsonify({"ok": False,
                        "error": "Too many attempts. Try again in a minute."}), 429
    if not _pin_ok(request.headers.get("X-Admin-Pin")):
        _pin_record_failure()
        return jsonify({"ok": False,
                        "error": denied_message}), 401
    return None


@bp.route("/api/settings")
def api_get_settings():
    """Administrator settings read (Phase 28).

    Same gate as the write, so the two halves of one resource cannot drift
    apart again. The mobile Admin screen sits behind AdminGate, which has
    already verified the PIN against /api/admin/verify before it mounts, so
    it attaches the stored PIN to this read exactly as it does to the PUT.
    """
    denied = _require_admin_pin()
    if denied:
        return denied
    return jsonify(database.get_settings())


@bp.route("/api/settings", methods=["PUT"])
def api_put_settings():
    denied = _require_admin_pin()
    if denied:
        return denied
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad_scan_request("Expected a valid JSON object.")
    updates = {}
    for key, value in data.items():
        if key not in database.SETTING_KEYS:
            return jsonify({"ok": False,
                            "error": "Unknown setting: %s" % key}), 400
        if key == "convocation_year" and type(value) is int:
            value = str(value)
        if not isinstance(value, str):
            return _bad_scan_request("%s must be text." % key)
        updates[key] = value
    # Master audit V-INP-01: bounded text fields.
    for key, cap in _SETTING_LEN_CAPS.items():
        if key in updates:
            if not isinstance(updates[key], str):
                return jsonify({"ok": False, "error": "%s must be text." % key}), 400
            updates[key] = updates[key].strip()
            if len(updates[key]) > cap:
                return jsonify({"ok": False, "error":
                                "%s must be at most %d characters." % (key, cap)}), 400
    if "convocation_datetime" in updates:
        try:
            datetime.fromisoformat(updates["convocation_datetime"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error":
                            "convocation_datetime must be a valid ISO 8601 datetime."}), 400
    if "convocation_year" in updates:
        year = str(updates["convocation_year"])
        if not (year.isdigit() and len(year) == 4):
            return jsonify({"ok": False, "error":
                            "convocation_year must be 4 digits."}), 400
        updates["convocation_year"] = year
    if "expected_attendance" in updates:
        # Administrator-configured target headcount. Stored as a plain string
        # like the other settings; 0 means unset — dashboards then show an
        # explicit "not set" state (the roster never substitutes, 35K B).
        try:
            expected = int(str(updates["expected_attendance"]).strip())
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error":
                            "expected_attendance must be a whole number."}), 400
        # 33-QA (I24): realistic cap — a university convocation does not
        # expect a million attendees; values beyond convocation scale are
        # rejected instead of silently accepted.
        if expected < 0 or expected > 25_000:
            return jsonify({"ok": False, "error":
                            "expected_attendance must be between 0 and 25000."}), 400
        updates["expected_attendance"] = str(expected)
    database.update_settings(updates)
    return jsonify(database.get_settings())


# ---------------------------------------------------------------- scanner
@bp.route("/scan")
def scan_page():
    return render_template("scanner.html", gates=_gates())


def _transient_busy_response():
    """503 + Retry-After: contention exhausted the wait budget, retry the scan.

    Truthful by construction: no admission was recorded, the pass was not
    consumed, and no verdict whatever was reached on the QR. It is NOT a
    success and NOT an invalid/revoked/unauthorized answer — those are
    permanent outcomes the client must act on, whereas this one is resolved
    by simply scanning again.
    """
    resp = jsonify({"status": database.BUSY_STATUS, "level": "amber",
                    "title": "TEMPORARILY BUSY",
                    "detail": "The system is busy right now. Please retry"
                              " this scan.",
                    "retryable": True})
    resp.status_code = 503
    resp.headers["Retry-After"] = str(database.BUSY_RETRY_AFTER)
    return resp


def process_scan(payload, gate_id, mode, volunteer, scanned_at=None,
                 source="online", occasion=convqr.DEFAULT_OCCASION):
    """Core scan logic. Returns a dict describing the outcome for the UI.

    Legacy roster codes (LGU1) retain the process-wide _SCAN_LOCK to avoid
    unnecessary in-process write contention. The authoritative state check
    and INSERT in models.record_scan also use BEGIN IMMEDIATE, protecting
    admissions across multiple processes (PR #7). Their roster path is
    operational check-in only; the occasion argument does not apply to it.

    Convocation passes (LGU2) deliberately do NOT take that lock. Their
    exactly-once guarantee is the UNIQUE (convocation_id, registration_id,
    occasion) index on convocation_admissions plus the IntegrityError
    catch, which is atomic across processes as well as threads. Phase 21
    measured what sharing the lock costs: every queued scan waited its FULL
    busy budget while holding it, so 24 concurrent scans stalled for 22.3 s
    and all returned 5xx. Letting each gate contend only with SQLite itself
    bounds any one scan's wait to its own budget.

    Phase 38 analytics: every refused verdict (status 'error') is recorded
    once in scan_rejections AFTER the verdict is decided — logging cannot
    alter, delay or duplicate it, and busy (a transient condition, not a
    verdict) never reaches the log.
    """
    if convqr.is_convocation_payload(payload):
        result = convqr.verify_scan(_gates(), payload, gate_id, mode, volunteer,
                                    scanned_at, source, occasion)
    else:
        try:
            with _SCAN_LOCK:
                result = _process_scan(payload, gate_id, mode, volunteer,
                                       scanned_at, source)
        except sqlite3.OperationalError as exc:
            # Same contract as the convocation path: contention is retryable,
            # not a verdict and not an unhandled 500. No scan was recorded —
            # so nothing is logged either (busy is not a rejection).
            if database.is_busy_error(exc):
                return convqr.busy_result()
            raise
    if result.get("status") == "error":
        models.record_scan_rejection(gate_id, mode, occasion,
                                     result.get("title") or "", source)
    return result


def _process_scan(payload, gate_id, mode, volunteer, scanned_at=None,
                  source="online", occasion=convqr.DEFAULT_OCCASION):
    # Phase 12: version-prefixed convocation passes (LGU2:) verify against the
    # registration/account ledger in convocation_qr — a separate path from the
    # legacy roster codes below (LGU1:), which are untouched.
    if convqr.is_convocation_payload(payload):
        return convqr.verify_scan(_gates(), payload, gate_id, mode, volunteer,
                                  scanned_at, source, occasion)
    ok, qr_id = ids.verify_payload(payload)
    if not ok:
        return {"status": "error", "level": "red", "title": "INVALID CODE",
                "detail": "Signature check failed. This code is tampered or forged."}
    try:
        gate_id = int(gate_id)
    except (TypeError, ValueError):
        return {"status": "error", "level": "red", "title": "NO GATE SELECTED",
                "detail": "Choose a gate before scanning."}
    if mode not in ("entry", "exit"):
        return {"status": "error", "level": "red", "title": "NO MODE SELECTED",
                "detail": "Choose Entry or Exit mode."}
    volunteer = volunteer.strip()[:_VOLUNTEER_CAP] if isinstance(volunteer, str) else ""
    volunteer = volunteer or "Volunteer"
    gate = next((g for g in _gates() if g["id"] == gate_id), None)
    if not gate:
        return {"status": "error", "level": "red", "title": "UNKNOWN GATE",
                "detail": "The selected gate does not exist."}

    person_type, person = models.find_person(qr_id)
    if not person:
        return {"status": "error", "level": "red", "title": "UNKNOWN CODE",
                "detail": "This code is not registered in the system."}

    if person_type == "guest":
        # Phase 34 (Part C): a revoked pass is refused before the used/entry
        # checks — revocation invalidates a lost or compromised pass BEFORE
        # it is ever scanned, and takes precedence over any other state.
        if person.get("status") == "revoked":
            return {"status": "error", "level": "red",
                    "title": "GUEST PASS REVOKED",
                    "detail": "%s: this guest pass was revoked and cannot"
                              " be used to enter." % person["name"],
                    "name": person["name"]}
        if models.guest_used(qr_id):
            ls = models.last_scan(qr_id)
            g = next((x for x in _gates() if ls and x["id"] == ls["gate_id"]), {})
            return {"status": "error", "level": "red", "title": "ALREADY USED",
                    "detail": "%s: this guest pass was already used. One entry per guest."
                    % person["name"],
                    # Structured fields so the app can show name / previous
                    # gate / time without parsing the detail string.
                    "name": person["name"],
                    "gate": g.get("label"),
                    "time": (ls or {}).get("scanned_at")}
        if mode == "exit":
            return {"status": "error", "level": "amber", "title": "GUEST PASS IS ENTRY ONLY",
                    "detail": "Guest passes are single-use entry passes."}
        accepted = models.record_scan(
            qr_id, "guest", person["name"], gate_id, "entry",
            volunteer, scanned_at, source
        )
        if not accepted:
            return {"status": "error", "level": "red", "title": "ALREADY USED",
                    "detail": "%s: this guest pass was already used. One entry per guest."
                    % person["name"]}
        return {"status": "ok", "level": "green", "title": "GUEST ENTRY RECORDED",
                "name": person["name"], "sub": "Guest of %s (%s)" % (
                    person["host_roll_no"], person["phone"]),
                "gate": gate["label"], "time": scanned_at or models.now_str()}

    if mode == "entry" and models.student_inside(qr_id):
        ls = models.last_scan(qr_id)
        g = next((x for x in _gates() if x["id"] == ls["gate_id"]), {})
        return {"status": "error", "level": "red", "title": "ALREADY INSIDE",
                "detail": "%s (%s) already entered at %s, %s." % (
                    person["name"], person["roll_no"], g.get("label", ""),
                    ls["scanned_at"]),
                # Structured fields for the scanner's ALREADY USED state
                # (name + previous gate + time without parsing detail).
                "name": person["name"],
                "gate": g.get("label"),
                "time": ls["scanned_at"]}
    if mode == "exit" and not models.student_inside(qr_id):
        return {"status": "error", "level": "amber", "title": "NOT INSIDE",
                "detail": "%s (%s) has no active entry to close."
                % (person["name"], person["roll_no"])}

    accepted = models.record_scan(
        qr_id, "student", person["name"], gate_id, mode,
        volunteer, scanned_at, source
    )
    if not accepted:
        if mode == "entry":
            ls = models.last_scan(qr_id)
            previous_gate = next((x for x in _gates() if ls and x["id"] == ls["gate_id"]), {})
            return {"status": "error", "level": "red", "title": "ALREADY INSIDE",
                    "name": person["name"], "gate": previous_gate.get("label"),
                    "time": (ls or {}).get("scanned_at"),
                    "detail": "This student already has an active entry."}
        return {"status": "error", "level": "amber", "title": "NOT INSIDE",
                "detail": "This student has no active entry to close."}
    return {"status": "ok", "level": "green",
            "title": "ENTRY RECORDED" if mode == "entry" else "EXIT RECORDED",
            "name": person["name"],
            "sub": "%s, %s, %s" % (person["roll_no"], person["program"], person["gender"]),
            "gate": gate["label"], "time": scanned_at or models.now_str()}


@bp.route("/api/scanner/login", methods=["POST"])
def api_scanner_login():
    """Exchange a scanner username + PIN for a session token.

    Rate-limited per client IP (429 after repeated failures) and audited
    per-account inside scanner_auth. No shared or default credential exists;
    accounts are provisioned only by the local manage_scanner_staff CLI or the
    non-production test helper below."""
    if _scan_login_rate_limited():
        return jsonify({"ok": False, "code": "rate_limited",
                        "error": "Too many attempts. Try again later."}), 429
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad_scan_request("Expected a valid JSON object.")
    username = data.get("username")
    pin = data.get("pin")
    if not isinstance(username, str) or not isinstance(pin, str):
        _scan_login_record_failure()
        return jsonify({"ok": False, "code": "invalid_credentials",
                        "error": "Enter your username and PIN."}), 401
    err = scanner_auth.validate_pin(pin)
    if err:
        _scan_login_record_failure()
        return jsonify({"ok": False, "code": "invalid_credentials",
                        "error": err}), 401
    scanner = scanner_auth.authenticate(username.strip(), pin)
    if not scanner:
        _scan_login_record_failure()
        return jsonify({"ok": False, "code": "invalid_credentials",
                        "error": "Incorrect username or PIN."}), 401
    token, expires_at = scanner_auth.create_session(scanner["id"])
    info = scanner_auth.resolve_session(token)
    return jsonify({"ok": True, "token": token, "expires_at": expires_at,
                    "scanner": {"username": info["username"],
                                "display_name": info["display_name"],
                                "gates": info["gates"]}})


@bp.route("/api/scanner/logout", methods=["POST"])
def api_scanner_logout():
    token = _scanner_token()
    if token:
        scanner_auth.revoke_session(token)
    return jsonify({"ok": True})


@bp.route("/api/test-scanner-session", methods=["POST"])
def api_test_scanner_session():
    """Non-production helper: provision a random synthetic scanner and return
    an active session token so real-HTTP fixtures can authenticate.

    Guarded by _test_tool_guard (404 on the production DB) so it can never
    create an account or mint a token against production. The scanner is
    random per call and no credential is committed to source."""
    guard = _test_tool_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad_scan_request("Expected a valid JSON object.")
    gate_ids = data.get("gate_ids") or [1]
    if not isinstance(gate_ids, list):
        gate_ids = [1]
    suffix = secrets.token_hex(4)
    username = f"test-scan-{suffix}"
    try:
        scanner_id = scanner_auth.create_scanner(
            username=username, display_name=f"Test Scanner {suffix}",
            pin=secrets.token_urlsafe(9), gate_ids=gate_ids,
            actor="test-helper")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    token, expires_at = scanner_auth.create_session(scanner_id)
    info = scanner_auth.resolve_session(token)
    return jsonify({"ok": True, "token": token, "expires_at": expires_at,
                    "scanner": {"username": info["username"],
                                "display_name": info["display_name"],
                                "gates": info["gates"]}})


def _bad_scan_request(message):
    """Return consistent JSON errors for malformed scanner HTTP requests."""
    return jsonify({"ok": False, "error": message}), 400


def _scan_item_shape_error(item, queued=False):
    """Validate only request structure, leaving QR verdicts to process_scan."""
    if not isinstance(item, dict):
        return "Each scan must be a JSON object."
    volunteer = item.get("volunteer")
    if volunteer is not None and not isinstance(volunteer, str):
        return "Volunteer must be a string."
    if queued:
        scanned_at = item.get("scanned_at")
        if scanned_at is not None and not isinstance(scanned_at, str):
            return "Queued scan timestamp must be a string."
    return None


@bp.route("/api/scan", methods=["POST"])
def api_scan():
    auth = _require_scanner()
    if not isinstance(auth, dict):
        return auth
    data = request.get_json(force=True, silent=True)
    error = _scan_item_shape_error(data)
    if error:
        return _bad_scan_request(error)
    # Phase 14: the server decides the gate and the recorded volunteer name.
    # The client's gate_id is only a request for a gate; it must be one of the
    # scanner's authorized gates or the scan is refused. The volunteer name is
    # taken from the authenticated identity, never from the request body.
    gate_id = _coerce_gate(data.get("gate_id"))
    if gate_id is None:
        # Phase 38 analytics: a refused request-level verdict is still a
        # refused scan (same titles api_sync logs per item) — recorded
        # before answering, never instead of answering.
        models.record_scan_rejection(None, data.get("mode"),
                                     data.get("occasion"), "NO GATE SELECTED")
        return jsonify({"status": "error", "level": "red",
                        "title": "NO GATE SELECTED",
                        "detail": "Choose a gate before scanning."}), 400
    # Phase 29: which occasion this scan records. A client that names an
    # unknown occasion is corrected to nothing — the scan is refused with a
    # clear outcome instead of silently recording the wrong occasion.
    occasion = _coerce_occasion(data.get("occasion"))
    if occasion is None:
        models.record_scan_rejection(gate_id, data.get("mode"),
                                     data.get("occasion"), "UNKNOWN OCCASION")
        return jsonify({"status": "error", "level": "red",
                        "title": "UNKNOWN OCCASION",
                        "detail": "Choose Rehearsal or Main convocation"
                                  " before scanning."}), 400
    # Authorization guards only REAL gates. A non-existent gate falls through
    # to process_scan, which answers UNKNOWN GATE (and admits nothing).
    real = {g["id"] for g in _gates()}
    if gate_id in real and gate_id not in auth["gates"]:
        models.record_scan_rejection(gate_id, data.get("mode"), occasion,
                                     "GATE NOT AUTHORIZED")
        return jsonify({"status": "error", "level": "red",
                        "title": "GATE NOT AUTHORIZED",
                        "detail": "This scanner is not authorized for that gate."}), 403
    # A bounded lock-wait timeout is an EXPECTED condition on a single-writer
    # engine. Report it as retryable service unavailability, never as an
    # unhandled 500 and never as a verdict on the scanned pass.
    try:
        result = process_scan(data.get("payload"), gate_id, data.get("mode"),
                              auth["display_name"], occasion=occasion)
    except sqlite3.OperationalError as exc:
        if database.is_busy_error(exc):
            return _transient_busy_response()
        raise
    if result.get("status") == database.BUSY_STATUS:
        return _transient_busy_response()
    return jsonify(result)


def _sync_item(payload, gate_id, mode, occasion, level, title, detail):
    """One queued scan's REFUSED verdict: recorded in the Phase 38 rejection
    log exactly like a live refusal (same titles, same duplicate flag), then
    shaped into the item result the queue consumes. Busy never flows through
    here — it is transient, not a verdict, and is not a rejection."""
    models.record_scan_rejection(gate_id, mode, occasion, title, "queued")
    return {"payload": payload,
            "result": {"status": "error", "level": level, "title": title,
                       "detail": detail}}


@bp.route("/api/sync", methods=["POST"])
def api_sync():
    """Push a queue of offline scans. Each item keeps its original timestamp."""
    auth = _require_scanner()
    if not isinstance(auth, dict):
        return auth
    data = request.get_json(force=True, silent=True)
    # Master audit E6: the whole body must be an object — a bare list or
    # any other JSON type previously crashed with AttributeError (500).
    if not isinstance(data, dict):
        return _bad_scan_request("Sync request must be a JSON object.")
    items = data.get("items", [])
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "items must be a list."}), 400
    if len(items) > 500:
        # One device queues at most a few hundred scans; anything larger is a
        # runaway client or a malicious payload, so reject it up front.
        return jsonify({"ok": False,
                        "error": "Too many items in one sync (max 500)."}), 400
    # Validate the entire batch before any attendance or rejection writes.
    for item in items:
        error = _scan_item_shape_error(item, queued=True)
        if error:
            return _bad_scan_request(error)
    results = []
    for it in items:
        if not isinstance(it, dict):
            results.append(_sync_item(None, None, None, None, "red",
                                      "INVALID CODE", "Malformed sync item."))
            continue
        scanned_at = it.get("scanned_at")
        # Phase 17: accept only real timestamps. The mobile queue writes
        # local wall-clock "%Y-%m-%d %H:%M:%S" (scannerConstants.
        # localTimestamp); anything else is normalised to None so the server
        # clock is used. A junk string such as "zzz" sorts lexicographically
        # AFTER every "2026-..." value, so it would land inside every
        # dashboard time window forever and permanently inflate throughput
        # (models._throughput_map compares scanned_at >= cutoff as text).
        scanned_at = _valid_scanned_at(scanned_at)
        payload = it.get("payload")
        gate_id = it.get("gate_id")
        mode = it.get("mode")
        # Master audit E6: coerce/normalise types BEFORE any sqlite call.
        # A dict/list gate_id or mode previously reached queued_scan_exists
        # raw and crashed the request with an uncaught InterfaceError (500).
        gate_id = _coerce_gate(gate_id)
        if not isinstance(mode, str):
            mode = None
        # Phase 29: per-item occasion. Absent means the main convocation
        # (pre-Phase-29 queued rows replay unchanged); an unknown value is a
        # malformed item, refused before any admission work.
        occasion = _coerce_occasion(it.get("occasion"))
        # A queued row with no code at all is malformed, not an authorization
        # problem — report it as such before the gate checks.
        if not isinstance(payload, str) or not payload:
            results.append(_sync_item(payload, gate_id, mode, occasion, "red",
                                      "INVALID CODE", "Malformed sync item."))
            continue
        # Phase 14: per-item gate authorization + server-derived volunteer.
        # A queued scan through a gate this scanner is not authorized for is
        # refused (not admitted); the volunteer is the authenticated identity,
        # never the client-supplied value. The wording matches /api/scan so a
        # volunteer sees the same outcome online and queued.
        if gate_id is None:
            results.append(_sync_item(payload, gate_id, mode, occasion, "red",
                                      "NO GATE SELECTED",
                                      "Choose a gate before scanning."))
            continue
        if gate_id not in auth["gates"]:
            results.append(_sync_item(
                payload, gate_id, mode, occasion, "red", "GATE NOT AUTHORIZED",
                "This scanner is not authorized for that gate."))
            continue
        if occasion is None:
            results.append(_sync_item(
                payload, gate_id, mode, occasion, "red", "UNKNOWN OCCASION",
                "Choose Rehearsal or Main convocation before scanning."))
            continue
        volunteer = auth["display_name"]
        # Phase 35K (O): idempotency — an identical queued row already in the
        # scans table (same qr/gate/mode/original timestamp/volunteer, source
        # 'queued') is skipped, not re-recorded. Duplicate sync batches must
        # never double-count entries. The client treats "ALREADY SYNCED" as a
        # permanent outcome and drops the item.
        # Master audit V-RACE-03: queued-check + process_scan run under the
        # scan lock so concurrent duplicate batches cannot double-count.
        try:
            if convqr.is_convocation_payload(payload or ""):
                # Phase 24D: idempotency for the convocation ledger, mirroring
                # the roster path's queued_scan_exists below. A re-sent
                # queued batch must be answered ALREADY SYNCED (amber,
                # permanent — the mobile queue drops it), NOT the red
                # ALREADY ADMITTED that a genuinely different duplicate earns.
                # Without this the replay was classified transient and retried
                # forever while showing a red failure for a successful scan.
                # The UNIQUE (convocation, registration, occasion) index still
                # prevents a second admission; this only labels the outcome
                # correctly.
                db_q = database.get_db()
                try:
                    already = convqr.queued_admission_exists(
                        db_q, payload or "", gate_id, scanned_at or "",
                        volunteer, occasion)
                finally:
                    db_q.close()
                if already:
                    results.append(_sync_item(
                        payload, gate_id, mode, occasion, "amber",
                        "ALREADY SYNCED",
                        "This scan was already recorded by an earlier sync."))
                    continue
                # Phase 22: the convocation ledger enforces its own
                # uniqueness, so it must not queue behind the roster path's
                # process-wide lock. One busy gate no longer stalls all gates.
                r = process_scan(payload, gate_id, mode, volunteer, scanned_at,
                                 source="queued", occasion=occasion)
            else:
                with _SCAN_LOCK:
                    ok_qr, qr_id = ids.verify_payload(payload or "")
                    if ok_qr and models.queued_scan_exists(
                            qr_id, gate_id, mode, scanned_at or "", volunteer):
                        results.append(_sync_item(
                            payload, gate_id, mode, occasion, "amber",
                            "ALREADY SYNCED",
                            "This scan was already recorded by an earlier sync."))
                        continue
                    r = process_scan(payload, gate_id, mode, volunteer,
                                     scanned_at, source="queued")
        except sqlite3.OperationalError as exc:
            if not database.is_busy_error(exc):
                raise
            # Contention must never be reported as a malformed code — that
            # would tell the volunteer the QR is bad — and must not abort
            # the rest of the batch. "synced" still counts only real
            # successes, so an unwritten admission is never claimed.
            r = convqr.busy_result(
                "The system is busy right now. Please retry this item.")
        except Exception:
            # Belt and braces: a malformed item must never 500 the batch.
            results.append(_sync_item(payload, gate_id, mode, occasion, "red",
                                      "INVALID CODE", "Malformed sync item."))
            continue
        results.append({"payload": payload, "result": r})
    return jsonify({"synced": sum(1 for r in results if r["result"]["status"] == "ok"),
                    "results": results})


@bp.route("/api/demo-payload")
def api_demo_payload():
    """Demo helper: return the payload of a student currently outside.
    Production databases: hidden (master audit B3)."""
    if config.is_production_db():
        return jsonify({"ok": False, "error": "Not found."}), 404
    environment = os.environ.get("LGU_APP_ENV", "").strip().lower()
    demo_enabled = os.environ.get("LGU_ENABLE_DEMO_QR", "").strip().lower()
    if environment not in ("development", "test") or demo_enabled not in ("1", "true", "yes"):
        return jsonify({"ok": False, "error": "Demo QR helper is disabled."}), 404
    st = models.first_outside_student()
    if st:
        return jsonify({"payload": ids.make_payload(st["qr_id"]),
                        "hint": "%s (%s)" % (st["name"], st["roll_no"])})
    return jsonify({"payload": None, "hint": "Everyone is inside already."})


@bp.route("/api/test-records")
def api_test_records():
    """TEST TOOL: deterministic records for the mobile Test Scan feature.

    Returns one male student, one female student and one seeded guest pass
    with signed payloads, so the app can exercise the real /api/scan flow
    (entry, duplicate, exit) repeatably. Production databases: hidden
    (master audit B1).
    """
    denied = _test_tool_guard()
    if denied:
        return denied
    return jsonify({"records": models.test_records()})


@bp.route("/api/test-reset", methods=["POST"])
def api_test_reset():
    """TEST TOOL: clear scans recorded by the deterministic test records so
    Entry/Exit/duplicate scenarios can be re-run. Production databases:
    hidden — the destructive path does not exist there (master audit B2).
    Issue 1 (Release blocker): also requires the admin PIN header so the
    server independently verifies authorization before any destructive
    operation, even on a test database."""
    denied = _test_tool_guard()
    if denied:
        return denied
    denied = _require_admin_pin()
    if denied is not None:
        return denied
    removed = models.reset_test_scans()
    return jsonify({"ok": True, "removed": removed})


# ---------------------------------------------------------------- admin
@bp.route("/admin", methods=["GET", "POST"])
def admin():
    denied = _require_web_admin()
    if denied is not None:
        return denied
    msg = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "generate":
            missing = models.students_missing_ids()
            n = models.assign_ids(missing, ids.generate_id)
            msg = "%d student ID(s) generated." % n
        elif action == "rename_gate":
            models.rename_gate(request.form.get("gate_id"),
                               request.form.get("label", ""))
            msg = "Gate label updated."
        elif action == "upload_roster":
            f = request.files.get("roster")
            if f and f.filename:
                try:
                    text = f.read().decode("utf-8-sig")
                except UnicodeDecodeError:
                    msg = ("The roster file could not be read. "
                           "Upload a UTF-8 encoded CSV file.")
                else:
                    rows = [r for r in csv.reader(io.StringIO(text))
                            if any(r)]
                    parsed, header_error = _parse_roster(rows)
                    if header_error:
                        msg = header_error
                    else:
                        added, skipped = models.add_students(parsed)
                        missing = models.students_missing_ids()
                        models.assign_ids(missing, ids.generate_id)
                        msg = ("Roster loaded: %d added, %d skipped "
                               "(duplicates or bad rows). IDs assigned."
                               % (added, skipped))
            else:
                msg = "No file selected."
    return render_template("admin.html", gates=_gates(), msg=msg,
                           total=len(models.all_students()),
                           with_ids=len(models.students_with_ids()))


@bp.route("/admin/cards")
def print_cards():
    denied = _require_web_admin()
    if denied is not None:
        return denied
    students = models.students_with_ids()
    cards = [{"name": s["name"], "roll_no": s["roll_no"], "program": s["program"],
              "qr": qrgen.qr_data_uri(ids.make_payload(s["qr_id"]))}
             for s in students]
    return render_template("cards.html", cards=cards)


@bp.route("/admin/vendor.csv")
def vendor_csv():
    denied = _require_web_admin()
    if denied is not None:
        return denied
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["roll_no", "name", "program", "qr_payload"])
    for s in models.students_with_ids():
        w.writerow([s["roll_no"], s["name"], s["program"],
                    ids.make_payload(s["qr_id"])])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             "attachment; filename=lgu_vendor_print_file.csv"})


# ---------------------------------------------------------------- guests
# Phase 38 (BE-003): guest registration is the one anonymous endpoint that
# mints a bearer QR credential, so it gets a dedicated windowed per-IP
# bucket (shared by the form and the JSON path — splitting them would
# double the budget) plus a table-derived daily cap that survives restarts.
_GUEST_REG_ATTEMPTS = {}
_GUEST_REG_LOCK = threading.Lock()
_GUEST_REG_MSG = ("Too many guest registrations right now. "
                  "Please try again in a minute.")
_GUEST_CAP_MSG = ("Guest registration is at capacity for today. "
                  "Please try again tomorrow.")


def _guest_reg_blocked():
    """(limited, message) — counts EVERY attempt, check-and-record atomic."""
    now = time.time()
    window = config.GUEST_RATE_WINDOW_SECONDS
    ip = _client_ip()
    with _GUEST_REG_LOCK:
        recent = [t for t in _GUEST_REG_ATTEMPTS.get(ip, [])
                  if now - t < window]
        if len(recent) >= config.GUEST_RATE_MAX_ATTEMPTS:
            _GUEST_REG_ATTEMPTS[ip] = recent
            return True, _GUEST_REG_MSG
        recent.append(now)
        _GUEST_REG_ATTEMPTS[ip] = recent
    if models.guests_created_today() >= config.GUEST_DAILY_CAP:
        return True, _GUEST_CAP_MSG
    return False, None


@bp.route("/guests", methods=["GET", "POST"])
def guests():
    """Public guest self-registration shell (Phase 27 C2).

    GET renders ONLY the registration form: the directory moved to
    ``/guests/directory``, so an anonymous caller can no longer read every
    guest's name, phone and host straight out of the page source. POST stays
    anonymous — a walk-up guest has no credential to present yet."""
    err = None
    if request.method == "POST":
        limited, err = _guest_reg_blocked()
        name = (request.form.get("name", "") or "").strip()
        phone = (request.form.get("phone", "") or "").strip()
        host = (request.form.get("host_roll_no", "") or "").strip()
        # Master audit V-INP-03: bounded fields on the web form too.
        if limited:
            pass                      # err already carries the limiter reply
        elif len(name) > _NAME_CAP or len(phone) > _PHONE_CAP or len(host) > _ROLL_CAP:
            err = "Name (max %d), phone (max %d) and host roll (max %d) are limited." % (
                _NAME_CAP, _PHONE_CAP, _ROLL_CAP)
        else:
            gid, err = models.register_guest(name, phone, host, ids.generate_id)
            if gid:
                # C3: hand the guest a scoped capability. It rides the signed
                # session cookie, never the URL, so it cannot land in an
                # access log or a forwarded link.
                session["guest_print"] = ids.make_print_token(
                    gid, config.GUEST_PRINT_TTL_MINUTES * 60)
                return redirect(url_for("main.guest_pass", gid=gid))
    return render_template("guests.html", err=err,
                           is_staff=session.get("lgu_admin") is True)


@bp.route("/guests/directory")
def guest_directory():
    """Protected guest directory (Phase 27 C2).

    Split out of ``/guests``: the walk-up registration page must never load
    the roster. Staff-session gate for the browser (the volunteer desk reads
    the same minimum fields from scanner-gated ``/api/guests``), rendering
    ``guest_directory()`` — no ``qr_id``, no ``created_at``."""
    denied = _require_web_admin()
    if denied is not None:
        return denied
    return render_template("guests.html", guests=models.guest_directory(),
                           err=None, is_staff=True)


@bp.route("/guests/<int:gid>/pass")
def guest_pass(gid):
    # Master audit F-INP-05: huge ids overflowed the sqlite INTEGER bind
    # (500). Bound the range; ids outside it cannot exist.
    if not (0 < gid < 1_000_000_000):
        return "Guest not found.", 404
    # Phase 27 C3: an enumerable gid alone must not mint a signed pass.
    # Authorisation runs BEFORE the lookup, so an anonymous prober cannot
    # read the 401/404 split as an oracle for which guest ids exist.
    if not _guest_print_allowed(gid):
        return ("This guest pass link is invalid or has expired. "
                "Ask the desk to reprint this pass."), 401
    g = models.guest_by_id(gid)
    if not g:
        return "Guest not found.", 404
    return render_template("guest_pass.html", guest=g,
                           qr=qrgen.qr_data_uri(ids.make_payload(g["qr_id"])))


# ---------------------------------------------------------------- broadcast
@bp.route("/broadcast", methods=["GET", "POST"])
def broadcast():
    denied = _require_web_admin()
    if denied is not None:
        return denied
    msg = None
    if request.method == "POST":
        audience = (request.form.get("audience", "All students") or "").strip()[:_AUDIENCE_CAP]
        message = request.form.get("message", "") or ""
        sent_by = (request.form.get("sent_by", "") or "").strip()[:_AUDIENCE_CAP]
        # Master audit V-INP-02: the web form enforces the same 160-char
        # cap as the JSON API.
        if len(message) > config.MESSAGE_CHAR_LIMIT:
            msg = "Message is limited to %d characters." % config.MESSAGE_CHAR_LIMIT
        elif message.strip():
            models.add_broadcast(audience, message.strip(), sent_by)
            msg = "Broadcast logged. Demo mode: messages are recorded here, not sent by SMS."
        else:
            msg = "Message text is required."
    return render_template("broadcast.html", gates=_gates(),
                           log=models.recent_broadcasts(), msg=msg,
                           broadcast_mode=config.BROADCAST_MODE)


# ---------------------------------------------------------------- mobile JSON API
# Small JSON helpers for the Expo mobile app. HTML routes above are untouched.

@bp.route("/api/health")
def api_health():
    """Lightweight liveness probe used by the app's connection checks."""
    return jsonify({"ok": True, "app": config.APP_NAME,
                    "version": config.ID_VERSION})


@bp.route("/api/gates")
def api_gates():
    return jsonify({"gates": models.gates()})


@bp.route("/api/gates/<int:gid>/rename", methods=["POST"])
def api_rename_gate(gid):
    denied = _require_admin_pin()
    if denied:
        return denied
    if not (0 < gid < 1_000_000_000):
        return jsonify({"ok": False, "error": "Unknown gate."}), 404
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad_scan_request("Expected a valid JSON object.")
    for field in ('label',):
        if field in data and not isinstance(data[field], str):
            return _bad_scan_request("%s must be text." % field)
    label = (data.get("label") or "").strip()
    if not label:
        return jsonify({"ok": False, "error": "Label is required."}), 400
    if len(label) > _AUDIENCE_CAP:
        return jsonify({"ok": False, "error":
                        "Label must be at most %d characters." % _AUDIENCE_CAP}), 400
    models.rename_gate(gid, label)
    gate = next((g for g in models.gates() if g["id"] == gid), None)
    return jsonify({"ok": True, "gate": gate})


@bp.route("/api/guests")
def api_guests():
    """Scanner-backed guest roster (Phase 26C).

    The kiosk list carries guest phone numbers and once leaked the signed
    ``qr_id`` credential via ``all_guests()``. It is now behind the same
    scanner session as /api/scan and returns only the minimum fields the
    volunteer desk renders (no ``qr_id`` / ``created_at``). Anonymous
    callers get the standard 401. Guest self-registration (POST) stays
    public; the single-guest print artefact (/api/guest-pass/<id>) now
    requires that guest's print capability or a scanner/staff session
    (Phase 27 C3), and registrants are handed the capability they need to
    read their own pass back.
    """
    auth = _require_scanner()
    if not isinstance(auth, dict):
        return auth
    return jsonify({"guests": models.guest_directory()})


@bp.route("/api/guests", methods=["POST"])
def api_register_guest():
    limited, msg = _guest_reg_blocked()
    if limited:
        return jsonify({"ok": False, "error": msg}), 429
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad_scan_request("Expected a valid JSON object.")
    for field in ('name', 'phone', 'host_roll_no'):
        if field in data and not isinstance(data[field], str):
            return _bad_scan_request("%s must be text." % field)
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    host_roll_no = (data.get("host_roll_no") or "").strip()
    if not name or not phone or not host_roll_no:
        return jsonify({"ok": False,
                        "error": "Name, phone and host roll number are required."}), 400
    # Master audit V-INP-03: bounded fields.
    if len(name) > _NAME_CAP or len(phone) > _PHONE_CAP or len(host_roll_no) > _ROLL_CAP:
        return jsonify({"ok": False, "error":
                        "Name (max %d), phone (max %d) and host roll (max %d) are limited."
                        % (_NAME_CAP, _PHONE_CAP, _ROLL_CAP)}), 400
    gid, err = models.register_guest(name, phone, host_roll_no, ids.generate_id)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    g = models.guest_by_id(gid)
    return jsonify({"ok": True, "gid": gid,
                    "payload": ids.make_payload(g["qr_id"]),
                    # Phase 27 C3: the registrant's own scoped capability —
                    # the approved way to read this pass back without a
                    # scanner or staff session.
                    "print_token": ids.make_print_token(
                        gid, config.GUEST_PRINT_TTL_MINUTES * 60)})


@bp.route("/api/guest-pass/<int:gid>")
def api_guest_pass(gid):
    """Single-guest pass JSON (Phase 27 C3).

    ``payload`` is a bearer credential, so an enumerable integer gid is no
    longer enough to read it: the caller must hold that guest's print
    capability (issued at registration) or be a signed-in scanner/staff
    operator. Authorisation precedes the lookup so an anonymous prober
    cannot read a 401/404 split as an oracle for which guest ids exist."""
    if not (0 < gid < 1_000_000_000):
        return jsonify({"ok": False, "error": "Guest not found."}), 404
    if not _guest_print_allowed(gid):
        return jsonify({"ok": False, "code": "guest_pass_forbidden",
                        "error": "Guest pass access requires this guest's "
                                 "print link, or a scanner sign-in."}), 401
    g = models.guest_by_id(gid)
    if not g:
        return jsonify({"ok": False, "error": "Guest not found."}), 404
    return jsonify({"ok": True, "gid": gid, "name": g["name"],
                    "phone": g["phone"], "host_roll_no": g["host_roll_no"],
                    # 33-QA (I23): host name travels with the pass payload.
                    "host_name": g.get("host_name"),
                    # Phase 34 (Part C): lifecycle state so the pass screen
                    # can show Ready / Used / Revoked from the server truth.
                    "status": g.get("status", "active"),
                    "used": models.guest_used(g["qr_id"]),
                    "payload": ids.make_payload(g["qr_id"])})


@bp.route("/api/guests/<int:gid>/revoke", methods=["POST"])
def api_revoke_guest(gid):
    """Phase 34 (Part C): revoke an unused guest pass (scanner/staff only).

    Guest self-registration stays public by design, but revocation is a
    management action that invalidates a bearer pass, so it rides the same
    scanner session as the roster. Only an ACTIVE pass transitions — a used
    pass keeps its terminal 'used' meaning (409), keeping 'used' (entered)
    and 'revoked' (invalidated) distinct lifecycle states.
    """
    auth = _require_scanner()
    if not isinstance(auth, dict):
        return auth
    if not (0 < gid < 1_000_000_000):
        return jsonify({"ok": False, "error": "Guest not found."}), 404
    g = models.guest_by_id(gid)
    if not g:
        return jsonify({"ok": False, "error": "Guest not found."}), 404
    if models.guest_used(g["qr_id"]):
        return jsonify({"ok": False, "error":
                        "This guest pass was already used; it cannot be revoked."}), 409
    changed = models.revoke_guest(gid)
    return jsonify({"ok": True, "gid": gid, "status": "revoked",
                    "changed": changed})


@bp.route("/api/broadcasts")
def api_broadcasts():
    return jsonify({"log": models.recent_broadcasts()})


@bp.route("/api/broadcasts", methods=["POST"])
def api_send_broadcast():
    """Log an announcement (admin surface, Phase 35G/35K).

    Requires the X-Admin-Pin header matching config.ADMIN_PIN. Messages are
    capped at config.MESSAGE_CHAR_LIMIT. The response note is driven by
    config.BROADCAST_MODE — "demo" (default) records only; "real" records
    too and states that no delivery gateway is configured. The server never
    claims delivery it did not perform (35K Part G).
    """
    # Phase 37 BE-001: this handler previously inlined the PIN comparison
    # and never consulted _pin_rate_limited(), leaving an unlimited online
    # guessing path on a 4-digit credential (audit-confirmed). The
    # centralized gate restores the per-IP 429 while keeping the exact
    # denial text pinned by mobile source regression tests.
    denied = _require_admin_pin(
        "Administrator access required to send announcements.")
    if denied:
        return denied
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad_scan_request("Expected a valid JSON object.")
    for field in ('message', 'audience', 'sent_by'):
        if field in data and not isinstance(data[field], str):
            return _bad_scan_request("%s must be text." % field)
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "Message text is required."}), 400
    if len(message) > config.MESSAGE_CHAR_LIMIT:
        return jsonify({"ok": False, "error": "Messages are limited to %d characters." %
                        config.MESSAGE_CHAR_LIMIT}), 400
    audience = (data.get("audience") or "All students").strip()[:_AUDIENCE_CAP]
    sent_by = (data.get("sent_by") or "Admin").strip()[:_AUDIENCE_CAP]
    models.add_broadcast(audience, message, sent_by)
    if config.BROADCAST_MODE == "real":
        note = ("Announcement recorded. Delivery gateway is not configured"
                " on this server.")
    else:
        note = ("Logged. Demo mode: not sent by SMS — recorded in the"
                " broadcast log only.")
    return jsonify({"ok": True, "note": note})


@bp.route("/api/broadcast/audience")
def api_broadcast_audience():
    """Announcement audience for the broadcast composer (Phase 35K Part I).

    ?gates=1,2 → students currently inside at the selected gates (derived
    from real scan history — no fabricated assignments). No param → the
    default all-students audience (roster count). The response carries a
    basis string stating the rule so the UI never overclaims, plus a
    per_gate breakdown (largest first, ties by label) when gates narrow
    the audience (33-QA I15).
    """
    raw = (request.args.get("gates") or "").strip()
    gate_ids = []
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                gate_ids.append(int(part))
            except ValueError:
                return jsonify({"ok": False,
                                "error": "gates must be a comma-separated list of ids."}), 400
    if gate_ids:
        known = {g["id"] for g in models.gates()}
        unknown = [gid for gid in gate_ids if gid not in known]
        if unknown:
            return jsonify({"ok": False,
                            "error": "Unknown gate id(s): %s." %
                            ", ".join(str(g) for g in unknown)}), 400
    audience = models.broadcast_audience(gate_ids or None)
    return jsonify({"ok": True, "count": audience["count"],
                    "basis": audience["basis"],
                    "per_gate": audience["per_gate"]})


@bp.route("/api/admin/verify", methods=["POST"])
def api_admin_verify():
    """Check an administrator PIN (Phase 35G). The mobile admin gate calls
    this once per unlock; the PIN itself is stored only on the device.
    Master audit V-AUTH-01: wrong attempts are rate limited per IP."""
    if _pin_rate_limited():
        return jsonify({"ok": False,
                        "error": "Too many attempts. Try again in a minute."}), 429
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad_scan_request("Expected a valid JSON object.")
    if "pin" in data and not isinstance(data["pin"], str):
        return _bad_scan_request("PIN must be text.")
    pin = (data.get("pin") or "").strip()
    if pin and _pin_ok(pin):
        return jsonify({"ok": True})
    if pin:
        _pin_record_failure()
    return jsonify({"ok": False, "error": "Incorrect PIN. Try again."}), 401


@bp.route("/api/search")
def api_search():
    """Attendee/guest lookup for the mobile Search screen (spec §12).

    Recovery path for damaged QR codes, missing passes and camera failures:
    find a person by name, roll number, phone or host roll number, and return
    their live gate state. Read-only over existing tables — no business rule
    is changed and opening a result records nothing.

    Phase 34 (Part D): rides the SAME scanner session as /api/gate — the
    lookup carries guest phone PII and once exposed the signed ``qr_id``
    credential, so anonymous callers now get the standard 401 and ``qr_id``
    is never returned (matching the Phase 27 C2 roster projection).
    """
    auth = _require_scanner()
    if not isinstance(auth, dict):
        return auth
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"ok": False,
                        "error": "Enter at least 2 characters to search."}), 400
    pattern = "%%%s%%" % q.replace("%", "\\%").replace("_", "\\_")
    # Phase 38 DB-003: guaranteed close — this handler runs many aggregate
    # queries and previously leaked the connection on any mid-loop error.
    with database.connection() as db:
        students = db.execute(
            "SELECT * FROM students"
            " WHERE name LIKE ? ESCAPE '\\' OR roll_no LIKE ? ESCAPE '\\'"
            " ORDER BY roll_no LIMIT 25", (pattern, pattern)).fetchall()
        guests = db.execute(
            "SELECT g.*, st.name AS host_name FROM guests g"
            " LEFT JOIN students st ON st.roll_no = g.host_roll_no"
            " WHERE g.name LIKE ? ESCAPE '\\' OR g.phone LIKE ? ESCAPE '\\'"
            " OR g.host_roll_no LIKE ? ESCAPE '\\' OR g.qr_id LIKE ? ESCAPE '\\'"
            " ORDER BY g.id DESC LIMIT 25",
            (pattern, pattern, pattern, pattern)).fetchall()

        gate_by_id = {g["id"]: g["label"] for g in
                      db.execute("SELECT id, label FROM gates").fetchall()}
        results = []
        for s in students:
            last = db.execute(
                "SELECT * FROM scans WHERE qr_id = ? ORDER BY id DESC LIMIT 1",
                (s["qr_id"],)).fetchone() if s["qr_id"] else None
            inside = bool(last and last["mode"] == "entry")
            results.append({
                "type": "student", "name": s["name"], "roll_no": s["roll_no"],
                "program": s["program"], "gender": s["gender"],
                "inside": inside, "used": False,
                "last_scan": {
                    "gate": gate_by_id.get(last["gate_id"], ""),
                    "time": last["scanned_at"], "mode": last["mode"],
                } if last else None,
            })
        for g in guests:
            last = db.execute(
                "SELECT * FROM scans WHERE qr_id = ? ORDER BY id DESC LIMIT 1",
                (g["qr_id"],)).fetchone()
            used = last is not None
            results.append({
                "type": "guest", "name": g["name"], "gid": g["id"],
                "host_roll_no": g["host_roll_no"],
                "host_name": g["host_name"], "phone": g["phone"],
                "status": g["status"], "inside": used, "used": used,
                "last_scan": {
                    "gate": gate_by_id.get(last["gate_id"], ""),
                    "time": last["scanned_at"], "mode": last["mode"],
                } if last else None,
            })
    return jsonify({"ok": True, "query": q, "results": results})


def create_app():
    config.assert_production_secrets()
    # Phase 37 BE-002 — fail-closed demo-secret guard AT the application
    # factory. run.py enforces the policy before init_db; every other way
    # to construct this app (a WSGI server importing create_app, a shell,
    # a script) previously ran with no check at all — audit BE-002.
    # Shared policy: config.demo_secret_violation() (names only, never
    # values). Raise rather than sys.exit: a library entry point must not
    # kill a hosting process that has its own error handling.
    violation = config.demo_secret_violation()
    if violation:
        raise RuntimeError("FATAL: " + violation)
    base = os.path.dirname(os.path.abspath(__file__))
    app = Flask(__name__, template_folder=os.path.join(base, "templates"),
                static_folder=os.path.join(base, "static"))
    app.secret_key = config.SECRET_KEY
    # Phase 20 §4 — session cookie hardening. HttpOnly is Flask's default and
    # is restated because the staff portal holds a single privileged session
    # that unlocks the ADMIN_PIN and every management page. SameSite was
    # previously unset, so the cookie rode along on cross-site requests; Lax
    # keeps same-origin form posts working while adding a browser-level
    # backstop behind the explicit CSRF tokens. Secure is deliberately NOT
    # set: the intended deployment is a trusted plain-HTTP LAN, and marking
    # the cookie Secure would make it undiscoverable over http:// and drop
    # every staff session. Set LGU_COOKIE_SECURE when TLS is fronted.
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.COOKIE_SECURE,
    )


    # Cap request bodies before Flask parses form uploads or JSON.
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    app.register_blueprint(bp)
    # exam_reg_routes attaches Phase 4 routes to the same exam blueprint, so
    # it must be imported before register_blueprint. Phase 6 adds the
    # medalists blueprint (own /exam/medalists prefix, same staff session).
    # Phase 7 attaches event + announcement routes to the exam blueprint.
    # Phase 9 attaches the support-request review queue to the exam
    # blueprint (same staff_required + CSRF guard). Phase 19 attaches the
    # authenticated scanner-administration surface to the same blueprint, so
    # it inherits the identical staff session and CSRF protection.
    from web import (exam_routes, exam_reg_routes, exam_event_routes,  # noqa: F401
                     exam_support_routes, exam_scanner_routes,
                     medalist_routes, student_routes)
    app.register_blueprint(exam_routes.bp)
    app.register_blueprint(medalist_routes.bp)
    # Phase 5: student JSON API (Bearer auth, no session cookies).
    app.register_blueprint(student_routes.bp)

    @app.after_request
    def add_cors_headers(response):
        # Master audit V-CORS-01: the wildcard origin is replaced with an
        # explicit allowlist — same-host origins, loopback dev origins
        # (Expo web / Metro) and the LAN host this server is reached
        # through. Native mobile fetch sends no Origin header and is
        # unaffected. Browser pages on other hosts get no CORS grant.
        origin = request.headers.get("Origin")
        if origin and _origin_allowed(origin, request.host):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
            # Phase 35G: POST /api/broadcasts carries an X-Admin-Pin header,
            # so browsers must allow it in the preflight (web / Metro target).
            # Phase 5: the student API authenticates with Authorization.
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Pin, Authorization"
            response.headers["Vary"] = "Origin"
        # Master audit V-HEAD-01: minimal hardening headers. A full CSP is
        # intentionally not set (inline scripts in the templates); HSTS is
        # not set because this is a plain-HTTP LAN tool.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.errorhandler(404)
    def not_found(_e):
        # JSON clients get JSON; browsers get the normal HTML 404 page.
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Not found."}), 404
        return "Not found.", 404

    @app.errorhandler(413)
    def request_entity_too_large(_error):
        message = "Request too large (maximum 8 MiB)."
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": message}), 413
        return Response(message, status=413, mimetype="text/plain")

    @app.context_processor
    def inject_brand():
        return {"APP_NAME": config.APP_NAME, "UNIVERSITY": config.UNIVERSITY,
                "MOTTO": config.MOTTO}

    return app
