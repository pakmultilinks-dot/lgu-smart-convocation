"""Medalist records for the Examination Department portal and public board.

Records belong to one convocation. The award slot
(department, award_category, position) is UNIQUE per convocation, so gold /
silver / bronze plus any additional officially published category or position
holder is data, not schema - nothing hard-codes three awards per department.
publication is the draft/approval gate: only 'published' rows ever reach the
student API, and every mutation writes a medalist_audit row (actor, action,
before/after JSON) attributed to the authenticated exam staff username.

Pictures are dedicated image assets (never student profile photos): validated
by magic bytes + Pillow decode, re-encoded to strip EXIF, stored under a
randomized name outside static/ and served only through the controlled public
route for published records. SQLite foreign keys are not enforced at runtime,
so callers always pass an explicit convocation_id.
"""

import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from io import BytesIO

from PIL import Image

import config

CATEGORIES = ("gold", "silver", "bronze")
PUBLICATIONS = ("draft", "published")
FIELDS = ("department", "student_name", "award_category", "position",
          "reference_number")
REQUIRED_FIELDS = ("department", "student_name", "award_category")
FIELD_LIMITS = {"department": 120, "student_name": 120,
                "award_category": 60, "position": 60,
                "reference_number": 64}
# No official identifier format was published by LGU, so any short plain
# token is accepted and matched case-insensitively against the convocation's
# registration_number / roll_number (see reference_matches). Never invented.
REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/]{0,63}$")
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_EDGE = 8000
_MAGIC = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff"}


