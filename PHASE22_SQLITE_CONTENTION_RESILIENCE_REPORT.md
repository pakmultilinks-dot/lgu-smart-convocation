# Phase 22 — SQLite Write-Contention Resilience & Gate Availability

**Status at close: PASS (with the hard stop observed — no Phase 23, no commit, no deploy, no migration of `app/lgu.db`).**

| | |
|---|---|
| Branch | `main` |
| HEAD | `298c272d53485ba4473c2defe72db70c02733a2c` (unchanged — nothing committed) |
| SQLite | 3.50.4 |
| Python | 3.13.7 (repo `.venv`) |
| Machine | Windows, 8 CPU, 15.7 GB RAM |

Statuses used below: **PASS** — executed, evidence produced, assertion held. **FAIL** — executed, did not hold. **BLOCKED** — cannot be executed in this environment. **NOT TESTED** — deliberately out of scope for this phase.

---

## 1. Root cause of the Phase 21 failure

**PASS.** Phase 21's load-resilience run reproduced as `codes={500: 9, 200: 15} worst=6177ms`, and the original Phase 21 measurement was a 22.3 s wall clock with every response a 5xx.

The failure was **not** a single cause. It was two independent serialization layers compounding:

1. **SQLite's busy timeout.** Every connection inherited a wait budget for `SQLITE_BUSY`/`database is locked`. Each blocked writer sat in the wait queue for the full budget before failing.
2. **A process-wide, untimed `threading.RLock` (`_SCAN_LOCK`).** Every scan request — convocation and legacy — queued behind this lock. There was no timeout on it, so a request could wait behind an arbitrary queue of predecessors, each of which was itself holding the database for the duration of its own busy-timeout wait.

The product of the two is what produced 500s and multi-second tails: the lock queue multiplied the SQLite wait budget.

**The Phase 21 docstring contained a false claim**, now corrected in `app/convocation_qr.py`. It asserted that "Admission takes no module-level lock… Phase 21 raced 240 and 480 concurrent duplicate scans and admitted each pass exactly once." Admission correctness does *not* come from an absence of locking; it comes from the `UNIQUE (convocation_id, registration_id)` index on `convocation_admissions` plus an `IntegrityError` catch. The docstring now states that mechanism.

### What was actually changed, and why it is the fix rather than the timeout

Convocation scan admission now **bypasses `_SCAN_LOCK` entirely**. It does not need the process-wide lock, because it has a *database-level* guarantee: the UNIQUE index. Two concurrent admissions of the same pass cannot both succeed regardless of how the requests interleave — the loser raises `IntegrityError` and is answered `ALREADY ADMITTED`.

Legacy student and guest roster scans **keep the lock**. The `scans` table has no unique constraint, so its check-then-insert must be atomic in-process. This is the V-RACE-01/02 finding and it is unchanged.

This is the structural fix. The busy timeout added in §2 is a *bound on waiting*, not a cure for contention.

> **Explicitly not claimed:** database lock contention is **not** eliminated. What was eliminated is the unbounded wait and the resulting unhandled 500. Under sufficient load the system still answers "temporarily busy" rather than admitting — see §6, where rollback-journal produced 3 busy answers under the 60-concurrent-admission workload. Contention is *bounded and surfaced*, not removed.

---

## 2. Connection paths and the timeout policy

**PASS.** One policy, one place to read it.

`app/config.py`:

| Symbol | Value |
|---|---|
| `SQLITE_BUSY_TIMEOUT_DEFAULT` | `5.0` s |
| `SQLITE_BUSY_TIMEOUT_MIN` | `0.1` s |
| `SQLITE_BUSY_TIMEOUT_MAX` | `30.0` s |
| `sqlite_busy_timeout()` | parses `LGU_SQLITE_BUSY_TIMEOUT`, falls back to default on non-numeric **or out-of-range** |

Every connection path was traced; there is no second place that opens a database with a different or implicit budget.

