"""Convocation event management and announcements (Phase 7, §1–§3).

Routes attach to the exam blueprint (exam_reg_routes pattern) so
staff_required and the CSRF guard cover every one of them. The convocation
row is the working draft; students only ever receive the published
snapshot via the student API.
"""

from flask import redirect, render_template, request, url_for

import announcements as ann
import convocation_events as ev
from database import get_db
from web.exam_routes import bp, staff_required

DONE = {
    "saved": "Draft saved. Publishing state was not changed.",
    "published": "Published. The student app now shows this information.",
    "created": "Announcement created as a draft. Students cannot see it "
               "until you publish it.",
    "unpublished": "Withdrawn. It is back in draft and no longer visible "
                   "to students.",
    "archived": "Archived. It no longer appears in the student feed.",
    "restored": "Restored to draft.",
    "created_event": "Event created. Activate it to make it the current "
                     "convocation.",
    "activated_event": "Event activated. It is now the convocation students "
                       "see.",
}


def _done(request_args):
    return DONE.get(request_args.get("done"))


def _render_event(staff, error=None, done=None):
    db = get_db()
    conv = ev.active(db)
    pub = ev.publication(db, conv["id"]) if conv else None
    draft = None
    if conv:
        # Legacy rows can carry a full ISO datetime in expected_date; the
        # form shows (and re-saves) only the normalized date part.
        draft = ev.details_of(conv)
        for field in ("expected_date", "confirmed_date", "rehearsal_date"):
            draft[field] = (draft[field] or "")[:10]
        draft["rehearsal_time"] = (draft["rehearsal_time"] or "")[:5]
        draft["ceremony_time"] = (draft["ceremony_time"] or "")[:5]
    out = render_template(
        "exam/event.html", staff=staff, error=error, done=done, conv=conv,
        draft=draft, pub=pub, dirty=ev.is_dirty(db, conv) if conv else False,
        state=ev.date_state(conv), pub_state=ev.date_state(pub),
        events=ev.list_events(db),
        trail=ev.audit_trail(db, conv["id"]) if conv else [])
    db.close()
    return out


@bp.route("/event")
@staff_required
def event_page(staff):
    return _render_event(staff, done=_done(request.args))


@bp.route("/event/save", methods=["POST"])
@staff_required
def event_save(staff):
    db = get_db()
    conv = ev.active(db)
    if conv is None:
        db.close()
        return _render_event(staff, "No active convocation to edit.")
    try:
        changed = ev.save_details(db, conv, ev.clean_details(request.form),
                                  staff["username"])
        db.commit()
    except ev.EventError as exc:
        db.close()
        return _render_event(staff, str(exc))
    db.close()
    if not changed:
        return _render_event(staff, "No changes to save.")
    return redirect(url_for("exam.event_page", done="saved"))


@bp.route("/event/publish", methods=["POST"])
@staff_required
def event_publish(staff):
    db = get_db()
    conv = ev.active(db)
    if conv is None:
        db.close()
        return _render_event(staff, "No active convocation to publish.")
    ev.publish(db, conv, staff["username"])
    db.commit()
    db.close()
    return redirect(url_for("exam.event_page", done="published"))


@bp.route("/event/create", methods=["POST"])
@staff_required
def event_create(staff):
    db = get_db()
    try:
        ev.create_event(db, ev.clean_details(request.form), staff["username"])
        db.commit()
    except ev.EventError as exc:
        db.close()
        return _render_event(staff, str(exc))
    db.close()
    return redirect(url_for("exam.event_page", done="created_event"))


@bp.route("/event/activate", methods=["POST"])
@staff_required
def event_activate(staff):
    db = get_db()
    conv = ev.get(db, request.form.get("convocation_id", type=int) or 0)
    if conv is None:
        db.close()
        return _render_event(staff, "Unknown convocation.")
    ev.set_active(db, conv["id"], staff["username"])
    db.commit()
    db.close()
    return redirect(url_for("exam.event_page", done="activated_event"))


def _render_announcements(staff, error=None, done=None, form=None):
    db = get_db()
    conv = ev.active(db)
    out = render_template(
        "exam/announcements.html", staff=staff, error=error, done=done,
        form=form, conv=conv,
        items=ann.list_for(db, conv["id"]) if conv else [],
        counts=ann.counts(db, conv["id"]) if conv else None)
    db.close()
    return out


def _render_ann_detail(staff, ann_id, error=None, done=None, form=None):
    db = get_db()
    row = ann.get(db, ann_id)
    trail = ann.audit_trail(db, ann_id)
    db.close()
    if row is None:
        return _render_announcements(staff, "Announcement not found.")
    return render_template("exam/announcement_detail.html", staff=staff,
                           item=row, error=error, done=done, form=form,
                           trail=trail)


@bp.route("/announcements")
@staff_required
def announcements_page(staff):
    return _render_announcements(staff, done=_done(request.args))


@bp.route("/announcements/create", methods=["POST"])
@staff_required
def announcement_create(staff):
    db = get_db()
    conv = ev.active(db)
    if conv is None:
        db.close()
        return _render_announcements(
            staff, "No active convocation — announcements belong to an event.")
    try:
        row = ann.create(db, conv["id"],
                         ann.clean(request.form, staff["username"]))
        db.commit()
    except ann.AnnouncementError as exc:
        db.close()
        return _render_announcements(staff, str(exc), form=request.form)
    db.close()
    return redirect(url_for("exam.announcement_detail", ann_id=row["id"],
                            done="created"))


@bp.route("/announcements/<int:ann_id>")
@staff_required
def announcement_detail(staff, ann_id):
    db = get_db()
    exists = ann.get(db, ann_id) is not None
    db.close()
    if not exists:
        return _render_announcements(staff, "Announcement not found.")
    return _render_ann_detail(staff, ann_id, done=_done(request.args))


@bp.route("/announcements/<int:ann_id>/save", methods=["POST"])
@staff_required
def announcement_save(staff, ann_id):
    db = get_db()
    row = ann.get(db, ann_id)
    if row is None:
        db.close()
        return _render_announcements(staff, "Announcement not found.")
    try:
        ann.update(db, row, ann.clean(request.form, staff["username"]))
        db.commit()
    except ann.AnnouncementError as exc:
        db.close()
        return _render_ann_detail(staff, ann_id, str(exc), form=request.form)
    db.close()
    return redirect(url_for("exam.announcement_detail", ann_id=ann_id,
                            done="saved"))


@bp.route("/announcements/<int:ann_id>/<action>", methods=["POST"])
@staff_required
def announcement_action(staff, ann_id, action):
    actions = {"publish": ann.publish, "unpublish": ann.unpublish,
               "archive": ann.archive, "restore": ann.restore}
    db = get_db()
    row = ann.get(db, ann_id)
    if row is None:
        db.close()
        return _render_announcements(staff, "Announcement not found.")
    if action not in actions:
        db.close()
        return _render_ann_detail(staff, ann_id, "Unknown action.")
    try:
        actions[action](db, row, staff["username"])
        db.commit()
    except ann.AnnouncementError as exc:
        db.close()
        return _render_ann_detail(staff, ann_id, str(exc))
    db.close()
    return redirect(url_for("exam.announcement_detail", ann_id=ann_id,
                            done=action))