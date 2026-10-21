"""Versioned, idempotent SQLite migrations tracked with PRAGMA user_version.

Append new (version, sql) pairs only; never edit an applied migration.
Each script runs in one transaction together with its version bump.
"""

import sqlite3

MIGRATIONS = [
    (1, """
CREATE TABLE IF NOT EXISTS convocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    year TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'confirmed', 'live', 'completed', 'archived')),
    expected_date TEXT,
    confirmed_date TEXT,
    rehearsal_date TEXT,
    venue TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_convocations_single_active
    ON convocations(is_active) WHERE is_active = 1;
"""),
    (2, """
CREATE TABLE IF NOT EXISTS staff_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_login_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""),
    # Phase 4: Examination Department convocation registrations + Excel import
    # batches (staging preview rows and per-registration audit history).
    # Identifiers are TEXT so leading zeros ("04550") round-trip exactly.
    # Uniqueness is enforced per convocation even for cancelled/revoked rows so
    # an identifier is never silently reused.
    (3, """
CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocation_id INTEGER NOT NULL REFERENCES convocations(id),
    filename TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'preview'
        CHECK (status IN ('preview', 'committed', 'failed')),
    mode TEXT NOT NULL DEFAULT '',
    total_rows INTEGER NOT NULL DEFAULT 0,
    blank_rows INTEGER NOT NULL DEFAULT 0,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    invalid_rows INTEGER NOT NULL DEFAULT 0,
    duplicate_rows INTEGER NOT NULL DEFAULT 0,
    conflict_rows INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    committed_at TEXT
);
CREATE TABLE IF NOT EXISTS import_staging (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id),
    row_no INTEGER NOT NULL,
    registration_number TEXT NOT NULL,
    university_email TEXT NOT NULL,
    roll_number TEXT NOT NULL,
    student_name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('valid', 'invalid', 'duplicate', 'conflict')),
    errors_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_import_staging_batch
    ON import_staging(batch_id, status);
CREATE TABLE IF NOT EXISTS convocation_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocation_id INTEGER NOT NULL REFERENCES convocations(id),
    registration_number TEXT NOT NULL COLLATE NOCASE,
    university_email TEXT NOT NULL COLLATE NOCASE,
    roll_number TEXT NOT NULL COLLATE NOCASE,
    student_name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'cancelled', 'revoked')),
    import_batch_id INTEGER REFERENCES import_batches(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (convocation_id, registration_number),
    UNIQUE (convocation_id, university_email),
    UNIQUE (convocation_id, roll_number)
);
CREATE INDEX IF NOT EXISTS idx_registrations_conv_status
    ON convocation_registrations(convocation_id, status);
CREATE TABLE IF NOT EXISTS registration_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_id INTEGER NOT NULL,
    convocation_id INTEGER NOT NULL,
    batch_id INTEGER REFERENCES import_batches(id),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT NOT NULL DEFAULT '',
    after_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reg_audit_registration
    ON registration_audit(registration_id, created_at);
"""),
    # Phase 5: student accounts. Codes/challenges and session tokens are
    # stored only as HMAC/sha256 digests (no plaintext code or token ever
    # hits the database); claims are unique per convocation on both sides so
    # one account holds one registration and one registration is held once.
    (4, """
CREATE TABLE IF NOT EXISTS student_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    university_email TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL DEFAULT '',
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS student_profiles (
    account_id INTEGER PRIMARY KEY REFERENCES student_accounts(id),
    phone TEXT NOT NULL DEFAULT '',
    photo_file TEXT NOT NULL DEFAULT '',
    photo_mime TEXT NOT NULL DEFAULT '',
    photo_updated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS registration_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES student_accounts(id),
    convocation_id INTEGER NOT NULL REFERENCES convocations(id),
    registration_id INTEGER NOT NULL REFERENCES convocation_registrations(id),
    created_at TEXT NOT NULL,
    UNIQUE (account_id, convocation_id),
    UNIQUE (convocation_id, registration_id)
);
CREATE INDEX IF NOT EXISTS idx_claims_registration
    ON registration_claims(registration_id);