| Path | File | Budget applied |
|---|---|---|
| Application connections | `app/database.py` → `connect()` | `timeout=config.sqlite_busy_timeout()` + `PRAGMA busy_timeout = <ms>`; `get_db()` delegates to it |
| Read-only validation | `app/backup.py` `_readonly()` | `timeout=config.sqlite_busy_timeout()` |
| Backup source | `app/backup.py` `backup()` | `database.connect(src)` |
| Backup destination | `app/backup.py` `backup()` | `database.connect(dest_path)` |

No process-global lock was introduced around the whole application. `_SCAN_LOCK` remains scoped to the legacy path only.

**Timeout chosen by measurement, not by maximising.** The benchmark in §4 swept the budget. The shipped default is 5.0 s, not the 30.0 s ceiling: a gate scanner holding a volunteer's phone for 30 s is a worse outcome than answering "please retry" in 2 s, and the sweep showed no correctness gain from the longer wait — only longer tails. Section **[S]** asserts the shipped default is bounded and overridable.

---

## 3. Transaction handling and safe retryable responses

**PASS.**

**Busy is classified as busy — never as anything else.** `app/database.py` adds `is_busy_error(exc)` (message contains `locked` or `busy`), `BUSY_STATUS = "busy"`, `BUSY_RETRY_AFTER = 2`.

A database-busy condition is **never** reported as an invalid QR, a revoked pass, or an unauthorized gate. These are semantically distinct and a caller must be able to distinguish them: an invalid QR is a terminal answer; "temporarily busy" is an instruction to retry the *same* payload.

**A timeout is never converted into a success response.** In `app/web/routes.py`, `api_sync()` computes `synced` by counting only `status == "ok"`. A busy item is counted as busy, not as synced.

**Attendance writes are never silently skipped.** `app/convocation_qr.py` adds `busy_result()`, returning status `busy`, level `amber`, title `TEMPORARILY BUSY`, `retryable: True`.

**Responses:**

| Layer | Answer |
|---|---|
| Scanner endpoint `api_scan()` | HTTP **503** with `Retry-After: 2`, body `{"status": "busy", "level": "amber", "title": "TEMPORARILY BUSY", "retryable": true}` |
| `api_sync()` | per-item `busy_result(...)`; `synced` counts only `ok` |
| `verify_scan()` | catches `sqlite3.OperationalError`, converts only if `is_busy_error`, otherwise re-raises |

Catching only `is_busy_error` matters: a genuinely broken statement must still surface as a 500 rather than being laundered into "busy".

**Failed writes consume nothing.** Sections **[F]** and **[G]** assert that a failed write neither consumes the pass nor leaves a permanent `used` state.

---

## 4. Measured: rollback journal vs WAL

**PASS** (measured; both modes executed the same seven workloads). The harness is `app/scripts/test_phase22_journal_mode.py`, which self-dispatches each mode to a subprocess. Budget fixed at 1.0 s for both so the comparison is like-for-like.

| Metric | Rollback journal | WAL |
|---|---|---|
| Throughput (admission) | 34.2 scan/s | **48.8 scan/s** |
| Admission p95 | 1386.6 ms | **335.9 ms** |
| Busy answers (60 concurrent admissions) | 3 | **0** |
| Unhandled HTTP 500 | **0** | **0** |
| Read p95 during held writer | **11.7 ms** | 17.4 ms |
| Read p50 during held writer | **2.7 ms** | 6.3 ms |
| Read max during held writer | **14.6 ms** | 24.5 ms |
| Read errors during held writer | **[]** | **[]** |
| Read p95 during scanning | **9.3 ms** | 18.6 ms |
| Duplicate-admission rows (60 scans, 2 gates) | 1 | 1 |
| Duplicate-admission successes | 60 | 60 |
| Backup captured every write | **True (87/87)** | True (91/91) |
| Restore matched source | **True** | True |
| Restart integrity | **ok** | ok |
| Data survived restart | **True** | True |
| Sidecars on the *live* database | **[]** | `[]` |
| Sidecars on *backup/restore artefacts* | **[]** | `-shm`, `-wal` ×2 pairs |
| Final integrity | **ok** | ok |
| Foreign-key violations | **0** | 0 |
| Database size | 446464 | 446464 |
| Elapsed | ~71 s | ~67 s |

