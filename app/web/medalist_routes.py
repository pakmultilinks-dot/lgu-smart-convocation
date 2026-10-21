"""Medalist management for the Exam portal: records, pictures, Excel import.

Attaches its own `medalists` blueprint under /exam/medalists; the Phase 3
CSRF guard and staff_required authorization are extended to cover this
blueprint unchanged. Nothing here is reachable without an authenticated
exam staff session, and no route touches the volunteer student roster.
"""

import io
import json

from flask import (Blueprint, abort, redirect, render_template, request,
                   send_file, url_for)

import database
import medalists as med
import medalist_import
from web.exam_routes import staff_required

bp = Blueprint("medalists", __name__, url_prefix="/exam/medalists")

PAGE = 50
_PUB_STATE = {"publish": "published", "unpublish": "draft"}


def _form_row(form):
    return {k: form.get(k, "") for k in med.FIELDS}


def _detail(staff, medalist_id, error=None, saved=False):
    db = database.get_db()
    row = med.get(db, medalist_id)
    trail = med.audit_trail(db, medalist_id) if row else []
    db.close()
    if row is None:
        abort(404)
    return render_template("medalist_detail.html", staff=staff,
                           row=dict(row), form=None, trail=trail,
                           error=error, saved=saved), \
        (400 if error else 200)


@bp.route("/")
@staff_required
def list_view(staff):
    q = request.args.get("q", "").strip()[:80]
    department = request.args.get("department", "").strip()[:120]
    category = request.args.get("category", "").strip()[:60]
    publication = request.args.get("publication", "")
    missing_photo = bool(request.args.get("missing_photo"))
    unmatched_ref = bool(request.args.get("unmatched_ref"))
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    db = database.get_db()
    conv = med.active_convocation(db)
    rows, totals, cov, departments, categories = [], {}, None, [], []
    error = None
    if conv is None:
        error = "No active convocation is configured, so medalists cannot be listed."
    else:
        rows = med.search(db, conv["id"], department, category, publication, q)
        if missing_photo:
            rows = [r for r in rows if not r["photo_file"]]
        if unmatched_ref:
            rows = [r for r in rows if r["reference_number"]
                    and not med.reference_matches(db, conv["id"],
                                                  r["reference_number"])]
        totals = med.counts(db, conv["id"])
        cov = med.coverage(db, conv["id"])
        departments = med.list_departments(db, conv["id"])
        categories = med.list_categories(db, conv["id"])
    db.close()
    start = (page - 1) * PAGE
    page_rows = rows[start:start + PAGE]
    return render_template(
        "medalists.html", staff=staff, rows=[dict(r) for r in page_rows],
        q=q, department=department, category=category,
        publication=publication, page=page,
        has_next=len(rows) > start + PAGE,
        missing_photo=missing_photo, unmatched_ref=unmatched_ref,
        totals=totals, coverage=cov, departments=departments,
        categories=categories, conv=dict(conv) if conv else None,
        error=error), (400 if error else 200)


@bp.route("/new", methods=["GET", "POST"])
@staff_required
def create(staff):
    db = database.get_db()
    conv = med.active_convocation(db)
    db.close()
    error = None
    form = _form_row(request.form) if request.method == "POST" \
        else {k: "" for k in med.FIELDS}
    if conv is None:
        error = "No active convocation is configured."
    elif request.method == "POST":
        clean, errors = med.clean_row(form)
        if errors:
            error = " ".join(errors)
        else:
            db = database.get_db()
            try:
                mid = med.insert(db, conv["id"], clean, staff["username"])
                db.commit()
            except med.MedalistError as exc:
                db.rollback()
                error = str(exc)
            finally:
                db.close()
            if error is None:
                return redirect(url_for("medalists.detail", medalist_id=mid))
    return render_template("medalist_detail.html", staff=staff, row=None,
                           form=form, trail=[], error=error), \
        (400 if error else 200)


@bp.route("/<int:medalist_id>")
@staff_required
def detail(staff, medalist_id):
    return _detail(staff, medalist_id)


@bp.route("/<int:medalist_id>/edit", methods=["POST"])
@staff_required
def edit(staff, medalist_id):
    db = database.get_db()
    row = med.get(db, medalist_id)
    db.close()
    if row is None:
        abort(404)
    try:
        with database.connection() as db:
            med.correct(db, row, request.form, staff["username"])
    except med.MedalistError as exc:
        return _detail(staff, medalist_id, error=str(exc))
    return _detail(staff, medalist_id, saved=True)


