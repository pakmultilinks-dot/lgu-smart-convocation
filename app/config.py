import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# --- Phase 35I: test database isolation ---------------------------------
# Production always uses app/lgu.db. The automated test suite points the
# backend at a dedicated disposable database by setting LGU_DB_PATH before
# starting Flask (mobile/scripts/api-test.mjs). Nothing in the application
# startup path performs destructive resets.
PRODUCTION_DB_PATH = os.path.join(BASE_DIR, "lgu.db")
DB_PATH = os.environ.get("LGU_DB_PATH") or PRODUCTION_DB_PATH


def is_production_db(path=None):
    """True when the given (or configured) DB path is the production file."""
    return os.path.abspath(path or DB_PATH) == os.path.abspath(PRODUCTION_DB_PATH)


def positive_int(name, default):
    """Read an integer env var, falling back to `default` when unusable.

    Any non-numeric, empty or non-positive value resolves to the default
    instead of raising at import, so a typo in an operator's environment
    degrades to the documented behaviour rather than taking the service
    down — and never silently disables a limit (0 would mean "no limit").
    """
    raw = os.environ.get(name)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def require_test_db(path=None):
    """Safety guard: refuse to run test-mode against the production database.

    Test execution sets LGU_TESTING=1 together with LGU_DB_PATH. If the
    configured path still resolves to app/lgu.db we fail loudly before any
    seed/write happens — never a silent fallback to production.
    """
    resolved = os.path.abspath(path or DB_PATH)
    if is_production_db(resolved):
        raise SystemExit(
            "FATAL: test database path resolves to the production database "
            "(%s). Set LGU_DB_PATH to a separate test database." % resolved
        )
    return resolved


SECRET_KEY = os.environ.get("LGU_SECRET_KEY", "lgu-convocation-demo-key-change-in-production")
# QR signing secret (bytes). Set LGU_HMAC_SECRET in the environment on the
# real server; the committed value is a demo default. Changing it
# invalidates previously issued QR codes, so set it once before cards
# are printed.
HMAC_SECRET = os.environ.get("LGU_HMAC_SECRET", "lgu-convocation-hmac-secret-change-in-production").encode("utf-8")

ID_VERSION = "LGU1"
ID_LENGTH = 8
ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I to avoid misreads

DISPLAY_TZ = "Asia/Karachi"

# Administrator PIN (Phase 35G): gates the broadcast POST endpoint and the
# mobile admin screens (broadcast/admin routes behind a PIN check). Demo
# default — set LGU_ADMIN_PIN in the environment on the real server.
ADMIN_PIN = os.environ.get("LGU_ADMIN_PIN", "2026")

# --- Phase 20: demo-secret guard -------------------------------------------
# The three defaults above are committed to the repository, so they are PUBLIC
# knowledge, not secrets. SECRET_KEY signs the Flask session cookie (staff
# access) and the student password-recovery HMAC; HMAC_SECRET signs every
# issued QR code; ADMIN_PIN gates the broadcast and settings endpoints. Anyone
# who can reach the server knows all three by reading this file.
#
# A warning at startup is not enough: run.py binds 0.0.0.0, so the service is
# reachable across the LAN, and a printed warning does not stop a forged
# session cookie. Startup therefore FAILS CLOSED on the real entry point
# unless an operator explicitly opts in for local development.
_DEMO_SECRETS = {
    "LGU_SECRET_KEY": ("lgu-convocation-demo-key-change-in-production",
                       SECRET_KEY, str),
    "LGU_HMAC_SECRET": ("lgu-convocation-hmac-secret-change-in-production",
                        HMAC_SECRET.decode("utf-8", "replace"), str),
    "LGU_ADMIN_PIN": ("2026", ADMIN_PIN, str),
}


def demo_secrets():
    """Names of settings still carrying their committed demo value.

    Empty list means every secret was supplied by the operator. Never returns
    a value, so it is safe to print or to include in a report.
    """
    return [name for name, (_, current, _) in _DEMO_SECRETS.items()
            if current == _DEMO_SECRETS[name][0]]


