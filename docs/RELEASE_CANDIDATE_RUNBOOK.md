# Release Candidate Runbook — LGU Smart Convocation

Phase 23 §8. This is the **repeatable preproduction acceptance procedure** for a
release candidate. It complements [OPERATIONS.md](OPERATIONS.md), which remains
the standing operational reference (secrets, provisioning, event-day routines,
troubleshooting). Where the two disagree, this document wins for release
activity and OPERATIONS.md wins for day-to-day operation.

This runbook is **dry-run safe**: every step below can be executed against a
rehearsal copy of the database without touching production. Step 4 is the only
step that changes a database, and it is written so that it is executed against
the backup copy first and against production only after an explicit approval
gate.

---

## 1. Scope and non-goals

**In scope** — validating one release candidate end to end: configuration,
schema, mail, devices, capacity, and the operator procedure to recover.

**Explicitly out of scope** — deploying the code, provisioning production
accounts, configuring production credentials, and migrating `app/lgu.db`. Those
belong to the release phase that follows an approved GO decision.

## 2. Roles and authority

| Role | Owns | May approve |
| --- | --- | --- |
| Release operator | running every step, capturing evidence | steps 1–3, 5–8 |
| Authorized migration operator | step 4 against production | GO / NO-GO |
| Institution (Examination Dept.) | event-day capacity, staff/scanner roster | capacity gate |
| Hosting provider contact | TLS, SMTP credentials, network path | external gates |

An approval gate that has no named owner is **BLOCKED**, never assumed.

---

## 3. Step 1 — Release preflight (read-only)

Run on the machine that will host the release, with the production environment
variables already exported:

```powershell
cd app
..\..\.venv\Scripts\python.exe scripts\preflight.py
```

The tool never prints a secret value, never connects to a remote service, never
sends mail, and opens the database **read-only**. It exits `1` if any check
FAILs.

Interpretation:

* `PASS` — the configuration is structurally correct.
* `FAIL` — an unmet precondition the operator must fix (for example, the
  committed demo secrets are still in place). **A missing production secret is
  a FAIL, never a fallback.**
* `BLOCKED` — a decision or credential only the institution or hosting provider
  can supply. This is a visible gate, not a pass.

Record the full output in the release evidence folder. A preflight that reports
`FAIL` on secrets is the expected and correct answer on a development machine.

## 4. Step 2 — Rehearse the migration on a copy (never production)

The historical production baseline was reported as schema v6. The current
migration ladder ends at **v14**; the actual production version is NOT
verified by this source-only review. The operator must verify the source
version independently before proceeding. The expected path is **v6→v14**.

Run the existing synthetic-only regression script (its old filename mentions
v11, but its `LATEST` variable uses the current migration target):

```powershell
cd app
..\..\.venv\Scripts\python.exe scripts\test_phase21_migration_v6_to_v11.py
```

Require every reported check to pass, including version, data preservation,
constraints, idempotency and rollback. Do not rely on an obsolete fixed
test count. Do NOT use the live database in this rehearsal.

Keep the validated SQLite journaling policy; do not change journal mode
during a release.

## 5. Step 3 — Back up and verify the restore path

An authorized operator chooses a private, access-restricted NEW backup
destination and records its path. The following is an example interface
only; this review did not run these commands on production:

```powershell
cd app
$backup = 'D:\approved-backups\convocation-pre-migration.db'
..\..\.venv\Scripts\python.exe scripts\backup_db.py create --dest "$backup"
..\..\.venv\Scripts\python.exe scripts\backup_db.py verify "$backup"
..\..\.venv\Scripts\python.exe scripts\backup_db.py list
```

Verify a restore to an UNUSED disposable destination, never the active
production path. Keep backup artifacts private: they contain student data
and credential hashes. Do not proceed without verified recovery evidence.

## 6. Step 4 — Migration (approval gate)

> **NO-GO without written approval.** Ordinary production startup must
> REFUSE outdated or missing schema files before initialization or seeding.
> This review adds a refusal guard, not an authorization to migrate.

1. Keep the live service stopped and independently verify the database
   version, integrity, owner and intended migration target (v14).
2. Obtain operator and institution sign-off, a verified backup, and a
   successful v6→v14 rehearsal on a separate disposable copy.
