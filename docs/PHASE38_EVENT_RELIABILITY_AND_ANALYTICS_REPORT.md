# Phase 38 — Event Reliability and Analytics — Implementation Report

**Role:** Principal Engineer · **Date:** 2026 · **Status:** Implemented and verified ·
**Release verdict: NO-GO** (unchanged — operator-gated migration and
non-scope blockers remain; see §8/§9)

Scope executed exactly as ordered: safety baseline first, then the six
named findings fixed in small batches, shared analytics built on existing
authoritative records, three dashboards integrated inside their
authorization/privacy boundaries, polling hardened, and every claim below
backed by a test that was actually executed in this phase.

---

## 0. Safety baseline (recorded before any change)

| Item | Value |
|---|---|
| `git status --porcelain` | 230 entries (saved to the Phase 38 baseline capture) |
| Stashes | 0 |
| HEAD | `298c272` |
| Production `app/lgu.db` sha256 | `820113702b02cb2ea87bd5bc8253ba8733f89696dded209465e94b5ee8cb915f` |
| Production size / `user_version` | 278528 bytes / 6 (not migrated) |
| Integrity | `ok` |

Guarantees honored throughout: **no commit, push, reset, clean, stash, or
pull; the production database was never opened for write and never
migrated; all schema work (migration v14) was developed and proven only
on disposable databases; all existing modifications and untracked files
preserved; no deployment performed; no new frameworks introduced.**

---

## 1. Updated architecture documentation (delivery item 1)

- `docs/PHASE37_SHARED_ANALYTICS_DESIGN.md` — new **§9 Phase 38
  addendum**: the student attendance card is no longer deferred (shipped
  as a dedicated counts-only endpoint instead of a
  `dashboard_summary` reuse), the shared metric block + exported
  `poll_interval_ms` cadence are live, and the rejection-logging design
  landed as specified (single choke point, busy excluded, duplicate ⊆
  rejected, day-scoped, honest pre-v14 zeros).
- `app/README.md` — new **“Phase 38 — shared analytics and event
  reliability”** section: payload keys and semantics, occasion filter,
  student privacy boundary, DB-002/DB-003/BE-003/MOB-001..003 changes,
  env knobs, test entry points, and the production-stays-v6 rule.
- This report (`docs/PHASE38_EVENT_RELIABILITY_AND_ANALYTICS_REPORT.md`)
  is the phase's architecture/change record (analytics core, endpoints,
  integration, polling design, blockers, runbook).

## 2. Implemented analytics endpoints (delivery item 2)

All metrics come from existing authoritative records (students, scans,
guest passes, convocation_admissions, settings, scan_rejections log) —
nothing is estimated, interpolated, or double-counted.

| Required metric | Key / endpoint | Source & semantics |
|---|---|---|
| Registered attendee count | `registered` | `COUNT(students)` roster rows |
| Verified attendance count | `verified` / `inside_total` | latest-scan-wins occupancy (V-RACE-01) |
| Remaining attendees | `remaining_attendance` / `remaining` | `max(0, expected − verified)`; **null** when target unset — never a fake 0 |
| Attendance percentage | `arrival_pct` / `percentage` | verified ÷ expected, clamped ≤100, 0 when unset |
| Gate-specific check-ins | `throughput[]` | existing windowed per-gate counts (unchanged) |
| Attendance trends | `trends[]` | hourly `entries / exits / cumulative_entries` for today — counts scan **events**; occupancy dedupes separately, deliberately |
| Recent scan activity | `feed[]` | existing 20-row feed on full dashboard (unchanged) |
| Rejected + duplicate scans | `rejected_count`, `duplicate_count` | today's `scan_rejections`; duplicate ⊆ rejected via one `is_duplicate` flag (`DUPLICATE_TITLES`); busy verdicts never logged |
| Event-specific filtering | `?occasion=ceremony\|rehearsal` → `occasion_filter`, `occasion_admitted` | scoped at the ROUTES layer so light/full payloads cannot diverge; 400 on invalid; untouched without the param |
| Data freshness | `generated_at` + `poll_interval_ms` | stamp + server-suggested cadence clamped 2000–30000 ms |

