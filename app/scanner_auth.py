"""Volunteer scanner identities: hashed PINs, lockout, short-lived sessions.

Phase 14. The scan endpoints previously accepted a volunteer name and gate id
straight from the client with no authentication. A scanner now proves who it
is with a per-account PIN (scrypt hash at rest — never plaintext) and holds a
short-lived session whose bearer token is stored only as a sha256 hash. The
server, never the client, decides which gates a scanner may admit through and
what volunteer name is recorded.

Kept separate from exam staff (exam_auth) and the web-admin PIN
(config.ADMIN_PIN); reuses exam_auth's scrypt hashing and the shared
audit_log so access-control changes land in one trail. No shared/default
credential or universal PIN exists — accounts are created only by the local
management command (scripts/manage_scanner_staff.py) or the non-production
test helper, both of which mint a per-account secret.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash

from exam_auth import audit, hash_password

import config
import database

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
MIN_PIN_LENGTH = 6
_USERNAME_CAP = 64
_NAME_CAP = 120
# Phase 18: default actor for a caller that names no operator. Deliberately
# NOT "system" — a provisioning action attributed to "system" looks like a
# trusted automated process when it was really a human at a shell, which is
# exactly the ownership gap this replaced. An honest "unknown" forces the
# operator identity to be supplied by the caller that actually knows it
# (scripts/manage_scanner_staff.py defaults to the OS login).
UNKNOWN_ACTOR = "unknown-operator"
_ACTOR_CAP = 64
# Phase 19: provenance of a lifecycle action, recorded in the audit detail so
# a genuine authenticated staff action is never confused with a local shell
# operator merely asserting a name on the command line.
VIA_PORTAL = "portal"   # authenticated Examination Department staff session
VIA_CLI = "cli"         # local operator attestation (NOT verified identity)
VIA_TEST = "test"       # non-production test helper
_VIAS = (VIA_PORTAL, VIA_CLI, VIA_TEST)

# Lifecycle actions that belong in the management history — including denied
# management attempts, which are recorded rather than silently dropped. Login
# success and failure rows stay in audit_log for investigation but are not
# management events, so they are excluded by name rather than by pattern.
MANAGEMENT_ACTIONS = (
    "scanner_created", "scanner_gates_set", "scanner_pin_reset",
    "scanner_sessions_revoked", "scanner_revoked", "scanner_activated",
    "scanner_mgmt_denied",
)


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _aware(dt):
    """Return an aware UTC datetime, treating a naive value as UTC.

    Sessions are always written aware, but a hand-edited or tampered
    timestamp must be handled safely (deny/lock) rather than crashing the
    route with a naive-vs-aware TypeError (500)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _actor(actor):
    """Normalise an operator identity for the audit trail.

    Empty/placeholder values collapse to UNKNOWN_ACTOR so no lifecycle action
    is ever recorded as "system".
    """
    name = (actor or "").strip()
    if not name or name.lower() in ("system", "none", "null"):
        return UNKNOWN_ACTOR
    return name[:_ACTOR_CAP]


def _via(via):
    """Normalise a provenance tag so an unknown value cannot masquerade."""
    return via if via in _VIAS else VIA_CLI


def _detail(via, extra):
    """Audit detail carrying provenance first, then event-specific fields."""
    return ("via=%s %s" % (_via(via), extra)).strip()


def validate_pin(pin):
    """Return an error message, or None when the PIN meets policy."""
    if not pin or len(pin) < MIN_PIN_LENGTH:
        return "Scanner PIN must be at least %d characters." % MIN_PIN_LENGTH
    if len(pin) > 256:
        return "Scanner PIN must be at most 256 characters."
    return None


def _valid_gates(db, gate_ids):
    """Normalise and validate a gate list against the gates table."""
    if gate_ids is None:
        gate_ids = []
    if not isinstance(gate_ids, (list, tuple)):
        raise ValueError("gate_ids must be a list of gate numbers.")
    cleaned = []
    for g in gate_ids:
        if isinstance(g, bool):
            raise ValueError("gate_ids must be numbers.")
        try:
            g = int(g)
        except (TypeError, ValueError) as exc:
            raise ValueError("gate_ids must be numbers.") from exc
        if g not in cleaned:
            cleaned.append(g)
    known = {r["id"] for r in db.execute("SELECT id FROM gates").fetchall()}
    unknown = [g for g in cleaned if g not in known]
    if unknown:
        raise ValueError("Unknown gate(s): %s." % ", ".join(str(g) for g in unknown))
    return cleaned


