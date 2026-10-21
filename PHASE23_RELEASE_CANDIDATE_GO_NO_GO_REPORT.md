# Phase 23 — Release Candidate Validation & Operational Go/No-Go

**Verdict: NO-GO.** Release-critical behavior is validated and the automated
surface is fully green, but five mandatory external and institutional gates
(8–12) remain open. Automated tests passing is necessary and is not sufficient.

Phase 23 objective: *validate the integrated system's release-critical
behavior, establish a repeatable preproduction acceptance procedure, and produce
a final evidence-based go/no-go decision without deploying or modifying
production data.*

---

## 1. Baseline and release discipline

### What was not done, by instruction

No commit, no push, no deploy, no provisioning of production accounts, no
configuration of production credentials, and **`app/lgu.db` was never migrated**.
No fallback production secret was generated. Every command in this phase ran
against disposable databases or read-only views.

### Production database boundary — unchanged

| Property | Value |
| --- | --- |
| Path | `app/lgu.db` |
| Size | 278 528 bytes |
| SHA-256 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` |
| `PRAGMA user_version` | `6` |
| `PRAGMA integrity_check` | `ok` |
| Tables | 27 |

The hash was captured **before and after every command** in this phase, including
the preflight, the migration rehearsal, and the full regression battery. It never
changed. Production is **five schema versions behind the build** (migrations 7–11
pending) — that remains an open gate, not a defect.

### Repository state

Branch `main`, HEAD `298c272d53485ba4473c2defe72db70c02733a2c` (unchanged), 173
dirty paths, 0 stashes. Nothing was staged, reset, stashed, amended or committed.

### Release discipline applied

* Every new database opened in this phase is disposable and is created inside a
  `tempfile` directory.
* The one command that touches the configured production path (`preflight.py`)
  opens it with a `mode=ro` URI and asserts nothing about it beyond read-only
  facts.
* A synthetic migration rehearsal is reported as a rehearsal. It is never
  described as a production migration.

---

## 2. Transient-busy behavior: contract trace and three defects fixed

Phase 22 established that SQLite write contention is answered with a controlled,
retryable HTTP 503. Phase 23 traced that answer **all the way to the volunteer's
handset** — a different and stronger property, because the mobile client
recognises a busy answer by JSON *shape*, and a rename on either side silently
degrades the volunteer into reading a red failure at a live gate.

The contract, both sides:

| Side | Contract |
| --- | --- |
| Backend | `{"status":"busy","level":"amber","title":"TEMPORARILY BUSY","detail":"…","retryable":true}` + `Retry-After: 2`, HTTP 503 |
| Mobile | `busyError()` recognises the body iff `status === "busy"` **and** `retryable === true`; the classifier returns a notice card with a **warning** haptic; the device stays **online** |

### Three defects found and fixed

**D1 — the amber contract was entirely lost.** `request()` saw
`response.ok === false` and threw `ApiError`. The body carries no `error` key, so
the message fell back to the generic *"The service is temporarily unavailable"*
and `title`, `level` and `retryable` were all discarded. `ScannerScreen` then
rendered a **red `status:"error"` card titled "SCAN FAILED" with an error
haptic**. A transient lock read to the volunteer as a broken scan.
*Fixed:* contention is now recognised **before** the generic error path and
rethrown carrying the backend's own amber body.

**D2 — a busy server was reported to the operator as an offline gate.** The catch
block called `setOnline(false)` unconditionally, including on a 503. The device
had received an answer, so it was demonstrably online; the *next* scan was
diverted to the offline queue and displayed as amber **"SCAN QUEUED"** — live
server contention being reported as an offline operation, with the scan silently
deferred.
*Fixed:* the device is marked offline only when the answer is **not** retryable.

**D3 — the type unions were untruthful.** `ScanResult.status` and
`SyncItemResult.status` were `"ok" | "error"` while the backend legitimately
emits a third value.
*Fixed:* both unions are now `"ok" | "error" | "busy"`.

### A fourth defect found while fixing the first three

The busy branch classified from `sanitizeTitle()`'s output, and that function
substitutes its own *"Scan failed"* fallback for an empty title — so a busy
answer with an empty title would have rendered exactly the red-sounding wording
the fix exists to prevent. `sanitizeTitle()` now takes a fallback parameter and
the busy path passes `"TEMPORARILY BUSY"`. Sanitization was also applied to the
busy path itself, which it had bypassed: a hostile title containing a URL or a
traceback now falls back to the sanctioned wording rather than reaching the
operator.

### The sync path needed no fix

`reconcileSync` drops items on `status === "ok"`, drops and reports items whose
title is a permanent rejection, and **keeps everything else queued for retry**.
`status:"busy"` is therefore correctly retained — confirmed in §3.

### Evidence

`app/scripts/test_phase23_busy_contract.py` — **27/27**, sections [A]–[E], on a
disposable database with a second connection holding `BEGIN IMMEDIATE`:

| Section | Proves |
| --- | --- |
| [A] | the exact body: `status`/`retryable`/`level`/`title`/`detail` all correct, `Retry-After` is a bare number, no `sqlite`/`locked`/`traceback` leaks |
| [B] | the client's own recognition predicate — mirrored literally from `client.ts` — accepts the real server body, and **rejects** three lookalikes |
| [C] | contention admits nobody and burns nothing; the **same** pass admits after release, exactly once |
| [D] | a busy device stays online; the immediately following scan is a real outcome, never a 500 |
| [E] | `/api/sync` answers 200 with one truthful result per item under contention, and replaying the batch after release admits both passes **exactly once** |

`mobile/scripts/scanner-logic-test.mjs` — **64/64** (was 58; six new checks pin
busy → `kind:"other"` + `"TEMPORARILY BUSY"` + warning haptic, busy never
valid/already-used/invalid, busy with an outcome-shaped title still a notice,
busy with an empty title, and busy with technical text).

---

## 3. Contention reproduced deliberately

Contention was reproduced with a second connection taking `BEGIN IMMEDIATE` and
refusing to release it — the only honest way to create real lock contention
rather than simulate it. Both §2 suites run this way, and Phase 22's own suite
(65/65) still passes unchanged.

Observed under a held writer: the response is **503 with the amber body**, never
an unhandled 500, and reads continue to be served.

---

## 4. Release preflight — **NEW**

No release preflight existed. `app/scripts/preflight.py` is a **read-only**
command that answers one question: *if this machine's environment were the
production environment, would the service start, and would it be safe to expose?*

It never prints a secret value (names, presence and lengths only), never connects
to a remote service, never sends mail, never creates an account, never changes a
credential, never deploys, and opens the configured database with a `mode=ro`
URI. Statuses are `PASS` / `FAIL` / `BLOCKED` / `NOT TESTED`; exit is `1` if any
check FAILs. `BLOCKED` is a decision only the institution or host can supply — a
visible gate, not a pass, and deliberately does not fail the exit code so a
config-only rehearsal can still run. **A missing production secret is a FAIL,
never a fallback.**

Result on this machine:

```
PREFLIGHT: 23 PASS, 4 FAIL, 8 BLOCKED, 0 NOT TESTED
PREFLIGHT RESULT: FAIL
```

| Check | Result |
| --- | --- |
| Demo-secret protection | PASS — `run.py` exits 1 before touching any database |
| Operator secrets | **FAIL** — all three still demo (names only, values never printed) |
| Email | LGU_EMAIL_MODE BLOCKED (`disabled`); structure PASS — but structural validity is not delivery evidence |
| Cookie / CSRF / CORS | HttpOnly, `SameSite=Lax`, `Secure` wired to `COOKIE_SECURE`; CORS allowlist, no wildcard |
| Rate limits | all six windows present and positive |
| Database | production path BLOCKED; opened `mode=ro`; integrity `ok`; **schema BLOCKED** — 5 migrations pending |
| Operational commands | backup CLI, scanner provisioning, staff provisioning, email checker, restore guard — all discoverable |
| Test-only flags | none enabled |
| Hosting decisions | TLS, SMTP credentials, capacity approval, migration operator — all BLOCKED |

The FAIL is the **correct** answer on a development machine and is reported as
such, not worked around.

---

## 5. Migration rehearsal and runbook

Re-ran the synthetic v6→v11 rehearsal: **91/91**, sections [01]–[10] — row
identity preserved, new tables/columns/indexes match, constraints enforce,
real workflows supported, re-run is a no-op, a newer schema still fails closed,
a failing migration leaves no partial schema and no version bump.

A fresh version-11 database holds **35 tables** (production is 27 on version 6).

`docs/RELEASE_CANDIDATE_RUNBOOK.md` is new: the repeatable preproduction
procedure, with a nine-step migration runbook carrying preconditions and
authorization, a maintenance state, backup and restore-verify, the migration
command, post-version/integrity checks, an event-day smoke test, a recovery
procedure, and explicit operator approval points. It accounts for the retained
**rollback journal** and instructs that WAL not be switched as part of a release.

**The migration has not been executed against `app/lgu.db` and is not claimed to
have been.** A successful synthetic rehearsal and a production migration are
different facts, and this report keeps them apart.

---

## 6. External acceptance evidence — **NOT TESTED**

Probed without reading any secret value:

```
LGU_SMTP_HOST / PORT / USER / PASSWORD / FROM   — all absent
adb, emulator, java, gradle                     — all absent
ANDROID_HOME, JAVA_HOME                         — absent
LGU_EMAIL_MODE                                  = disabled
```

Gate 8 (real SMTP delivery) and gate 9 (Android device validation) are
**NOT TESTED**. The email configuration is structurally valid in every
environment; that is a shape check, not a delivery observation. No email was
sent and no device was exercised, so neither is claimed.

---

## 7. Operational acceptance threshold — **BLOCKED**

Phase 22 measured, on both journal modes, a 60-concurrent synthetic admission
workload:

| Mode | Throughput | Admission p95 | Busy answers | Unhandled 500s | Read p95 during held writer |
| --- | --- | --- | --- | --- | --- |
| Rollback journal (retained) | 34.2 scan/s | 1386.6 ms | **3** | **0** | 11.7 ms |
| WAL | 48.8 scan/s | 335.9 ms | 0 | 0 | 17.4 ms |

Phase 21 benchmarks for the same system: 24.0 / 47.7 / 52.4 scan/s at concurrency
1 / 4 / 8; scanner login **6.1 rps, p50 631 ms** (the scrypt ceiling — it bounds
volunteer *sign-in*, not scan throughput); student reads degrade at concurrency 8
(p95 1260.6 ms).

**The three busy responses are not classified as defects.** They are bounded,
honest, retryable answers carrying `Retry-After: 2` — safer than a long hang or
an incorrect admission, and §2 proves they are now surfaced to the volunteer as
a retry notice rather than a failure.

**Capacity approval is BLOCKED, not approved.** No institutional concurrency
estimate and no response-time target has been supplied, so there is no target
against which these numbers can be judged. Synthetic throughput measured on a
development machine is **not** a production SLA and is not presented as one.

---

## 8. Full regression battery — **PASS**

**64 suites, 0 failures.**

| Gate | Result |
| --- | --- |
| Python suites (31) | 0 failures — including contention 65/65, journal mode 25/25, migration 91/91, busy contract 27/27, config audit 84/84, authz matrix 35/35, backup/restore 40/40, production-DB boundary **UNCHANGED** |
| Mobile suites (33) | 0 failures — including scanner-logic 64/64, master-audit-regression, release-safety |
| `tsc --noEmit` | exit 0 |
| `eslint .` | exit 0 (3 pre-existing `no-unused-vars` warnings in test scripts) |
| `git diff --check` | exit 0 (3 LF/CRLF notices on pre-existing files) |
| Production DB stamp | **unchanged** before and after |

Ruff: 1143 (Phase 22 close was 1104). The delta is confined to the two new Phase
23 scripts and comprises 36 `UP031` percent-format findings (house style —
explicitly not "fixed"), 6 `E402` findings required by the deliberate
env-var-before-import pattern every suite in this repo uses, and 3 deliberate
diagnostic `except Exception` handlers. **No new class of lint finding and no
finding in shipped application code.** Two genuine unused imports and two
unclosed `open()` calls found in the new files were cleaned.

---

## 9. Release candidate runbook

`docs/RELEASE_CANDIDATE_RUNBOOK.md` — new. It complements `docs/OPERATIONS.md`
(which remains the standing operational reference) and covers scope and
non-goals, roles and authority, the read-only preflight, the disposable-copy
migration rehearsal, backup-and-verify, the approval-gated production migration,
post-migration verification, the event-day smoke test, the recovery procedure,
the external acceptance gates, and the go/no-go decision record.

It is written dry-run safe: every step can be executed against a rehearsal copy
without touching production, and step 6 is the only step that changes a database
— executed against the backup copy first, against production only after an
explicit approval gate.

---

## 10. Release gate audit

Numbering is the canonical gate list from the Phase 20 readiness report, so
status is comparable across phases.

| # | Gate | Status | Evidence / gap |
|---|---|---| --- |
| 1 | Automated regression (Python + mobile + tsc + eslint) | **PASS** | §8 — 0 failures across 64 suites |
| 2 | Migration rehearsal on disposable DBs | **PASS** | §5 — 91/91 |
| 3 | Backup / restore workflow | **PASS** | 40/40; online-backup API, WAL-safe; `restore()` refuses the production path |
| 4 | Runtime configuration audit | **PASS** | 84/84, plus the new read-only `preflight.py` |
| 5 | Authorization matrix closed or classified | **PASS** | 35/35 |
| 6 | Operations runbook exists | **PASS** | `docs/OPERATIONS.md` + new `docs/RELEASE_CANDIDATE_RUNBOOK.md` |
| 7 | Production DB integrity preserved | **PASS** | byte-identical; `integrity_check ok`; hash unchanged before/after every command |
| 8 | **Real SMTP delivery** | **NOT TESTED** | No SMTP credentials present in this environment (§6). Structural validity is not delivery evidence. |
| 9 | **Android device / emulator validation** | **NOT TESTED** | No `adb`, emulator, `java` or `ANDROID_HOME` (§6). |
| 10 | **Migration applied to production** | **NOT APPLIED** | Production is at `user_version = 6`; build supports 11. A rehearsal is not a deployment. |
| 11 | **Performance / capacity under event-day load** | **BLOCKED** | No institutional concurrency estimate or response-time target supplied, so no target exists to test against (§7). Synthetic numbers are not an SLA. |
| 12 | **Production credentials provisioned** | **NOT DONE** | Preflight reports 4 FAILs: all three secrets still hold committed demo values (§4). The guard correctly refuses to start. |

### Verdict: **NO-GO**

Gates 8–12 remain open. Gate 10 means the running production database is **five
schema versions behind** the code. Gate 12 means the server will refuse to start
until an operator sets real secrets. Gate 11 has no institutional target to
measure against. Both refusals are correct and deliberate — they are the system
working, not defects.

**Do not declare production readiness merely because automated tests pass.**
**Do not describe migration 11 as production-applied because it passed on a
disposable database.**
**Do not generate a fallback production secret.**

---

## 11. What would close the remaining gates

| Gate | Required action | Owner |
| --- | --- | --- |
| 8 | Supply real SMTP credentials, then deliver a real sign-up code and a real recovery code to real mailboxes from the production account | Institution + hosting |
| 9 | Install the mobile build on a physical device and scan real passes against the release | Institution |
| 10 | Follow runbook steps 4–6 with the named authorized migration operator and a verified backup | Migration operator |
| 11 | Supply an event-day concurrency estimate and response-time target; then test against that target | Institution |
| 12 | Set real `LGU_SECRET_KEY`, `LGU_HMAC_SECRET`, `LGU_ADMIN_PIN` on the host; re-run `preflight.py` until 0 FAIL | Hosting |

---

## 12. Hard stop

Phase 23 is finished and this report is written. Stopping for review.

Not done, by instruction: Phase 24 not begun; no commit; no push; no deploy; no
production accounts provisioned; production credentials unaltered;
`app/lgu.db` unmodified and **not migrated**; no fallback production secret
generated.
