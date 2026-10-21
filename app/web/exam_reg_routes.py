"""Registration management for the Exam portal: Excel import + record admin.

Every route attaches to the existing `exam` blueprint, so the Phase 3 CSRF
guard (POST-only, session-bound token) and staff_required authorization cover
these routes unchanged. Nothing here is reachable without an authenticated
exam staff session, and no route touches the volunteer student roster.
"""

import io
import json

from flask import (abort, redirect, render_template, request, send_file,
                   url_for)

import database
import exam_import
import exam_registrations as reg
from web.exam_routes import bp, staff_required

PAGE = 50
STATUS_NOTES = {
    "cancel": "The registration becomes Cancelled. It can be reinstated later.",
    "revoke": "The registration becomes Revoked. This is permanent: the "
              "identifiers stay reserved and can never be reused.",
    "reinstate": "The registration returns to Active.",
}


def _detail(staff, reg_id, error=None, saved=False, form=None):
    db = database.get_db()
    row = reg.get(db, reg_id)
    trail = reg.audit_trail(db, reg_id) if row else []
    db.close()
    if row is None:
        abort(404)
    row = dict(row)
    allowed = [(a, reg.ACTION_LABELS[a]) for a, sources in reg.ACTIONS.items()
               if row["status"] in sources]
    return render_template("exam_registration_detail.html", staff=staff,
                           row=row, trail=trail, allowed=allowed,
                           error=error, saved=saved, form=form), \
        (400 if error else 200)


def _review(staff, batch_id, error=None, committed=False):
    db = database.get_db()
    batch = exam_import.get_batch(db, batch_id)
    problems = sample = None
    problems_total = 0
    if batch is not None:
        problems = exam_import.error_rows(db, batch_id)
        problems_total = (batch["invalid_rows"] + batch["duplicate_rows"]
                          + batch["conflict_rows"])
        sample = exam_import.sample_rows(db, batch_id)
    db.close()
    if batch is None:
        abort(404)
    result = json.loads(batch["result_json"]) if batch["result_json"] else None
    return render_template("exam_import_preview.html", staff=staff,
                           batch=dict(batch), result=result, problems=problems,
                           problems_total=problems_total, sample=sample,
                           error=error, committed=committed), \
        (400 if error else 200)


@bp.route("/registrations")
@staff_required
def registrations(staff):
    q = request.args.get("q", "").strip()[:80]
    status = request.args.get("status", "")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    db = database.get_db()
    conv = reg.active_convocation(db)
    rows, totals, error = [], {}, None
    if conv is None:
        error = "No active convocation is configured, so registrations cannot be listed."
    else:
        rows = reg.search(db, conv["id"], q, status, PAGE + 1,
                          (page - 1) * PAGE)
        totals = reg.count_status(db, conv["id"])
    db.close()
    has_next = len(rows) > PAGE
    return render_template("exam_registrations.html", staff=staff,
                           rows=[dict(r) for r in rows[:PAGE]], q=q,
                           status=status, page=page, has_next=has_next,
                           totals=totals, conv=dict(conv) if conv else None,
                           error=error)


@bp.route("/registrations/template")
@staff_required
def import_template(staff):
    return send_file(io.BytesIO(exam_import.build_template()),
                     mimetype="application/vnd.openxmlformats-officedocument"
                              ".spreadsheetml.sheet",
                     as_attachment=True,
                     download_name="convocation-registration-template.xlsx")


@bp.route("/registrations/import", methods=["GET", "POST"])
@staff_required
def import_upload(staff):
    error = None
    if request.method == "POST":
        db = database.get_db()
        conv = reg.active_convocation(db)
        db.close()
        upload = request.files.get("file")
        if conv is None:
            error = "No active convocation is configured."
        elif not upload or not upload.filename:
            error = "Choose an .xlsx file to upload."
        else:
            try:
                batch_id, _ = exam_import.parse_upload(upload, conv["id"],
                                                       staff["username"])
                return redirect(url_for("exam.import_review",
                                        batch_id=batch_id))
            except exam_import.ImportRejected as exc:
                error = str(exc)
            except Exception:
                error = ("The file could not be read as an Excel workbook. "
                         "It may be corrupt, password-protected, or not .xlsx.")
    return render_template("exam_import.html", staff=staff, error=error)


