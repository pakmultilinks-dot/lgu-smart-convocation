# LGU Smart Convocation Platform Expansion Design

## Scope and method

This document is a product and architecture design only. It does not implement any new code, database change, route, account, file upload, migration, screen, or dependency.

This design is grounded in the verified repository state as of 2026-10-10. Existing behavior is separated from design recommendations and unresolved decisions.

## Verified repository facts

- `app/run.py`: bootstraps SQLite schema and seed data with `init_db()` and `seed()`, supports `LGU_TESTING`, `LGU_DB_PATH`, `LGU_PORT` and warns on demo secrets.
- `app/database.py`: SQLite schema is created in `SCHEMA`; there is no migration framework. The database is `app/lgu.db` by default.
- `app/models.py`: all business logic and query logic live here (`find_person`, `record_scan`, `dashboard_summary`, `app_config_payload`, `broadcast_audience`, `guest_by_id`, etc.).
- `app/web/routes.py`: Flask blueprint `main` defines the current web/admin and JSON API surface, including `/admin`, `/dashboard`, `/api/scan`, `/api/settings`, `/api/broadcasts`, `/api/search`, `/api/config`, and `create_app()`.
- `app/config.py`: one demo admin PIN (`ADMIN_PIN`, default `2026`) is the only current server-side auth control; there are no user accounts, student login flows, or email-verification features in the codebase.
- `app/ids.py`: QR identity is an opaque HMAC-signed payload `LGU1:<qr_id>:<sig>`, and `ids.verify_payload()` verifies every scan.
- `mobile/app/(volunteer)/_layout.tsx`: current mobile routing is a volunteer app with five visible tabs (`home`, `scanner`, `search`, `guests`, `more`) and hidden routes for `settings`, `admin`, and `broadcast`.
- `mobile/src/store/settings.ts`: backend URL discovery is device-session-based and uses `lgu.api_base_url` / `lgu.api_base_url_mode`.
- `mobile/src/api/client.ts`: typed API client for scan, guest, broadcast, settings, and dashboard calls; it performs timeout handling and sanitized error reporting.

## 1. Product vision and priorities

### 1.1 Product purpose

The existing platform already solves the core operational problem for convocation-day volunteer and gate operations: QR scanning, guest passes, attendance, gates, broadcast logging, and dashboard totals. The target product should extend this operational capability into a full convocation platform with a connected student experience and an exam-department administration layer, while keeping day-of volunteer operations intact.

### 1.2 Priority order

1. Preserve the working volunteer and gate experience.
2. Add student-facing convocation experience built around official records and verified identity.
3. Add examination-department administration with safe import, correction, and publication tools.
4. Add medalist publication, event information, and historical records.
5. Add advanced UX enhancements once the core trust model is in place.

### 1.3 Product boundaries

The product must remain a convocation platform, not a generic university super-app. It should cover:

- official student registration and verification;
- student account setup and profile completion;
- public event information and official announcements;
- medalist recognition; and
- operational support for volunteer entry/exit scanning.

It should not add unrelated academic portals, commerce, payments, or generic campus services.

### 1.4 Verified facts vs design choice

- Verified fact: the current app has no student authentication, no email verification, no role model, and no registration table.
- Agreed requirement: the student app must include verified official registration before account completion and access to the student dashboard.
- Design recommendation: keep the existing scanning roster and volunteer operations as a separate operational capability from the exam-registration domain.

## 2. User roles and permissions

### 2.1 Roles to support

1. Super administrator
   - Full control over global configuration, roles, event publication, and high-risk actions.
   - Owns system-level policy and access review.

2. Examination Department administrator
   - Imports and manages official convocation registration records.
   - Reviews validation errors, correction requests, cancellations, and import history.
   - Publishes event dates, rehearsal details, and announcements to students.
   - Manages medalist submissions and approved photographs.

3. Examination Department reviewer / approver
   - Reviews flagged records and approval flows without full import rights.
   - Can validate corrections and account-related disputes.

4. Volunteer / gate operator
   - Current role is operational only.
   - Must not have exam-module permissions.
   - Continues to use QR scan flows based on the operational roster.

