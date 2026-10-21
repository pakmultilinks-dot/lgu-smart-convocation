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

The production database is at `PRAGMA user_version = 6`; this build supports
`11`. Five migrations (7–11) are pending and have **never been applied to
production**.

Prove the upgrade on a disposable copy before any production step:

```powershell
cd app
..\..\.venv\Scripts\python.exe scripts\test_phase21_migration_v6_to_v11.py
```

This suite builds a synthetic version-6 database containing live records, runs
the real migration runner to 11, and proves row identity, enforced constraints,
workflow support, idempotence, fail-closed behaviour on a newer schema, and
atomic rollback of a failing migration. It must report **91/91**.

The journal mode is **ROLLBACK JOURNAL (the default)**, retained after the
Phase 22 investigation. WAL is faster under concurrent readers but changes the
backup story and is not justified by the measured gate load; do not switch it
as part of a release.

## 5. Step 3 — Back up and verify the restore path

```powershell
cd app
..\..\.venv\Scripts\python.exe scripts\backup_db.py create  --label pre-migration
..\..\.venv\Scripts\python.exe scripts\backup_db.py verify --label pre-migration
..\..\.venv\Scripts\python.exe scripts\backup_db.py list
```

`backup()` uses SQLite's online backup API (`conn.backup`), which is correct
for the rollback journal and does not block readers. `restore()` refuses to
write to the production path, so a restore rehearsal must name a different
destination — that refusal is itself an assertion, not an obstacle.

**Do not proceed to step 4 until a backup exists and has verified.**

## 6. Step 4 — Migration (approval gate)

> **Approval gate.** This is the only step that alters a database. It requires
> the named authorized migration operator, a verified backup from step 3, and a
> written GO. It has **not** been executed against production.

1. Take the service offline for maintenance (see §7).
2. Confirm the on-disk version is still the expected one:
   `PRAGMA user_version;` must return `6`. A different value means the database
   moved since preflight — stop and re-run step 1.
3. Run the migration as a deliberate, separate action. Migrations run as part
   of application start-up, so starting the service against the production
   database performs the upgrade. Start it and watch for a clean start.
4. Immediately confirm the result (step 5). If anything is wrong, go to §8
   **before** admitting a single attendee.

Because migrations 7–11 are additive (tables, columns with defaults, indexes),
an interrupted run leaves no partial schema and no version bump — that property
is asserted by the rehearsal suite and is why the run is safe to retry.

## 7. Step 5 — Verify the migrated database

```powershell
cd app
..\..\.venv\Scripts\python.exe scripts\preflight.py
```

Required evidence:

| Check | Expected |
| --- | --- |
| `PRAGMA user_version` | `11` |
| `PRAGMA integrity_check` | `ok` |
| table count | 35 (production is at 27 on version 6; migrations 7–11 add 8) |
| preflight `schema version` | `PASS (current)` |

Then confirm no data moved unexpectedly: a spot-check of convocation
registrations, claims, passes and admissions counts against the pre-migration
backup.

## 8. Step 6 — Event-day smoke test

With the service running against the migrated database, in this order:

1. Health: `GET /healthz` returns `{"ok":true}` — note there is **no space**
   after the colon when matching the body text.
2. Staff sign-in succeeds and the dashboard renders.
3. A volunteer signs in on one gate device and scans one known-valid pass:
   expect a green **CONVOCATION ENTRY RECORDED**.
4. Scan the same pass again: expect the already-used outcome, and confirm the
   admissions ledger still holds exactly **one** row for it.
5. Scan an expired or unknown pass: expect a red rejection, and confirm the
   ledger is unchanged.
6. Confirm a second device on a different gate reports independently.

A failure at any step is a NO-GO for the release, not a defect to be worked
around on the day.

## 9. Step 7 — Recovery procedure

**Before** the event, not after:

1. Stop the service.
2. `restore()` the verified backup to the production path. The command refuses
   the production destination by design, so perform this as an explicit,
   witnessed restore — never silently.
3. Restart and re-run step 5 to confirm `user_version = 6` and integrity `ok`.
4. Re-run the smoke test with the pre-migration build.

Recovery is only credible if it has been **rehearsed once against a copy**
before the event. Do not rehearse it against production.

## 10. Step 8 — External acceptance gates

These cannot be closed by any automated suite. Each is a release gate with a
named owner; each remains open until that owner supplies evidence.

| Gate | What must be shown | Owner |
| --- | --- | --- |
| Real SMTP delivery | a real sign-up code and a real recovery code delivered to real mailboxes, from the production SMTP account | Institution + hosting |
| Android device run | the mobile build installed on a physical device, scanning real passes against the release | Institution |
| Event-day capacity | an institutional concurrency estimate and response-time target, then a load test against **that** target | Institution |
| Production credentials | real `LGU_SECRET_KEY`, `LGU_HMAC_SECRET`, `LGU_ADMIN_PIN` set on the host | Hosting |
| TLS decision | plain-HTTP LAN vs TLS, driving `LGU_COOKIE_SECURE` | Hosting |

The email configuration is *structurally* valid in every environment — host,
port, TLS, sender, user/password pairing and TTL all parse — but **structural
validity is not delivery evidence**. A device run and a delivered email are
observations; a passing suite is not.

## 11. Step 9 — Go / no-go decision record

Record all of the following before deciding. The numbering is the canonical
release-gate list first established in the Phase 20 readiness report, so status
is comparable across phases. A GO requires **every** gate closed.

| # | Gate | Evidence | Status | Owner | Next action |
| --- | --- | --- | --- | --- | --- |
| 1 | Automated regression (Python + mobile + tsc + eslint) | full battery, 0 failures | | Release operator | |
| 2 | Migration rehearsal on disposable DBs | v6→v11 suite, 91/91 | | Release operator | |
| 3 | Backup / restore workflow | backup suite, 40/40 | | Release operator | |
| 4 | Runtime configuration audit + preflight | config audit 84/84; `preflight.py` | | Release operator | |
| 5 | Authorization matrix closed or classified | authz matrix, 35/35 | | Release operator | |
| 6 | Operations runbook exists | OPERATIONS.md + this runbook | | Release operator | |
| 7 | Production DB integrity preserved | stamp unchanged, integrity ok | | Release operator | |
| 8 | **Real SMTP delivery** | a real code received in a real mailbox | | Institution + hosting | |
| 9 | **Android device validation** | physical device, real passes | | Institution | |
| 10 | **Migration applied to production** | executed and verified to `11` | | Migration operator | |
| 11 | **Performance / capacity under event-day load** | institutional target met | | Institution | |
| 12 | **Production credentials provisioned** | real secrets set, demo guard satisfied | | Hosting | |

**The release is NO-GO while any row above is BLOCKED or NOT TESTED.** Automated
tests passing is necessary and never sufficient: gates 8, 9, 11 and 12 are
external observations that no suite in this repository can produce.

See [PHASE23_RELEASE_CANDIDATE_GO_NO_GO_REPORT.md](../PHASE23_RELEASE_CANDIDATE_GO_NO_GO_REPORT.md)
for the current status of every gate.