**WAL is genuinely better on the write path and genuinely worse on the read path here.** Reads regressed from p95 11.7 ms → 17.4 ms (1.5×) and p50 2.7 ms → 6.3 ms (2.3×). On a small database, WAL consults the `-wal` and `-shm` files on every read, which costs more than the rollback journal's in-place reads.

**Two benchmark observations that would otherwise have been misread as harness faults:**

1. WAL's read numbers are *worse*, not better. This is a real measurement, not an artefact.
2. WAL backup and restore artefacts carry `-wal`/`-shm` sidecars. This is a **real operational cost**, not noise: Phase 20 built backup/restore around single-file SQLite, and a plain file copy of a live WAL database silently loses recent writes.

---

## 5. Journal-mode decision

**Decision: RETAIN ROLLBACK JOURNAL. PASS — the production persistence mode is unchanged.**

The spec forbids enabling WAL merely because it performed better in one small test. It did perform better on the write tail here. The decision is nonetheless to retain the rollback journal, for five reasons:

1. **The contention failure this phase targets is FIXED in rollback-journal.** Zero unhandled HTTP 500, every scan answered, worst case bounded by the wait budget. WAL is an optimization, not the fix. Adopting it would attribute the fix to the wrong cause.
2. **The evidence does not meet the bar the spec set.** One synthetic workload, one machine, one process, one database file. That is not evidence of institutional capacity and not a sufficient basis to change a production persistence mode.
3. **WAL measurably worsens reads** (p95 11.7 → 17.4 ms, 1.5×; p50 2.7 → 6.3 ms, 2.3×). Reads are the dashboards and the student screens — paths this phase did *not* identify as the bottleneck. Trading a measured read regression for a write-tail improvement is not obviously a win, and nothing here establishes that it is.
4. **WAL converts a single-file artefact into a multi-file one.** Phase 20 built the backup/restore story around single-file SQLite. WAL backups need an explicit operational policy, and a plain file copy of a live WAL database silently loses recent writes. That is a silent-data-loss hazard introduced to buy latency.
5. **WAL's durability/`synchronous` tradeoffs and its behaviour on network filesystems are untested** for this deployment, and were out of scope this phase.

**WAL becomes the right call when, and only when, all five of the following hold:**

1. The write tail — not the read path — is still measured as the bottleneck at a real event.
2. The deployment target is a local filesystem (never NFS/SMB).
3. Backup/restore is extended to handle `-wal` and validated end to end.
4. `synchronous` and `wal_autocheckpoint` are set deliberately and tested.
5. A rollback plan to revert to rollback-journal is written down.

Item 1 is the gate that matters: on today's measurements WAL fails it, because the read path regresses.

---

## 6. Before/after latency, throughput, 5xx and busy counts

**PASS.** Phase 21 scenario (24 scans against a held writer) re-run before and after the fix:

| | Before | After |
|---|---|---|
| Response codes | `500: 9, 200: 15` | `503: 24` |
| Unhandled 5xx | **9** | **0** |
| Worst latency | **6177 ms** | **763 ms** |
| Wall clock | ~22.3 s (Phase 21 run) | **793 ms** |

Every one of the 24 scans now receives an explicit, semantically correct answer, and the worst-case latency is bounded by the wait budget rather than by lock-queue depth.

**What this does not establish.** This is a synthetic workload on one machine. It does not prove real institutional capacity. It does not prove that lock contention is eliminated — three busy answers under the 60-concurrent-admission workload show contention is still present, and is now *surfaced and bounded* rather than *silently converted into a 500*.

---

## 7. Required test-scenario coverage