5. Student
   - Creates account only after official registration verification.
   - Completes profile and receives approved convocation information.

6. Public / unauthenticated viewer
   - Limited to public event info and medalist board if intentionally published.
   - Not permitted to view internal import history, private registration data, or attendee operational reports.

### 2.2 Permission model recommendation

The current code uses a single shared `ADMIN_PIN` in `app/config.py` and web session-based `lgu_admin` gating in `app/web/routes.py`. That is not a scalable role model for the expansion.

The least risky path is to preserve the current volunteer gate PIN and add a separate exam-authority permission model. This means:

- keep volunteer permissions as-is;
- add a distinct exam-role layer to the Flask web app for examination admin tasks;
- do not repurpose the volunteer PIN as a blanket admin credential.

### 2.3 Attributable changes

The existing repository has no staff account table. For the new exam module, every sensitive action should be attributable to an authenticated user, including:

- import batches,
- correction or cancellation,
- publication of dates/announcements,
- medalist approvals,
- role assignments,
- account claim issues.

This is a design requirement, not an existing repository feature.

## 3. Student journeys before, during and after convocation

### 3.1 Before convocation

Primary journey:

1. Student sees public landing and event overview.
2. Student signs up using university email, roll number, and convocation registration number.
3. Server validates the provided details against the official registration for the active convocation.
4. Email ownership is verified using an approved mechanism.
5. Student completes personal profile, including profile picture validation.
6. Student sees a student home screen with readiness checklist and event schedule.

### 3.2 During convocation

1. Student can access their own personal dashboard and event guidance.
2. Student sees confirmed event date, rehearsal schedule, and venue information.
3. Student sees essential announcements and reminders from the backend.
4. Student can browse medalist board, department groupings, and public event information.
5. Student should not have access to volunteer or admin operational data.

### 3.3 After convocation

1. Student can access historical convocation information that is marked public.
2. Student may review their verified registration history and any official archive relevant to the event.
3. Student may not be exposed to internal operational, exam, or staff management functions.

### 3.4 Essential launch features

The first viable student app should deliver:

- secure signup and sign-in;
- official registration validation against active convocation dataset;
- profile completion and photo requirement;
- student home;
- readiness checklist;
- event dates and venue;
- official announcements; and
- medalist board.

### 3.5 Later enhancements

Examples of enhancements that should not be part of the first phase:

- detailed student messaging center;
- personalized advice recommendations;
- internal academic planning modules;
- additional campus utilities not directly related to the convocation.

## 4. Examination Department workflows

### 4.1 Primary responsibilities

The Examination Department manages official information that is shown to students and used to verify identity. This includes:

- current and future convocation records;
- official registration lists;
- registration status, cancellations, and corrections;
- medalist data and approved images;
- official event dates and announcements;
- import history and review tasks.

### 4.2 Web module design recommendation

The existing Flask web app already supports admin patterns through `app/web/routes.py`. The smallest safe extension is to add a second web module for the examination department, rather than folding it into volunteer or mobile route design.

Recommended approach:

- keep current volunteer & gate flows in the mobile + existing web routes;
- add a distinct exam module with separate route group and admin role permission checks;
- use the same SQLite database and same data access layer where possible;
- keep operational scans and gate data separate from official registration and medalist data.

### 4.3 Core exam workflows

1. Event management
   - create a convocation record;
   - set expected date, confirmed date, rehearsal date, venue and instructions;
   - archive or publish the event while preserving historical records.

2. Registration import and review
   - import official registration Excel files;
   - preview records before import;
   - validate duplicate, malformed, cancelled, and mismatched rows;
   - approve or reject the import batch;
   - record uploader + approval history.

3. Registration lifecycle
   - verify a record is valid for the active convocation;
   - allow corrections and review flags;
   - cancel/revoke records without deleting historical data;
   - re-enable or replace only through approved administrative flows.

4. Medalist management
   - upload or approve medalist photos;
   - assign department, award category and award position;
   - keep public cards to name + photo only.

5. Publication
   - publish dates, announcements, and medals only after staff review.
   - keep draft content private to the exam module until published.

## 5. Existing volunteer operations that must remain unchanged

