"""Convocation entry QR issuance + gate verification (Phase 12, §3A–§3C).

A convocation entry pass is a high-entropy bearer token bound to ONE claimed
registration, ONE account and ONE convocation. Only the token's sha256 hash is
stored — the plaintext is minted once at issuance, returned to the owning
student, and never persisted or logged. This path is deliberately INDEPENDENT
of the legacy operational roster (``students.qr_id`` → ``models.find_person``
→ ``scans``): a registration carries no roster qr_id and shares no key with
it, so its pass is verified here against the authoritative registration /
account ledger instead. Issuing a convocation pass never inserts or touches a
legacy ``students`` row, and admission is recorded in its own
``convocation_admissions`` ledger (UNIQUE per convocation + registration +
occasion) so two gates scanning the same pass near-simultaneously cannot
admit it twice for the same occasion.

The QR payload is version-prefixed (``LGU2:``) so the volunteer scanner can
dispatch between legacy (``LGU1:``) codes and convocation passes without
touching the legacy verification path. Eligibility is recomputed from current
records on both issuance AND every scan, so a cancelled / revoked registration
or an open blocking review stops validating the moment it changes.
"""

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import config
import convocation_pass as cp
import student_auth as sa
from exam_registrations import utc_now

# QR payload version for convocation passes (legacy roster codes use "LGU1").
PAYLOAD_VERSION = "LGU2"
# 32 random bytes → 43-char URL-safe token (256 bits of entropy).
_TOKEN_BYTES = 32
_VOLUNTEER_CAP = 64
# The two occasions of the annual cycle (Phase 29). Every admission records
# which one it belongs to; a scan that names no occasion (every scanner
# build before Phase 29, and any legacy queued record) means the main
# convocation, exactly as the single occasion behaved before this existed.
OCCASIONS = ("rehearsal", "ceremony")
DEFAULT_OCCASION = "ceremony"


