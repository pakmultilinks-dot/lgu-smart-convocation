"""Student accounts: verification challenges, sessions, claims, profile photo.

Security invariants (Phase 5):
- Verification codes exist in plaintext only inside the outgoing email; the
  database stores an HMAC digest keyed by SECRET_KEY.
- Session tokens are random 32-byte URL strings; only their sha256 digest is
  stored, and sessions expire/revoked rows are honoured on every request.
- One account holds one registration per convocation and one registration is
  claimed exactly once (UNIQUE pairs in migration 4).
- Profile photos are validated (magic bytes + Pillow re-encode strips EXIF),
  stored under a random name outside static/, and served only to the owner.
"""

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image
from werkzeug.security import check_password_hash

import config
from exam_auth import (LOCK_MINUTES, MAX_FAILED_ATTEMPTS, audit,
                       hash_password, validate_password)
from exam_registrations import EMAIL_RE, utc_now

IDENT_LIMIT = 64
NAME_LIMIT = 120
PHONE_LIMIT = 32
EMAIL_LIMIT = 254
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_EDGE = 8000
_MAGIC = {"jpeg": (b"\xff\xd8\xff",), "png": (b"\x89PNG\r\n\x1a\n",)}


class StudentError(Exception):
    """HTTP-mappable error: (status, machine code, human message)."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def expiry_iso(seconds):
    return _iso(_now() + timedelta(seconds=seconds))


# --------------------------------------------------------------- normalization

def norm_email(value):
    return (value or "").strip().lower()


def norm_ident(value):
    # leading zeros and internal spacing preserved; nothing else touched
    return (value or "").strip()


def norm_name(value):
    return " ".join((value or "").split())


def names_match(a, b):
    return norm_name(a).casefold() == norm_name(b).casefold()


def mask_email(email):
    local, sep, domain = email.partition("@")
    if not sep:
        return "•••"
    return (local[:1] or "•") + "•••@" + domain


def require_fields(payload, fields):
    out, missing = {}, []
    for name, clean in fields:
        value = clean(payload.get(name, ""))
        if not value:
            missing.append(name)
        out[name] = value
    if missing:
        raise StudentError(400, "missing_field",
                           "%s is required." % ", ".join(missing))
    return out


# ------------------------------------------------------------- codes / tokens

def new_code():
    return "%06d" % secrets.randbelow(1_000_000)


def code_digest(email, code):
    key = config.SECRET_KEY.encode() if isinstance(config.SECRET_KEY, str) \
        else config.SECRET_KEY
    return hmac.new(key, ("%s:%s" % (email, code)).encode(),
                    hashlib.sha256).hexdigest()


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def code_ok(row, email, code):
    return hmac.compare_digest(row["code_hash"], code_digest(email, code))


# -------------------------------------------------------- challenge lifecycle

def active_challenge(db, purpose, email):
    return db.execute(
        "SELECT * FROM verification_challenges"
        " WHERE purpose = ? AND university_email = ?"
        " AND consumed_at IS NULL AND expires_at > ?"
        " ORDER BY id DESC LIMIT 1",
        (purpose, email, utc_now())).fetchone()


def create_challenge(db, purpose, email, code, convocation_id=None,
                     registration_id=None):
    now = utc_now()
    cur = db.execute(
        "INSERT INTO verification_challenges"
        " (purpose, university_email, convocation_id, registration_id,"
        "  code_hash, sent_count, attempt_count, expires_at, created_at,"
        "  last_sent_at) VALUES (?,?,?,?,?,1,0,?,?,?)",
        (purpose, email, convocation_id, registration_id,
         code_digest(email, code), expiry_iso(config.VERIFICATION_TTL_SECONDS),
         now, now))
    return cur.lastrowid


def resend_challenge(db, row, code):
    if row["consumed_at"]:
        raise StudentError(410, "challenge",
                           "That verification code has already been used.")
    if row["sent_count"] >= config.CODE_MAX_SENDS:
        raise StudentError(429, "send_limit",
                           "This code has reached its resend limit. Start "
                           "the sign-up again to get a fresh code.")
    # note: attempt_count is NOT reset — a resend never grants extra guesses
    db.execute(
        "UPDATE verification_challenges SET code_hash = ?, expires_at = ?,"
        " sent_count = sent_count + 1, last_sent_at = ? WHERE id = ?",
        (code_digest(row["university_email"], code),
         expiry_iso(config.VERIFICATION_TTL_SECONDS), utc_now(), row["id"]))


def get_challenge(db, challenge_id, purpose):
    row = db.execute(
        "SELECT * FROM verification_challenges WHERE id = ? AND purpose = ?",
        (challenge_id, purpose)).fetchone()
    if row is None:
        raise StudentError(404, "challenge",
                           "This verification step no longer exists. Start "
                           "again.")
    return row


def verify_challenge(db, row, code):
    """Check the code and atomically consume the challenge (single use)."""
    if row["consumed_at"]:
        raise StudentError(410, "challenge",
                           "That verification code has already been used.")
    if row["expires_at"] <= utc_now():
        raise StudentError(410, "expired",
                           "That verification code has expired. Request a "
                           "new one.")
    if row["attempt_count"] >= config.CODE_MAX_ATTEMPTS:
        raise StudentError(429, "attempts",
                           "Too many incorrect attempts for this code. "
                           "Start again to get a fresh one.")
    if not code_ok(row, row["university_email"], code):
        db.execute(
            "UPDATE verification_challenges SET attempt_count ="
            " attempt_count + 1 WHERE id = ?", (row["id"],))
        db.commit()
        left = max(0, config.CODE_MAX_ATTEMPTS - row["attempt_count"] - 1)
        raise StudentError(400, "code",
                           "Incorrect verification code. %d attempt%s left."
                           % (left, "" if left == 1 else "s"))
    cur = db.execute(
        "UPDATE verification_challenges SET consumed_at = ? WHERE id = ?"
        " AND consumed_at IS NULL", (utc_now(), row["id"]))
    if cur.rowcount != 1:  # lost a concurrent race — treat as used
        raise StudentError(410, "challenge",
                           "That verification code has already been used.")


# ------------------------------------------------------------- accounts / login

_DUMMY = None


def _dummy_hash():
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("timing-equalisation-placeholder")
    return _DUMMY


def get_account(db, email):
    return db.execute("SELECT * FROM student_accounts WHERE university_email = ?",
                      (email,)).fetchone()


def ensure_profile(db, account_id):
    """Idempotently create the profile row and PERSIST it before returning.

    sqlite3 opens a deferred transaction, so an uncommitted INSERT is rolled
    back on close(). Callers read straight through this row and some UPDATE
    it, so the ensure must be committed here — otherwise the row silently
    vanishes and every later write no-ops against a missing row.
    """
    db.execute(
        "INSERT OR IGNORE INTO student_profiles"
        " (account_id, created_at, updated_at) VALUES (?,?,?)",
        (account_id, utc_now(), utc_now()))
    db.commit()
    return db.execute("SELECT * FROM student_profiles WHERE account_id = ?",
                      (account_id,)).fetchone()


def create_account(db, email, password):
    error = validate_password(password)
    if error:
        raise StudentError(400, "password", error)
    if not EMAIL_RE.match(email) or len(email) > EMAIL_LIMIT:
        raise StudentError(400, "email", "Enter a valid university email address.")
    try:
        cur = db.execute(
            "INSERT INTO student_accounts"
            " (university_email, password_hash, created_at, updated_at)"
            " VALUES (?,?,?,?)",
            (email, hash_password(password), utc_now(), utc_now()))
    except sqlite3.IntegrityError:
        raise StudentError(409, "exists",
                           "An account already exists for this email. "
                           "Sign in instead.")
    ensure_profile(db, cur.lastrowid)
    return cur.lastrowid


def login(db, email, password):
    """Password sign-in with per-account lockout (5 fails → 15 minutes)."""
    row = get_account(db, email)
    if row is None:
        check_password_hash(_dummy_hash(), password or "x")
        raise StudentError(401, "credentials",
                           "Email or password is incorrect.")
    if row["locked_until"] and row["locked_until"] > utc_now():
        raise StudentError(429, "locked",
                           "Too many failed attempts. Try again in %d "
                           "minutes." % LOCK_MINUTES)
    if not row["password_hash"] or not check_password_hash(
            row["password_hash"], password or ""):
        failed = row["failed_attempts"] + 1
        locked_until = (_iso(_now() + timedelta(minutes=LOCK_MINUTES))
                        if failed >= MAX_FAILED_ATTEMPTS else row["locked_until"])
        db.execute(
            "UPDATE student_accounts SET failed_attempts = ?, locked_until = ?,"
            " updated_at = ? WHERE id = ?",
            (failed, locked_until, utc_now(), row["id"]))
        db.commit()
        if failed >= MAX_FAILED_ATTEMPTS:
            raise StudentError(429, "locked",
                               "Too many failed attempts. Try again in %d "
                               "minutes." % LOCK_MINUTES)
        raise StudentError(401, "credentials", "Email or password is incorrect.")
    db.execute(
        "UPDATE student_accounts SET failed_attempts = 0, locked_until = NULL,"
        " last_login_at = ?, updated_at = ? WHERE id = ?",
        (utc_now(), utc_now(), row["id"]))
    return get_account(db, email)


def set_password(db, account_id, password):
    error = validate_password(password)
    if error:
        raise StudentError(400, "password", error)
    db.execute(
        "UPDATE student_accounts SET password_hash = ?, failed_attempts = 0,"
        " locked_until = NULL, updated_at = ? WHERE id = ?",
        (hash_password(password), utc_now(), account_id))


# ------------------------------------------------------------------ sessions

def issue_session(db, account_id):
    token = secrets.token_urlsafe(32)
    expires = expiry_iso(config.SESSION_HOURS * 3600)
    db.execute(
        "INSERT INTO student_sessions (account_id, token_hash, created_at,"
        " expires_at) VALUES (?,?,?,?)",
        (account_id, _token_hash(token), utc_now(), expires))
    return token, expires


def account_for_token(db, token):
    if not token:
        return None
    return db.execute(
        "SELECT a.* FROM student_sessions s"
        " JOIN student_accounts a ON a.id = s.account_id"
        " WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?",
        (_token_hash(token), utc_now())).fetchone()


def revoke_token(db, token):
    if token:
        db.execute("UPDATE student_sessions SET revoked_at = ?"
                   " WHERE token_hash = ? AND revoked_at IS NULL",
                   (utc_now(), _token_hash(token)))


def revoke_all_sessions(db, account_id):
    db.execute("UPDATE student_sessions SET revoked_at = ?"
               " WHERE account_id = ? AND revoked_at IS NULL",
               (utc_now(), account_id))


# -------------------------------------------------------------------- claims

def claim_for(db, account_id, convocation_id):
    return db.execute(
        "SELECT * FROM registration_claims WHERE account_id = ?"
        " AND convocation_id = ?", (account_id, convocation_id)).fetchone()


def claim_registration(db, account_id, convocation_id, registration_id):
    try:
        db.execute(
            "INSERT INTO registration_claims"
            " (account_id, convocation_id, registration_id, created_at)"
            " VALUES (?,?,?,?)",
            (account_id, convocation_id, registration_id, utc_now()))
    except sqlite3.IntegrityError:
        raise StudentError(409, "claimed",
                           "This registration is already linked to a student "
                           "account. Sign in instead.")


def claimed_registration(db, account_id, convocation_id):
    """The claimed registration row (with claimed_at) or None."""
    return db.execute(
        "SELECT c.created_at AS claimed_at, r.* FROM registration_claims c"
        " JOIN convocation_registrations r ON r.id = c.registration_id"
        " WHERE c.account_id = ? AND c.convocation_id = ?",
        (account_id, convocation_id)).fetchone()


# ------------------------------------------------------------ profile photo

def _sniff(data):
    if data.startswith(_MAGIC["png"]):
        return "png", "image/png"
    if data.startswith(_MAGIC["jpeg"]):
        return "jpeg", "image/jpeg"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None, None


def store_photo(db, account_id, data):
    """Validate + re-encode (strips EXIF), save under a random name."""
    if len(data) > config.PHOTO_MAX_BYTES:
        raise StudentError(400, "photo",
                           "The photo is larger than the %d MB limit."
                           % (config.PHOTO_MAX_BYTES // (1024 * 1024)))
    fmt, mime = _sniff(data)
    if fmt is None:
        raise StudentError(400, "photo",
                           "The photo must be a JPEG, PNG, or WebP image.")
    try:
        img = Image.open(BytesIO(data))
        if img.width * img.height > MAX_IMAGE_PIXELS or \
                img.width > MAX_IMAGE_EDGE or img.height > MAX_IMAGE_EDGE:
            raise StudentError(400, "photo",
                               "That image has too many pixels. Choose a "
                               "photo under 20 megapixels.")
        img.load()  # fully decodes — raises on truncated/corrupt data
        out = BytesIO()
        if fmt == "jpeg":
            img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
            ext = ".jpg"
        elif fmt == "png":
            img.save(out, "PNG", optimize=True)
            ext = ".png"
        else:
            img.convert("RGB").save(out, "WEBP", quality=85)
            ext = ".webp"
        payload, mime = out.getvalue(), "image/" + ("jpeg" if fmt == "jpeg" else fmt)
    except StudentError:
        raise
    except Exception:
        raise StudentError(400, "photo",
                           "That file could not be read as an image.")

    directory = config.STUDENT_PHOTO_DIR
    os.makedirs(directory, exist_ok=True)
    name = secrets.token_hex(16) + ext
    tmp = os.path.join(directory, name + ".part")
    with open(tmp, "wb") as fh:
        fh.write(payload)
    os.replace(tmp, os.path.join(directory, name))

    # The row must exist before this UPDATE: a missing profile row would make
    # the write a silent no-op and the SELECT below return None (HTTP 500).
    profile = ensure_profile(db, account_id)
    old = profile["photo_file"] if profile else ""
    db.execute(
        "UPDATE student_profiles SET photo_file = ?, photo_mime = ?,"
        " photo_updated_at = ?, updated_at = ? WHERE account_id = ?",
        (name, mime, utc_now(), utc_now(), account_id))
    if old and old != name:  # bounded cleanup — replace, never accumulate
        try:
            os.remove(os.path.join(directory, os.path.basename(old)))
        except OSError:
            pass
    return db.execute("SELECT * FROM student_profiles WHERE account_id = ?",
                      (account_id,)).fetchone()


def read_photo(db, account_id):
    profile = db.execute("SELECT * FROM student_profiles WHERE account_id = ?",
                         (account_id,)).fetchone()
    if not profile or not profile["photo_file"]:
        raise StudentError(404, "photo", "No profile photo has been uploaded.")
    path = os.path.join(config.STUDENT_PHOTO_DIR,
                        os.path.basename(profile["photo_file"]))
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        raise StudentError(404, "photo", "No profile photo has been uploaded.")
    return data, profile["photo_mime"] or "image/jpeg"