def demo_secret_violation(startup=False):
    """Fail-closed policy: message when demo secrets must be refused,
    else None. Single source of truth for BOTH entry points (Phase 37
    BE-002): run.py passes startup=True (process startup), every other
    caller — notably web.routes.create_app — passes startup=False.

    Policy:
      * no demo secrets left        -> always permitted
      * production DB configured    -> NEVER permitted, even with the
        development opt-in or LGU_TESTING (the committed defaults must
        never sign session cookies or QR codes over real data)
      * startup (run.py): refused unless LGU_ALLOW_DEMO_SECRETS=1
      * factory (create_app): refused unless LGU_TESTING=1 (isolated
        disposable database) or LGU_ALLOW_DEMO_SECRETS=1 (dev opt-in)

    Returned text carries setting NAMES only — never values — so it is
    safe for stderr, logs and raised exceptions.
    """
    names = demo_secrets()
    if not names:
        return None
    listed = ", ".join(names)
    optin_msg = ("refusing to start with committed demo secrets: %s.\n"
                 "Set LGU_SECRET_KEY, LGU_HMAC_SECRET and LGU_ADMIN_PIN in"
                 " the environment (see docs/OPERATIONS.md), or set"
                 " LGU_ALLOW_DEMO_SECRETS=1 for local development only."
                 % listed)
    if is_production_db():
        return ("refusing to run committed demo secrets against the production"
                " database: %s. Set them in the environment (see"
                " docs/OPERATIONS.md) or point LGU_DB_PATH at a"
                " non-production database." % listed)
    if startup:
        if os.environ.get("LGU_ALLOW_DEMO_SECRETS") == "1":
            return None
        return optin_msg
    if os.environ.get("LGU_TESTING") == "1":
        return None
    if os.environ.get("LGU_ALLOW_DEMO_SECRETS") == "1":
        return None
    return optin_msg

# Official product naming: "Lahore Garrison University Smart Convocation"
# (full, in templates) / "LGU Smart Convocation" (short, in API + titles).
APP_NAME = "LGU Smart Convocation"
UNIVERSITY = "Lahore Garrison University"
MOTTO = "Nurturing the Future of Pakistan in an Excellent Environment"

# Import-time numeric settings should never raise from a typo, or permit
# zero/negative values to disable rate limits, TTLs or bounds. Use the
# existing positive_int helper consistently (including email and scanner).
# --- Phase 35K: shared operational configuration ---------------------------
# One server-side source for values shared between backend queries and the
# mobile UI (exposed through GET /api/config). Backend queries and UI
# labels both consume these — no duplicated client constants.
GATE_ACTIVITY_WINDOW_MINUTES = positive_int("LGU_GATE_WINDOW_MINUTES", 15)
MESSAGE_CHAR_LIMIT = positive_int("LGU_MESSAGE_LIMIT", 160)
# Broadcast delivery mode: "demo" (default — announcements are recorded
# only) or "real". "real" is a configuration state, not an SMS gateway:
# no delivery implementation exists, and the server never claims delivery
# it did not perform. The mobile UI reads this from /api/config.
BROADCAST_MODE = (os.environ.get("LGU_BROADCAST_MODE", "demo") or "demo").strip().lower()
if BROADCAST_MODE not in ("demo", "real"):
    BROADCAST_MODE = "demo"

# --- PIN attempt rate limiting (master audit V-AUTH-01/02) ----------------
# Per client IP, in-process. Isolated test backends can raise these via
# environment to avoid cross-script lockouts; production keeps the default
# of 5 wrong attempts per 60 seconds (→ HTTP 429).
PIN_RATE_WINDOW_SECONDS = positive_int("LGU_PIN_WINDOW", 60)
PIN_RATE_MAX_FAILS = positive_int("LGU_PIN_MAX_FAILS", 5)

# --- Examination Admin login rate limiting (Phase 3.1) --------------------
# Separate per-client-IP, in-process limiter for /exam/login so the exam
# portal and the volunteer PIN cannot throttle each other. 5 wrong attempts
# per 60 seconds (→ HTTP 429), on top of the per-account lockout in
# exam_auth. Same env-var override pattern as the PIN limiter.
EXAM_RATE_WINDOW_SECONDS = positive_int("LGU_EXAM_WINDOW", 60)
EXAM_RATE_MAX_FAILS = positive_int("LGU_EXAM_MAX_FAILS", 5)

