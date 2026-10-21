"""Fail-closed verification-email delivery (Phase 5, hardened in Phase 16).

There is no "console" or "dev" delivery mode: a code that cannot be sent is
never accepted silently. With the default LGU_EMAIL_MODE=disabled the sender
raises EmailUnavailable and routes answer HTTP 503, so signup and recovery
stay closed until an operator configures SMTP. The "fake" mode stores codes
in an in-process outbox for the test suite only — it refuses to run on the
production database or outside LGU_TESTING.

Every SMTP failure carries a (stage, detail) pair — config, connect, tls,
auth or send — so the operator tool scripts/check_email_config.py can name
the failing hop. Routes discard that pair and answer a generic student
message, so provider internals never reach a client, and nothing here is
logged: no code, password or token can leak into a log file.
"""

import os
import socket
import smtplib
import ssl
from email.message import EmailMessage

import config

OUTBOX = []  # [(to_email, code)] — test-only mirror, never a delivery path.

# Accepted LGU_SMTP_TLS values, in the order the operator tool lists them.
TLS_MODES = ("auto", "starttls", "ssl", "none")


class EmailUnavailable(RuntimeError):
    """Raised when verification email cannot be delivered right now.

    stage names the failing hop (config/connect/tls/auth/send); detail is an
    operator-facing cause that never contains a password or token.
    """

    def __init__(self, message, stage="unavailable", detail=""):
        super().__init__(message)
        self.stage = stage
        self.detail = detail


def _fake_allowed():
    return (os.environ.get("LGU_TESTING") == "1"
            and not config.is_production_db())


def smtp_problems():
    """Secret-free list of reasons SMTP delivery cannot work right now."""
    problems = []
    if config.EMAIL_MODE not in ("disabled", "fake", "smtp"):
        problems.append("LGU_EMAIL_MODE must be disabled, fake or smtp "
                        "(got %r)." % config.EMAIL_MODE)
    if config.EMAIL_MODE != "smtp":
        return problems
    if not config.SMTP_HOST:
        problems.append("LGU_SMTP_HOST is required when LGU_EMAIL_MODE=smtp.")
    if config.SMTP_PORT < 1 or config.SMTP_PORT > 65535:
        problems.append("LGU_SMTP_PORT must be a valid TCP port (got %d)."
                        % config.SMTP_PORT)
    if config.SMTP_TLS not in TLS_MODES:
        problems.append("LGU_SMTP_TLS must be one of %s (got %r)."
                        % (", ".join(TLS_MODES), config.SMTP_TLS))
    if config.SMTP_TIMEOUT < 1:
        problems.append("LGU_SMTP_TIMEOUT must be at least 1 second "
                        "(got %d)." % config.SMTP_TIMEOUT)
    if not (config.MAIL_FROM or config.SMTP_USER):
        problems.append("LGU_MAIL_FROM must hold the sender address when no "
                        "LGU_SMTP_USER is configured.")
    if config.SMTP_USER and not config.SMTP_PASSWORD:
        problems.append("LGU_SMTP_USER is set but LGU_SMTP_PASSWORD is empty.")
    if config.SMTP_PASSWORD and not config.SMTP_USER:
        problems.append("LGU_SMTP_PASSWORD is set but LGU_SMTP_USER is empty.")
    if config.VERIFICATION_TTL_SECONDS < 60:
        problems.append("LGU_VERIFICATION_TTL must be at least 60 seconds.")
    return problems


def available():
    """True when a real or test delivery path exists right now.

    Routes probe this BEFORE any account lookup, so an unconfigured service
    cannot be used as an "email exists" oracle.
    """
    if config.EMAIL_MODE == "fake":
        return _fake_allowed()
    if config.EMAIL_MODE != "smtp":
        return False
    return not smtp_problems()


def _connect():
    """Open an SMTP session per LGU_SMTP_TLS. Sends nothing.

    "auto" preserves the historical behaviour: STARTTLS only when a username
    is configured. "ssl" is implicit TLS (normally port 465).
    """
    ctx = ssl.create_default_context()
    if config.SMTP_TLS == "ssl":
        return smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT,
                                timeout=config.SMTP_TIMEOUT, context=ctx)
    smtp = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT,
                        timeout=config.SMTP_TIMEOUT)
    try:
        if config.SMTP_TLS == "starttls" or (
                config.SMTP_TLS == "auto" and config.SMTP_USER):
            smtp.starttls(context=ctx)
            smtp.ehlo()
    except BaseException:
        smtp.close()
        raise
    return smtp


def _classify(exc):
    """Map an exception to a (stage, secret-free detail) pair."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "auth", "the server rejected the configured credentials"
    if isinstance(exc, ssl.SSLError):
        return "tls", "TLS handshake failed (%s)" % type(exc).__name__
    if isinstance(exc, socket.gaierror):
        return "connect", "the SMTP hostname could not be resolved"
    if isinstance(exc, smtplib.SMTPConnectError):
        return "connect", "the SMTP server refused the connection"
    if isinstance(exc, smtplib.SMTPException):
        return "send", "the SMTP server reported an error (%s)" % type(exc).__name__
    if isinstance(exc, TimeoutError):
        return "connect", "the SMTP server did not answer within the timeout"
    if isinstance(exc, (ConnectionError, OSError)):
        return "connect", "network error reaching the SMTP server (%s)" % type(exc).__name__
    return "send", "unexpected delivery failure (%s)" % type(exc).__name__


def _deliver(msg):
    """Send one message over SMTP. Returns None, or raises EmailUnavailable."""
    smtp = None
    try:
        smtp = _connect()
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(msg)
        return None
    except Exception as exc:
        stage, detail = _classify(exc)
        raise EmailUnavailable("The mail server could not be reached.",
                               stage, detail) from None
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:
                pass


def _message(to_email, subject, body):
    msg = EmailMessage()
    msg["From"] = config.MAIL_FROM or config.SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def send_verification(to_email, code):
    mode = config.EMAIL_MODE
    if mode == "fake":
        if not _fake_allowed():
            raise EmailUnavailable("The test email provider is disabled "
                                   "outside test mode.")
        OUTBOX.append((to_email, code))
        return
    if mode == "smtp":
        problems = smtp_problems()
        if problems:
            raise EmailUnavailable("Email delivery is not configured on this "
                                   "server.", "config", problems[0])
        _deliver(_message(
            to_email, "Your convocation portal verification code",
            "Your verification code is: %s\n\nIt expires in %d minutes. "
            "If you did not request it, ignore this message."
            % (code, config.VERIFICATION_TTL_SECONDS // 60)))
        return
    raise EmailUnavailable("Email delivery is not configured on this server.",
                           "config", "LGU_EMAIL_MODE=%r" % mode)


def send_test_note(to_email, body):
    """Deliver one operator-requested test message. Returns None.

    Only scripts/check_email_config.py calls this, and only after an explicit
    --test-send with a mailbox on the command line — never a route, the app
    itself, or the test suite. It rides the same connect/auth/send path as a
    real verification code, so a pass proves the provider works end to end.
    """
    problems = smtp_problems()
    if problems:
        raise EmailUnavailable("Email delivery is not configured on this "
                               "server.", "config", problems[0])
    _deliver(_message(to_email, "LGU convocation portal test message", body))
