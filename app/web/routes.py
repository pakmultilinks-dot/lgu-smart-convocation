"""All HTTP routes: pages, scanner API, dashboard API, admin, guests, broadcast."""

import csv
import io
import os
from datetime import datetime

from flask import (Blueprint, Flask, Response, jsonify, redirect, render_template,
                   request, url_for)

import config
import database
import ids
import models
import qrgen

bp = Blueprint("main", __name__)


def _gates():
    return models.gates()


def _normalise_gender(value):
    """Accept M/F, male/female, any case; return Male/Female or the raw value."""
    v = (value or "").strip().lower()
    if v in ("m", "male", "boy", "men"):
        return "Male"
    if v in ("f", "female", "girl", "women"):
        return "Female"
    return (value or "").strip()


def _parse_roster(rows):
    """Parse roster CSV rows into (roll_no, name, gender, program) tuples.

    If the first row is a header, columns are mapped by name so any column
    order works; otherwise roll_no, name, gender, program order is assumed.
    Returns (parsed_rows, error_message_or_None).
    """
    if not rows:
        return [], None
    header_map = {
        "roll_no": "roll_no", "roll no": "roll_no", "rollno": "roll_no",
        "rollnumber": "roll_no", "roll number": "roll_no",
        "name": "name", "student name": "name", "fullname": "name",
        "full name": "name",
        "gender": "gender", "sex": "gender",
        "program": "program", "programme": "program", "degree": "program",
    }
    first = [c.strip().lower() for c in rows[0]]
    if any(c in header_map for c in first):
        idx = {}
        for i, c in enumerate(first):
            key = header_map.get(c)
            if key and key not in idx:
                idx[key] = i
        missing = [k for k in ("roll_no", "name", "gender", "program") if k not in idx]
        if missing:
            return [], ("Roster header is missing columns: %s. Expected "
                        "roll_no, name, gender, program." % ", ".join(missing))
        data = rows[1:]
        parsed = [
            (r[idx["roll_no"]].strip(), r[idx["name"]].strip(),
             _normalise_gender(r[idx["gender"]]), r[idx["program"]].strip())
            for r in data if len(r) > max(idx.values())
        ]
        return parsed, None
    parsed = [
        (r[0].strip(), r[1].strip(), _normalise_gender(r[2]), r[3].strip())
        for r in rows if len(r) >= 4
    ]
    return parsed, None


# ---------------------------------------------------------------- home
@bp.route("/")
def index():
    return render_template("index.html", gates=_gates())


# ---------------------------------------------------------------- dashboard
@bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", gates=_gates())


@bp.route("/api/dashboard")
def api_dashboard():
    return jsonify(models.dashboard())


@bp.route("/api/dashboard/summary")
def api_dashboard_summary():
    """Lightweight KPI summary: expected roster totals plus live counts."""
    return jsonify(models.dashboard_summary())


# ---------------------------------------------------------------- settings
# Event-level settings (convocation name/year/datetime/venue), editable via
# the settings screen. Dates remain placeholders until confirmed.

@bp.route("/api/settings")
def api_get_settings():
    return jsonify(database.get_settings())


@bp.route("/api/settings", methods=["PUT"])
def api_put_settings():
    data = request.get_json(force=True, silent=True) or {}
    updates = {}
    for key, value in data.items():
        if key not in database.SETTING_KEYS:
            return jsonify({"ok": False,
                            "error": "Unknown setting: %s" % key}), 400
        updates[key] = value
    if "convocation_datetime" in updates:
        try:
            datetime.fromisoformat(updates["convocation_datetime"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error":
                            "convocation_datetime must be a valid ISO 8601 datetime."}), 400
    if "convocation_year" in updates:
        year = str(updates["convocation_year"])
        if not (year.isdigit() and len(year) == 4):
            return jsonify({"ok": False, "error":
                            "convocation_year must be 4 digits."}), 400
        updates["convocation_year"] = year
    database.update_settings(updates)
    return jsonify(database.get_settings())


# ---------------------------------------------------------------- scanner
@bp.route("/scan")
def scan_page():
    return render_template("scanner.html", gates=_gates())