class PassError(Exception):
    """Rejected issuance — carries a message safe to show the student."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def make_payload(token):
    return "%s:%s" % (PAYLOAD_VERSION, token)


def is_convocation_payload(payload):
    return isinstance(payload, str) and payload.startswith(PAYLOAD_VERSION + ":")


def busy_result(detail=None):
    """Controlled, retryable answer for a bounded lock-wait timeout.

    A TRANSIENT SYSTEM CONDITION, never a verdict on the pass. It is not a
    success (no admission was recorded, the pass stays active), and it is
    deliberately distinct from INVALID CODE / ALREADY ADMITTED / GATE NOT
    AUTHORIZED — those are permanent outcomes the volunteer must act on,
    whereas this one is resolved simply by scanning again.
    """
    import database
    return _out(database.BUSY_STATUS, "amber", "TEMPORARILY BUSY",
                detail or "The system is busy right now. Please retry this"
                          " scan.",
                retryable=True)


def parse_payload(payload):
    """The bearer token when the payload is a convocation pass, else None."""
    if not isinstance(payload, str):
        return None
    prefix = PAYLOAD_VERSION + ":"
    text = payload.strip()
    if not text.startswith(prefix):
        return None
    token = text[len(prefix):].strip()
    return token or None


def _audit(db, conv_id, actor, action, before, after):
    db.execute(
        "INSERT INTO convocation_audit"
        " (convocation_id, actor, action, before_json, after_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (conv_id, actor, action,
         json.dumps(before, sort_keys=True) if before else "",
         json.dumps(after, sort_keys=True) if after else "",
         utc_now()))


def queued_admission_exists(db, payload, gate_id, scanned_at, volunteer,
                            occasion=DEFAULT_OCCASION):
    """True when an identical offline-queued CONVOCATION scan already
    recorded its admission (Phase 24D — sync idempotency for LGU2).

    Mirrors models.queued_scan_exists on the roster path so re-sending a
    queued batch (retry after a flaky network, a lost response, or a
    duplicate device) is answered ALREADY SYNCED — a permanent, amber
    outcome the mobile queue drops — instead of the red ALREADY ADMITTED
    that a genuinely different duplicate earns. Without this, a replayed
    convocation scan that already succeeded was treated as transient and
    retried forever.

    Matched on the business identity of the queued row: the pass, the gate,
    the occasion, the device-stamped original timestamp and the volunteer,
    restricted to source='queued'.

    This is a LABEL improvement only — it never weakens duplicate protection.
    The UNIQUE (convocation_id, registration_id, occasion) index plus the
    IntegrityError catch in verify_scan remain the atomic backstop, and a
    duplicate arriving at a different gate, time or occasion still returns
    ALREADY ADMITTED.
    """
    token = parse_payload(payload)
    if token is None:
        return False
    volunteer = volunteer.strip()[:_VOLUNTEER_CAP] if isinstance(volunteer, str) else ""
    volunteer = volunteer or "Volunteer"
    row = db.execute(
        "SELECT 1 FROM convocation_admissions a"
        " JOIN convocation_passes p ON p.id = a.pass_id"
        " WHERE p.token_hash = ? AND a.gate_id = ? AND a.occasion = ?"
        " AND a.admitted_at = ?"
        " AND a.volunteer = ? AND a.source = 'queued' LIMIT 1",
        (token_hash(token), gate_id, occasion, scanned_at or "",
         volunteer)).fetchone()
    return row is not None


def _expiry(issued_at):
    try:
        moment = datetime.fromisoformat(issued_at)
    except (TypeError, ValueError):
        return None
    return (moment + timedelta(
        hours=config.CONVOCATION_PASS_TTL_HOURS)).isoformat(timespec="seconds")


def live_pass(db, conv_id, registration_id):
    return db.execute(
        "SELECT * FROM convocation_passes"
        " WHERE convocation_id = ? AND registration_id = ? AND status = 'active'"
        " ORDER BY id DESC LIMIT 1",
        (conv_id, registration_id)).fetchone()


def _revoke_active(db, conv_id, registration_id, actor):
    """Revoke every live pass for this registration so reissue leaves exactly
    one active token. Returns how many were revoked."""
    rows = db.execute(
        "SELECT id FROM convocation_passes"
        " WHERE convocation_id = ? AND registration_id = ? AND status = 'active'",
        (conv_id, registration_id)).fetchall()
    if not rows:
        return 0
    db.execute(
        "UPDATE convocation_passes SET status = 'revoked', revoked_at = ?"
        " WHERE convocation_id = ? AND registration_id = ? AND status = 'active'",
        (utc_now(), conv_id, registration_id))
    for r in rows:
        _audit(db, conv_id, actor, "pass_revoke", {"pass_id": r["id"]}, None)
    return len(rows)


def issue_pass(db, account, conv):
    """Issue (or reissue) the student's convocation entry QR.

    Recomputes eligibility from authoritative records — the same source GET
    /pass derives its invitation from — and only an eligible student receives
    a token. Reissue revokes the prior active pass so the previous QR stops
    validating at the gate. Returns the QR view (payload + metadata); the
    bearer token appears here exactly once and is never stored.
    """
    if conv is None:
        raise PassError(409, "no_convocation",
                        "There is no active convocation to issue a pass for.")
    conv_id = conv["id"]
    invitation = cp.pass_for_account(db, account, conv)
    if invitation["state"] != "eligible":
        raise PassError(403, invitation["state"],
                        invitation["detail"] or
                        "You are not eligible for a convocation pass.")
    row = sa.claimed_registration(db, account["id"], conv_id)
    registration_id = row["id"]
    actor = "student:%d" % account["id"]
    _revoke_active(db, conv_id, registration_id, actor)

    token = secrets.token_urlsafe(_TOKEN_BYTES)
    issued_at = utc_now()
    expires_at = _expiry(issued_at)
    cur = db.execute(
        "INSERT INTO convocation_passes"
        " (token_hash, convocation_id, registration_id, account_id, status,"
        "  issued_at, expires_at) VALUES (?, ?, ?, ?, 'active', ?, ?)",
        (token_hash(token), conv_id, registration_id, account["id"],
         issued_at, expires_at))
    pass_id = cur.lastrowid
    _audit(db, conv_id, actor, "pass_issue", None,
           {"pass_id": pass_id, "registration_id": registration_id})
    db.commit()
    return {"pass_id": pass_id, "payload": make_payload(token),
            "issued_at": issued_at, "expires_at": expires_at,
            "convocation": {"id": conv_id, "name": conv["name"],
                            "year": conv["year"]},
            "registration": invitation["registration"],
            "event": invitation["event"]}


def _out(status, level, title, detail="", **kw):
    d = {"status": status, "level": level, "title": title, "detail": detail}
    d.update(kw)
    return d


def verify_scan(gates, payload, gate_id, mode, volunteer, scanned_at, source,
                occasion=DEFAULT_OCCASION):
    """Verify a scanned convocation pass and (only if authorized) admit it.

    The BACKEND decides — never the client. Eligibility is recomputed from
    authoritative records at scan time.

    ONE pass credential serves both occasions of the annual cycle (Phase 29);
    what differs is the OCCASION the scan names. A rehearsal admission never
    consumes the pass — only the main convocation does — and a registration
    can be admitted once per occasion, never twice to the same one.

    Correctness under concurrency rests on the UNIQUE
    (convocation_id, registration_id, occasion) index over
    convocation_admissions plus the IntegrityError catch below: a concurrent
    duplicate that slips past the pre-check fails the INSERT and is answered
    ALREADY ADMITTED. Do not weaken that index — it is the only thing
    preventing a double admission.

    A failed scan records nothing; error messages and the audit trail never
    expose the token or unnecessary personal data.
    """
    token = parse_payload(payload)
    if token is None:
        return _out("error", "red", "INVALID CODE",
                    "This is not a valid convocation pass.")
    try:
        gate_id = int(gate_id)
    except (TypeError, ValueError):
        return _out("error", "red", "NO GATE SELECTED",
                    "Choose a gate before scanning.")
    if mode != "entry":
        return _out("error", "amber", "CONVOCATION PASSES ARE ENTRY-ONLY",
                    "Convocation passes admit attendees; they do not record an exit.")
    if occasion not in OCCASIONS:
        occasion = DEFAULT_OCCASION  # defensive: unknown → main convocation
    gate = next((g for g in gates if g["id"] == gate_id), None)
    if not gate:
        return _out("error", "red", "UNKNOWN GATE",
                    "The selected gate does not exist.")

    import database
    db = database.get_db()
    try:
        row = db.execute("SELECT * FROM convocation_passes WHERE token_hash = ?",
                         (token_hash(token),)).fetchone()
        if row is None:
            return _out("error", "red", "PASS INVALID",
                        "This pass is not valid. Open your invitation to issue a fresh pass.")
        if row["status"] == "revoked":
            return _out("error", "red", "PASS INVALID",
                        "This pass was replaced by a newer one. Open your invitation to show the latest pass.")
        if row["status"] == "used":
            prev = db.execute(
                "SELECT a.admitted_at, g.label FROM convocation_admissions a"
                " LEFT JOIN gates g ON g.id = a.gate_id WHERE a.pass_id = ?",
                (row["id"],)).fetchone()
            return _out("error", "red", "ALREADY ADMITTED",
                        "This pass was already used for entry.",
                        gate=(prev["label"] if prev else None),
                        time=(prev["admitted_at"] if prev else None))

        # Expiry is enforced at SCAN time, not merely reported to the student:
        # a pass past its TTL stops admitting even while still marked active.
        if row["expires_at"]:
            try:
                now = datetime.fromisoformat(utc_now())
                exp = datetime.fromisoformat(row["expires_at"])
                if exp.tzinfo is None:   # naive stamps are UTC
                    exp = exp.replace(tzinfo=timezone.utc)
                expired = now >= exp
            except (TypeError, ValueError):
                expired = False
            if expired:
                return _out("error", "red", "PASS EXPIRED",
                            "This pass has expired. Open your invitation to issue a fresh pass.")

        account = db.execute("SELECT * FROM student_accounts WHERE id = ?",
                             (row["account_id"],)).fetchone()
        conv = db.execute(
            "SELECT * FROM convocations WHERE id = ? AND is_active = 1",
            (row["convocation_id"],)).fetchone()
        if account is None or conv is None:
            return _out("error", "red", "CONVOCATION UNAVAILABLE",
                        "This convocation is not open for entry.")
        if occasion == "rehearsal" and not conv["rehearsal_date"]:
            return _out("error", "red", "REHEARSAL NOT SCHEDULED",
                        "This convocation has no rehearsal configured."
                        " Scan for the main convocation instead.",
                        occasion=occasion)
        registration = db.execute(
            "SELECT * FROM convocation_registrations WHERE id = ?",
            (row["registration_id"],)).fetchone()
        if registration is None:
            return _out("error", "red", "REGISTRATION NOT ELIGIBLE",
                        "This registration is not currently eligible for entry.")

        # Recompute eligibility from authoritative records at scan time.
        state = cp.pass_for_account(db, account, conv)["state"]
        if state != "eligible":
            return _out("error", "red", "REGISTRATION NOT ELIGIBLE",
                        "This registration is not currently eligible for entry.")

        # Single-admission backstop per occasion (also enforced by the UNIQUE
        # index): a rehearsal check-in here does not block the main ceremony
        # later — they are two distinct records — but a repeat of the SAME
        # occasion is refused.
        admitted = db.execute(
            "SELECT 1 FROM convocation_admissions"
            " WHERE convocation_id = ? AND registration_id = ? AND occasion = ?",
            (row["convocation_id"], row["registration_id"], occasion)).fetchone()
        if admitted:
            if row["status"] != "used":
                db.execute("UPDATE convocation_passes SET status = 'used' WHERE id = ?",
                           (row["id"]))
                db.commit()
            return _out("error", "red", "ALREADY ADMITTED",
                        "This registration has already been admitted.",
                        occasion=occasion)

        volunteer = volunteer.strip()[:_VOLUNTEER_CAP] if isinstance(volunteer, str) else ""
        volunteer = volunteer or "Volunteer"
        admitted_at = scanned_at or utc_now()
        try:
            db.execute(
                "INSERT INTO convocation_admissions"
                " (pass_id, convocation_id, registration_id, gate_id, volunteer,"
                "  admitted_at, source, occasion) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (row["id"], row["convocation_id"], row["registration_id"],
                 gate_id, volunteer, admitted_at, source, occasion))
        except sqlite3.IntegrityError:
            # Concurrent duplicate slipped past the pre-check — the UNIQUE
            # (convocation, registration, occasion) index is the backstop.
            db.rollback()
            return _out("error", "red", "ALREADY ADMITTED",
                        "This registration has already been admitted.",
                        occasion=occasion)
        # ONLY the main convocation consumes the credential: a student who
        # checks in at the rehearsal keeps a live pass for the ceremony.
        if occasion == "ceremony":
            db.execute("UPDATE convocation_passes SET status = 'used' WHERE id = ?",
                       (row["id"],))
        _audit(db, row["convocation_id"], "gate:%s" % gate["code"], "pass_admit",
               None, {"pass_id": row["id"],
                      "registration_id": row["registration_id"],
                      "gate_id": gate_id, "occasion": occasion})
        db.commit()
        return _out("ok", "green",
                    "REHEARSAL ENTRY RECORDED" if occasion == "rehearsal"
                    else "CONVOCATION ENTRY RECORDED", "",
                    name=registration["student_name"],
                    sub="%s, %s" % (registration["registration_number"],
                                    registration["department"] or
                                    registration["roll_number"]),
                    gate=gate["label"], time=admitted_at, occasion=occasion)
    except sqlite3.OperationalError as exc:
        # Phase 22: a bounded lock-wait that exhausted its budget is an
        # EXPECTED single-writer condition, not a scan failure. Classify it
        # here so no caller — scanner, sync batch or test — can mistake it
        # for a permanent verdict on the pass, or leak "database is locked"
        # to a volunteer. The pass stays active and admits on a retry.
        import database
        if database.is_busy_error(exc):
            return busy_result()
        raise
    finally:
        db.close()