### 5.1 Verified retained workflow

Volunteer and event-day paths are already established in the mobile app and backend:

- `mobile/app/(volunteer)/_layout.tsx` defines the volunteer tab flow.
- `mobile/src/store/ops.ts` stores selected gate and scan mode.
- `mobile/src/scanner/*` contains the camera, gate selection, result states, and offline queue logic.
- `app/web/routes.py` includes `process_scan()`, `api_scan()`, `api_sync()`, and the guest-pass logic.
- `app/models.py` stores scan identity, guest usage semantics, and gate activity aggregates.

### 5.2 Constraints

The expansion must not:

- redesign the volunteer tab UX;
- remove gate selection or offline scan flow;
- rewrite attendee check-in logic;
- reset `scans`, `guests`, `gates`, or `students` data through a registration import;
- let exam modules auto-update QR assignments or gate configuration.

### 5.3 Safe relationship

The operational roster and the official registration system are separate domains:

- official registration data answers: “Is this student eligible and verified?”
- operational roster answers: “Who is currently inside at which gate, and what was scanned?”

A student’s registration status should not automatically alter the QR scanning roster or attendance history. Approved operational synchronization should preserve existing QR identities and historical scan rows.

## 6. Registration verification and student account lifecycle

### 6.1 Required verification model

The student signup flow must not treat a registration number alone as proof of identity. The active convocation record must be checked server-side against all of the following, as applicable:

- registration number,
- university email,
- roll number,
- active convocation ID,
- record status.

It is not enough to compare only one field. The same record must match the active convocation and the same student identity.

### 6.2 Official record states

Recommended record states:

- `active` — eligible and normal.
- `pending_review` — mismatch or manual correction needed.
- `cancelled` — revoked or cancelled.
- `replaced` — superseded by a newer approved record.
- `archived` — historical, no longer active for the current event.

### 6.3 Account lifecycle

Recommended lifecycle:

1. Student submits registration details.
2. System checks active official registration record.
3. If not found or mismatched, student receives a clear and non-diagnostic status: not found, pending review, cancelled, or mismatch.
4. Email ownership is verified using an approved mechanism.
5. Student completes account setup plus required profile information.
6. Student enters the main dashboard only after profile completion and active registration verification.
7. A failed network or server error must never be reported as `unregistered`.

### 6.4 Duplicate and claim protection

The system must prevent:

- the same student claiming multiple different records;
- multiple students claiming the same official registration;
- duplicate account setups with conflicting names or email addresses;
- recovery from a stale or cancelled official record.

The claim should be an atomic transaction: only one account may be associated with a valid official registration row for a given convocation.

### 6.5 Email verification options

The repo has no email infrastructure. This is a design decision requirement. Viable options include:

1. University email OTP via approved SMTP or institutional mail relay.
   - Security benefit: strong identity proof.
   - Risk: requires SMTP, sender setup, and operational support.

2. One-time claim code issued by Examination Department from approved official registration data.
   - Security benefit: works without a new email gateway.
   - Risk: weaker than email-ownership proof if not tightly controlled.

3. Institutional SSO or central identity provider.
   - Security benefit: strong and standard.
   - Risk: requires university identity integration and governance.

No option should be silently assumed. The university must approve the chosen method before production implementation.

### 6.6 Missing or erroneous records

- Missing record: show `not found` or `pending review`, not `unregistered`.
- Incorrect details: show `details do not match official records` and allow correction submission.
- Malformed or duplicate source rows: must be handled in the exam import and review process, not by the student signup page alone.
- Temporary backend outage: present a neutral “verification unavailable, try again later” state; never mark the student as unregistered solely because the backend is not responding.

## 7. Excel dataset catalogue and import workflows

### 7.1 Data categories to support

The repository already proves a roster import path in the web admin (`app/web/routes.py`, `admin()` route, `_parse_roster()`) and `app/models.py` `add_students()`. That import is a CSV roster for student records, not an exam registration system.

The expansion should support the following dataset categories, each with a separate admin workflow:

1. Official registration records
   - purpose: active identity validation for student signup and eligibility.
   - source: Examination Department official list.