def generate_pin(length=8):
    """A one-time PIN handed to an operator (portal) or printed by the CLI.

    Unambiguous alphabet — no 0/O, 1/I/L — and comfortably above the
    6-character minimum. The server keeps only the scrypt hash, so this value
    can never be shown again: losing it means issuing a new one.
    """
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(max(MIN_PIN_LENGTH, length)))


def _pending_pin_hash():
    """An unverifiable hash standing in for "no credential established".

    A real scrypt hash of a value nobody knows, so a defect in the
    credential_established check degrades to "wrong PIN" and can never
    degrade into a successful authentication.
    """
    return hash_password(secrets.token_urlsafe(32))


def create_scanner(username, display_name, pin=None, gate_ids=(),
                   actor=UNKNOWN_ACTOR, via=VIA_CLI):
    """Provision a scanner account with gate assignments. Returns the new id.

    Raises ValueError on invalid input, duplicate username, or unknown gates.

    pin=None provisions the account in a PENDING-credential state: it carries
    an unverifiable hash plus credential_established = 0, so it cannot
    authenticate until a PIN is explicitly established through reset_pin().
    No default or shared PIN exists at any point in that path. When a PIN is
    supplied it is stored only as a scrypt hash and the caller handles the
    plaintext. The account row and its gate rows are written in one
    transaction, so a rejected request leaves no half-configured account.
    """
    username = (username or "").strip()
    display_name = (display_name or "").strip()
    if not username or len(username) > _USERNAME_CAP:
        raise ValueError("Username is required (max %d characters)." % _USERNAME_CAP)
    if not display_name or len(display_name) > _NAME_CAP:
        raise ValueError("Display name is required (max %d characters)." % _NAME_CAP)
    pending = pin is None
    if not pending:
        error = validate_pin(pin)
        if error:
            raise ValueError(error)
    now = _iso(_utcnow())
    db = database.get_db()
    try:
        gates = _valid_gates(db, gate_ids)
        cur = db.execute(
            "INSERT INTO scanner_users (username, display_name, pin_hash,"
            " credential_established, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (username, display_name,
             _pending_pin_hash() if pending else hash_password(pin),
             0 if pending else 1, now, now))
        sid = cur.lastrowid
        for g in gates:
            db.execute("INSERT INTO scanner_gates (scanner_id, gate_id) VALUES (?, ?)",
                       (sid, g))
        audit(db, _actor(actor), "scanner_created", _detail(via, (
            "username=%s gates=%s credential=%s"
            % (username, ",".join(str(g) for g in gates),
               "pending" if pending else "established"))))
        db.commit()
        return sid
    except Exception as exc:
        db.rollback()
        if "UNIQUE" in str(exc):
            raise ValueError("That scanner username already exists.") from exc
        raise
    finally:
        db.close()


def set_gates(scanner_id, gate_ids, actor=UNKNOWN_ACTOR, via=VIA_CLI):
    """Replace a scanner's permitted gates. Raises ValueError if unknown.

    Gate rows are deleted and re-inserted inside one transaction: a rejected
    request (unknown gate id, non-numeric input) rolls back and leaves the
    previous gate set intact rather than half-applied.
    """
    db = database.get_db()
    try:
        row = db.execute("SELECT username FROM scanner_users WHERE id = ?",
                         (scanner_id,)).fetchone()
        if not row:
            raise ValueError("No scanner with that id.")
        gates = _valid_gates(db, gate_ids)
        db.execute("DELETE FROM scanner_gates WHERE scanner_id = ?", (scanner_id,))
        for g in gates:
            db.execute("INSERT INTO scanner_gates (scanner_id, gate_id) VALUES (?, ?)",
                       (scanner_id, g))
        db.execute("UPDATE scanner_users SET updated_at = ? WHERE id = ?",
                   (_iso(_utcnow()), scanner_id))
        audit(db, _actor(actor), "scanner_gates_set", _detail(via, (
            "username=%s gates=%s" %
            (row["username"], ",".join(str(g) for g in gates)))))
        db.commit()
        return gates
    finally:
        db.close()


