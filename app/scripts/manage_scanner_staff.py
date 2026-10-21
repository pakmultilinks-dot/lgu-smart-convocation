#!/usr/bin/env python
"""Provision and manage volunteer scanner accounts (Phase 14).

Controlled local command run on the server host. Accounts are the ONLY way to
obtain a scan-authorized session; there is no shared or default credential and
no production administrator is invented here. The scanner PIN is printed once
at creation and never stored in plaintext — reset it any time with `pin`.

Every mutating subcommand takes `--actor`, the operator recorded in the audit
log, and defaults to the current OS login — so provisioning, PIN resets, gate
changes and revocations are attributable to a named person rather than the
placeholder "system". Pass `--actor` explicitly on a shared service login.

Usage (from app/):
    ..\\.venv\\Scripts\\python.exe scripts\\manage_scanner_staff.py create ^
        --username gateA-ana --name "Ana Cruz" --gates 1,2 --actor j.dela cruz
    ..\\.venv\\Scripts\\python.exe scripts\\manage_scanner_staff.py list
    ..\\.venv\\Scripts\\python.exe scripts\\manage_scanner_staff.py gates 1 --gates 2,3
    ..\\.venv\\Scripts\\python.exe scripts\\manage_scanner_staff.py pin 1
    ..\\.venv\\Scripts\\python.exe scripts\\manage_scanner_staff.py sessions 1
    ..\\.venv\\Scripts\\python.exe scripts\\manage_scanner_staff.py revoke 1
    ..\\.venv\\Scripts\\python.exe scripts\\manage_scanner_staff.py activate 1

Every action is recorded with via=cli. That tag marks the --actor value as
LOCAL OPERATOR ATTESTATION, not verified identity: the shell proves only who
can run this file on the host. Authenticated staff actions performed in the
Examination Department portal are recorded with via=portal and an actor
derived from the server session, never from submitted form data.
"""
import argparse
import getpass
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scanner_auth  # noqa: E402


def _gates(arg):
    if not arg:
        return []
    return [int(x) for x in arg.split(",") if x.strip()]


def _default_actor():
    """Operator identity for the audit trail — a real person, never "system".

    Provisioning runs as a local command on the server host, so the OS login
    is the only identity the code can attest to without inventing a second
    auth system. `--actor` overrides it when the runner is not the account
    holder (shared service login, handover, scripted run).
    """
    try:
        return getpass.getuser() or "unknown-operator"
    except Exception:
        return "unknown-operator"


def _fail(exc):
    print("error: %s" % exc, file=sys.stderr)
    return 1


def main():
    p = argparse.ArgumentParser(description="Manage scanner accounts.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="Create a scanner account")
    c.add_argument("--username", required=True)
    c.add_argument("--name", required=True, dest="display_name")
    c.add_argument("--gates", required=True, help="comma-separated gate ids")
    c.add_argument("--pin", help="PIN (default: generated)")

    for name in ("list",):
        sub.add_parser(name, help="List scanner accounts")

    for name in ("revoke", "activate", "sessions"):
        s = sub.add_parser(name, help={
            "revoke": "Disable a scanner and kill its sessions",
            "activate": "Re-enable a scanner",
            "sessions": "Revoke a scanner's live sessions (account stays usable)",
        }[name])
        s.add_argument("scanner_id", type=int)

    g = sub.add_parser("gates", help="Set a scanner's gates")
    g.add_argument("scanner_id", type=int)
    g.add_argument("--gates", required=True)

    pi = sub.add_parser("pin", help="Reset a scanner's PIN")
    pi.add_argument("scanner_id", type=int)
    pi.add_argument("--pin", help="new PIN (default: generated)")

    # Every mutating subcommand records WHO ran it, so the audit trail names
    # an accountable operator instead of the placeholder "system".
    for subcmd in (c, g, pi, *[sub.choices[n]
                                for n in ("revoke", "activate", "sessions")]):
        subcmd.add_argument(
            "--actor", help="operator recorded in the audit log "
            "(default: the current OS login)")

    args = p.parse_args()
    # `list` takes no --actor (it mutates nothing).
    actor = (getattr(args, "actor", None) or _default_actor()).strip() \
        or scanner_auth.UNKNOWN_ACTOR

    try:
        if args.cmd == "create":
            pin = args.pin or scanner_auth.generate_pin()
            sid = scanner_auth.create_scanner(args.username, args.display_name,
                                              pin, _gates(args.gates),
                                              actor=actor,
                                              via=scanner_auth.VIA_CLI)
            print("Created scanner id=%s username=%s gates=%s by=%s" % (
                sid, args.username, args.gates, actor))
            print("PIN (shown once, not recoverable): %s" % pin)
        elif args.cmd == "list":
            rows = scanner_auth.list_scanners()
            if not rows:
                print("No scanner accounts.")
            for r in rows:
                print(("id=%s username=%s name=%s active=%s credential=%s"
                       " gates=%s live_sessions=%s last_login=%s") % (
                    r["id"], r["username"], r["display_name"], r["is_active"],
                    "established" if r["credential_established"] else "pending",
                    ",".join(str(g) for g in r["gates"]) or "-",
                    r["live_sessions"], r["last_login_at"] or "-"))
        elif args.cmd == "revoke":
            scanner_auth.deactivate_scanner(args.scanner_id, actor=actor,
                                             via=scanner_auth.VIA_CLI)
            print("Revoked scanner id=%s by=%s (sessions invalidated)." % (
                args.scanner_id, actor))
        elif args.cmd == "activate":
            scanner_auth.activate_scanner(args.scanner_id, actor=actor,
                                           via=scanner_auth.VIA_CLI)
            print("Activated scanner id=%s by=%s." % (args.scanner_id, actor))
        elif args.cmd == "sessions":
            n = scanner_auth.revoke_sessions(args.scanner_id, actor=actor,
                                              via=scanner_auth.VIA_CLI)
            print("Revoked %d live session(s) for id=%s by=%s (account stays"
                  " usable)." % (n, args.scanner_id, actor))
        elif args.cmd == "gates":
            scanner_auth.set_gates(args.scanner_id, _gates(args.gates),
                                   actor=actor, via=scanner_auth.VIA_CLI)
            print("Set gates for id=%s: %s by=%s" % (
                args.scanner_id, args.gates, actor))
        elif args.cmd == "pin":
            pin = args.pin or scanner_auth.generate_pin()
            scanner_auth.reset_pin(args.scanner_id, pin, actor=actor,
                                   via=scanner_auth.VIA_CLI)
            print("Reset PIN for id=%s by=%s. New PIN (shown once): %s" % (
                args.scanner_id, actor, pin))
    except ValueError as exc:
        return _fail(exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