CREATE TABLE IF NOT EXISTS verification_challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purpose TEXT NOT NULL CHECK (purpose IN ('signup', 'recovery')),
    university_email TEXT NOT NULL COLLATE NOCASE,
    convocation_id INTEGER,
    registration_id INTEGER,
    code_hash TEXT NOT NULL,
    sent_count INTEGER NOT NULL DEFAULT 1,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_at TEXT NOT NULL,
    last_sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_challenges_lookup
    ON verification_challenges(university_email, purpose, consumed_at);
CREATE TABLE IF NOT EXISTS student_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES student_accounts(id),
    token_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_student_sessions_account
    ON student_sessions(account_id, revoked_at);
"""),
    # Phase 6: medalist records for the public board. The publication
    # column is the draft/approval gate - the student API only ever reads
    # published rows. Uniqueness is per convocation on
    # (department, award_category, position) so two people can never share
    # an award slot, while extra categories and position holders need no
    # schema change. reference_number is an OPTIONAL official identifier
    # matched against the convocation's registration list (see
    # medalist_import.py) - no identifier format is invented here.
    (5, """
CREATE TABLE IF NOT EXISTS medalists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocation_id INTEGER NOT NULL REFERENCES convocations(id),
    department TEXT NOT NULL COLLATE NOCASE,
    student_name TEXT NOT NULL,
    award_category TEXT NOT NULL COLLATE NOCASE,
    position TEXT NOT NULL DEFAULT '',
    reference_number TEXT NOT NULL DEFAULT '',
    photo_file TEXT NOT NULL DEFAULT '',
    photo_mime TEXT NOT NULL DEFAULT '',
    photo_updated_at TEXT,
    publication TEXT NOT NULL DEFAULT 'draft'
        CHECK (publication IN ('draft', 'published')),
    import_batch_id INTEGER REFERENCES medalist_import_batches(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_medalists_award_slot
    ON medalists(convocation_id, department, award_category, position);
CREATE INDEX IF NOT EXISTS idx_medalists_public_board
    ON medalists(convocation_id, publication, department, award_category);
CREATE TABLE IF NOT EXISTS medalist_import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocation_id INTEGER NOT NULL REFERENCES convocations(id),
    filename TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'preview'
        CHECK (status IN ('preview', 'committed', 'failed')),
    total_rows INTEGER NOT NULL DEFAULT 0,
    blank_rows INTEGER NOT NULL DEFAULT 0,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    invalid_rows INTEGER NOT NULL DEFAULT 0,
    duplicate_rows INTEGER NOT NULL DEFAULT 0,
    conflict_rows INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    committed_at TEXT
);
CREATE TABLE IF NOT EXISTS medalist_import_staging (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES medalist_import_batches(id),
    row_no INTEGER NOT NULL,
    department TEXT NOT NULL,
    student_name TEXT NOT NULL,
    award_category TEXT NOT NULL,
    position TEXT NOT NULL DEFAULT '',
    reference_number TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('valid', 'invalid', 'duplicate', 'conflict')),
    errors_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_medalist_staging_batch
    ON medalist_import_staging(batch_id, status);
CREATE TABLE IF NOT EXISTS medalist_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medalist_id INTEGER NOT NULL,
    convocation_id INTEGER NOT NULL,
    batch_id INTEGER REFERENCES medalist_import_batches(id),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT NOT NULL DEFAULT '',
    after_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_medalist_audit_record
    ON medalist_audit(medalist_id, created_at);
"""),
    # Phase 7 — event management and announcements. The convocation row stays
    # the working (draft) record; students only ever see the published snapshot
    # in convocation_publications, and every change is attributed in the audit
    # tables. rehearsal_time completes the rehearsal date/time/venue trio.
    (6, """
