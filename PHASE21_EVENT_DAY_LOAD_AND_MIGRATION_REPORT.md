# Phase 21 — Event-Day Load, Resilience & Migration Compatibility

**Date:** 2026-10-14
**Branch:** `main` @ `298c272d53485ba4473c2defe72db70c02733a2c` (unchanged — nothing committed)
**Release status:** **NO-GO unchanged from Phase 20.** Phase 21 produced no new blocker, but it did
produce one material availability finding (§5.3) that must be decided before release. All work in
this phase ran against **synthetic, disposable databases**. **No production migration was performed.**

---

## 1. Confirmed baseline and tested environment

| Item | Value |
|---|---|
| Git branch / HEAD | `main` @ `298c272d53485ba4473c2defe72db70c02733a2c` |
| Stashes / commits ahead | 0 / 0 |
| Working tree entries | 158 at baseline | **164** at close (+6: 5 Phase 21 scripts + this report) |
| Python | 3.13.7 (repo-root `.venv`) |
| Flask / SQLite | 3.1.3 / **3.50.4** |
| Machine | 8 logical CPUs, 15.7 GB RAM, Windows, PowerShell |
| Available | No `adb`, no emulator, no Java, no SMTP, `psutil` not installed |
| Production DB | 278528 bytes, `PRAGMA user_version = 6`, 27 tables — see §9 |

The five release gates left open by Phase 20 are **unchanged**: production credentials, authorized
migration execution, external SMTP, real Android camera verification, and institutional
capacity approval. Phase 21 adds none of its own but surfaces the write-contention finding in §5.3.

**Test environment limitation, stated up front:** the machine was shared during measurement and the
process was single-host. **Numbers vary materially between runs** — repeat executions of the same
harness produced read throughput of 33.0, 38.8 and 16.4 rps at concurrency 1 for the same workload.
Figures below are therefore reported as **observed ranges**, not as stable capacity claims.

---

## 2. Version-6-to-11 migration results (synthetic data)

**Status: PASS — 91/91 checks, exit 0.** Script: `app/scripts/test_phase21_migration_v6_to_v11.py`

A genuine v6 database was built by limiting `migrations.MIGRATIONS` to the definitions through
version 6, then running `database.init_db()` and `database.seed()`. **No fixture was derived from
production data** — every row is synthetic. The real `migrations.migrate()` was then run 6 → 11.

| Verification required by spec | Result |
|---|---|
| All five subsequent migrations complete | **PASS** |
| Existing student, guest, gate, attendance, staff records remain correct | **PASS** — identity preserved column-by-column |
| New tables, indexes, columns, constraints, defaults match expected schema | **PASS** — snapshot diff over `PRAGMA table_info` / `index_list` / `index_xinfo` |
| Existing scanner and convocation data preserved | **PASS** |
| No synthetic legacy record silently reassigned | **PASS** — every `(id, identity)` pair re-checked |
| Resulting application initializes and executes workflows | **PASS** — registration, claim, pass issue, scan, admission |
| Running the migration runner again is safe | **PASS** — idempotent no-op |
| Unsupported newer schemas fail closed | **PASS** — `user_version = 99` raises `RuntimeError`, metadata untouched |
| A failed migration does not leave advanced metadata or partial changes | **PASS** — `user_version` rolled back, no partial DDL |

Schema changes confirmed: **10 new indexes**, `credential_established` backfill (1 row), and a
**UNIQUE backstop** on admission. **No defect was found; no regression test was added for §2** —
there was nothing to encode.

---

## 3. Fresh-database and repeat-migration results

**Status: PASS** (within the same 91/91 suite)

- Fresh `database.init_db()` lands directly on **version 11**, never on an intermediate version.
- `user_version = 10` → migration to 11 succeeds **with data present**; existing rows survive.
- Repeat `migrate()` against an already-current database is a safe no-op.

---

## 4. Workload sizes, concurrency, throughput and latency