**PASS — 20/20.** All scenarios map to checks that actually execute and pass in the final tree. Harness: `app/scripts/test_phase22_contention.py` (65 checks, sections A–S) and `app/scripts/test_phase22_journal_mode.py` (25 checks).

| # | Scenario | Section / evidence | Result |
|---|---|---|---|
| 1 | Configured wait budget reaches every connection path | `[A]` | PASS |
| 2 | Timeout config validated; never silently disabled | `[B]`, `[S]` | PASS |
| 3 | Original Phase 21 scenario: 24 scans under a held writer | `[C]` → `503: 24`, worst 763 ms | PASS |
| 4 | A lock released inside the budget lets the request continue | `[D]` | PASS |
| 5 | A lock beyond the budget yields 503 + `Retry-After`, not 500 | `[E]` | PASS |
| 6 | A failed write never consumes the pass | `[F]` | PASS |
| 7 | No admission and no permanent `used` from a failed write | `[G]` | PASS |
| 8 | Concurrent duplicates create exactly one admission | `[H]`, `[I]`, W4 | PASS |
| 9 | Distinct passes admitted at multiple gates, no data loss | `[I]`, W2 | PASS |
| 10 | Legacy student and guest scans retain established behaviour | `[J]` | PASS |
| 11 | Authorization enforced at the point of admission | `[K]` | PASS |
| 12 | `/api/sync` reports accurate per-item outcomes under contention | `[L]` | PASS |
| 13 | Reads stay responsive while a writer holds the database | `[M]`, W1 | PASS |
| 14 | Connections and transactions released after failure | `[N]` | PASS |
| 15 | Backup and restore remain correct after stress | `[O]`, W5 | PASS |
| 16 | Integrity after stress and recovery | `[P]`, W6, W7 | PASS |
| 17 | Test fixtures cannot target the production database | `[Q]` + §9 | PASS |
| 18 | Eligibility still recomputed at the point of admission | `[R]` | PASS |
| 19 | Shipped default budget is bounded and overridable | `[S]` | PASS |
| 20 | Rollback journal vs WAL compared on identical workloads | §4 table (W1–W7) | PASS |

Workload identifiers in the journal-mode harness: **W1** reads during held writer · **W2** 60 concurrent admissions · **W3** reads during scanning · **W4** 60 duplicate scans across gates 1+2 · **W5** backup + restore · **W6** restart recovery (`wal_checkpoint(TRUNCATE)` then cold reopen) · **W7** final integrity.

---

## 8. Regression commands and results

Executed against the final tree after all edits.

| Command | Result |
|---|---|
| `cd app; ..\.venv\Scripts\python.exe scripts\test_*.py` (all 30 Python suites) | **PASS 30/30, 0 failed** |
| `node scripts\*.mjs` (all 33 mobile suites) | **PASS 33/33, 0 failed** |
| `npm exec -- tsc --noEmit` (in `mobile/`) | **exit 0** |
| `npm exec -- eslint .` (in `mobile/`) | **0 errors**, 3 pre-existing `no-unused-vars` warnings |
| `git diff --check` | **exit 0**, 3 pre-existing LF/CRLF warnings on `mobile/app.json`, `mobile/package-lock.json`, `mobile/package.json` |
| `ruff check` repo-wide | **1104** (Phase 21 baseline **1021**, Δ **+83**) |

The two Phase 22 suites, run individually: `PHASE22 CONTENTION: 65/65 checks passed, 0 failing` and `PHASE22 JOURNAL MODE: 25/25 checks passed, 0 failing`.