3. Execute the migration only through a separately reviewed and explicitly
   operator-invoked offline procedure. There is NO approved automatic
   production migration command in this PR. Until that procedure exists,
   **this step remains BLOCKED**. Do not disable the startup guard.
4. Record migration evidence and approve startup only after the checks
   in Step 5 pass. If anything differs, stop before any admissions.

## 7. Step 5 — Verify the migrated database

Verification is performed by the named authorized operator after approval.
Do not attempt live validation in an unapproved review workflow.

| Check | Expected |
| --- | --- |
| `PRAGMA user_version` | `14` |
| `PRAGMA integrity_check` | `ok` |
| tables and indexes | match the tested v14 fixture and migration plan |
| preserved data | row counts / integrity evidence compared privately with the verified backup |
| preflight schema version | `PASS (current)` |

Do not disclose student records or credentials in CI logs or PRs.

## 8. Step 6 — Event-day smoke test

Only after authorized release approval, using approved test records and
physical devices:

1. GET `/api/health` must return HTTP 200 and parsed JSON with `ok: true`.
2. Staff login and dashboard must work over HTTPS with Secure cookies.
3. A real device at one gate scans a valid synthetic pass once successfully.
4. Repeat the scan: duplicate rejected without a second admission.
5. Unknown/expired pass rejected; offline queue reconciles correctly.
6. Verify a second physical gate device with its authorized scanner login.

Failure at any step means NO-GO.

## 9. Step 7 — Recovery procedure

Before the event, rehearse recovery on a disposable COPY with a private
verified backup; do not write to or overwrite production. Use
`backup_db.py restore <backup> --to <new-file>` only with a nonexistent
destination. A witnessed live recovery is a separate operator decision.
Verify the copy's schema, integrity and compatibility with the previous
application build; record the rollback decision and approval.

## 10. Step 8 — External acceptance gates

| Gate | Required verification | Owner |
| --- | --- | --- |
| Production backup/migration | verified backup + approved v6→v14 offline procedure | Institution + migration operator |
| HTTPS and session cookies | trusted HTTPS from client devices, `LGU_COOKIE_SECURE=1`, reachable backend | Hosting |
| Real SMTP delivery | received signup and recovery emails at controlled real mailboxes | Institution + hosting |
| Signed Android preview APK | installed and scanned on physical phone; offline/online sync with synthetic staging records | Institution |
| Event-day capacity | field/LAN load tested against the event's actual targets | Institution |
| Production secrets | operator supplies real keys/PIN via secret store, never in source or CI | Hosting |
## 11. Step 9 — Go / no-go decision record

Record all of the following before deciding. The numbering is the canonical
release-gate list first established in the Phase 20 readiness report, so status
is comparable across phases. A GO requires **every** gate closed.

| # | Gate | Evidence | Status | Owner | Next action |
| --- | --- | --- | --- | --- | --- |
| 1 | Automated regression (Python + mobile + tsc + eslint) | full battery, 0 failures | | Release operator | |
| 2 | Migration rehearsal on disposable DBs | v6→v14 suite, all checks pass | | Release operator | |
| 3 | Backup / restore workflow | backup suite, 40/40 | | Release operator | |
| 4 | Runtime configuration audit + preflight | config audit 84/84; `preflight.py` | | Release operator | |
| 5 | Authorization matrix closed or classified | authz matrix, 35/35 | | Release operator | |
| 6 | Operations runbook exists | OPERATIONS.md + this runbook | | Release operator | |
| 7 | Production DB integrity preserved | stamp unchanged, integrity ok | | Release operator | |
| 8 | **Real SMTP delivery** | a real code received in a real mailbox | | Institution + hosting | |
| 9 | **Android device validation** | physical device, real passes | | Institution | |
| 10 | **Migration applied to production** | separately approved and verified to `14` | | Migration operator | |
| 11 | **Performance / capacity under event-day load** | institutional target met | | Institution | |
| 12 | **Production credentials provisioned** | real secrets set, demo guard satisfied | | Hosting | |

**The release is NO-GO while any row above is BLOCKED or NOT TESTED.** Automated
tests passing is necessary and never sufficient: gates 8, 9, 11 and 12 are
external observations that no suite in this repository can produce.

See [PHASE23_RELEASE_CANDIDATE_GO_NO_GO_REPORT.md](../PHASE23_RELEASE_CANDIDATE_GO_NO_GO_REPORT.md)
for the current status of every gate.