**Status: PASS (measured and repeatable). Explicit caveat: this is a SYNTHETIC BENCHMARK.**

> No realistic institutional demand estimate has been supplied, so **these numbers must not be read
> as real convocation-day demand or as approved capacity.** Production-capacity approval remains
> **pending**. No SLA is invented here.

Script: `app/scripts/test_phase21_load_resilience.py` — **26/26 checks, exit 0.**

**Synthetic world:** 3,000 registrations across 8 departments, 3,000 student accounts, 3,000 claims,
2,500 active passes, 500 legacy roster students (`BQR%07d`), one published convocation, 8 scanners
(7 gate-scoped + 1 rover across all 7 gates). DB starts at 2,424,832 bytes.

| Workload | Concurrency | Throughput (rps) | p50 (ms) | p95 (ms) | 4xx | 5xx | db err |
|---|---|---|---|---|---|---|---|
| Staff reads (health/gates/config/dashboard) | 1 / 4 / 8 | 16.4 / 29.7 / 34.9 | 58.0 / 132.4 / 221.8 | 68.7 / 152.5 / 295.6 | 0 | 0 | 0 |
| Student reads (event/readiness/feed) | 1 / 4 / 8 | 15.3 / 18.4 / 18.2 | 64.1 / 194.4 / 232.0 | 76.1 / 363.2 / **1260.6** | 0 | 0 | 0 |
| Registration search | 1 / 4 / 8 | 109.9 / 232.8 / 275.5 | 8.5 / 16.9 / 28.4 | — / — / 39.7 | 0 | 0 | 0 |
| **Scan (gate 1, real traffic)** | 1 / 4 / 8 | **24.0 / 47.7 / 52.4** | 41.4 / 82.7 / 146.8 | 48.3 / 101.7 / 186.8 | 0 | 0 | 0 |
| Invalid / forged payloads | 1 / 4 / 8 | 68.0 / 104.7 / 97.2 | — | — | all | 0 | 0 |
| Unauthenticated / expired / revoked | 4 | 355.4 | 13.6 | 20.8 | 600 | 0 | 0 |
| **Scanner login (scrypt verify)** | 4 | **6.1** | **631.0** | **751.3** | 0 | 0 | 0 |
| Scan at a gate the scanner is not provisioned for | 4 | 143.1 | 26.8 | — | 240 | 0 | 0 |
| Dashboard attendance summary | 1 / 4 / 8 | 69.4 / 125.9 / 143.2 | 14.4 / 29.7 / 53.9 | — / — / 74.3 | 0 | 0 | 0 |

**Observed ranges across repeat runs:** read throughput at c=1 spanned **16.4–38.8 rps**; scan at
c=8 spanned **51.9–52.4 rps**; registration search at c=8 spanned **249.2–275.5 rps**; scanner login
at c=4 spanned **5.8–6.1 rps** with p50 **630.6–631.0 ms**.

**Two structural observations, both measured:**

1. **Scanner login is the throughput ceiling at 6.1 rps / p50 ~631 ms.** `student_auth`/`scanner_auth`
   verify a **scrypt** hash on every login. Scanning is *not* affected — it hashes once with SHA-256
   (§5). This bounds how many volunteers can sign in simultaneously, not how fast they can scan.
   Mitigation is operational, not architectural: pre-provision sessions before gates open.
2. **Student reads degrade badly at c=8** (p95 1260.6 ms, ~6× the c=1 median) while staff reads and
   search stay flat. Student read paths are the least index-friendly of the measured set.

**Resource and size data:** `psutil` is not installed, so CPU and memory were **NOT TESTED**. DB size
grew 2,424,832 → 2,822,144 bytes (**+397,312**) across the whole benchmark.

---

## 5. Locking, duplicate-admission and resilience results

**Status: PASS on correctness; one material availability finding.**

Script: `app/scripts/test_phase21_load_resilience.py` §B–G, plus
`app/scripts/test_phase21_sqlite_limits.py` — **10/10, exit 0.**

