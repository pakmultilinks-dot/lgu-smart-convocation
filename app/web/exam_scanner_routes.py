"""Authenticated scanner administration inside the Examination portal (Phase 19).

Routes attach to the exam blueprint (exam_event_routes pattern) so
staff_required and the CSRF guard cover every one of them. The portal is the
only supported way to manage scanner accounts from a browser; the local
command (scripts/manage_scanner_staff.py) remains for host operators and is
tagged via=cli, i.e. operator attestation rather than verified identity.

Authorization is deliberately the smallest defensible rule: any authenticated,
active staff member may manage scanner accounts. staff_users has no role or
permission column, so inventing an institutional policy here would be a
fabrication — the enforced boundary is "authenticated staff, nobody else",
and every action is attributed to the server-side session identity. A
submitted actor/staff_id/display name is never trusted.

One-time credentials (a generated PIN) are returned only in the response that
created them. They are never stored in plaintext, never placed in a URL, and
never re-rendered — a refresh re-reads the database, which holds only a hash.
"""

import functools

from flask import abort, redirect, render_template, request, url_for

import exam_auth
import scanner_auth
from database import get_db
from web.exam_routes import _audit_mgmt_denied, bp, staff_required

DONE = {
    "created": "Account created.",
    "gates": "Gate assignments saved.",
    "pin": "PIN replaced. The previous credential no longer works.",
    "sessions": "Live sessions revoked. The account itself is still usable.",
    "revoked": "Account disabled. It cannot sign in and every session is gone.",
    "activated": "Account re-enabled.",
}


def _gates():
    db = get_db()
    try:
        return [dict(r) for r in db.execute(
            "SELECT id, code, label FROM gates ORDER BY id").fetchall()]
    finally:
        db.close()


def _gate_ids(form):
    """Gate ids from the submitted checkboxes.

    A missing or empty selection is an explicit "no gates", never a silent
    keep of the previous set — an accidental empty submit must not leave an
    operator believing access was removed when it was not.
    """
    values = form.getlist("gate_id") or (form.get("gates") or "").split(",")
    return [v.strip() for v in values if str(v).strip()]


def _mgmt_staff(view):
    """staff_required, plus a recorded rejection.

    The portal has a single staff tier (staff_users carries no role column),
    so an active authenticated staff account IS the authorization rule. An
    absent or inactive session is the only rejection — and it is recorded.
    """
    guard = staff_required(view)

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if exam_auth.current_staff() is None:
            _audit_mgmt_denied(request.path, "unauthenticated")
        return guard(*args, **kwargs)
    return wrapper


def _page(staff, extra=None):
    """Shared list-view payload, so every render lands on fresh data."""
    return {"staff": staff, "scanners": scanner_auth.list_scanners(),
            "gates": _gates(), "history": scanner_auth.history(50),
            **(extra or {})}


@bp.route("/scanners")
@_mgmt_staff
def scanners(staff):
    return render_template("exam/scanners.html",
                           **_page(staff, {"done": request.args.get("done"),
                                           "error": request.args.get("error")}))


@bp.route("/scanners/new", methods=["GET", "POST"])
@_mgmt_staff
def scanner_new(staff):
    error, one_time = None, None
    if request.method == "POST":
        # Three provisioning modes, all of which store only a scrypt hash:
        #   pending   -> no usable credential yet (nothing to verify against)
        #   supplied  -> staff types the initial PIN themselves
        #   otherwise -> a generated one-time PIN, shown exactly once below
        supplied = (request.form.get("pin") or "").strip()
        pending = request.form.get("pending") == "1"
        pin = None if pending else (supplied or scanner_auth.generate_pin())
        try:
            sid = scanner_auth.create_scanner(
                request.form.get("username"), request.form.get("display_name"),
                pin, _gate_ids(request.form), actor=staff["username"],
                via=scanner_auth.VIA_PORTAL)
        except ValueError as exc:
            error = str(exc)
        else:
            if pending or supplied:
                # Post/Redirect/Get: nothing secret exists to re-render.
                return redirect(url_for("exam.scanner_detail", scanner_id=sid,
                                        done=DONE["created"]))
            # Rendered straight from the POST, never redirected: the one-time
            # PIN exists in this single response. A refresh re-POSTs and lands
            # on the duplicate-username error, which renders no secret.
            one_time = {"username": (request.form.get("username") or "").strip(),
                        "pin": pin}
            return render_template("exam/scanners.html",
                                   **_page(staff, {"done": DONE["created"],
                                                   "one_time": one_time}))
    return render_template("exam/scanner_new.html", staff=staff, gates=_gates(),
                           error=error, form=request.form), (422 if error else 200)


@bp.route("/scanners/<int:scanner_id>", methods=["GET", "POST"])
@_mgmt_staff
def scanner_detail(staff, scanner_id):
    row = scanner_auth.get_scanner(scanner_id)
    if row is None:
        abort(404)
    error, one_time, done = None, None, None
    action = request.form.get("action") if request.method == "POST" else None
    if action:
        try:
            if action == "gates":
                scanner_auth.set_gates(scanner_id, _gate_ids(request.form),
                                       actor=staff["username"],
                                       via=scanner_auth.VIA_PORTAL)
                done = DONE["gates"]
            elif action == "pin":
                supplied = (request.form.get("pin") or "").strip()
                pin = supplied or scanner_auth.generate_pin()
                pending = scanner_auth.reset_pin(
                    scanner_id, pin, actor=staff["username"],
                    via=scanner_auth.VIA_PORTAL)
                done = ("PIN established. The account can now sign in."
                        if pending else DONE["pin"])
                if not supplied:
                    one_time = {"username": row["username"], "pin": pin}
            elif action == "revoke":
                scanner_auth.deactivate_scanner(scanner_id,
                                                 actor=staff["username"],
                                                 via=scanner_auth.VIA_PORTAL)
                done = DONE["revoked"]
            elif action == "activate":
                scanner_auth.activate_scanner(scanner_id,
                                               actor=staff["username"],
                                               via=scanner_auth.VIA_PORTAL)
                done = DONE["activated"]
            elif action == "sessions":
                scanner_auth.revoke_sessions(scanner_id,
                                              actor=staff["username"],
                                              via=scanner_auth.VIA_PORTAL)
                done = DONE["sessions"]
            else:
                error = "Unknown action."
        except ValueError as exc:
            error = str(exc)
        # No secret produced -> Post/Redirect/Get, so a refresh cannot repeat
        # the action. A one-time PIN must be shown from this very response.
        if not one_time:
            key = "error" if error else "done"
            return redirect(url_for("exam.scanner_detail", scanner_id=scanner_id,
                                    **{key: (error or done or "Saved.")[:200]}))
        row = scanner_auth.get_scanner(scanner_id)
    return render_template(
        "exam/scanner_detail.html", staff=staff, scanner=row, gates=_gates(),
        error=error, one_time=one_time, done=done,
        history=scanner_auth.history(50, username=row["username"]))