@bp.route("/registrations/import/<int:batch_id>")
@staff_required
def import_review(staff, batch_id):
    return _review(staff, batch_id,
                   committed=bool(request.args.get("committed")))


@bp.route("/registrations/import/<int:batch_id>/commit", methods=["POST"])
@staff_required
def import_commit(staff, batch_id):
    mode = request.form.get("mode", "insert")
    if mode not in exam_import.MODES:
        mode = "insert"
    try:
        exam_import.commit_batch(batch_id, staff["username"], mode)
        return redirect(url_for("exam.import_review", batch_id=batch_id,
                                committed=1))
    except ValueError as exc:
        return _review(staff, batch_id, error=str(exc))
    except Exception:
        return _review(staff, batch_id,
                       error="The import failed and was fully rolled back. "
                             "No registrations were changed. Review the file "
                             "and try again.")


@bp.route("/registrations/history")
@staff_required
def import_history(staff):
    db = database.get_db()
    conv = reg.active_convocation(db)
    batches = ([{**dict(b), "result": json.loads(b["result_json"])
                 if b["result_json"] else None}
                for b in exam_import.list_batches(db, conv["id"])]
               if conv else [])
    db.close()
    return render_template("exam_import_history.html", staff=staff,
                           batches=batches, conv=dict(conv) if conv else None)


@bp.route("/registrations/<int:reg_id>")
@staff_required
def registration_detail(staff, reg_id):
    return _detail(staff, reg_id, saved=bool(request.args.get("saved")))


@bp.route("/registrations/<int:reg_id>/correct", methods=["POST"])
@staff_required
def registration_correct(staff, reg_id):
    fields = {k: request.form.get(k, "") for k in
              ("university_email", "roll_number", "student_name", "department")}
    db = database.get_db()
    row = reg.get(db, reg_id)
    if row is None:
        db.close()
        abort(404)
    error = None
    try:
        reg.correct(db, row, fields, staff["username"])
    except ValueError as exc:
        error = str(exc)
    db.close()
    if error is None:
        return redirect(url_for("exam.registration_detail", reg_id=reg_id,
                                saved=1))
    return _detail(staff, reg_id, error=error, form=request.form)


@bp.route("/registrations/<int:reg_id>/status", methods=["GET", "POST"])
@staff_required
def registration_status(staff, reg_id):
    action = (request.args.get("action") if request.method == "GET"
              else request.form.get("action", ""))
    db = database.get_db()
    row = reg.get(db, reg_id)
    if row is None:
        db.close()
        abort(404)
    error = None
    if action not in reg.ACTIONS:
        error = "Unknown action."
    elif row["status"] not in reg.ACTIONS[action]:
        error = f"Cannot {action} a registration that is {row['status']}."
    elif request.method == "POST":
        try:
            reg.set_status(db, row, action, staff["username"])
            db.close()
            return redirect(url_for("exam.registration_detail",
                                    reg_id=reg_id, saved=1))
        except ValueError as exc:
            error = str(exc)
    db.close()
    label = reg.ACTION_LABELS.get(action, "Apply")
    row = dict(row)
    return render_template(
        "exam_confirm.html", staff=staff,
        title=f"{label} registration {row['registration_number']}",
        question=f"{label} registration {row['registration_number']} "
                 f"({row['student_name']})?",
        lines=[f"Current status: {row['status']}.",
               STATUS_NOTES.get(action, "")],
        post_url=url_for("exam.registration_status", reg_id=reg_id),
        back_url=url_for("exam.registration_detail", reg_id=reg_id),
        action=action, submit_label=f"Yes, {label.lower()}",
        error=error), (400 if error else 200)