### 5.1 Duplicate admission is impossible under concurrency — PASS

| Scenario | Attempts | Passes | Result |
|---|---|---|---|
| c=4, 4 concurrent duplicates per pass | 240 over 60 passes in 5.03 s | 60 | **60 admitted, 0 admitted more than once**, ledger = 531 |
| c=8, 8 concurrent duplicates per pass | 480 over 60 passes in 8.65 s | 60 | **60 admitted, 0 admitted more than once**, ledger = 591 |

Correctness rests **entirely** on the `UNIQUE (convocation_id, registration_id)` index
(`idx_convocation_admissions_once`) plus the `sqlite3.IntegrityError` catch — there is **no
module-level lock**. Section 5.1's two races are the evidence for that claim. See §7 for the
docstring defect this finding corrected.

### 5.2 Failed scans never create admissions — PASS

Invalid/forged payloads (c=1/4/8) returned **all 4xx, zero 5xx, zero DB errors**.
Unauthorized, expired and revoked scanner sessions: **600 requests, 600 × 4xx**.
**Refused bursts changed nothing: admissions 591 → 591, used passes 591 → 591.**
Cross-gate attempts by an under-scoped scanner: **240/240 refused**, no admission written.

### 5.3 Database locking under a held writer — **MATERIAL FINDING**

While a writer held `BEGIN IMMEDIATE`:

```
admitted=0  refused=0  busy/locked=0  5xx=24  slowest client = 22,337.7 ms
```

**24 of 24 scans failed with HTTP 5xx, and the slowest client waited 22.3 seconds.** The failure is
an unhandled `sqlite3.OperationalError` surfacing at `app/convocation_qr.py:271` → HTTP 500.
**Data integrity was never compromised** — post-recovery `admissions=591, used_passes=591,
distinct=591`, and `PRAGMA integrity_check` remained `ok`.

**Root cause is confirmed by §5's source audit, not guessed:**

| Setting | Actual value | Consequence |
|---|---|---|
| `busy_timeout` | **5000 ms** (SQLite default — `get_db()` passes no `timeout=`) | A blocked writer stalls for seconds before failing |
| `journal_mode` | **`delete`** (rollback journal, **not WAL**) | Readers block writers and vice-versa |
| `synchronous` | **FULL** (SQLite default) | Every commit pays an fsync |
| Connection lifecycle | **one connection per operation**, no pooling, no shared cache | Each blocked request holds its own connection |

**Practical impact:** a single slow or interrupted write (e.g. a staff dashboard export or a backup
running concurrently with scanning) can degrade **every** scan at every gate into 5xx for tens of
seconds. At a real event this reads as "the scanners are down."

**Smallest defensible remedy (recommended, NOT implemented):** pass `timeout=` in
`database.get_db()` and set `PRAGMA busy_timeout` per connection; evaluate WAL mode, which
distinguishes reader-blocks-writer from writer-blocks-readers and would let scans proceed during a
dashboard write. **This is deliberately left uncoded** — the phase mandate is testing and preparation
only, and this is a change to the application's core persistence path that needs its own review.
This is a **measured limitation**, not a hypothetical risk.

### 5.4 Backup, restore, restart recovery — PASS

Backup created and restored after the synthetic workload; application restarted against the tested
database. Post-recovery: `admissions=591, used_passes=591, distinct=591` — **no lost, duplicated or
corrupted admission.** Dashboard counts and admission records agree after recovery.
`app/scripts/test_phase20_backup_restore.py` re-confirmed the CLI round trip (exit 0).

### 5.5 Process interruption during disposable-DB operations — PASS

Covered by the §2 rollback check: an injected migration failure leaves `user_version` **not**
advanced and no partial DDL applied.

---

## 6. SQLite operational limits

**Status: PASS (documented). Full script: `app/scripts/test_phase21_sqlite_limits.py`, 10/10, exit 0.**