**Endpoints**

- `GET /api/dashboard` and `GET /api/dashboard/summary` — extended
  additively (no existing key changed) with the block above plus
  `admissions_by_occasion {ceremony, rehearsal}`; shared keys are
  byte-identical between light and full payloads (payload-parity test).
  Auth posture unchanged (BE-005 residual documented, not worsened).
- `GET /api/student/attendance` — **new**, student Bearer session
  required (401 otherwise), returns `{registered, verified, remaining,
  percentage, expected, attendance_set, generated_at}` — counts only.
- Rejection logging: one choke point in `process_scan` after the verdict
  (logged rows = refused verdicts only), request/item-level refusals in
  `api_scan`/`api_sync` logged with `source="queued"`, LGU2-mode verdicts
  share the same choke point; log writes are best-effort (a busy log can
  never delay or fail the verdict it describes) and migration-free reads
  degrade to honest zeros pre-v14.

**Fixes in the same scope (smallest safe changes, disposable DBs only):**

- **DB-002** — `PRAGMA foreign_keys = ON` on every connection in
  `connect()`; migration **v14** adds `UNIQUE INDEX idx_guests_host_once
  ON guests(host_roll_no)` + the `scan_rejections` table (append-only,
  production still at v6); `register_guest` converts the index conflict
  into the existing friendly “one guest per student” refusal, closing the
  concurrent check-then-insert race (4-way concurrent race test: exactly
  one row persists).