def deactivate_scanner(scanner_id, actor=UNKNOWN_ACTOR, via=VIA_CLI):
    """Revoke a scanner: deactivate the account AND kill every live session.

    Subsequent scans with any previously issued token are rejected because
    resolve_session requires is_active = 1."""
    db = database.get_db()
    try:
        row = db.execute("SELECT username FROM scanner_users WHERE id = ?",
                         (scanner_id,)).fetchone()
        if not row:
            raise ValueError("No scanner with that id.")
        db.execute("UPDATE scanner_users SET is_active = 0, updated_at = ? WHERE id = ?",
                   (_iso(_utcnow()), scanner_id))
        db.execute("UPDATE scanner_sessions SET revoked_at = ?"
                   " WHERE scanner_id = ? AND revoked_at IS NULL",
                   (_iso(_utcnow()), scanner_id))
        audit(db, _actor(actor), "scanner_revoked",
              _detail(via, "username=%s" % row["username"]))
        db.commit()
    finally:
        db.close()


def activate_scanner(scanner_id, actor=UNKNOWN_ACTOR, via=VIA_CLI):
    db = database.get_db()
    try:
        row = db.execute("SELECT username FROM scanner_users WHERE id = ?",
                         (scanner_id,)).fetchone()
        if not row:
            raise ValueError("No scanner with that id.")
        db.execute("UPDATE scanner_users SET is_active = 1, failed_attempts = 0,"
                   " locked_until = NULL, updated_at = ? WHERE id = ?",
                   (_iso(_utcnow()), scanner_id))
        audit(db, _actor(actor), "scanner_activated",
              _detail(via, "username=%s" % row["username"]))
        db.commit()
    finally:
        db.close()


def revoke_sessions(scanner_id, actor=UNKNOWN_ACTOR, via=VIA_CLI):
    """Revoke every live session for a scanner. Returns the number affected.

    The account stays usable: this is the action for a lost or handed-over
    device, or for signing a volunteer out without disabling their identity.
    """
    db = database.get_db()
    try:
        row = db.execute("SELECT username FROM scanner_users WHERE id = ?",
                         (scanner_id,)).fetchone()
        if not row:
            raise ValueError("No scanner with that id.")
        cur = db.execute(
            "UPDATE scanner_sessions SET revoked_at = ?"
            " WHERE scanner_id = ? AND revoked_at IS NULL",
            (_iso(_utcnow()), scanner_id))
        count = cur.rowcount
        audit(db, _actor(actor), "scanner_sessions_revoked", _detail(
            via, "username=%s revoked=%d" % (row["username"], count)))
        db.commit()
        return count
    finally:
        db.close()


def reset_pin(scanner_id, new_pin, actor=UNKNOWN_ACTOR, via=VIA_CLI):
    """Establish or replace a scanner's PIN. True when the account was still
    awaiting its first credential.

    Replacing the hash invalidates the previous PIN immediately: the very next
    authentication can only succeed against the new value. Live sessions are
    deliberately NOT revoked here — resetting a forgotten PIN mid-event should
    not sign the volunteer out; revoke_sessions() is the explicit action for
    that. The plaintext PIN is never written to the audit trail or any log.
    """
    db = database.get_db()
    try:
        row = db.execute("SELECT username, credential_established"
                         " FROM scanner_users WHERE id = ?",
                         (scanner_id,)).fetchone()
        if not row:
            raise ValueError("No scanner with that id.")
        error = validate_pin(new_pin)
        if error:
            raise ValueError(error)
        was_pending = row["credential_established"] != 1
        db.execute("UPDATE scanner_users SET pin_hash = ?,"
                   " credential_established = 1, updated_at = ? WHERE id = ?",
                   (hash_password(new_pin), _iso(_utcnow()), scanner_id))
        audit(db, _actor(actor), "scanner_pin_reset", _detail(via, (
            "username=%s credential=%s" %
            (row["username"], "established" if was_pending else "replaced"))))
        db.commit()
        return was_pending
    finally:
        db.close()


