"""Opaque ID generation and HMAC signing for QR codes.

A QR payload looks like:  LGU1:K9P2M7Q4:a1b2c3d4e5
The code itself is opaque: no name, roll number, or gender is encoded in it.
All personal data lives in the server database and is looked up at scan time.
"""

import hashlib
import hmac
import secrets

import config


def generate_id():
    return "".join(secrets.choice(config.ID_ALPHABET) for _ in range(config.ID_LENGTH))


def _signature(qr_id):
    mac = hmac.new(config.HMAC_SECRET, qr_id.encode("ascii"), hashlib.sha256)
    return mac.hexdigest()[:10]


def make_payload(qr_id):
    return "%s:%s:%s" % (config.ID_VERSION, qr_id, _signature(qr_id))


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
