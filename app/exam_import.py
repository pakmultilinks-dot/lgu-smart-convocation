"""Excel (.xlsx) import for convocation registrations: preview then commit.

Canonical template columns (no official Examination Department format was
supplied, so this is the documented assumption - see the template's notes
sheet): registration_number, university_email, roll_number, student_name,
department. Extra columns are tolerated and reported, never trusted.

Flow: parse + validate the whole file in memory, then write batch + staging
rows in ONE transaction (preview never touches official registration rows).
Commit re-evaluates every structurally-clean row against the current DB inside
a single write transaction: insert new rows, optionally replace changed fields
(mode='replace'), never delete anything. Any unexpected error rolls the whole
commit back and marks the batch failed.
"""

import hashlib
import io
import json
import os
import re
import zipfile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

import database
import exam_auth
import exam_registrations as reg

# Limits read at call time so tests can tune them. 6,000 students fit with
# headroom: 5 MB of xlsx holds far more than 6,500 rows.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_DATA_ROWS = 6500
MAX_ERROR_ROWS = 200
SAMPLE_ROWS = 15
MODES = ("insert", "replace")


class ImportRejected(ValueError):
    """File-level rejection: no batch row is created."""


def _cell_text(value):
    """Canonical text for a cell, or None when the value is malformed."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    return None  # dates and anything else are malformed for these columns


def _normalise_header(value):
    text = ("" if value is None else str(value)).strip().lower()
    return re.sub(r"[\s\-]+", "_", text)


def _safe_filename(name):
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = re.sub(r"[^\w.\- ]", "_", name)[:120]
    return name or "upload.xlsx"


def build_template():
    """Standard .xlsx template: header-only registrations sheet + notes."""
    wb = Workbook()
    ws = wb.active
    ws.title = "registrations"
    ws.append(list(reg.CANONICAL_COLUMNS))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for col, width in zip("ABCDE", (22, 32, 14, 28, 24)):
        ws.column_dimensions[col].width = width

    notes = wb.create_sheet("notes")
    for row in (
        ("Convocation registration import - canonical template", ""),
        ("", ""),
        ("Required columns", "registration_number, university_email, roll_number, student_name"),
        ("Optional column", "department"),
        ("Extra columns", "Tolerated: they are reported in the preview and never imported."),
        ("Identifiers", "Stored as TEXT. Format cells as text (or prefix with ') to keep leading zeros, e.g. 04550."),
        ("Example row (for reference only - delete before uploading)",
         "045501 | student01@university.edu.pk | 04550 | Jane Doe | Computer Science"),
        ("", ""),
        ("Assumption", "No official Examination Department Excel format was provided. This template defines the canonical columns; if the issued sheet uses different header names, map them to these five before uploading."),
        ("Scope", "Rows are imported for the currently active convocation only."),
        ("Safety", "Preview never changes official records. Commit inserts new rows; existing registrations are only updated in Replace mode and are never deleted."),
    ):
        notes.append(row)
    notes.column_dimensions["A"].width = 46
    notes.column_dimensions["B"].width = 90

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def parse_upload(file_storage, convocation_id, actor):
    """Validate an uploaded .xlsx and stage it as a preview batch.

    Returns (batch_id, summary). Raises ImportRejected for file-level
    problems, in which case no batch row exists.
    """
    data = file_storage.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise ImportRejected("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImportRejected(
            f"File is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ImportRejected(
            "Not a valid .xlsx file. Old .xls files and CSVs are not supported - "
            "please use the downloadable template.")
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ImportRejected("The file could not be read as an Excel workbook.")
    try:
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        try:
            header = next(rows)
        except StopIteration:
            raise ImportRejected("The first worksheet is empty.")
        index, ignored = {}, []
        for pos, value in enumerate(header):
            name = _normalise_header(value)
            if name in reg.CANONICAL_COLUMNS and name not in index:
                index[name] = pos
            elif name:
                ignored.append(name)
        missing = [c for c in reg.CANONICAL_COLUMNS
                   if c not in index and c != "department"]
        if missing:
            raise ImportRejected(
                "Missing required column(s): " + ", ".join(missing) +
                ". Download the standard template for the exact headers.")

        db = database.get_db()
        try:
            db_regs = {r[0].lower() for r in db.execute(
                "SELECT registration_number FROM convocation_registrations"
                " WHERE convocation_id = ?", (convocation_id,))}
            db_rolls = {r[0].lower() for r in db.execute(
                "SELECT roll_number FROM convocation_registrations"
                " WHERE convocation_id = ?", (convocation_id,))}
            db_emails = {r[0].lower() for r in db.execute(
                "SELECT university_email FROM convocation_registrations"
                " WHERE convocation_id = ?", (convocation_id,))}
        finally:
            db.close()

        staged, seen = [], {k: {} for k in
                            ("registration_number", "roll_number", "university_email")}
        blank = total = 0
        for row_no, row in enumerate(rows, start=2):
            total += 1
            if total > MAX_DATA_ROWS:
                raise ImportRejected(
                    f"More than {MAX_DATA_ROWS} data rows. Split the file.")
            cells = row or ()
            if not any(v is not None and str(v).strip() for v in cells):
                blank += 1
                continue
            raw, errors = {}, []
            for name in reg.CANONICAL_COLUMNS:
                pos = index.get(name)
                text = _cell_text(cells[pos]) if pos is not None and pos < len(cells) else ""
                if text is None:
                    errors.append(f"{name}: unsupported cell value.")
                    text = ""
                raw[name] = text
            clean, row_errors = reg.clean_row(raw)
            errors.extend(row_errors)
            status = "valid" if not errors else "invalid"
            if not errors:
                dup = next(((k, seen[k][clean[k]]) for k in seen
                            if clean[k] in seen[k]), None)
                if dup:
                    status = "duplicate"
                    errors.append(f"{dup[0]} duplicates row {dup[1]} of this file.")
                else:
                    for k in seen:
                        seen[k][clean[k]] = row_no
                    if (clean["registration_number"].lower() in db_regs
                            or clean["roll_number"].lower() in db_rolls
                            or clean["university_email"].lower() in db_emails):
                        status = "conflict"
                        errors.append(
                            "Already exists in the official records for this convocation.")
            staged.append((row_no, clean, status, errors))

        counts = {"valid": 0, "invalid": 0, "duplicate": 0, "conflict": 0}
        for _, _, status, _ in staged:
            counts[status] += 1
        now = reg.utc_now()
        # Fresh connection: batch + staging rows must land in one transaction
        # so a failed preview leaves no partial batch behind.
        db = database.get_db()
        try:
            cur = db.execute(
                "INSERT INTO import_batches"
                " (convocation_id, filename, file_sha256, status, total_rows,"
                "  blank_rows, valid_rows, invalid_rows, duplicate_rows,"
                "  conflict_rows, notes, created_by, created_at)"
                " VALUES (?, ?, ?, 'preview', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (convocation_id, _safe_filename(file_storage.filename),
                 hashlib.sha256(data).hexdigest(), total, blank,
                 counts["valid"], counts["invalid"], counts["duplicate"],
                 counts["conflict"],
                 "Ignored columns: " + ", ".join(sorted(set(ignored))) if ignored else "",
                 str(actor or "")[:64], now))
            batch_id = cur.lastrowid
            db.executemany(
                "INSERT INTO import_staging"
                " (batch_id, row_no, registration_number, university_email,"
                "  roll_number, student_name, department, status, errors_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(batch_id, row_no, clean["registration_number"],
                  clean["university_email"], clean["roll_number"],
                  clean["student_name"], clean["department"], status,
                  json.dumps(errors, ensure_ascii=False), now)
                 for row_no, clean, status, errors in staged])
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return batch_id, {"total_rows": total, "blank_rows": blank, **counts}
    finally:
        wb.close()


def _insert_row(db, convocation_id, clean, batch_id, actor):
    """Indirection so tests can force a mid-commit failure."""
    return reg.insert(db, convocation_id, clean, batch_id, actor)


def commit_batch(batch_id, actor, mode="insert"):
    """Apply staged valid rows in one transaction. Returns result counts.

    insert (default): only add registrations that do not exist yet; rows whose
    identifiers collide with a different registration are skipped.
    replace: additionally update changed fields of matching registrations
    (audited, status untouched). Nothing is ever deleted.
    """
    if mode not in MODES:
        raise ValueError("Unknown import mode.")
    db = database.get_db()
    txn_started = False  # only a real transaction failure marks the batch failed
    try:
        batch = db.execute("SELECT * FROM import_batches WHERE id = ?",
                           (batch_id,)).fetchone()
        if batch is None:
            raise ValueError("Import batch not found.")
        if batch["status"] != "preview":
            raise ValueError(f"Batch is already {batch['status']}.")
        convocation_id = batch["convocation_id"]
        skipped = {s: db.execute(
            "SELECT COUNT(*) FROM import_staging WHERE batch_id = ? AND status = ?",
            (batch_id, s)).fetchone()[0] for s in ("invalid", "duplicate")}
        rows = db.execute(
            "SELECT * FROM import_staging WHERE batch_id = ?"
            " AND status IN ('valid', 'conflict') ORDER BY row_no",
            (batch_id,)).fetchall()

        reg_map, roll_map, email_map = {}, {}, {}
        for r in db.execute("SELECT * FROM convocation_registrations"
                            " WHERE convocation_id = ?", (convocation_id,)):
            d = dict(r)
            reg_map[d["registration_number"].lower()] = d
            roll_map[d["roll_number"].lower()] = d["id"]
            email_map[d["university_email"].lower()] = d["id"]

        counts = {"inserted": 0, "updated": 0, "unchanged": 0,
                  "skipped_conflict": 0, "skipped_invalid": skipped["invalid"],
                  "skipped_duplicate": skipped["duplicate"]}
        db.execute("BEGIN IMMEDIATE")
        txn_started = True
        for row in rows:
            clean = {k: row[k] for k in reg.REG_FIELDS}
            key = clean["registration_number"].lower()
            current = reg_map.get(key)
            current_id = current["id"] if current else None
            owner_roll = roll_map.get(clean["roll_number"].lower())
            owner_email = email_map.get(clean["university_email"].lower())
            if owner_roll not in (None, current_id) or owner_email not in (None, current_id):
                counts["skipped_conflict"] += 1
                continue
            if current is None:
                rid = _insert_row(db, convocation_id, clean, batch_id, actor)
                now = reg.utc_now()
                entry = {**clean, "id": rid, "convocation_id": convocation_id,
                         "status": "active", "import_batch_id": batch_id,
                         "created_at": now, "updated_at": now}
                reg_map[key] = entry
                roll_map[clean["roll_number"].lower()] = rid
                email_map[clean["university_email"].lower()] = rid
                counts["inserted"] += 1
                continue
            changed = {k: clean[k] for k in reg.REG_FIELDS if clean[k] != current[k]}
            if not changed:
                counts["unchanged"] += 1
                continue
            if mode != "replace":
                counts["skipped_conflict"] += 1
                continue
            db.execute(
                "UPDATE convocation_registrations SET"
                f" {', '.join(f'{k} = ?' for k in changed)}, updated_at = ?"
                " WHERE id = ?",
                (*changed.values(), reg.utc_now(), current["id"]))
            reg.audit(db, current["id"], convocation_id, actor, "import_update",
                      {k: current[k] for k in changed}, changed, batch_id)
            for k, m in (("roll_number", roll_map), ("university_email", email_map)):
                old_key = current[k].lower()
                if m.get(old_key) == current["id"]:
                    m.pop(old_key, None)
                m[clean[k].lower()] = current["id"]
            current.update(changed)
            counts["updated"] += 1

        result = {**counts, "mode": mode}
        db.execute(
            "UPDATE import_batches SET status = 'committed', mode = ?,"
            " result_json = ?, committed_at = ? WHERE id = ?",
            (mode, json.dumps(result), reg.utc_now(), batch_id))
        exam_auth.audit(db, actor, "import_committed",
                        f"batch {batch_id}: {counts['inserted']} inserted, "
                        f"{counts['updated']} updated, "
                        f"{counts['unchanged']} unchanged, "
                        f"{counts['skipped_conflict']} skipped ({mode})")
        db.commit()
        return result
    except Exception:
        db.rollback()
        if txn_started:
            try:
                db.execute("UPDATE import_batches SET status = 'failed',"
                           " result_json = ? WHERE id = ? AND status = 'preview'",
                           (json.dumps({"error": "commit rolled back"}), batch_id))
                exam_auth.audit(db, actor, "import_failed",
                                f"batch {batch_id}: commit rolled back, no records changed")
                db.commit()
            except Exception:
                db.rollback()
        raise
    finally:
        db.close()


def get_batch(db, batch_id):
    return db.execute("SELECT * FROM import_batches WHERE id = ?",
                      (batch_id,)).fetchone()


def list_batches(db, convocation_id, limit=50):
    return db.execute(
        "SELECT * FROM import_batches WHERE convocation_id = ?"
        " ORDER BY id DESC LIMIT ?", (convocation_id, limit)).fetchall()


def error_rows(db, batch_id, limit=MAX_ERROR_ROWS):
    rows = db.execute(
        "SELECT * FROM import_staging WHERE batch_id = ?"
        " AND status IN ('invalid', 'duplicate', 'conflict')"
        " ORDER BY row_no LIMIT ?", (batch_id, limit)).fetchall()
    return [{**dict(r), "errors": json.loads(r["errors_json"])} for r in rows]


def sample_rows(db, batch_id, limit=SAMPLE_ROWS):
    return db.execute(
        "SELECT * FROM import_staging WHERE batch_id = ? AND status = 'valid'"
        " ORDER BY row_no LIMIT ?", (batch_id, limit)).fetchall()