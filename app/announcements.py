"""Announcements for the active convocation (Phase 7, §3).

Draft → published → archived lifecycle with staff attribution, publication
timestamps and a full audit trail. Only published, student-audience rows
ever reach the student feed; drafts and archived rows never leave the exam
portal. Content is validated and bounded server-side.
"""

import json

from database import _now
from exam_registrations import utc_now

AUDIENCES = ("students", "staff")
STATUSES = ("draft", "published", "archived")
MAX_TITLE = 140
MAX_BODY = 4000


class AnnouncementError(Exception):
    """Rejected announcement input — message is safe to show in the portal."""


def clean(form, actor):
    """Validate the form into a complete announcement dict (no ids/times)."""
    title = (form.get("title") or "").strip()
    body = (form.get("body") or "").strip()
    if not title:
        raise AnnouncementError("A title is required.")
    if len(title) > MAX_TITLE:
        raise AnnouncementError(
            f"Title is too long (limit {MAX_TITLE} characters).")
    if not body:
        raise AnnouncementError("A body is required.")
    if len(body) > MAX_BODY:
        raise AnnouncementError(
            f"Body is too long (limit {MAX_BODY} characters).")
    audience = (form.get("audience") or "students").strip()
    if audience not in AUDIENCES:
        raise AnnouncementError("Unknown audience.")
    return {"title": title, "body": body, "audience": audience,
            "is_important": 1 if form.get("is_important") in ("1", "on",
                                                              "true") else 0,
            "actor": actor}


def get(db, ann_id):
    return db.execute("SELECT * FROM announcements WHERE id = ?",
                      (ann_id,)).fetchone()


def list_for(db, conv_id, status=None):
    sql = "SELECT * FROM announcements WHERE convocation_id = ?"
    args = [conv_id]
    if status:
        sql += " AND status = ?"
        args.append(status)
    return db.execute(sql + " ORDER BY id DESC", args).fetchall()


def counts(db, conv_id):
    """Draft / published / archived tallies for dashboard indicators."""
    rows = db.execute(
        "SELECT status, COUNT(*) AS n FROM announcements "
        "WHERE convocation_id = ? GROUP BY status", (conv_id,)).fetchall()
    out = {s: 0 for s in STATUSES}
    out.update({r["status"]: r["n"] for r in rows})
    return out


def _audit(db, ann, actor, action, before, after):
    db.execute(
        "INSERT INTO announcement_audit "
        "(announcement_id, convocation_id, actor, action, before_json, "
        " after_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ann["id"], ann["convocation_id"], actor, action,
         json.dumps(before, sort_keys=True), json.dumps(after, sort_keys=True),
         utc_now()))


def create(db, conv_id, data):
    now = _now()
    cur = db.execute(
        "INSERT INTO announcements "
        "(convocation_id, title, body, audience, status, is_important, "
        " created_by, updated_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)",
        (conv_id, data["title"], data["body"], data["audience"],
         data["is_important"], data["actor"], data["actor"], now, now))
    ann = get(db, cur.lastrowid)
    _audit(db, ann, data["actor"], "create", {}, _state(ann))
    return ann


def update(db, ann, data):
    """Edit content. Publishing/archiving is always a separate explicit act."""
    before = _state(ann)
    db.execute(
        "UPDATE announcements SET title = :title, body = :body, "
        "audience = :audience, is_important = :is_important, "
        "updated_by = :actor, updated_at = :now WHERE id = :id",
        {**{k: data[k] for k in ("title", "body", "audience",
                                 "is_important")},
         "actor": data["actor"], "now": _now(), "id": ann["id"]})
    ann = get(db, ann["id"])
    _audit(db, ann, data["actor"], "update", before, _state(ann))
    return ann


def publish(db, ann, actor):
    if ann["status"] == "published":
        raise AnnouncementError("This announcement is already published.")
    before = _state(ann)
    now = _now()
    db.execute(
        "UPDATE announcements SET status = 'published', published_at = ?, "
        "published_by = ?, archived_at = NULL, updated_by = ?, updated_at = ? "
        "WHERE id = ?",
        (now, actor, actor, now, ann["id"]))
    ann = get(db, ann["id"])
    _audit(db, ann, actor, "publish", before, _state(ann))
    return ann


def unpublish(db, ann, actor):
    """Return a published announcement to draft (withdrawn from students)."""
    if ann["status"] != "published":
        raise AnnouncementError("Only a published announcement can be withdrawn.")
    before = _state(ann)
    now = _now()
    db.execute(
        "UPDATE announcements SET status = 'draft', published_at = NULL, "
        "published_by = NULL, updated_by = ?, updated_at = ? WHERE id = ?",
        (actor, now, ann["id"]))
    ann = get(db, ann["id"])
    _audit(db, ann, actor, "unpublish", before, _state(ann))
    return ann


def archive(db, ann, actor):
    if ann["status"] == "archived":
        raise AnnouncementError("This announcement is already archived.")
    before = _state(ann)
    now = _now()
    db.execute(
        "UPDATE announcements SET status = 'archived', archived_at = ?, "
        "updated_by = ?, updated_at = ? WHERE id = ?",
        (now, actor, now, ann["id"]))
    ann = get(db, ann["id"])
    _audit(db, ann, actor, "archive", before, _state(ann))
    return ann


def restore(db, ann, actor):
    """Archived → draft."""
    if ann["status"] != "archived":
        raise AnnouncementError("Only an archived announcement can be restored.")
    before = _state(ann)
    now = _now()
    db.execute(
        "UPDATE announcements SET status = 'draft', archived_at = NULL, "
        "updated_by = ?, updated_at = ? WHERE id = ?",
        (actor, now, ann["id"]))
    ann = get(db, ann["id"])
    _audit(db, ann, actor, "restore", before, _state(ann))
    return ann


def audit_trail(db, ann_id, limit=20):
    return db.execute(
        "SELECT * FROM announcement_audit WHERE announcement_id = ? "
        "ORDER BY id DESC LIMIT ?", (ann_id, limit)).fetchall()


def feed(db, conv_id, limit=50):
    """Published, student-audience rows only — the sole student-facing query."""
    return db.execute(
        "SELECT id, title, body, audience, is_important, created_at, "
        " updated_at, published_at FROM announcements "
        "WHERE convocation_id = ? AND status = 'published' "
        "AND audience = 'students' ORDER BY published_at DESC, id DESC "
        "LIMIT ?", (conv_id, limit)).fetchall()


def _state(ann):
    return {k: ann[k] for k in
            ("title", "body", "audience", "is_important", "status",
             "published_at", "published_by", "archived_at")}