def process_scan(payload, gate_id, mode, volunteer, scanned_at=None, source="online"):
    """Core scan logic. Returns a dict describing the outcome for the UI."""
    ok, qr_id = ids.verify_payload(payload)
    if not ok:
        return {"status": "error", "level": "red", "title": "INVALID CODE",
                "detail": "Signature check failed. This code is tampered or forged."}
    try:
        gate_id = int(gate_id)
    except (TypeError, ValueError):
        return {"status": "error", "level": "red", "title": "NO GATE SELECTED",
                "detail": "Choose a gate before scanning."}
    if mode not in ("entry", "exit"):
        return {"status": "error", "level": "red", "title": "NO MODE SELECTED",
                "detail": "Choose Entry or Exit mode."}
    volunteer = (volunteer or "").strip() or "Volunteer"
    gate = next((g for g in _gates() if g["id"] == gate_id), None)
    if not gate:
        return {"status": "error", "level": "red", "title": "UNKNOWN GATE",
                "detail": "The selected gate does not exist."}

    person_type, person = models.find_person(qr_id)
    if not person:
        return {"status": "error", "level": "red", "title": "UNKNOWN CODE",
                "detail": "This code is not registered in the system."}

    if person_type == "guest":
        if models.guest_used(qr_id):
            return {"status": "error", "level": "red", "title": "ALREADY USED",
                    "detail": "%s: this guest pass was already used. One entry per guest."
                    % person["name"]}
        if mode == "exit":
            return {"status": "error", "level": "amber", "title": "GUEST PASS IS ENTRY ONLY",
                    "detail": "Guest passes are single-use entry passes."}
        models.record_scan(qr_id, "guest", person["name"], gate_id, "entry",
                           volunteer, scanned_at, source)
        return {"status": "ok", "level": "green", "title": "GUEST ENTRY RECORDED",
                "name": person["name"], "sub": "Guest of %s (%s)" % (
                    person["host_roll_no"], person["phone"]),
                "gate": gate["label"], "time": scanned_at or models.now_str()}

    if mode == "entry" and models.student_inside(qr_id):
        ls = models.last_scan(qr_id)
        g = next((x for x in _gates() if x["id"] == ls["gate_id"]), {})
        return {"status": "error", "level": "red", "title": "ALREADY INSIDE",
                "detail": "%s (%s) already entered at %s, %s." % (
                    person["name"], person["roll_no"], g.get("label", ""),
                    ls["scanned_at"])}
    if mode == "exit" and not models.student_inside(qr_id):
        return {"status": "error", "level": "amber", "title": "NOT INSIDE",
                "detail": "%s (%s) has no active entry to close."
                % (person["name"], person["roll_no"])}

    models.record_scan(qr_id, "student", person["name"], gate_id, mode,
                       volunteer, scanned_at, source)
    return {"status": "ok", "level": "green",
            "title": "ENTRY RECORDED" if mode == "entry" else "EXIT RECORDED",
            "name": person["name"],
            "sub": "%s, %s, %s" % (person["roll_no"], person["program"], person["gender"]),
            "gate": gate["label"], "time": scanned_at or models.now_str()}


@bp.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.get_json(force=True) or {}
    result = process_scan(data.get("payload"), data.get("gate_id"),
                          data.get("mode"), data.get("volunteer"))
    return jsonify(result)


@bp.route("/api/sync", methods=["POST"])
def api_sync():
    """Push a queue of offline scans. Each item keeps its original timestamp."""
    data = request.get_json(force=True) or {}
    items = data.get("items", [])
    results = []
    for it in items:
        r = process_scan(it.get("payload"), it.get("gate_id"), it.get("mode"),
                         it.get("volunteer"), it.get("scanned_at"), source="queued")
        results.append({"payload": it.get("payload"), "result": r})
    return jsonify({"synced": sum(1 for r in results if r["result"]["status"] == "ok"),
                    "results": results})


@bp.route("/api/demo-payload")
def api_demo_payload():
    """Demo helper: return the payload of a student currently outside."""
    st = models.first_outside_student()
    if st:
        return jsonify({"payload": ids.make_payload(st["qr_id"]),
                        "hint": "%s (%s)" % (st["name"], st["roll_no"])})
    return jsonify({"payload": None, "hint": "Everyone is inside already."})


# ---------------------------------------------------------------- admin
@bp.route("/admin", methods=["GET", "POST"])
def admin():
    msg = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "generate":
            missing = models.students_missing_ids()
            n = models.assign_ids(missing, ids.generate_id)
            msg = "%d student ID(s) generated." % n
        elif action == "rename_gate":
            models.rename_gate(request.form.get("gate_id"),
                               request.form.get("label", ""))
            msg = "Gate label updated."
        elif action == "upload_roster":
            f = request.files.get("roster")
            if f and f.filename:
                text = f.read().decode("utf-8-sig")
                rows = [r for r in csv.reader(io.StringIO(text)) if any(r)]
                parsed, header_error = _parse_roster(rows)
                if header_error:
                    msg = header_error
                else:
                    added, skipped = models.add_students(parsed)
                    missing = models.students_missing_ids()
                    models.assign_ids(missing, ids.generate_id)
                    msg = ("Roster loaded: %d added, %d skipped "
                           "(duplicates or bad rows). IDs assigned." % (added, skipped))
            else:
                msg = "No file selected."
    return render_template("admin.html", gates=_gates(), msg=msg,
                           total=len(models.all_students()),
                           with_ids=len(models.students_with_ids()))