# --- Phase 5: student accounts, email delivery, rate limits ---------------
# Email delivery is FAIL-CLOSED: the default mode is "disabled" and no
# credential has a default value. Until an operator sets LGU_EMAIL_MODE=smtp
# plus the SMTP_* env vars, signup and password recovery return HTTP 503
# instead of silently dropping verification codes. The "fake" mode exists
# ONLY for the test suite (emailer refuses it on the production DB).
EMAIL_MODE = (os.environ.get("LGU_EMAIL_MODE", "disabled") or "disabled").strip().lower()
SMTP_HOST = os.environ.get("LGU_SMTP_HOST", "") or ""
SMTP_PORT = positive_int("LGU_SMTP_PORT", 587)
SMTP_USER = os.environ.get("LGU_SMTP_USER", "") or ""
SMTP_PASSWORD = os.environ.get("LGU_SMTP_PASSWORD", "") or ""
MAIL_FROM = os.environ.get("LGU_MAIL_FROM", "") or ""
# TLS mode for the SMTP hop: "auto" (STARTTLS only when a username is set —
# the historical behaviour), "starttls", "ssl" (implicit TLS, port 465) or
# "none". Timeout applies to connect and to the whole session.
SMTP_TLS = (os.environ.get("LGU_SMTP_TLS", "auto") or "auto").strip().lower()
SMTP_TIMEOUT = positive_int("LGU_SMTP_TIMEOUT", 10)
VERIFICATION_TTL_SECONDS = positive_int("LGU_VERIFICATION_TTL", 600)
CODE_MAX_ATTEMPTS = positive_int("LGU_CODE_MAX_ATTEMPTS", 5)
CODE_MAX_SENDS = positive_int("LGU_CODE_MAX_SENDS", 3)
SESSION_HOURS = positive_int("LGU_STUDENT_SESSION_HOURS", 168)

# Per-IP limits for the student JSON API (same pattern as EXAM_RATE_*).
# Phase 18: each bucket carries its OWN documented window; the shared
# student window is only the default for buckets that do not declare one.
STUDENT_RATE_WINDOW_SECONDS = positive_int("LGU_STUDENT_WINDOW", 60)
STUDENT_RATE_MAX_VERIFY = positive_int("LGU_STUDENT_MAX_VERIFY", 6)
STUDENT_RATE_MAX_RECOVERY = positive_int("LGU_STUDENT_MAX_RECOVERY", 3)
STUDENT_RATE_MAX_LOGIN = positive_int("LGU_STUDENT_MAX_LOGIN", 5)
# Code-entry attempts (/complete, /recovery/complete) per client IP. The
# per-challenge attempt cap is the primary guard; this bounds how many
# DIFFERENT challenges one client can probe, so a sequential challenge_id
# cannot be brute-forced across accounts.
STUDENT_RATE_MAX_CONFIRM = positive_int("LGU_STUDENT_MAX_CONFIRM", 20)

# --- Phase 9: student support requests ------------------------------------
# Bounds are read at call time (like the other tunables) so isolated test
# backends can relax them. SUBJECT/MESSAGE cap submitted text server-side;
# MAX_OPEN bounds how many requests one account may hold open at once, and
# the window/rate limiter throttles creation per client IP.
SUPPORT_SUBJECT_MAX = positive_int("LGU_SUPPORT_SUBJECT_MAX", 160)
SUPPORT_MESSAGE_MAX = positive_int("LGU_SUPPORT_MESSAGE_MAX", 4000)
SUPPORT_MAX_OPEN = positive_int("LGU_SUPPORT_MAX_OPEN", 20)
# A request open (unresolved) for longer than this is surfaced on the staff
# dashboard as "older, may need attention". Resolved/rejected rows never count.
SUPPORT_STALE_DAYS = positive_int("LGU_SUPPORT_STALE_DAYS", 7)
SUPPORT_RECENT_DAYS = positive_int("LGU_SUPPORT_RECENT_DAYS", 7)
SUPPORT_RATE_WINDOW_SECONDS = positive_int("LGU_SUPPORT_WINDOW", 300)
SUPPORT_RATE_MAX_CREATE = positive_int("LGU_SUPPORT_MAX_CREATE", 10)

# Phase 10 — readiness centre. The read endpoint is served on the same
# freshness cadence as other student screens; only the reminder write is
# throttled per client IP so a misbehaving client cannot spam state changes.
READINESS_RATE_WINDOW_SECONDS = positive_int("LGU_READINESS_WINDOW", 60)
READINESS_RATE_MAX_MARK = positive_int("LGU_READINESS_MAX_MARK", 30)