@bp.route("/<int:medalist_id>/<action>", methods=["POST"])
@staff_required
def publication(staff, medalist_id, action):
    if action not in _PUB_STATE:
        abort(404)
    db = database.get_db()
    row = med.get(db, medalist_id)
    db.close()
    if row is None:
        abort(404)
    try:
        # set_publication enforces "picture before publish" in the domain.
        with database.connection() as db:
            med.set_publication(db, row, _PUB_STATE[action],
                                staff["username"])
    except med.MedalistError as exc:
        return _detail(staff, medalist_id, error=str(exc))
    return _detail(staff, medalist_id, saved=True)


@bp.route("/<int:medalist_id>/photo", methods=["POST"])
@staff_required
def upload_photo(staff, medalist_id):
    db = database.get_db()
    row = med.get(db, medalist_id)
    db.close()
    if row is None:
        abort(404)
    upload = request.files.get("photo")
    if not upload or not upload.filename:
        return _detail(staff, medalist_id, error="Choose a picture to upload.")
    try:
        with database.connection() as db:
            med.store_photo(db, row, upload.read(), staff["username"])
    except med.MedalistError as exc:
        return _detail(staff, medalist_id, error=str(exc))
    return _detail(staff, medalist_id, saved=True)


# ------------------------------------------------------------ Excel import

def _import_page(staff, batch=None, problems=None, sample=None, error=None,
                 committed=False, problems_total=0):
    db = database.get_db()
    conv = med.active_convocation(db)
    batches = medalist_import.list_batches(db, conv["id"]) if conv else []
    db.close()
    result = json.loads(batch["result_json"]) if (
        batch and batch["result_json"]) else None
    return render_template(
        "medalist_import.html", staff=staff, batch=batch, result=result,
        problems=problems, problems_total=problems_total, sample=sample,
        batches=[dict(b) for b in batches],
        conv=dict(conv) if conv else None, error=error, committed=committed), \
        (400 if error else 200)


def _review(staff, batch_id, error=None, committed=False):
    db = database.get_db()
    batch = medalist_import.get_batch(db, batch_id)
    problems = sample = None
    problems_total = 0
    if batch is not None:
        problems = medalist_import.error_rows(db, batch_id)
        problems_total = (batch["invalid_rows"] + batch["duplicate_rows"]
                          + batch["conflict_rows"])
        sample = medalist_import.sample_rows(db, batch_id)
    db.close()
    if batch is None:
        abort(404)
    return _import_page(staff, batch=dict(batch), problems=problems,
                        sample=sample, error=error, committed=committed,
                        problems_total=problems_total)


@bp.route("/import")
@staff_required
def import_view(staff):
    return _import_page(staff)


@bp.route("/import/template")
@staff_required
def import_template(staff):
    return send_file(io.BytesIO(medalist_import.build_template()),
                     mimetype="application/vnd.openxmlformats-officedocument"
                              ".spreadsheetml.sheet",
                     as_attachment=True,
                     download_name="convocation-medalist-template.xlsx")


@bp.route("/import", methods=["POST"])
@staff_required
def import_upload(staff):
    upload = request.files.get("file")
    db = database.get_db()
    conv = med.active_convocation(db)
    db.close()
    if conv is None:
        return _import_page(staff, error="No active convocation is configured.")
    if not upload or not upload.filename:
        return _import_page(staff, error="Choose an .xlsx file to upload.")
    try:
        batch_id, _ = medalist_import.parse_upload(upload, conv["id"],
                                                   staff["username"])
    except medalist_import.ImportRejected as exc:
        return _import_page(staff, error=str(exc))
    except Exception:
        return _import_page(staff, error=(
            "The file could not be read as an Excel workbook. It may be "
            "corrupt, password-protected, or not .xlsx."))
    return redirect(url_for("medalists.import_review", batch_id=batch_id))


@bp.route("/import/<int:batch_id>")
@staff_required
def import_review(staff, batch_id):
    return _review(staff, batch_id)


@bp.route("/import/<int:batch_id>/commit", methods=["POST"])
@staff_required
def import_commit(staff, batch_id):
    try:
        medalist_import.commit_batch(batch_id, staff["username"])
    except ValueError as exc:
        return _review(staff, batch_id, error=str(exc))
    return _review(staff, batch_id, committed=True)