@bp.route("/admin/cards")
def print_cards():
    students = models.students_with_ids()
    cards = [{"name": s["name"], "roll_no": s["roll_no"], "program": s["program"],
              "qr": qrgen.qr_data_uri(ids.make_payload(s["qr_id"]))}
             for s in students]
    return render_template("cards.html", cards=cards)


@bp.route("/admin/vendor.csv")
def vendor_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["roll_no", "name", "program", "qr_payload"])
    for s in models.students_with_ids():
        w.writerow([s["roll_no"], s["name"], s["program"],
                    ids.make_payload(s["qr_id"])])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             "attachment; filename=lgu_vendor_print_file.csv"})


# ---------------------------------------------------------------- guests
@bp.route("/guests", methods=["GET", "POST"])
def guests():
    err = None
    if request.method == "POST":
        gid, err = models.register_guest(request.form.get("name", ""),
                                         request.form.get("phone", ""),
                                         request.form.get("host_roll_no", ""),
                                         ids.generate_id)
        if gid:
            return redirect(url_for("main.guest_pass", gid=gid))
    return render_template("guests.html", guests=models.all_guests(), err=err)


@bp.route("/guests/<int:gid>/pass")
def guest_pass(gid):
    g = models.guest_by_id(gid)
    if not g:
        return "Guest not found.", 404
    return render_template("guest_pass.html", guest=g,
                           qr=qrgen.qr_data_uri(ids.make_payload(g["qr_id"])))


# ---------------------------------------------------------------- broadcast
@bp.route("/broadcast", methods=["GET", "POST"])
def broadcast():
    msg = None
    if request.method == "POST":
        audience = request.form.get("audience", "All students")
        message = request.form.get("message", "")
        sent_by = request.form.get("sent_by", "")
        if message.strip():
            models.add_broadcast(audience, message, sent_by)
            msg = "Broadcast logged. Demo mode: messages are recorded here, not sent by SMS."
        else:
            msg = "Message text is required."
    return render_template("broadcast.html", gates=_gates(),
                           log=models.recent_broadcasts(), msg=msg)


# ---------------------------------------------------------------- mobile JSON API
# Small JSON helpers for the Expo mobile app. HTML routes above are untouched.

@bp.route("/api/gates")
def api_gates():
    return jsonify({"gates": models.gates()})


@bp.route("/api/gates/<int:gid>/rename", methods=["POST"])
def api_rename_gate(gid):
    data = request.get_json(force=True, silent=True) or {}
    label = (data.get("label") or "").strip()
    if not label:
        return jsonify({"ok": False, "error": "Label is required."}), 400
    models.rename_gate(gid, label)
    gate = next((g for g in models.gates() if g["id"] == gid), None)
    return jsonify({"ok": True, "gate": gate})


@bp.route("/api/guests")
def api_guests():
    return jsonify({"guests": models.all_guests()})


@bp.route("/api/guests", methods=["POST"])
def api_register_guest():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    host_roll_no = (data.get("host_roll_no") or "").strip()
    if not name or not phone or not host_roll_no:
        return jsonify({"ok": False,
                        "error": "Name, phone and host roll number are required."}), 400
    gid, err = models.register_guest(name, phone, host_roll_no, ids.generate_id)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    g = models.guest_by_id(gid)
    return jsonify({"ok": True, "gid": gid,
                    "payload": ids.make_payload(g["qr_id"])})


@bp.route("/api/guest-pass/<int:gid>")
def api_guest_pass(gid):
    g = models.guest_by_id(gid)
    if not g:
        return jsonify({"ok": False, "error": "Guest not found."}), 404
    return jsonify({"ok": True, "gid": gid, "name": g["name"],
                    "phone": g["phone"], "host_roll_no": g["host_roll_no"],
                    "used": models.guest_used(g["qr_id"]),
                    "payload": ids.make_payload(g["qr_id"])})


@bp.route("/api/broadcasts")
def api_broadcasts():
    return jsonify({"log": models.recent_broadcasts()})


@bp.route("/api/broadcasts", methods=["POST"])
def api_send_broadcast():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "Message text is required."}), 400
    audience = (data.get("audience") or "All students").strip()
    sent_by = (data.get("sent_by") or "Admin").strip()
    models.add_broadcast(audience, message, sent_by)
    return jsonify({"ok": True, "note": "Logged. Demo mode: not sent by SMS."})


def create_app():
    base = os.path.dirname(os.path.abspath(__file__))
    app = Flask(__name__, template_folder=os.path.join(base, "templates"),
                static_folder=os.path.join(base, "static"))
    app.secret_key = config.SECRET_KEY
    app.register_blueprint(bp)

    @app.context_processor
    def inject_brand():
        return {"APP_NAME": config.APP_NAME, "UNIVERSITY": config.UNIVERSITY,
                "MOTTO": config.MOTTO}

    return app