ALTER TABLE convocations ADD COLUMN rehearsal_time TEXT;
CREATE TABLE IF NOT EXISTS convocation_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocation_id INTEGER NOT NULL UNIQUE REFERENCES convocations(id),
    name TEXT NOT NULL,
    year TEXT NOT NULL,
    expected_date TEXT,
    confirmed_date TEXT,
    rehearsal_date TEXT,
    rehearsal_time TEXT,
    venue TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    published_by TEXT NOT NULL,
    published_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS convocation_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocation_id INTEGER NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT NOT NULL DEFAULT '',
    after_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_convocation_audit_record
    ON convocation_audit(convocation_id, created_at);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocation_id INTEGER NOT NULL REFERENCES convocations(id),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    audience TEXT NOT NULL DEFAULT 'students'
        CHECK (audience IN ('students', 'staff')),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'published', 'archived')),
    is_important INTEGER NOT NULL DEFAULT 0 CHECK (is_important IN (0, 1)),
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT,
    published_by TEXT,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_announcements_feed
    ON announcements(convocation_id, status, audience, published_at);
CREATE TABLE IF NOT EXISTS announcement_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    announcement_id INTEGER NOT NULL,
    convocation_id INTEGER NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT NOT NULL DEFAULT '',
    after_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_announcement_audit_record
    ON announcement_audit(announcement_id, created_at);
"""),
    # Phase 9 — student support requests and the Examination Department
    # review queue. A request is always owned by exactly one student account
    # and bound to one convocation; it NEVER mutates an official registration
    # (any resulting correction goes through the existing registration
    # correction workflow, linked by registration_id when a claim exists).
    # Every status change and response is appended to support_events so the
    # student-visible history and the internal audit trail are the same rows.
    (7, """
CREATE TABLE IF NOT EXISTS support_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference TEXT UNIQUE NOT NULL,
    convocation_id INTEGER NOT NULL REFERENCES convocations(id),
    account_id INTEGER NOT NULL REFERENCES student_accounts(id),
    registration_id INTEGER REFERENCES convocation_registrations(id),
    category TEXT NOT NULL
        CHECK (category IN ('missing_registration', 'correction',
                            'cancellation', 'account_claim', 'general')),
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('submitted', 'under_review', 'info_required',
                          'resolved', 'rejected')),
    handled_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_support_requests_queue
    ON support_requests(convocation_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_support_requests_owner
    ON support_requests(account_id, convocation_id, created_at);
CREATE TABLE IF NOT EXISTS support_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    support_request_id INTEGER NOT NULL REFERENCES support_requests(id),
    actor TEXT NOT NULL,
    actor_role TEXT NOT NULL CHECK (actor_role IN ('student', 'staff')),
    action TEXT NOT NULL,
    student_visible INTEGER NOT NULL DEFAULT 1 CHECK (student_visible IN (0, 1)),
    body TEXT NOT NULL DEFAULT '',
    before_status TEXT NOT NULL DEFAULT '',
    after_status TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_support_events_request
    ON support_events(support_request_id, id);
"""),
    # Phase 10 — per-account read/dismiss state for personalized reminders.
    # Readability and dismissal are stored server-side (not on the device) so
    # a reminder the student has already seen or dismissed never re-alerts on
    # another sign-in, and a dismissal is validated against the live reminder
    # set rather than trusted from the client. Only informational reminders
    # are ever dismissible — an unresolved registration/support issue is
    # never removed by this table.
    (8, """
CREATE TABLE IF NOT EXISTS student_reminder_state (
    account_id INTEGER NOT NULL REFERENCES student_accounts(id),
    reminder_key TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'read' CHECK (state IN ('read','dismissed')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, reminder_key)
);
CREATE INDEX IF NOT EXISTS idx_reminder_state_account
    ON student_reminder_state(account_id, state);
"""),
    # Phase 12 — convocation entry QR passes + admissions ledger. Deliberately
    # INDEPENDENT of the legacy operational roster (students.qr_id → scans): a
    # convocation registration carries no roster qr_id and shares no key with
    # it, so its entry pass is verified against the registration/account
    # ledger here instead. A pass binds a high-entropy bearer token (stored
    # ONLY as a sha256 hash — the plaintext is returned once at issuance and
    # never persisted or logged) to one registration + account + convocation.
    # Reissue revokes the prior active pass, so exactly one token is live.
    (9, """
CREATE TABLE IF NOT EXISTS convocation_passes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT UNIQUE NOT NULL,
    convocation_id INTEGER NOT NULL REFERENCES convocations(id),
    registration_id INTEGER NOT NULL REFERENCES convocation_registrations(id),
    account_id INTEGER NOT NULL REFERENCES student_accounts(id),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'revoked', 'used')),
    issued_at TEXT NOT NULL,
    expires_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_convocation_passes_live
    ON convocation_passes(convocation_id, registration_id, status);