def authenticate(username, pin):
    """Verify credentials. Returns the scanner row dict on success, else None.

    Unknown users and wrong PINs return the same result and burn comparable
    time so they are not distinguishable by latency. Repeated failures lock
    the account for LOCK_MINUTES. Both outcomes are audited without the PIN."""
    raw = (username or "").strip()
    name = raw[:_USERNAME_CAP]
    pin = pin or ""
    db = database.get_db()
    try:
        row = None
        if len(raw) <= _USERNAME_CAP:
            row = db.execute("SELECT * FROM scanner_users WHERE username = ?",
                             (name,)).fetchone()
        now = _utcnow()
        if row is None:
            check_password_hash(hash_password("x" * MIN_PIN_LENGTH), pin[:256])
            audit(db, name or "?", "scanner_login_failed", "unknown user")
            db.commit()
            return None
        pending = row["credential_established"] != 1
        locked = row["locked_until"] and _aware(datetime.fromisoformat(row["locked_until"])) > now
        if not row["is_active"] or locked:
            audit(db, name, "scanner_login_blocked",
                  "inactive" if not row["is_active"] else "locked")
            db.commit()
            return None
        # A pending account carries an unverifiable hash, so it can never
        # match — this block makes the refusal explicit and auditable rather
        # than letting a half-provisioned device burn five failures and lock.
        if pending:
            audit(db, name, "scanner_login_blocked", "credential_pending")
            db.commit()
            return None
        if len(pin) <= 256 and check_password_hash(row["pin_hash"], pin):
            db.execute("UPDATE scanner_users SET failed_attempts = 0,"
                       " locked_until = NULL, last_login_at = ? WHERE id = ?",
                       (_iso(now), row["id"]))
            audit(db, name, "scanner_login_ok")
            db.commit()
            return dict(row)
        fails = row["failed_attempts"] + 1
        locked_until = (_iso(now + timedelta(minutes=LOCK_MINUTES))
                        if fails >= MAX_FAILED_ATTEMPTS else None)
        db.execute("UPDATE scanner_users SET failed_attempts = ?, locked_until = ?"
                   " WHERE id = ?",
                   (0 if locked_until else fails, locked_until, row["id"]))
        audit(db, name, "scanner_login_failed", "wrong pin")
        db.commit()
        return None
    finally:
        db.close()


def create_session(scanner_id):
    """Mint a short-lived session. Returns (plaintext_token, expires_at_iso).

    Only the token's sha256 hash is persisted; the plaintext is returned once
    for the client to hold and is never stored or logged."""
    token = secrets.token_urlsafe(32)
    now = _utcnow()
    expires = now + timedelta(hours=config.SCANNER_SESSION_HOURS)
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO scanner_sessions (scanner_id, token_hash, created_at,"
            " expires_at) VALUES (?, ?, ?, ?)",
            (scanner_id, hashlib.sha256(token.encode()).hexdigest(),
             _iso(now), _iso(expires)))
        db.commit()
        return token, _iso(expires)
    finally:
        db.close()


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def revoke_session(token):
    """Revoke one session (logout). Safe to call with an unknown token."""
    if not token:
        return
    db = database.get_db()
    try:
        db.execute("UPDATE scanner_sessions SET revoked_at = ?"
                   " WHERE token_hash = ? AND revoked_at IS NULL",
                   (_iso(_utcnow()), _token_hash(token)))
        db.commit()
    finally:
        db.close()


