"""Opaque ID generation and HMAC signing for QR codes.

A QR payload looks like:  LGU1:K9P2M7Q4:a1b2c3d4e5
The code itself is opaque: no name, roll number, or gender is encoded in it.
All personal data lives in the server database and is looked up at scan time.
"""

import hashlib
import hmac
import secrets
import time

import config


def generate_id():
    return "".join(secrets.choice(config.ID_ALPHABET) for _ in range(config.ID_LENGTH))


def _signature(qr_id):
    mac = hmac.new(config.HMAC_SECRET, qr_id.encode("ascii"), hashlib.sha256)
    return mac.hexdigest()[:10]


def make_payload(qr_id):
    return "%s:%s:%s" % (config.ID_VERSION, qr_id, _signature(qr_id))


def _print_signature(gid, expires):
    body = "PRINT:%s:%d:%d" % (config.ID_VERSION, gid, expires)
    return hmac.new(config.HMAC_SECRET, body.encode("ascii"),
                    hashlib.sha256).hexdigest()[:20]


def make_print_token(gid, ttl_seconds):
    """Mint a guest-scoped, time-limited PRINT capability (Phase 27 C3).

    Distinct from ``make_payload``: that one authorises ADMISSION at a gate,
    this one only authorises viewing/reprinting one guest's pass artefact and
    grants no directory or admin access. Binding purpose + ``gid`` + expiry
    into the signed body means a token cannot be replayed for another guest,
    another purpose or past expiry, and cannot be forged without HMAC_SECRET.
    """
    expires = int(time.time()) + int(ttl_seconds)
    return "%d.%d.%s" % (gid, expires, _print_signature(gid, expires))


def verify_print_token(token, gid):
    """True only for an unexpired token minted FOR THIS ``gid``."""
    try:
        raw_gid, raw_exp, sig = str(token or "").strip().split(".")
        raw_gid, raw_exp = int(raw_gid), int(raw_exp)
    except (AttributeError, TypeError, ValueError):
        return False
    if raw_gid != int(gid) or raw_exp <= int(time.time()):
        return False
    return hmac.compare_digest(_print_signature(raw_gid, raw_exp), sig)


def verify_payload(payload):
    """Return (True, qr_id) if the payload is well formed and the signature
    matches, otherwise (False, None)."""
    try:
        parts = str(payload).strip().split(":")
        if len(parts) != 3:
            return False, None
        version, qr_id, sig = parts
        if version != config.ID_VERSION:
            return False, None
        if len(qr_id) != config.ID_LENGTH:
            return False, None
        if not all(c in config.ID_ALPHABET for c in qr_id):
            return False, None
        expected = _signature(qr_id)
        if not hmac.compare_digest(expected, sig):
            return False, None
        return True, qr_id
    except Exception:
        return False, None