# --- Phase 12: convocation entry QR passes --------------------------------
# A convocation pass is a high-entropy bearer token bound to ONE claimed
# registration + account + convocation, stored only as a sha256 hash. Reissue
# mints a fresh token and revokes the previous one, so the TTL is a generous
# backstop (not the primary lifecycle control). Verified against the
# registration/account ledger at scan time — never the legacy roster.
CONVOCATION_PASS_TTL_HOURS = positive_int("LGU_PASS_TTL_HOURS", 72)
# Per-IP throttle on the issuance endpoint (same pattern as the other student
# limiters) so a misbehaving client cannot mint unbounded tokens.
PASS_ISSUE_RATE_WINDOW_SECONDS = positive_int("LGU_PASS_ISSUE_WINDOW", 60)
PASS_ISSUE_RATE_MAX = positive_int("LGU_PASS_ISSUE_MAX", 10)

# --- Phase 14: volunteer scanner identities -------------------------------
# Individually provisioned scanners authenticate with a hashed PIN and hold a
# short-lived session. The session TTL is a backstop; a lost device is
# neutralised instantly by revoking the account (all sessions die). Repeated
# login failures are rate limited per client IP on top of the per-account
# lockout enforced in scanner_auth. No default scanner credential exists.
SCANNER_SESSION_HOURS = positive_int("LGU_SCANNER_SESSION_HOURS", 12)
SCANNER_RATE_WINDOW_SECONDS = positive_int("LGU_SCANNER_WINDOW", 60)
SCANNER_RATE_MAX_FAILS = positive_int("LGU_SCANNER_MAX_FAILS", 5)

# --- Phase 38 (BE-003): guest self-registration throttling ---------------
# Self-service guest minting hands out a bearer QR credential, so both the
# JSON and the form path share ONE per-IP windowed bucket (splitting them
# would double the budget). The daily cap is counted from the guests table
# itself, so it survives restarts and bounds minting regardless of IP.
# Isolated test backends relax these via environment (same pattern as the
# PIN limiter).
GUEST_RATE_WINDOW_SECONDS = positive_int("LGU_GUEST_WINDOW", 60)
GUEST_RATE_MAX_ATTEMPTS = positive_int("LGU_GUEST_MAX_ATTEMPTS", 30)
GUEST_DAILY_CAP = positive_int("LGU_GUEST_DAILY_CAP", 500)

# --- Phase 38: live dashboard polling -------------------------------------
# The server SUGGESTS a period; clients clamp to [2000, 30000] ms (models.
# _poll_interval_ms) so a stale or hostile value can never become a load
# amplifier, and no client polls faster than this floor.
DASHBOARD_POLL_MS = positive_int("LGU_DASHBOARD_POLL_MS", 5000)

# Phase 20 §4 — the staff session cookie is Secure only when the operator
# opts in. The intended deployment is a trusted plain-HTTP LAN, where a
# Secure cookie would never be sent over http:// and would lock every member
# of staff out of the portal. Any deployment fronted by TLS must set this.
COOKIE_SECURE = (os.environ.get("LGU_COOKIE_SECURE", "") or "").strip().lower() \
    in ("1", "true", "yes", "on")

# --- Phase 27 (C3): guest print capability --------------------------------
# An enumerable guest id used to mint the signed pass for anyone who could
# guess one. Self-registration now issues a narrowly scoped, unguessable,
# time-limited capability instead: signed with HMAC_SECRET, bound to ONE
# guest id, carried in the signed session cookie or the X-Print-Token header
# (never in a URL, so it never reaches an access log), and authorising only
# view/reprint of that guest's own pass. It is a backstop, not the primary
# lifecycle control — the pass itself stays single-use at the gate, and staff
# can always reprint without one, so a lapsed capability never locks a guest
# out. Default 24 h covers same-day reprints and reshared passes.
GUEST_PRINT_TTL_MINUTES = positive_int("LGU_GUEST_PRINT_TTL_MINUTES", 1440)