def resolve_session(token):
    """Resolve a bearer token to an authorized scanner, else None.

    Returns {id, username, display_name, gates:[...]} — the gates come from
    the server-side scanner_gates table, never from client request data. A
    revoked/expired session, an inactive account, or an unknown token all
    return None so the caller rejects the scan."""
    if not token or len(token) > 256:
        return None
    now = _utcnow()
    db = database.get_db()
    try:
        row = db.execute(
            "SELECT s.*, u.username, u.display_name, u.is_active"
            " FROM scanner_sessions s JOIN scanner_users u ON u.id = s.scanner_id"
            " WHERE s.token_hash = ?", (_token_hash(token),)).fetchone()
        if not row or row["revoked_at"] is not None:
            return None
        if row["is_active"] != 1:
            return None
        if _aware(datetime.fromisoformat(row["expires_at"])) <= now:
            return None
        gates = [r["gate_id"] for r in db.execute(
            "SELECT gate_id FROM scanner_gates WHERE scanner_id = ?"
            " ORDER BY gate_id", (row["scanner_id"],)).fetchall()]
        return {"id": row["scanner_id"], "username": row["username"],
                "display_name": row["display_name"], "gates": gates}
    finally:
        db.close()


def _gate_list(value):
    return [int(g) for g in (value or "").split(",") if g]


def list_scanners():
    """All scanner accounts with their gates and live session count.

    Deliberately never selects pin_hash or any session token hash: this shape
    is rendered on an ordinary staff page and printed by the CLI, and neither
    surface should ever hold a credential secret.
    """
    db = database.get_db()
    try:
        rows = db.execute(
            "SELECT u.id, u.username, u.display_name, u.is_active,"
            " u.credential_established, u.failed_attempts, u.locked_until,"
            " u.last_login_at, u.created_at, u.updated_at,"
            " (SELECT group_concat(gate_id) FROM scanner_gates g"
            "  WHERE g.scanner_id = u.id) AS gates,"
            " (SELECT COUNT(*) FROM scanner_sessions s"
            "  WHERE s.scanner_id = u.id AND s.revoked_at IS NULL"
            "   AND s.expires_at > ?) AS live_sessions"
            " FROM scanner_users u ORDER BY u.username",
            (_iso(_utcnow()),)).fetchall()
        return [{**dict(r), "gates": _gate_list(r["gates"])} for r in rows]
    finally:
        db.close()


def get_scanner(scanner_id):
    """One account with its gates and live sessions, or None.

    No pin_hash and no token_hash ever leaves this function.
    """
    db = database.get_db()
    try:
        row = db.execute(
            "SELECT u.id, u.username, u.display_name, u.is_active,"
            " u.credential_established, u.failed_attempts, u.locked_until,"
            " u.last_login_at, u.created_at, u.updated_at"
            " FROM scanner_users u WHERE u.id = ?", (scanner_id,)).fetchone()
        if row is None:
            return None
        now = _iso(_utcnow())
        gates = _gate_list(db.execute(
            "SELECT group_concat(gate_id) FROM scanner_gates"
            " WHERE scanner_id = ? ORDER BY gate_id",
            (scanner_id,)).fetchone()[0])
        sessions = [dict(r) for r in db.execute(
            "SELECT id, created_at, expires_at FROM scanner_sessions"
            " WHERE scanner_id = ? AND revoked_at IS NULL AND expires_at > ?"
            " ORDER BY id DESC", (scanner_id, now)).fetchall()]
        return {**dict(row), "gates": gates, "sessions": sessions}
    finally:
        db.close()


def _like_literal(value):
    """Escape a value for use in a LIKE pattern with ESCAPE '\\'."""
    return (value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_"))


def history(limit=100, username=None):
    """Recent scanner lifecycle entries from the shared audit trail.

    Only management actions are returned (see MANAGEMENT_ACTIONS); login
    success and failure rows stay in audit_log for investigation but are not
    management events. username narrows to one account, matching the exact
    `username=<name> ` field written into the detail.
    """
    db = database.get_db()
    try:
        sql = ("SELECT id, actor, action, detail, created_at FROM audit_log"
               " WHERE action IN (%s)" % ",".join("?" for _ in MANAGEMENT_ACTIONS))
        args = list(MANAGEMENT_ACTIONS)
        if username:
            sql += " AND detail LIKE ? ESCAPE '\\'"
            args.append("username=%s %%" % _like_literal(username))
        rows = db.execute(sql + " ORDER BY id DESC LIMIT ?",
                          (*args, int(limit))).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_scanner_by_username(username):
    db = database.get_db()
    try:
        row = db.execute("SELECT * FROM scanner_users WHERE username = ?",
                         ((username or "").strip(),)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()