class MedalistError(ValueError):
    """User-facing validation failure with an HTTP status and machine code."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_date():
    return datetime.now(timezone.utc).date().isoformat()


def audit(db, medalist_id, convocation_id, actor, action, before, after,
          batch_id=None):
    db.execute(
        "INSERT INTO medalist_audit"
        " (medalist_id, convocation_id, batch_id, actor, action,"
        "  before_json, after_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (medalist_id, convocation_id, batch_id, str(actor or "")[:64],
         action,
         json.dumps(before, ensure_ascii=False, sort_keys=True) if before else "",
         json.dumps(after, ensure_ascii=False, sort_keys=True) if after else "",
         utc_now()))


def active_convocation(db):
    return db.execute(
        "SELECT * FROM convocations WHERE is_active = 1 ORDER BY id LIMIT 1"
    ).fetchone()


def validate_field(name, value):
    """Clean one canonical field -> (clean_value, error_or_None)."""
    text = value.strip() if isinstance(value, str) else (
        "" if value is None else str(value).strip())
    limit = FIELD_LIMITS[name]
    if name in REQUIRED_FIELDS and not text:
        return text, "%s is required." % name
    if len(text) > limit:
        return text, "%s is longer than %d characters." % (name, limit)
    if any(ord(c) < 32 for c in text):
        return text, "%s contains control characters." % name
    if name == "award_category" and text:
        text = text.lower()
    if name == "reference_number" and text and not REFERENCE_RE.match(text):
        return text, ("reference_number must be a plain identifier such as "
                      "REG-9001 or 04550 (letters, digits, - _ / only).")
    return text, None


def clean_row(raw):
    """Validate a dict of canonical fields -> (clean dict, error list)."""
    clean, errors = {}, []
    for name in FIELDS:
        if name not in raw:
            clean[name] = ""
            if name in REQUIRED_FIELDS:
                errors.append("%s: is required." % name)
            continue
        value, err = validate_field(name, raw[name])
        clean[name] = value
        if err:
            errors.append("%s: %s" % (name, err))
    return clean, errors


def reference_matches(db, convocation_id, reference):
    """True when the optional identifier matches an official registration.

    Matched against registration_number or roll_number, case-insensitively.
    A reference that matches nothing is reported as a warning (never an
    error): no official identifier format has been confirmed by LGU.
    """
    if not reference:
        return False
    like = reference.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    row = db.execute(
        "SELECT 1 FROM convocation_registrations"
        " WHERE convocation_id = ? AND (registration_number = ? COLLATE NOCASE"
        " OR roll_number = ? COLLATE NOCASE) LIMIT 1",
        (convocation_id, reference, reference)).fetchone()
    return row is not None


def get(db, medalist_id):
    return db.execute("SELECT * FROM medalists WHERE id = ?",
                      (medalist_id,)).fetchone()


def list_departments(db, convocation_id, published_only=False):
    sql = ("SELECT DISTINCT department FROM medalists WHERE convocation_id = ?")
    if published_only:
        sql += " AND publication = 'published'"
    return [r[0] for r in db.execute(
        sql + " ORDER BY department COLLATE NOCASE", (convocation_id,))]


def list_categories(db, convocation_id, published_only=False):
    sql = ("SELECT DISTINCT award_category FROM medalists"
           " WHERE convocation_id = ?")
    if published_only:
        sql += " AND publication = 'published'"
    return [r[0] for r in db.execute(
        sql + " ORDER BY award_category COLLATE NOCASE", (convocation_id,))]


def search(db, convocation_id, department="", category="", publication="",
           query="", limit=200):
    sql = "SELECT * FROM medalists WHERE convocation_id = ?"
    args = [convocation_id]
    if department:
        sql += " AND department = ? COLLATE NOCASE"
        args.append(department)
    if category:
        sql += " AND award_category = ? COLLATE NOCASE"
        args.append(category)
    if publication in PUBLICATIONS:
        sql += " AND publication = ?"
        args.append(publication)
    if query:
        like = "%" + (query.replace("\\", "\\\\").replace("%", "\\%")
                      .replace("_", "\\_")) + "%"
        sql += (" AND (student_name LIKE ? ESCAPE '\\'"
                " OR reference_number LIKE ? ESCAPE '\\')"
                " ORDER BY student_name COLLATE NOCASE")
        args += [like, like]
    else:
        sql += (" ORDER BY department COLLATE NOCASE, award_category,"
                " position, student_name COLLATE NOCASE")
    return db.execute(sql + " LIMIT ?", (*args, limit)).fetchall()


def insert(db, convocation_id, clean, actor, batch_id=None):
    """Insert one clean record as a draft and audit it.

    Always draft: publishing requires an approved picture, which can only
    exist after the record does (see set_publication).
    """
    now = utc_now()
    try:
        cur = db.execute(
            "INSERT INTO medalists"
            " (convocation_id, department, student_name, award_category,"
            "  position, reference_number, publication, import_batch_id,"
            "  created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
            (convocation_id, clean["department"], clean["student_name"],
             clean["award_category"], clean["position"],
             clean["reference_number"], batch_id, now, now))
    except sqlite3.IntegrityError:
        raise MedalistError(
            409, "award_conflict",
            "%s %s in %s already has an award record for this convocation."
            % (clean["award_category"], clean["position"] or "medal",
               clean["department"]))
    mid = cur.lastrowid
    audit(db, mid, convocation_id, actor, "create", None,
          {k: clean[k] for k in FIELDS} | {"publication": "draft"},
          batch_id)
    return mid


def correct(db, medalist, fields, actor):
    """Apply a staff correction with before/after audit. Commits on success."""
    clean, errors = clean_row({k: fields.get(k, medalist[k]) for k in FIELDS})
    if errors:
        raise MedalistError(400, "invalid", " ".join(errors))
    changed = {k: clean[k] for k in FIELDS if clean[k] != medalist[k]}
    if not changed:
        raise MedalistError(400, "invalid",
                            "Nothing changed - all values are already correct.")
    try:
        db.execute(
            "UPDATE medalists SET"
            f" {', '.join(f'{k} = ?' for k in changed)}, updated_at = ?"
            " WHERE id = ?",
            (*changed.values(), utc_now(), medalist["id"]))
    except sqlite3.IntegrityError:
        db.rollback()
        raise MedalistError(
            409, "award_conflict",
            "Another medalist already holds that award slot "
            "(department, category, position).")
    audit(db, medalist["id"], medalist["convocation_id"], actor, "correct",
          {k: medalist[k] for k in changed}, changed)
    db.commit()
    return {**medalist, **changed}


def set_publication(db, medalist, publication, actor):
    """Publish or unpublish with audit. Commits on success.

    Publishing requires an approved picture: a card without one is not a
    publishable honours record.
    """
    if publication not in PUBLICATIONS:
        raise MedalistError(400, "invalid", "Unknown publication state.")
    if medalist["publication"] == publication:
        raise MedalistError(400, "invalid",
                            "The record is already %s." % publication)
    if publication == "published" and not medalist["photo_file"]:
        raise MedalistError(
            400, "photo",
            "Upload and approve a picture before publishing this record.")
    db.execute("UPDATE medalists SET publication = ?, updated_at = ?"
               " WHERE id = ?", (publication, utc_now(), medalist["id"]))
    audit(db, medalist["id"], medalist["convocation_id"], actor,
          "publish" if publication == "published" else "unpublish",
          {"publication": medalist["publication"]},
          {"publication": publication})
    db.commit()
    return publication


def audit_trail(db, medalist_id, limit=100):
    """Newest-first audit rows with parsed before/after diffs."""
    rows = db.execute(
        "SELECT * FROM medalist_audit WHERE medalist_id = ?"
        " ORDER BY id DESC LIMIT ?", (medalist_id, limit)).fetchall()
    out = []
    for row in rows:
        entry = dict(row)
        before = json.loads(entry["before_json"]) if entry["before_json"] else {}
        after = json.loads(entry["after_json"]) if entry["after_json"] else {}
        entry["changes"] = [(k, str(before.get(k, "-")), str(after.get(k, "-")))
                            for k in sorted(set(before) | set(after))]
        out.append(entry)
    return out


# ------------------------------------------------------------ data quality

def data_quality(db, convocation_id):
    """Genuine issues computed from records only - never invented counts.

    Returns a list of {level, text, href, label} dicts for the dashboard.
    Duplicate names are reported as warnings (two students may share a
    name); award-slot duplicates cannot exist thanks to the unique index and
    are therefore not scanned for.
    """
    rows = [dict(r) for r in db.execute(
        "SELECT * FROM medalists WHERE convocation_id = ?",
        (convocation_id,))]
    issues = []
    missing_photo = [r for r in rows if not r["photo_file"]]
    if missing_photo:
        issues.append({
            "level": "warn",
            "text": "%d medalist record%s have no picture. Published cards "
                    "without a picture show a placeholder until one is "
                    "uploaded." % (len(missing_photo),
                                   "" if len(missing_photo) == 1 else "s"),
            "href": "/exam/medalists?missing_photo=1",
            "label": "Open records without pictures"})
    by_name = {}
    for r in rows:
        by_name.setdefault(r["student_name"].strip().lower(), []).append(r)
    dupes = {k: v for k, v in by_name.items() if len(v) > 1}
    if dupes:
        sample = sorted(dupes)[0]
        first = dupes[sample][0]
        issues.append({
            "level": "warn",
            "text": "%d student name%s appear more than once in this "
                    "convocation's medalist list. Confirm they are different "
                    "people (e.g. %r) before publishing."
                    % (len(dupes), "" if len(dupes) == 1 else "s",
                       dupes[sample][0]["student_name"]),
            "href": "/exam/medalists?q=%s" % first["student_name"],
            "label": "Review the duplicate names"})
    unmatched = [r for r in rows
                 if r["reference_number"] and not reference_matches(
                     db, convocation_id, r["reference_number"])]
    if unmatched:
        issues.append({
            "level": "warn",
            "text": "%d record%s carry a reference number that matches no "
                    "official registration in this convocation."
                    % (len(unmatched), "" if len(unmatched) == 1 else "s"),
            "href": "/exam/medalists?unmatched_ref=1",
            "label": "Review the unmatched references"})
    return issues


def coverage(db, convocation_id):
    """Award coverage per department against the categories in use.

    Returns (departments, categories, missing) where missing is a list of
    {department, missing} rows. The baseline gold/silver/bronze expectation
    is only applied when the convocation has at least one record (an empty
    board is reported by the dashboard as "no records", not as 30 missing
    awards).
    """
    departments = list_departments(db, convocation_id)
    categories = list_categories(db, convocation_id)
    if not categories:
        categories = list(CATEGORIES)
    present = {(r["department"].lower(), r["award_category"].lower())
               for r in db.execute(
                   "SELECT department, award_category FROM medalists"
                   " WHERE convocation_id = ?", (convocation_id,))}
    missing = [{"department": d,
                "missing": [c for c in categories
                            if (d.lower(), c.lower()) not in present]}
               for d in departments]
    missing = [m for m in missing if m["missing"]]
    return departments, categories, missing


def counts(db, convocation_id):
    """Real COUNT queries for the dashboard."""
    out = {"total": 0, "published": 0, "draft": 0, "missing_photo": 0,
           "with_photo": 0}
    for row in db.execute(
            "SELECT publication, COUNT(*) AS n,"
            " SUM(CASE WHEN photo_file = '' THEN 1 ELSE 0 END) AS no_photo"
            " FROM medalists WHERE convocation_id = ? GROUP BY publication",
            (convocation_id,)):
        out["total"] += row["n"]
        out[row["publication"]] = row["n"]
        out["missing_photo"] += row["no_photo"]
    out["with_photo"] = out["total"] - out["missing_photo"]
    return out


# ------------------------------------------------------------ pictures

def _sniff(data):
    if data.startswith(_MAGIC["png"]):
        return "png", "image/png"
    if data.startswith(_MAGIC["jpeg"]):
        return "jpeg", "image/jpeg"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None, None


def store_photo(db, medalist, data, actor):
    """Validate + re-encode (strips EXIF), save under a random name.

    The filename from any upload is never trusted: bytes are sniffed for
    real image magic, fully decoded by Pillow, size-capped, then written to
    a fresh secrets.token_hex name via an atomic rename. Commits on success.
    """
    if len(data) > config.MEDALIST_PHOTO_MAX_BYTES:
        raise MedalistError(
            400, "photo", "The picture is larger than the %d MB limit."
            % (config.MEDALIST_PHOTO_MAX_BYTES // (1024 * 1024)))
    fmt, mime = _sniff(data)
    if fmt is None:
        raise MedalistError(400, "photo",
                            "The picture must be a JPEG, PNG, or WebP image.")
    try:
        img = Image.open(BytesIO(data))
        if img.width * img.height > MAX_IMAGE_PIXELS or \
                img.width > MAX_IMAGE_EDGE or img.height > MAX_IMAGE_EDGE:
            raise MedalistError(400, "photo",
                                "That image has too many pixels. Choose a "
                                "picture under 20 megapixels.")
        img.load()  # fully decodes - raises on truncated/corrupt data
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
    except MedalistError:
        raise
    except Exception:
        raise MedalistError(400, "photo",
                            "That file could not be read as an image.")

    directory = config.MEDALIST_PHOTO_DIR
    os.makedirs(directory, exist_ok=True)
    name = secrets.token_hex(16) + ext
    tmp = os.path.join(directory, name + ".part")
    with open(tmp, "wb") as fh:
        fh.write(payload)
    os.replace(tmp, os.path.join(directory, name))

    old = medalist["photo_file"]
    db.execute(
        "UPDATE medalists SET photo_file = ?, photo_mime = ?,"
        " photo_updated_at = ?, updated_at = ? WHERE id = ?",
        (name, mime, utc_now(), utc_now(), medalist["id"]))
    audit(db, medalist["id"], medalist["convocation_id"], actor,
          "photo_set" if not old else "photo_replace",
          {"photo_file": bool(old)}, {"photo_file": True})
    db.commit()
    if old and old != name:  # bounded cleanup - replace, never accumulate
        try:
            os.remove(os.path.join(directory, os.path.basename(old)))
        except OSError:
            pass
    return db.execute("SELECT * FROM medalists WHERE id = ?",
                      (medalist["id"],)).fetchone()


def read_photo(db, medalist_id):
    """Read a stored picture. Only published records are publicly readable."""
    row = get(db, medalist_id)
    if row is None or row["publication"] != "published" or not row["photo_file"]:
        raise MedalistError(404, "photo", "No published picture exists.")
    path = os.path.join(config.MEDALIST_PHOTO_DIR,
                        os.path.basename(row["photo_file"]))
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        raise MedalistError(404, "photo", "No published picture exists.")
    return data, row["photo_mime"] or "image/jpeg"


# ------------------------------------------------------------ public board

def public_payload(db, convocation_id):
    """The ONLY shape the student API may return: grouping + name + picture.

    Private fields (reference_number, publication, timestamps, import batch,
    audit data) never enter this payload. The picture reference is the
    record id used by the controlled image route - never a file path.
    """
    rows = db.execute(
        "SELECT id, department, student_name, award_category, position,"
        " photo_file, photo_updated_at FROM medalists"
        " WHERE convocation_id = ? AND publication = 'published'"
        " ORDER BY department COLLATE NOCASE, award_category, position,"
        " student_name COLLATE NOCASE",
        (convocation_id,)).fetchall()
    return [{"id": r["id"], "department": r["department"],
             "student_name": r["student_name"],
             "award_category": r["award_category"], "position": r["position"],
             "has_photo": bool(r["photo_file"])} for r in rows]