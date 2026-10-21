#!/usr/bin/env python
"""Validate the convocation email configuration — safely (Phase 16).

Three commands, in order of how much they touch the network:

  check         Static validation only. No connection, no message. Reports
                missing or inconsistent settings and never prints a password,
                app password, bearer token or verification code.
  probe         Connect, EHLO, upgrade to TLS and authenticate if a username
                is configured, then quit. NO message is sent.
  test-send     Deliver ONE message, and only when --to names a mailbox on
                this command line. Nothing is sent merely because the app
                starts or the test suite runs.

Usage (from app/):
    ..\\.venv\\Scripts\\python.exe scripts\\check_email_config.py check
    ..\\.venv\\Scripts\\python.exe scripts\\check_email_config.py probe
    ..\\.venv\\Scripts\\python.exe scripts\\check_email_config.py test-send ^
        --to operator@example.edu.pk

Exit status: 0 = configuration usable (and, for probe/test-send, the hop
succeeded), 1 = a problem was reported. Works with LGU_EMAIL_MODE=disabled —
it explains what is missing instead of failing, so it is safe to run before
any provider is chosen.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import emailer  # noqa: E402
import config  # noqa: E402


def _set(value):
    """Describe a credential without revealing it."""
    return "set (%d chars)" % len(value) if value else "not set"


def _report(mode_ok, lines):
    for line in lines:
        print(line)
    if mode_ok:
        print("Result: configuration is usable as written.")
        return 0
    print("Result: configuration is NOT usable yet. Fix the items marked"
          " [x] above.")
    return 1


def cmd_check(_args):
    """Static validation — the safe default, no network, no message."""
    print("Email configuration check (no connection, no message sent)")
    print("  LGU_EMAIL_MODE ............ %s" % config.EMAIL_MODE)
    print("  LGU_SMTP_HOST ............. %s"
          % (config.SMTP_HOST or "not set"))
    print("  LGU_SMTP_PORT ............. %d" % config.SMTP_PORT)
    print("  LGU_SMTP_TLS .............. %s" % config.SMTP_TLS)
    print("  LGU_SMTP_TIMEOUT .......... %d s" % config.SMTP_TIMEOUT)
    print("  LGU_SMTP_USER ............. %s" % _set(config.SMTP_USER))
    print("  LGU_SMTP_PASSWORD ......... %s" % _set(config.SMTP_PASSWORD))
    print("  LGU_MAIL_FROM ............. %s"
          % (config.MAIL_FROM or "not set"))
    print("  LGU_VERIFICATION_TTL ...... %d s" % config.VERIFICATION_TTL_SECONDS)
    print("  LGU_CODE_MAX_SENDS ........ %d" % config.CODE_MAX_SENDS)
    print("  LGU_CODE_MAX_ATTEMPTS ..... %d" % config.CODE_MAX_ATTEMPTS)
    print("  TLS mode .................. %s"
          % {"auto": "STARTTLS only when a username is set",
             "starttls": "always upgrade with STARTTLS",
             "ssl": "implicit TLS from connect (port 465)",
             "none": "plaintext (local test relay only)"}.get(
                 config.SMTP_TLS, "unknown"))
    print("  Authentication ............ %s"
          % ("required" if config.SMTP_USER else "not configured"))

    problems = emailer.smtp_problems()
    if config.EMAIL_MODE != "smtp":
        print()
        print("  Note: LGU_EMAIL_MODE=%r means signup and recovery answer"
              " HTTP 503 (fail closed) until SMTP is configured."
              % config.EMAIL_MODE)
    lines = []
    for problem in problems:
        lines.append("  [x] " + problem)
    if not problems:
        lines.append("  [ok] no missing or inconsistent settings found")
    return _report(not problems, lines)


def cmd_probe(args):
    """Connect, upgrade TLS and authenticate — then quit. Sends nothing."""
    status = cmd_check(args)
    if status:
        return status
    print()
    print("Probing %s:%d (no message will be sent)..."
          % (config.SMTP_HOST, config.SMTP_PORT))
    try:
        smtp = emailer._connect()
    except Exception as exc:  # noqa: BLE001 — reported by stage
        stage, detail = emailer._classify(exc)
        print("  [x] %s failed: %s" % (stage, detail))
        return 1
    try:
        print("  [ok] connection + TLS established (%s)"
              % smtp.esmtp_features.get("starttls", "smtp"))
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            print("  [ok] authentication accepted")
        else:
            print("  [ok] no username configured, authentication skipped")
    except Exception as exc:  # noqa: BLE001
        stage, detail = emailer._classify(exc)
        print("  [x] %s failed: %s" % (stage, detail))
        return 1
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
    print("Result: provider reachable. No message was sent.")
    return 0


def cmd_test_send(args):
    """Deliver exactly one message, only when --to names a mailbox."""
    if config.EMAIL_MODE != "smtp":
        print("test-send needs LGU_EMAIL_MODE=smtp; it is %r. The fake test"
              " provider never leaves this process, so it cannot prove real"
              " delivery." % config.EMAIL_MODE)
        return 1
    status = cmd_check(args)
    if status:
        return status
    print()
    print("Sending one test message to %s ..." % args.to)
    body = ("This is a test message from the LGU Smart Convocation portal.\n"
            "\n"
            "If you can read this, the configured provider accepted the\n"
            "message and delivered it to this mailbox. No student data is\n"
            "included. Safe to delete.\n")
    try:
        emailer.send_test_note(args.to, body)
    except emailer.EmailUnavailable as exc:
        print("  [x] %s failed: %s" % (exc.stage, exc.detail))
        return 1
    print("  [ok] provider accepted and reported the message as sent")
    print("Result: delivery to %s succeeded. Open the mailbox to confirm"
          " arrival." % args.to)
    return 0


def main():
    p = argparse.ArgumentParser(
        description="Validate or exercise the email configuration.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("check", help="static validation only (default, safe)")
    sub.add_parser("probe", help="connect + TLS + auth, no message")
    t = sub.add_parser("test-send", help="send ONE message to --to")
    t.add_argument("--to", required=True,
                   help="operator-controlled mailbox that will receive it")
    args = p.parse_args()
    cmd = args.cmd or "check"  # bare invocation = safe static check
    return {"check": cmd_check, "probe": cmd_probe,
            "test-send": cmd_test_send}[cmd](args)


if __name__ == "__main__":
    sys.exit(main())