Confirmed against the application's own connection path, not a hypothetical one:

- **Index support for the hot path is sound.** `convocation_passes.token_hash` is `TEXT UNIQUE NOT
  NULL` — the scan lookup is index-backed via the implicit autoindex. `idx_convocation_admissions_once`
  is a `UNIQUE` index and exists. Both index-for-index as expected.
- **Lock behaviour is safe, just slow.** A second writer blocked by a held lock waited 407 ms
  (with `busy_timeout = 300`) and then raised `OperationalError: database is locked` rather than
  corrupting anything. Blocking is bounded by the timeout; there is no silent failure and no
  corruption path.
- **Scrypt cost is confined to login,** not to scanning — the scan path hashes once with SHA-256.

**Assessment:** the transaction strategy and journal mode are **adequate for the measured synthetic
load on correctness**, but the **default 5 s busy timeout combined with a rollback journal is not
adequate for write-contention availability** (§5.3). No database switch, no distributed
infrastructure and no new dependency is proposed — the remedy is two lines of configuration plus a
WAL evaluation.

---

## 7. Release safety and security

**Status: PASS — 15/15 checks, exit 0.** Script: `app/scripts/test_phase21_security_guardrails.py`

| Requirement | Result |
|---|---|
| Phase 20 demo-secret guard prevents unsafe startup | **PASS** — `run.py` exits 1; names the settings; **never prints secret values**; no DB file created before the guard fires |
| Unsupported schema versions refused | **PASS** — `user_version = 99` → `RuntimeError`, metadata untouched |
| Test opt-ins confined to test harnesses | **PASS** — `_test_tool_guard` is inert under `LGU_TESTING`, answers **404** when `DB_PATH` is production |
| Production config validation does not disclose secrets | **PASS** |
| Scanner authorization / gate assignment cannot be bypassed | **PASS** — unknown token 401; student-style `Bearer` 401; unprovisioned gate refused server-side (240/240 in §4) |
| Staff and student authorization intact | **PASS** |
| No tokens, PINs or passwords in public payloads/logs | **PASS** — valid and failed scans echo neither the token nor any hash; no `sqlite`/`traceback` leakage |
| Backup/restore cannot overwrite production via an accidental test path | **PASS** — `_test_tool_guard` 404 + `config.require_test_db()` |
| Staff cookie hardening intact | **PASS** — `HttpOnly`, `SameSite=Lax`, `Secure` tracking `config.COOKIE_SECURE` |

No security control was weakened to improve benchmark numbers.

**Two defects found and fixed (evidence-backed, both small and both re-tested green):**

1. `app/web/routes.py` — `api_test_scanner_session()` opened a database connection that was **never
   used and never closed**: a leaked connection on every call to a test-only endpoint. Removed;
   `scanner_auth.create_scanner()` already opens its own.
2. `app/convocation_qr.py` — the `verify_scan` docstring asserted *"Admission is recorded in
   convocation_admissions under the caller's scan lock."* **There is no such lock.** The docstring
   now states the real mechanism (UNIQUE index + `IntegrityError`), warns that the index is the only
   thing preventing a double admission, and cites the §5.1 race as evidence. This was a
   correctness-critical documentation defect: it invited a future change to remove the index on the
   belief a lock existed.

---

## 8. Regression battery and exact commands

**Status: PASS — 28/28 Python suites, 33/33 mobile scripts, `tsc` 0, `eslint` 0 errors,
`git diff --check` exit 0.** All runs used a clean environment; `LGU_DB_PATH`, `LGU_TESTING` and
email variables were set per-run to disposable paths, never inherited from the shell.

Command (run from `app/`, using the repo-root venv):

```powershell
cd "c:\Users\Lenovo\Documents\Code_PlayGround\LGU\lgu-smart-convocation\app"
& "...\lgu-smart-convocation\.venv\Scripts\python.exe" scripts\<suite>.py
```