2. Student roster / operational registration list
   - purpose: operational attendance and QR-linked roster.
   - source: approved convocation roster or department-issued list.

3. Medalist and award records
   - purpose: public medalist board.
   - source: department-approved award submissions.

4. Event date and venue records
   - purpose: public student information and display.
   - source: official convocation office decisions.

5. Announcement content
   - purpose: official student communication.
   - source: exam authority or approved staff.

6. Optional future data
   - QR-related Excel import is not validated as a required feature in the current repository. It should only be added if the official process requires a new QR table or bulk reissue flow.

### 7.2 Required and optional columns

The exact spreadsheet formats are not yet known. The design should not invent final mappings. The required information for registration records is known from the requirements:

- registration number,
- university email,
- student roll number,
- other official source fields as supplied by the university.

Unknowns that must be resolved before implementation:

- whether the official source provides `student_name`, `department`, `program`, `gender`, `phone` and `national_id`;
- whether mandatory fields vary by department or year;
- whether each convocation has a unique registration template.

### 7.3 Import workflow stages

1. File upload
2. File preview
3. Row-level validation
4. Duplicate detection
5. Batch approval
6. Transactional import
7. Audit history and notifications
8. Correction and cancellation

### 7.4 Safe import and rollback boundaries

For each batch:

- create a batch record with uploader and timestamp;
- validate rows before any write to final registration tables;
- if any row is invalid, show a review report and do not commit;
- on explicit approval, insert all valid rows in one transaction;
- if validation fails mid-commit, roll back the entire batch.

The current repo does not support transactional import patterns yet, and no migration framework exists. This is deliberately a new design requirement.

### 7.5 Replacement rules

An uploaded file must not silently replace every existing record. Safe behavior should be:

- import is batch-scoped to a convocation;
- current record versions are compared against the existing active set;
- replacement is explicit and audited;
- old records remain available in history unless a specific cancellation or archive action is approved.

### 7.6 Dataset size and performance

Approximately 6,000 student records is manageable for SQLite in a local development environment and within a single server event flow. The main complexity is not row volume but data quality, validation, and auditability. This size does not justify a speculative microservice or paid database in the design phase.

## 8. Medalist management and public board

### 8.1 Requirements

The medalist board is a student-facing feature. Baseline expectation: three medalists per department for gold, silver, and bronze. The implementation must allow:

- additional award categories;
- additional position holders;
- per-department variations;
- public board grouping without exposing private details.

### 8.2 Public display rule

The public medalist card should show only:

- medalist name;
- medalist picture.

No roll number, email, phone number, academic results, biography, or other personal data should be exposed. Department grouping is allowed, but not personal detail exposure.

### 8.3 Staff workflow

1. Medalist submission is approved by the exam department.
2. Staff select department, award category, and position.
3. Staff upload or approve picture.
4. Public board entry is published only after approval.
5. Public card uses only approved display name and approved photo.

### 8.4 Photo handling

The repository has no dedicated image upload flow. This should be implemented as a dedicated image/consent workflow rather than reusing unrelated student profile image fields without permission. The design assumption is:

- an approved medalist photograph is distinct from a student profile picture for privacy reasons;
- public medalist image URLs or file paths must be internal-only and never exposed to the public API payload;
- medalist public renderers only consume approved metadata and a safe image reference.

## 9. Event dates, announcements and notifications

### 9.1 Event data model

The current repository has flat settings keys (`convocation_name`, `convocation_year`, `convocation_datetime`, `venue`, `expected_attendance`, `university_name`) in `app/database.py` and `app/models.py` `app_config_payload()`. That is a good foundation for event metadata, but it is not enough for the expansion.

Recommended distinction:

- `expected_date`: a planned target date;
- `confirmed_date`: the official date announced by the university;
- `rehearsal_date`: rehearsal plan;
- `venue`: official venue;
- `instructions`: event instructions for students;
- `announcements`: draft/published messages for students.

### 9.2 Publication model

- Drafts remain private to exam staff.
- Published announcements are visible through the backend API to the student app.
- Students should consume backend data at runtime rather than relying on app releases.

### 9.3 Notification mechanism status