- **DB-003** — `database.connection()` contextmanager plus `_db()`
  conversions across models, and (found red during this phase's battery)
  `get_settings()`/`update_settings()` wrapped in `try/finally` so a busy
  read/write can no longer strand a handle.
- **BE-003** — guest self-registration rate limiting: fixed-window
  per-IP bucket shared by the JSON **and** form paths (429 pre-empts
  validation once exhausted), configurable daily cap, `GET /guests`
  unaffected; env `LGU_GUEST_RATE_WINDOW_SECONDS`,
  `LGU_GUEST_RATE_MAX_ATTEMPTS`, `LGU_GUEST_DAILY_CAP`.
- **MOB-001** — `mobile/src/store/secureStorage.ts`: scanner session and
  admin PIN now live in `expo-secure-store` (`WHEN_UNLOCKED`) on native,
  in-memory on web, with silent first-read migration of legacy
  AsyncStorage rows (no logout required); `WRONG_PIN` contract preserved.
- **MOB-002** — network-failed scans auto-queue through one shared
  `queueScan` helper (stamped payload + local timestamp) with an amber
  “SCAN QUEUED” notice and queue-count refresh; the offline branch and
  failure path share it.
- **MOB-003** — only transport failures (`ApiError.status === 0`,
  `networkError()`) set the device offline; busy (503/retryable) stays a
  notice and 4xx/5xx never flip offline — on scanner, sync, and gates
  loads; a failed sync still re-locks a revoked session (Phase 14 kept).

## 3. Dashboard integration summary (delivery item 3)

| Surface | Integration | Authorization/privacy |
|---|---|---|
| Admin dashboard (`dashboard.html`) | Three new tiles — remaining (em dash when target unset), rejected, duplicate — fed by the same `/api/dashboard/summary` block; cadence label shows the server cadence | Unauthenticated by design as before (BE-005 residual); no new data class exposed (counts only) |
| LiveBoard (`LiveBoardScreen.tsx`) | Consumes `poll_interval_ms`, clamped to [2000, 30000]; interval restarts when the cadence changes; staleness/offline bands scale with the cadence (floors 15 s / 30 s preserve Phase 35I/L semantics); one-request-at-a-time guard kept | Same public display surface as before |
| Student portal (`app/(student)/home.tsx` + `studentApi.ts`) | New “Live attendance” card: `verified of registered`, `remaining · %` with progress track, explicit “Not set by the administration” state, honest load-failure hint | `GET /api/student/attendance` is session-gated and counts-only — the payload was tested to exclude feed, sync, throughput, busiest_gate, qr_id, rejected_count, announcement audience, and names |
| Home summary (`HomeScreen.tsx`) | Focus-refetch has an inflight guard (mount + focus never overlap) | unchanged |

Navigation, layouts, and all pre-existing behavior preserved — the full
mobile source battery (39 suites) passes with zero failures.

## 4. Modified file list (delivery item 4)

**New files**

- `app/scripts/test_phase38_db_reliability.py` (23)
- `app/scripts/test_phase38_guest_rate_limit.py` (13)
- `app/scripts/test_phase38_analytics.py` (58)
- `mobile/src/store/secureStorage.ts`
- `mobile/scripts/phase38-reliability-test.mjs` (38)
- `docs/PHASE38_EVENT_RELIABILITY_AND_ANALYTICS_REPORT.md` (this file)

**Backend modified**

- `app/database.py` — FK pragma per connection; `connection()`
  contextmanager; `get_settings`/`update_settings` try/finally
- `app/migrations.py` — append-only migration v14 (unique guest index +
  `scan_rejections` + time index)
- `app/models.py` — `_db()` connection cleanup; rejection logger;
  rejection/duplicate/trend/poll analytics; `student_attendance()`;
  dashboard payloads extended additively
- `app/config.py` — `GUEST_RATE_*` limits; `DASHBOARD_POLL_MS`
- `app/web/routes.py` — BE-003 limiter (JSON + form); rejection logging
  at every scan/sync refusal site; occasion scoping wrappers;
  `api_search` on `connection()`
- `app/web/student_routes.py` — attendance endpoint
- `app/web/templates/dashboard.html` — analytics tiles; one-shot
  server-cadence scheduler
- `app/README.md` — Phase 38 section
- Test fixtures/pins updated for v14 + FK enforcement (behavior-neutral):
  `test_phase27_convocation_lifecycle.py` (account row before claims),
  `test_phase34_scanner_guest_attendance.py` +
  `test_phase37_migration_rehearsal.py` (latest = v14 pins),
  `test_student_accounts.py` (legacy fixture seeds base SCHEMA before
  replaying migrations)

**Mobile/web modified**

- `mobile/src/store/scannerSession.ts`, `mobile/src/store/adminAccess.ts`
  — secureStorage migration
- `mobile/src/api/client.ts` — `DashboardData` additive keys; explicit
  `networkError()`/busy classification
- `mobile/src/api/studentApi.ts` — `StudentAttendance` + `fetchAttendance`
- `mobile/src/screens/ScannerScreen.tsx` — `queueScan` auto-queue +
  network-only offline rule + sync/gates handling
- `mobile/src/screens/LiveBoardScreen.tsx` — server cadence, clamps,
  scaled freshness bands
- `mobile/src/screens/HomeScreen.tsx` — inflight guard + focus refetch
- `mobile/app/(student)/home.tsx` — live attendance card
- `mobile/scripts/ui-35i-source-test.mjs`,
  `mobile/scripts/ui-35j-source-test.mjs` — freshness pins updated to
  the cadence-scaled constants (intent preserved: ≥30 s offline floor at
  the default cadence, values retained)

**Docs modified:** `docs/PHASE37_SHARED_ANALYTICS_DESIGN.md` (§9).

## 5. Regression test evidence — exact executed results (delivery item 5)

**Backend** — `compileall -q` over `app/` → exit 0.
Full battery: **50/50 suites exit 0, 0 failures** (44 suites with
counters: **2 031 checks, 0 failures**; 6 stamp/PASS-style suites green).

| Suite | Result | | Suite | Result |
|---|---|---|---|---|
| convocation_migration | PASS | | phase21_load_resilience | 26/26 |
| event_announcements | 58/0 | | phase21_migration_v6_to_v14 | 91/91 |
| exam_auth | ALL PASSED | | phase21_prod_db_boundary | UNCHANGED |
| exam_dashboard | 31/0 | | phase21_security_guardrails | 15/15 |
| exam_registration | PASS | | phase21_sqlite_limits | 10/10 |
| medalist_management | 55/0 | | phase22_contention | 65/65 |
| phase10_readiness | 52/0 | | phase22_journal_mode | 25/25 |
| phase11_pass_history | 75/0 | | phase23_busy_contract | 27/0 |
| phase12_qr_scanner | 41/0 | | phase24b_states | PROD_DB untouched |
| phase13_e2e_acceptance | 53/0 | | phase24d_replay | 16/0 |
| phase14_scanner_access | prod untouched | | phase24e_guest_dashboard | 25/0 |
| phase16_lifecycle | 52/0 | | phase24f_broadcast_authz | 16/0 |
| phase17_cross_role_acceptance | 157/0 | | phase26a_lifecycle | 22/0 |
| phase18_residual_closure | 43/0 | | phase26b_support_queue | 9/0 |
| phase19_scanner_management | 105/0 | | phase26c_guest_list_security | 24/0 |
| phase20_authz_matrix | 40/0 | | phase27_convocation_lifecycle | 27/0 |
| phase20_backup_restore | 40/0 | | phase27_guest_pass_authorization | 52/0 |
| phase20_config_audit | 84/0 | | phase28_authorization_closure | 34/0 |
| phase20_migration_rehearsal | 54/0 | | phase29_annual_event_and_student | 66/0 |
| phase34_scanner_guest_attendance | 40/0 | | phase37_broadcast_rate_limit | 21/0 |
| phase37_migration_rehearsal | 31/0 (v6→v14) | | phase37_security_posture | 29/0 |
| phase37_startup_secrets | 34/0 | | **test_phase38_analytics** | **58/0** |
| **test_phase38_db_reliability** | **23/0** | | **test_phase38_guest_rate_limit** | **13/0** |
| phase8_acceptance | 85/0 | | phase8_integration | 57/0 |
| phase9_support | 58/0 | | student_accounts | 92/0 |

Phase 38 focused coverage inside those suites: rejection-logging exact
counts, api_scan/api_sync refusal sites, busy/day-scoping exclusion,
payload parity + trends + occasion filter, student privacy boundary
(key-by-key), zero-write GET polling (5 rounds, no table changed),
concurrency (4 writer threads ×5 scans + 4 reader threads ×5 dashboards →
20 scans + 20 dashboards, zero errors, final counts exactly (28, 3)),
poll clamps 2000/30000, pre-v14 honest-zero degradation, concurrent guest
race (one winner), connection-cleanup fault injection, and a production
re-stamp in each of the three Phase 38 suites.

**Mobile** (from `mobile/`): `npm run tsc` → **0 errors**; `npm run lint`
→ **0 problems**; `npm run test:scanner` → **74 passed, 0 failed**;
`npm run test:api` → **0 failures** (isolated temp DB; production stamped
byte-identical before/after); `phase38-reliability-test.mjs` → **38
passed, 0 failed**; full source battery → **0 failing files of 36**, plus
`phase31-student-nav-test.mjs` (10/0) and `phase32-student-profile-test.mjs`
(19/0) verified from `mobile/` (those two resolve paths relative to cwd
and fail from the repo root by design — pre-existing, unrelated).

**Safety re-verification after all changes:** stash 0, HEAD `298c272`,
porcelain 230 baseline entries all intact (nothing removed) + only the
intentional Phase 38 files added (temp runners deleted), production
`app/lgu.db` sha256/size/`user_version=6`/integrity unchanged in every
suite tail that stamps it.

## 6. Remaining production blockers (delivery item 6)

Phase 38 closes **BE-003, DB-002, DB-003, MOB-001, MOB-002, MOB-003**
from the Phase 37 list. Still open:

- **DB-001 (operator-gated):** real production migration now waits at
  **v14** (v6 → v14 rehearsed end-to-end on disposable copies — 31/0
  rehearsal + 91/91 phase21 suite — data digests preserved). Requires
  explicit operator approval: approve → `backup_db.py create` → boot →
  re-baseline boundary canary. **Not executed; production stays v6.**
- **MEDIUM:** SEC-001 (cleartext LAN — needs TLS fronting or a signed
  trust-boundary statement) · OPS-001 (no CI, ruff debt, no coverage) ·
  BE-008* (`seed()` demo data on first boot — potential).
- **LOW:** BE-004 (dev server/hardcoded host/no WSGI entry) · BE-005
  (dashboard GET endpoints unauthenticated by design — documented
  residual) · BE-006 (JSON 500 handler / `MAX_CONTENT_LENGTH`) · BE-007
  (config int-parsing inconsistency) · SEC-003 (LGU1 40-bit signature) ·
  SEC-004 (in-process limiter keying; proxy collapse) · DB-004
  (`add_students` swallows all exceptions) · DB-005 (ALTER
  non-idempotent) · OPS-002 (docs staleness — mobile README) · OPS-003
  (stale boundary canary, by design) · MOB-004 (confirmed non-issue).
- **Environment:** Android SDK/AVD deleted → Phase 35 QR-through-camera
  still UNVERIFIED; SMTP UNVERIFIED.

## 7. Updated deployment checklist (delivery item 7)

1. Operator approves DB-001 → run `backup_db.py create` and verify the
   backup opens.
2. Deploy code; on first boot the app migrates the production DB
   v6 → v14 (unique guest index + `scan_rejections`); confirm
   `PRAGMA user_version = 14` and `integrity_check = ok`; keep the
   boundary canary re-baseline step in the runbook.
3. Optional env review: `LGU_DASHBOARD_POLL_MS` (default 5000; clamped
   2000–30000), `LGU_GUEST_RATE_WINDOW_SECONDS`,
   `LGU_GUEST_RATE_MAX_ATTEMPTS`, `LGU_GUEST_DAILY_CAP` — defaults are
   safe; document any override.
4. Run the verification gates: backend full battery (50 suites),
   `compileall`, mobile `tsc`/`lint`/`test:scanner`/`test:api` +
   `phase38-reliability-test.mjs` + full `mobile/scripts` battery — all
   must stay 0 failures on the deployed commit.
5. Field-check the three surfaces: admin dashboard tiles + cadence
   label, LiveBoard cadence/staleness/offline bands, student attendance
   card (set and unset target states).
6. Confirm scanner keystore storage (session survives restart; legacy
   rows migrate) and offline auto-queue behavior on a device.
7. Resolve or explicitly accept SEC-001 (TLS/trust-boundary statement)
   before any network beyond the trusted LAN.
8. Do **not** deploy automatically — this checklist is manual,
   operator-signed; SMTP/camera validations remain UNVERIFIED until
   hardware is restored.

## 8. GO / NO-GO verdict (delivery item 8)

**NO-GO for production release.** Phase 38 delivers all six assigned
findings, the shared analytics contract, and the three dashboard
integrations with green executed evidence (backend 50/50 suites / 2 031
counted checks; mobile tsc 0, lint 0, scanner 74/74, API 0 failures,
39 source suites 0 failures, new reliability suite 38/38), and it
preserves the safety invariants (no git surgery, production untouched at
v6, no deployment). Release remains blocked by the operator-gated
DB-001 migration (now awaiting v14), SEC-001, OPS-001, the documented
LOW-tier debt, and the UNVERIFIED hardware-dependent validations (§6).