| Suite | Result | Suite | Result |
|---|---|---|---|
| `test_phase21_migration_v6_to_v11` | **91/91, exit 0** | `test_phase12_qr_scanner` | 41/0, exit 0 |
| `test_phase21_load_resilience` | **26/26, exit 0** | `test_phase13_e2e_acceptance` | 53/0, exit 0 |
| `test_phase21_sqlite_limits` | **10/10, exit 0** | `test_phase14_scanner_access` | exit 0 (prod DB before/after identical) |
| `test_phase21_security_guardrails` | **15/15, exit 0** | `test_phase16_lifecycle` | 52/0, exit 0 |
| `test_phase21_prod_db_boundary` | **exit 0** | `test_phase17_cross_role_acceptance` | 156/0, exit 0 |
| `test_phase8_integration` | 57/0, exit 0 | `test_phase18_residual_closure` | exit 0 |
| `test_phase8_acceptance` | 85/0, exit 0 | `test_phase19_scanner_management` | exit 0 |
| `test_exam_registration` | PASS, exit 0 | `test_phase20_authz_matrix` | exit 0 |
| `test_exam_dashboard` | 31/0, exit 0 | `test_phase20_backup_restore` | exit 0 |
| `test_exam_auth` | ALL PASSED, exit 0 | `test_phase20_config_audit` | exit 0 |
| `test_convocation_migration` | PASS, exit 0 | `test_phase20_migration_rehearsal` | exit 0 |
| `test_event_announcements` | 58/0, exit 0 | `test_student_accounts` | 92/0, exit 0 |
| `test_medalist_management` | 55/0, exit 0 | `test_phase9_support` | 58/0, exit 0 |
| `test_phase10_readiness` | 52/0, exit 0 | `test_phase11_pass_history` | 75/0, exit 0 |

Mobile (`mobile/`):

```powershell
npm exec -- tsc --noEmit          # exit 0
npm exec -- eslint .              # 0 errors, 3 pre-existing warnings
node scripts\<each>.mjs           # 33/33 passed
```

The 3 eslint warnings (`no-unused-vars` in `event-announcements-test.mjs`,
`layout-p9-source-test.mjs`, `phase8-freshness-test.mjs`) are **pre-existing and not in code touched
this phase**.

**Python lint (`ruff` 0.16.10): 1,021 pre-existing findings repo-wide, exit 1 — NOT a Phase 21
regression.** This is the codebase's standing style baseline (predominantly `UP031`, `%`-format
preference). To prove no new finding was introduced, both files changed this phase were diffed
against their own baselines:

- `app/convocation_qr.py` — 4 findings, all `UP031` at lines 55, 140, 292, 299. **None fall on the
  rewritten docstring.** Count unchanged.
- `app/web/routes.py` — **zero findings in lines 510–559**, the region of the edit. The edit only
  removed a line.

`git diff --check`: **exit 0**, with 3 pre-existing LF→CRLF warnings on `mobile/app.json`,
`mobile/package-lock.json`, `mobile/package.json` — identical to the Phase 20 baseline.

---

## 9. Production database boundary

**Status: PASS — UNCHANGED.** Script: `app/scripts/test_phase21_prod_db_boundary.py`, exit 0.
Opened **read-only** (`mode=ro` URI) for the digest only; never used as a fixture, migration target,
benchmark database or backup/restore target; never populated from real student data.

| Field | Before (§1 baseline) | After (§8 close) | Match |
|---|---|---|---|
| Size | 278528 | 278528 | **yes** |
| mtime (ns) | 1791660921839278500 | 1791660921839278500 | **yes** |
| mtime (UTC) | `2026-10-10T19:35:21.839278+00:00` | `2026-10-10T19:35:21.839278+00:00` | **yes** |
| SHA-256 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | same | **yes** |
| `PRAGMA user_version` | 6 | 6 | **yes** |
| Tables | 27 | 27 | **yes** |
| `PRAGMA integrity_check` | ok | ok | **yes** |