The current system has a `broadcasts` log and a demo-only broadcast mode in `app/config.py` and `app/web/routes.py` (`BROADCAST_MODE`). That is not a real delivery system. It is only a record of messages saved to the database. The expansion should distinguish:

- in-app data polling,
- direct backend delivery via the student app,
- push notifications (requires additional infrastructure),
- SMS/email gateways (requires separate service decisions).

No delivery feature should be claimed as already implemented.

## 10. Proposed data entities and their relationships

### 10.1 Core entities

- `convocations`
- `convocation_events` (if kept separate for event metadata, or merged into `convocations`)
- `registration_import_batches`
- `official_registrations`
- `student_accounts`
- `student_profiles`
- `student_registration_claims`
- `medalists`
- `announcements`
- `audit_log`
- `role_assignments`
- `staff_users`

### 10.2 Relationship model

- One convocation has many official registrations.
- One official registration can be claimed by at most one student account.
- One student account can have one active registration per convocation.
- One convocation can have many medalists and announcements.
- Every import, correction, publication, cancellation, and role change writes an `audit_log` record.
- Operational scan tables remain separate from registration/auth tables.

### 10.3 Existing repository mapping

- `students` currently represents operational roster / scan identity (`app/database.py` `SCHEMA`).
- `guests` is guest-pass identity.
- `scans` records attendee movement and use history.
- `settings` stores event metadata and counts.

These should be preserved and kept separate from official-registration and student-account records. Only approved operational synchronization should copy or reference official eligibility fields, never replace the scan tables.

## 11. Data-retention and archival policy options

The repository does not define retention policy. The design should require an explicit university decision.

### 11.1 Recommended policy categories

1. Active information for current event
   - current convocation record,
   - active registrations,
   - currently published announcements,
   - active medalists,
   - current event dates/venue/instructions.

2. Historical official records
   - archived registration records for prior convocations,
   - old event metadata,
   - prior medalist and announcement records after publication.

3. Temporary operational data
   - temporary Excel upload files,
   - preview validation artifacts,
   - import logs that are no longer needed,
   - delivery logs or push message traces where they are not official records.

### 11.2 Required policy decisions

The university must decide:

- how long official registration records should remain visible;
- whether past convocation lists are archived or soft-deleted;
- how long temporary import files should remain after a successful import;
- whether delivery logs are retained for operational evidence or expire quickly;
- whether medalist records remain publicly visible after an event ends.

No retention policy should be enforced in code without a stated institutional requirement.

## 12. Security, privacy and audit requirements

### 12.1 Security principles

- No student identity should be established from a single field (`registration_no` alone is insufficient).
- No unauthenticated public route should expose private registration or audit data.
- Student account passwords and secure session tokens must be introduced only through a real auth design.
- A student must never be told they are unregistered merely because the backend failed or is temporarily unavailable.
- Public medalist payloads must contain only approved display data.

### 12.2 Privacy requirements

- Public-facing medalist data: name + picture only.
- Public-facing event information: approved event details only.
- Internal exam data: registration list, correction workflows, import history, and audit rows remain restricted.
- No private profile data or student contact details should leak into public or medalist APIs.

### 12.3 Audit requirements

Each sensitive action must be attributable to an authenticated user:

- batch import approved/rejected;
- row correction or cancellation;
- registration match or claim override;
- publication of announcements;
- medalist photo approval;
- role changes.

This is a design requirement for the new examination module. It does not exist in the current codebase.

## 13. Database and migration strategy

### 13.1 Current state

Verified current implementation:

- SQLite database (`app/lgu.db`) created by `database.init_db()` and `seed()`.
- No migration tool is present.
- The code intentionally uses `CREATE TABLE IF NOT EXISTS` pattern; there is no Alembic or equivalent framework.

### 13.2 Development recommendation

Keep SQLite for development and local testing. It is sufficient for roughly 6,000 students, event-specific records, and safe local workflows. The current architecture is already a local, single-process development setup. No paid database or service should be introduced in this phase.

### 13.3 Production transition strategy

The future production database decision should be a deliberate deployment decision. The architecture should support a later migration by keeping:

- one SQL connection abstraction,
- business logic inside data-access modules rather than duplicated ad hoc queries,
- event-scoped tables with explicit `convocation_id`, and
- a migration table that tracks schema changes.

This allows a later move to PostgreSQL or another production database without rewriting the entire platform logic.

### 13.4 Operational separation

Official registration and account data should be intentionally separated from the existing attendee scan data. This preserves:

- QR identities,
- gate assignments,
- attendance history,
- guest pass lifecycle,
- current volunteer workflows.

The operational scan system is already implemented and should remain authoritative for event-day operations. Registration approval is a separate eligibility and account-service domain.

## 14. Risks and backward-compatibility safeguards

### 14.1 Key risks

- mixing official-registration logic into the existing scan roster;
- silently replacing the operational roster during exam import;
- using a single admin PIN as a blanket credential for all roles;
- setting the student system to rely on a single registration field instead of full server-side validation;
- exposing medalist or student-profile data unintentionally;
- creating a real email system without an approved institutional decision.

### 14.2 Backward-compatibility safeguards

- preserve current volunteer UI and route behavior;
- do not alter `students`, `guests`, `gates`, `scans`, or `broadcasts` schemas without a migration plan and explicit approval;
- keep the new official registration system separate from operational scan flows;
- authenticate exam admin actions through a distinct role model;
- treat all imported batches as auditable and reversible;
- preserve historical records by archival status rather than destructive replacement.

## 15. Recommended implementation phases and acceptance criteria

### Phase 1 — foundation and role separation

Scope:
- role model,
- exam module scaffolding,
- convocation record table,
- migration table.

Acceptance:
- volunteer and gate flows remain unchanged;
- exam module has separate permissions;
- current SQLite setup remains local and free.

### Phase 2 — official registrations and import pipeline

Scope:
- registration import batches,
- validation preview,
- transactional import,
- corrections and cancellations,
- import history and audit.

Acceptance:
- bad files are rejected before commit;
- partial writes never occur;
- every batch is attributable.

### Phase 3 — student account and verification

Scope:
- account creation,
- registration verification,
- profile completion,
- approved photo requirement,
- sign-in flow.

Acceptance:
- no identity claim from a single field;
- no false “unregistered” message on backend failure;
- profile required before dashboard access.

### Phase 4 — event information and announcements

Scope:
- convocation dates,
- confirmed vs expected schedules,
- rehearsal details,
- venue and instructions,
- draft/published announcements.

Acceptance:
- draft content hidden from students;
- published info updates via backend with no app release required.

### Phase 5 — medalist board

Scope:
- department awards,
- medalist photos,
- public board rendering.

Acceptance:
- public API exposes name + photo only;
- no private contact or academic details exposed.

### Phase 6 — historical retention and export

Scope:
- archival rules,
- export of previous convocations,
- historical display and cleanup policy.

Acceptance:
- no accidental deletion of active operational data;
- old convocations remain accessible according to approved retention policy.

## 16. Decisions that require the user or university input

This design deliberately leaves the following unresolved because the current repository does not supply them:

1. Which email-verification mechanism will the university approve: SMTP-based OTP, SSO, or an exam-controlled claim-code flow?
2. What are the exact official spreadsheet columns for the registration file and the medalist file?
3. Will medalist photographs allow reuse of a student profile image or must they always be separate approved images?
4. What is the retention policy for old convocation data, temporary import files, and announcement logs?
5. Will the university require individual exam staff accounts, or is a role-based shared credential acceptable for the first revision?
6. Is a separate public student app required immediately, or should the new student experience first ship in a web portal with the mobile app added later?
7. Does the university require a production DB decision now, or is the local SQLite + migration plan acceptable before deployment?

## Final design position

The smallest safe architecture is not a rewrite. It is a layered expansion over the current system:

- keep the operational QR/scan platform intact;
- add a separate examination-module role and web admin space;
- add official registration data and verification services;
- add a student account lifecycle and student app; and
- publish event and medalist data through backend APIs without changing the existing volunteer and gate workflows.

This preserves the repository’s existing working behavior while creating a clean domain boundary between operational attendance and official student identity management.