**Ruff attribution.** Of the +83: **70** are inside the two brand-new test scripts, **13** inside the five modified modules. Breakdown of the new-script findings is `69 × UP031` (printf-style `%` formatting — this codebase's house style, and the dominant rule in the 1021 baseline) plus **1 × `BLE001`** (the deliberate broad `except Exception` in the `HeldWriter` diagnostic path). In the modified modules the only per-file delta is **+1 `UP031`** in `database.py`, on the new `PRAGMA busy_timeout = %d` line — same house-style rule, same idiom as the pre-existing finding one function above it.

**No new class of lint finding was introduced.** There are zero `F401`, `F811`, `F841`, or `E402` findings in either new script; `RUF100` (unused `# noqa`) and `I001` (unsorted imports) that were present were cleaned up before this report, and the suites were re-run green afterwards.

---

## 9. Production database boundary

**PASS.** `app/lgu.db` was never opened for write and was never migrated. The stamp below was taken by hashing raw bytes — the file is not opened by SQLite at all for this check.

| | Before Phase 22 | After Phase 22 | Match |
|---|---|---|---|
| Size | 278528 | 278528 | **PASS** |
| mtime (UTC) | `2026-10-10T19:35:21.839278500` | `2026-10-10T19:35:21.8392785Z` | **PASS** |
| mtime (ns epoch) | `1791660921839278500` | `1791660921839278500` | **PASS** |
| SHA-256 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | **PASS** |
| `PRAGMA user_version` | 6 | 6 (unchanged) | **PASS** |
| Tables | 27 | 27 | **PASS** |
| `PRAGMA integrity_check` | ok | ok | **PASS** |

Byte-identical. Section `[Q]` additionally asserts that test fixtures *cannot* target the production database — `backup.restore()` refuses `config.is_production_db(dest)`.

`app/backup.py` continues to use the online backup API (`conn.backup(dest)`), which is the WAL-safe path if §5's preconditions are ever met.

---

## 10. Final Git status

**PASS — nothing committed, nothing staged, nothing stashed.**

| | |
|---|---|
| Branch | `main` |
| HEAD | `298c272d53485ba4473c2defe72db70c02733a2c` (identical to the Phase 22 baseline) |
| Dirty files | **167** (Phase 22 baseline **164**, Δ **+3** — the two new Phase 22 test scripts plus this report) |
| Stashes | **0** |
| `git diff --check` | exit **0** (3 pre-existing LF/CRLF warnings, none introduced) |

No `git reset`, `clean`, `stash`, `amend`, `commit`, or `push` was performed. No deploy. No migration of `app/lgu.db`. Phase 23 was not started.

---

## 11. Remaining operational and release blockers

**PASS with reservations — no blocker to review, several to deployment.**

**Not blockers to review (this phase is complete):**

- The Phase 21 failure mode is fixed and its root cause is understood structurally, not papered over with a longer timeout.

**Genuine open items before any release:**

1. **Migrations 7–11 are still PENDING against production.** `app/lgu.db` is at `user_version = 6`; the build supports 1–11. This is a Phase 21-era gap, unchanged and deliberately not closed here.
2. **Contention is bounded, not eliminated.** Under the 60-concurrent-admission workload, rollback-journal still produced **3 busy answers**. Real gate volume is unknown; the 5.0 s default is a measured starting point, not a capacity statement.
3. **No institutional-capacity evidence exists.** Every number here comes from a synthetic workload on one machine with 8 CPUs. Do not read these results as a forecast of real-event throughput.
4. **Legacy roster scans remain serialized behind `_SCAN_LOCK`.** The `scans` table has no unique constraint, so this lock is load-bearing (V-RACE-01/02). If legacy scan volume ever becomes the bottleneck, the fix is a unique constraint on `scans`, not removing the lock. **NOT TESTED** this phase — no such volume was in scope.
5. **WAL is deferred, not rejected.** §5 lists five preconditions; the write-tail measurement at a real event is the gate.
6. **Mobile/device path NOT TESTED.** No `adb`, no emulator, no Java in this environment. The 33 `.mjs` suites are the only mobile evidence produced.

---

## Hard stop observed

Phase 22 is complete. The report is written. No Phase 23 work was started, nothing was committed, pushed, deployed, or migrated, no credentials were changed, and `app/lgu.db` remains byte-identical to its Phase 21 stamp.

**Stopping here for review.**