All 5 stamp fields match the baseline byte-for-byte. **The production database was not migrated,
not backed up, not restored against, not benchmarked, and not written to.** Migrations 7–11 remain
**pending** against production, as they were at the end of Phase 20.

---

## 10. Final Git status and `git diff --check`

| Item | Baseline | Close | Status |
|---|---|---|---|
| Branch | `main` | `main` | **PASS** |
| HEAD | `298c272d53485ba4473c2defe72db70c02733a2c` | same | **PASS** |
| Commits ahead of HEAD | 0 | 0 | **PASS** |
| Stashes | 0 | 0 | **PASS** |
| Working tree entries | 158 | **164** | **PASS** (+6 untracked: 5 scripts + this report) |
| `git diff --check` | exit 0 (3 warnings) | **exit 0 (3 warnings)** | **PASS** |

Nothing was reset, cleaned, stashed, amended, committed, pushed or deployed. All intentionally
uncommitted prior work is preserved.

**Phase 21 deliverables added (untracked):**

```
app/scripts/test_phase21_migration_v6_to_v11.py
app/scripts/test_phase21_load_resilience.py
app/scripts/test_phase21_sqlite_limits.py
app/scripts/test_phase21_security_guardrails.py
app/scripts/test_phase21_prod_db_boundary.py
PHASE21_EVENT_DAY_LOAD_AND_MIGRATION_REPORT.md   (this file)
```

**Modified this phase (2 files, both re-tested green):** `app/web/routes.py`,
`app/convocation_qr.py`.

---

## 11. Remaining release blockers

Statuses: **PASS** / **FAIL** / **BLOCKED** / **NOT TESTED**.

| # | Gate | Status | Notes |
|---|---|---|---|
| 1 | Migration v6→v11 correctness | **PASS** | §2, 91/91 on synthetic data |
| 2 | Fresh-DB init and v10→v11 | **PASS** | §3 |
| 3 | Duplicate-admission safety under concurrency | **PASS** | §5.1, 240 and 480 concurrent duplicates, 0 double-admissions |
| 4 | Failed scans produce no admissions | **PASS** | §5.2 |
| 5 | Backup / restore / restart recovery | **PASS** | §5.4 |
| 6 | Security and release guardrails | **PASS** | §7, 15/15 |
| 7 | Full regression battery | **PASS** | §8, 28 Python + 33 mobile + tsc + eslint |
| 8 | Production DB boundary | **PASS** | §9, byte-identical |
| 9 | **Write-contention availability** | **FAIL** | §5.3 — 24/24 scans 5xx, 22.3 s worst case. Needs the §6 remedy decided. |
| 10 | **Institutional capacity approval** | **BLOCKED** | §4 — synthetic benchmark only; **no demand estimate supplied**; no SLA invented |
| 11 | **Production credentials** | **BLOCKED** | Not configured; out of scope for this phase |
| 12 | **Authorized production migration (7–11)** | **BLOCKED** | Never executed; §9 proves `app/lgu.db` untouched |
| 13 | **External SMTP** | **BLOCKED** | No SMTP available; email delivery unverified end-to-end |
| 14 | **Real Android camera / QR capture** | **NOT TESTED** | No `adb`, no emulator, no Java on this machine |
| 15 | **CPU and memory under load** | **NOT TESTED** | `psutil` not installed; DB size growth reported instead |

**Recommendation for Phase 22:** resolve gate 9 (two-line `busy_timeout` fix plus a WAL evaluation,
with the §5.1 race tests as the regression guard), then obtain gate 10's demand estimate so the
§4 benchmark can be re-run against a real target. Gates 11–14 remain external to the codebase.

**Hard stop — work stops here for review.** Phase 22 was not started, nothing was committed or
pushed, nothing was deployed, no production credential was configured, and `app/lgu.db` was not
migrated.