CREATE INDEX IF NOT EXISTS idx_convocation_passes_account
    ON convocation_passes(account_id, convocation_id, status);
-- Successful convocation admissions — a SEPARATE ledger from the legacy
-- scans table (which is keyed to the roster's qr_id and person_type
-- student|guest). A registration cannot be represented there without
-- fabricating a roster row, so admitted attendees live here. The partial
-- UNIQUE (one row per convocation + registration) is the atomic backstop
-- that stops two gates scanning the same pass near-simultaneously from
-- admitting it twice: the second INSERT fails on the constraint.
CREATE TABLE IF NOT EXISTS convocation_admissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pass_id INTEGER NOT NULL REFERENCES convocation_passes(id),
    convocation_id INTEGER NOT NULL REFERENCES convocations(id),
    registration_id INTEGER NOT NULL REFERENCES convocation_registrations(id),
    gate_id INTEGER NOT NULL REFERENCES gates(id),
    volunteer TEXT NOT NULL,
    admitted_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'online'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_convocation_admissions_once
    ON convocation_admissions(convocation_id, registration_id);
CREATE INDEX IF NOT EXISTS idx_convocation_admissions_conv
    ON convocation_admissions(convocation_id, admitted_at);
CREATE INDEX IF NOT EXISTS idx_convocation_admissions_gate
    ON convocation_admissions(gate_id, admitted_at);
"""),
    # Phase 14: individually provisioned volunteer SCANNER identities.
    # The scan endpoints previously trusted a client-supplied volunteer name
    # and gate id with no authentication. A scanner now proves who it is with
    # a per-account PIN (scrypt hash at rest), receives a short-lived session,
    # and the server — never the client — decides which gates it may admit
    # through and what volunteer name is recorded. No shared/default
    # credential exists; accounts are created only by the local management
    # command (scripts/manage_scanner_staff.py) or the non-production test
    # helper. Session secrets are stored only as sha256 hashes.
    (10, """
CREATE TABLE IF NOT EXISTS scanner_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    display_name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_login_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- Server-side gate authorization: a scanner may admit ONLY through the gates
-- listed here. The client cannot choose an arbitrary gate by editing request
-- data; the route intersects the requested gate with this set.
CREATE TABLE IF NOT EXISTS scanner_gates (
    scanner_id INTEGER NOT NULL REFERENCES scanner_users(id) ON DELETE CASCADE,
    gate_id INTEGER NOT NULL REFERENCES gates(id),
    PRIMARY KEY (scanner_id, gate_id)
);
-- Short-lived authenticated sessions. Only the sha256 hash of the bearer
-- token is stored; the plaintext is returned once at login and never
-- persisted or logged. Revoked and expired rows are honoured on every scan.
CREATE TABLE IF NOT EXISTS scanner_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scanner_id INTEGER NOT NULL REFERENCES scanner_users(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_scanner_sessions_scanner
    ON scanner_sessions(scanner_id, revoked_at, expires_at);
"""),
    # Phase 19: explicit credential lifecycle for provisioned scanner
    # accounts, and a lookup index for the scanner management history the
    # staff portal renders. An account created from the portal starts with no
    # usable credential (credential_established = 0) and cannot authenticate
    # until a PIN has been explicitly established; no default or shared PIN
    # exists anywhere. The DEFAULT 1 backfills every pre-existing account as
    # already provisioned, so nothing already deployed changes behaviour.
    (11, """
ALTER TABLE scanner_users ADD COLUMN credential_established INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action, id);
"""),
    # Phase 29 — annual convocation lifecycle: ONE annual cycle now carries
    # TWO distinct occasions (rehearsal before the main ceremony), each with
    # its own start time and venue, and admissions are scoped per occasion so
    # a rehearsal check-in can never consume main-ceremony admission.
    # Existing admission rows are backfilled 'ceremony' (before Phase 29 a
    # convocation had exactly one admission, for the convocation itself) and
    # the UNIQUE backstop keeps its name while gaining the occasion column.
    (12, """