# --- Phase 22 §3: bounded SQLite lock waiting ------------------------------
# SQLite admits ONE writer at a time, and in rollback-journal mode a writer
# also excludes readers while it checkpoints. Every other request therefore
# BLOCKS. Left unconfigured, that wait falls through to the sqlite3 driver
# default (5 s) and, worse, is invisible to the code that must report it.
#
# The budget is bounded deliberately. A floor below which waiting is disabled
# would turn a millisecond of contention into a failed scan; a ceiling above
# which a gate operator is left staring at a spinner would be worse than an
# honest refusal. Volunteers need a PROMPT, TRUTHFUL outcome when contention
# exceeds the budget, so the ceiling is short and the response is retryable.
SQLITE_BUSY_TIMEOUT_DEFAULT = 5.0
SQLITE_BUSY_TIMEOUT_MIN = 0.1
SQLITE_BUSY_TIMEOUT_MAX = 30.0


def sqlite_busy_timeout():
    """Lock-wait budget in seconds, read at call time like the other tunables.

    Degraded values resolve to the DEFAULT rather than raising at import —
    an operator typo must not take the service down, and must never resolve
    to "no waiting" (which would fail every scan under trivial contention) or
    to "wait forever" (which would hang a gate for the length of a stall).
    """
    try:
        value = float(os.environ.get("LGU_SQLITE_BUSY_TIMEOUT") or
                      SQLITE_BUSY_TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        return SQLITE_BUSY_TIMEOUT_DEFAULT
    if not (SQLITE_BUSY_TIMEOUT_MIN <= value <= SQLITE_BUSY_TIMEOUT_MAX):
        return SQLITE_BUSY_TIMEOUT_DEFAULT
    return value

# Profile photos live OUTSIDE static/ and are served only to the owning
# session, so a random filename is defence in depth, not the only barrier.
STUDENT_PHOTO_DIR = (os.environ.get("LGU_STUDENT_PHOTO_DIR", "")
                     or os.path.join(BASE_DIR, "data", "student_photos"))
PHOTO_MAX_BYTES = int(os.environ.get("LGU_PHOTO_MAX_BYTES",
                                     str(2 * 1024 * 1024)) or str(2 * 1024 * 1024))

# --- Phase 6: medalist board -------------------------------------------------
# Approved medalist pictures are SEPARATE image assets (never student
# profile photos), stored under randomized names outside static/ and
# served only through the controlled public route for published records.
# A 5 MB cap is generous for portrait cards; limits are read at call time
# so isolated test backends can tune them like the other tunables.
MEDALIST_PHOTO_DIR = (os.environ.get("LGU_MEDALIST_PHOTO_DIR", "")
                      or os.path.join(BASE_DIR, "data", "medalist_photos"))
MEDALIST_PHOTO_MAX_BYTES = int(os.environ.get("LGU_MEDALIST_PHOTO_MAX_BYTES",
                                              str(5 * 1024 * 1024)) or str(5 * 1024 * 1024))


def assert_production_secrets():
    """Reject weak or demo credentials before serving production traffic.

    Called by the WSGI app factory and by run.py before any DB bootstrap.
    This is one prerequisite for production readiness, not a replacement
    for authorization, TLS, backup, or operator-approved DB migrations.
    """
    if os.environ.get("LGU_APP_ENV", "").strip().lower() != "production":
        return

    session_secret = SECRET_KEY
    qr_secret = HMAC_SECRET
    if (
        not isinstance(session_secret, str)
        or len(session_secret) < 32
        or "demo" in session_secret.lower()
        or "change-in-production" in session_secret.lower()
    ):
        raise RuntimeError(
            "Production requires a unique LGU_SECRET_KEY "
            "of at least 32 characters (not the demo key)."
        )
    if (
        not isinstance(qr_secret, bytes)
        or len(qr_secret) < 32
        or b"demo" in qr_secret.lower()
        or b"change-in-production" in qr_secret.lower()
    ):
        raise RuntimeError(
            "Production requires a unique LGU_HMAC_SECRET "
            "of at least 32 bytes (not the demo signing key)."
        )
    if session_secret.encode("utf-8") == qr_secret:
        raise RuntimeError(
            "LGU_SECRET_KEY and LGU_HMAC_SECRET must be different."
        )
    # Staff session cookies authorize administrative actions. Explicit
    # production deployments must use HTTPS and Secure cookies. This guard
    # runs in run.py before DB bootstrap and in the Flask app factory.
    # Development/LAN rehearsals retain their existing HTTP behavior.
    if not COOKIE_SECURE:
        raise RuntimeError(
            "Production requires LGU_COOKIE_SECURE=1 and HTTPS "
            "before staff sessions can be served."
        )