ALTER TABLE convocations ADD COLUMN ceremony_time TEXT;
ALTER TABLE convocations ADD COLUMN rehearsal_venue TEXT NOT NULL DEFAULT '';
ALTER TABLE convocation_publications ADD COLUMN ceremony_time TEXT;
ALTER TABLE convocation_publications ADD COLUMN rehearsal_venue TEXT NOT NULL DEFAULT '';
ALTER TABLE convocation_admissions ADD COLUMN occasion TEXT NOT NULL DEFAULT 'ceremony';
DROP INDEX IF EXISTS idx_convocation_admissions_once;
CREATE UNIQUE INDEX IF NOT EXISTS idx_convocation_admissions_once
    ON convocation_admissions(convocation_id, registration_id, occasion);
CREATE INDEX IF NOT EXISTS idx_convocation_admissions_occasion
    ON convocation_admissions(convocation_id, occasion);
"""),
    # Phase 34 (Part C) — guest pass lifecycle: guests could only be
    # unused/used, so a lost or compromised single-use pass had no way to be
    # invalidated before it was scanned. Adds an explicit lifecycle column.
    # 'active' is the backward-compatible default (every existing guest stays
    # scannable); 'revoked' is refused at the gate and by the dashboard.
    # SQLite cannot add a CHECK via ALTER, so the value set is enforced in
    # models.revoke_guest (active -> revoked only). Additive + default-only,
    # so an unmigrated reader still sees 'active'-equivalent behaviour.
    (13, """
ALTER TABLE guests ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
"""),
    # Phase 38 (DB-002 + analytics): make the long-standing app rule "one
    # guest per host roll" a database invariant so two concurrent
    # registrations cannot both pass the check-then-insert window. Verified
    # against the production database before adding: 3 guests, no duplicate
    # host_roll_no. If a database ever carries duplicates the CREATE fails
    # closed inside the migration transaction (index name in the error,
    # version not advanced) — no row is deleted automatically.
    # scan_rejections is the event log for refused scan verdicts (Phase 38
    # analytics): rejected/duplicate counts were previously unobservable.
    # Deliberately NO foreign keys — gate_id/mode/occasion are recorded as
    # observed and may be malformed by definition; a log row must never be
    # refused for the same reason the verdict was.
    (14, """
CREATE UNIQUE INDEX IF NOT EXISTS idx_guests_host_once
    ON guests(host_roll_no);
CREATE TABLE IF NOT EXISTS scan_rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    gate_id INTEGER,
    mode TEXT,
    occasion TEXT,
    title TEXT NOT NULL,
    is_duplicate INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'online'
);
CREATE INDEX IF NOT EXISTS idx_scan_rejections_time
    ON scan_rejections(occurred_at);
"""),
]


def migrate(db):
    """Apply every migration whose version is newer than the database's user_version.

    Each script runs inside one transaction together with its version bump, so a
    failure leaves BOTH the schema and the version metadata untouched (Phase 20
    rehearses this deliberately — a half-applied migration is the one failure
    mode a versioned migrator must never produce).

    Raises RuntimeError rather than opening a database this build does not
    understand. Silently applying nothing and returning would let the app run
    against a newer schema and fail later on a missing column with a far less
    diagnosable error.
    """
    versions = [v for v, _ in MIGRATIONS]
    if versions != sorted(set(versions)):
        # Programmer error, not a runtime condition: appending a migration out
        # of order would make the ordering guarantee above untrue.
        raise RuntimeError("migration versions must be strictly ascending: %s"
                           % versions)
    latest = versions[-1]
    current = db.execute("PRAGMA user_version").fetchone()[0]
    if current > latest:
        raise RuntimeError(
            "Database schema version %d is newer than this build supports"
            " (latest: %d). Refusing to run against it — restore a database"
            " from a supported release, or deploy the matching application."
            % (current, latest))
    for version, script in MIGRATIONS:
        if version <= current:
            continue
        try:
            db.executescript("BEGIN;\n%sPRAGMA user_version = %d;\nCOMMIT;" % (script, version))
        except sqlite3.Error:
            db.rollback()
            raise
    return db.execute("PRAGMA user_version").fetchone()[0]
