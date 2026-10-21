# PHASE 37 — PRODUCTION BLOCKER REMEDIATION (DELIVERY REPORT)

**Role:** Principal Engineer · **Status:** Remediation complete, verification executed, **release stays NO-GO**
**Scope:** BE-001, BE-002, DB-001 (preparation), production security posture, shared analytics design, full regression.

---

## 1. Files changed

### Modified (all pre-existing worktree modifications — nothing staged, nothing committed)
| File | Change |
|---|---|
| `app/web/routes.py` | **BE-001:** broadcast handler now goes through centralized `_require_admin_pin()` (exact pinned denial text preserved) → 429 limiter + failure recording apply; **SEC-002:** `_pin_ok()` (`hmac.compare_digest`, UTF-8 bytes) replaces all raw `==`/`!=` PIN comparisons (gate, web form, verify API); **BE-002:** `create_app()` fails closed on `config.demo_secret_violation()` before anything else |
| `app/config.py` | **BE-002:** new single-source policy `demo_secret_violation(startup=...)` — unconditional refusal against production DB; startup refusal for demo secrets unless `LGU_ALLOW_DEMO_SECRETS=1`; messages name variables only, never values |
| `app/run.py` | Phase-20 inline guard replaced by `demo_secret_violation(startup=True)` → `FATAL` + exit 1 **before** `init_db()/seed()`; production-DB refusal added; message contract byte-compatible |
| `app/README.md` | "Admin PIN architecture" section rewritten: four gated endpoints, shared gate, constant-time compare, per-IP 429, TLS/cookie guidance |

### New
| File | Purpose |
|---|---|
| `app/scripts/test_phase37_broadcast_rate_limit.py` | BE-001 regression — 21 checks (401 wording, wrong-PIN recording, 5-fails→429, correct PIN blocked in lockout, shared bucket with `/api/settings`, authorized broadcast 200 + persisted, validation paths, `_pin_ok` semantics) |
| `app/scripts/test_phase37_startup_secrets.py` | BE-002 startup security — 34 checks across run.py / `create_app()` / production-DB / opt-in / operator-secret matrices |
| `app/scripts/test_phase37_migration_rehearsal.py` | DB-001 rehearsal — 31 checks: prod baseline read-only, backup mirror, disposable copy `migrate()` v6→v13, integrity, 8 new tables, row counts + digests preserved, backfills, idempotency, downgrade refusal, prod re-stamp |
| `app/scripts/test_phase37_security_posture.py` | SEC-002 + posture — 29 checks (source pin: zero raw PIN compares, ≥5 centralized calls; form/verify 401/429/unlock; cookies; CORS echo-only; hardening headers; `/api/scan` 401 with no QR/hash leakage) |
| `docs/PHASE37_SHARED_ANALYTICS_DESIGN.md` | Step 6 deliverable — shared backend analytics design (see §6) |
| `app/backups/convocation-20261021-114144.db` (+ `.manifest.json`) | **Verified pre-migration backup** of production DB (sha256 `767b6983…06ecc`, `backup_db.py verify` exit 0) |

`git status --porcelain` = **229** = baseline **223** + the **6 intentional additions** above (5 files + `app/backups/`). Modified still 64, staged 0, stash 0, HEAD `298c272` — no reset/clean/commit/push at any point.

## 2. Issues resolved

| ID | Sev | Status | Evidence |
|---|---|---|---|
| **BE-001** | HIGH | **RESOLVED** | Broadcast route uses `_require_admin_pin()`; shared limiter 429 proven; pinned denial strings preserved for source tests |
| **BE-002** | HIGH | **RESOLVED** | Fail-closed validation now at **every** entry point (`run.py` **and** `create_app()`); demo secrets rejected against production DB absolutely; dev/test preserved via `LGU_TESTING=1` / `LGU_ALLOW_DEMO_SECRETS=1`; no secret values in source or messages |
| **SEC-002** | MED | **RESOLVED** | `hmac.compare_digest` at all three PIN sites; grep-proven zero raw comparisons; 29-check behavioral suite |
| **DB-001** | HIGH | **PREPARED — real migration NOT executed** | Verified backup + full v6→v13 rehearsal on disposable copy (schema integrity, student/attendance/QR data digests preserved); production DB untouched; **explicit operator approval required before real migration** |
| **DB-006 / BE-009** | LOW | Addressed (capability) | New rehearsal covers the full ladder to v13; legacy `test_phase21_migration_v6_to_v11.py` docstring left as-is (not modified this phase) |

## 3. Test results (Step 7 verification)

| Area | Result | Evidence |
|---|---|---|
| Backend compile | **PASSED** | `compileall` exit 0 (all app files incl. new scripts) |
| Auth / authorization | **PASSED** | phase20 authz 40/0, phase17 cross-role 157/0, phase21 guardrails 15/15, phase20 config 84/0 |
| QR validation | **PASSED** | phase12 41/0, phase13 E2E 53/0 |
| Duplicate attendance prevention | **PASSED** | phase12 + phase13 dedupe checks (within suites above) |
| Scanner authorization | **PASSED** | phase14 50/0 (incl. prod-DB untouched stamp) |
| DB isolation | **PASSED** | phase21 prod boundary **UNCHANGED (5 stamp fields)**; `test:api` “Production DB unchanged by tests”; migration rehearsal 31/0 with prod re-stamp identical |
| BE-001 regression | **PASSED** | p37 broadcast 21/0; phase24f 16/0 |
| Startup secrets (BE-002) | **PASSED** | p37 startup 34/0 |
| Security posture (SEC-002/cookies/CORS/headers) | **PASSED** | p37 security 29/0 |
| TypeScript | **PASSED** | `npm run tsc` exit 0 |
| Lint | **PASSED** | `npm run lint` exit 0 |
| Mobile scanner logic | **PASSED** | `test:scanner` **74/74** |
| API integration | **PASSED** | `test:api` exit 0 — **0 failures**, broadcast 401-without-PIN / 200-with-PIN / persisted-to-log all PASS, prod DB proof printed |
| Source-pin tests (post-BE-001) | **PASSED** | `navigation-broadcast-test` 0 failures, `ui-35j-source-test` 83/83, `display-admin-auth` 16/16 |
| Backend suite battery | **PASSED** | **13/13 suites exit 0** — 571+ named checks, 0 failures (logs `%TEMP%\p37_*.log`) |
| Android device/emulator camera QR | **UNVERIFIED** | SDK/AVD removed in Phase 35 teardown — requires rebuild |
| SMTP delivery | **UNVERIFIED** | no mail sink in environment |

**FAILED: none.**

## 4. Production database preservation evidence

- **Baseline sha256** `820113702b02cb2ea87bd5bc8253ba8733f89696dded209465e94b5ee8cb915f` — **final sha256 identical**; size 278 528 B unchanged; **user_version still 6**; 27 tables; `PRAGMA integrity_check = ok`.
- Production DB opened **only read-only** (`mode=ro` URI) for inspection; every test ran on disposable temp DBs (`LGU_TESTING=1` + temp `LGU_DB_PATH`); `run.py` never executed against it; `backup_db.py restore` refuses prod by design.
- Verified backup `app/backups/convocation-20261021-114144.db` (sha256 `767b6983b8a189e06b57b9aaf53ff99ab969f3610475965b14d0a6d61ae06ecc`) passes `verify`; mirrors prod (27 tables, v6).
- Migration ran **only** on a disposable copy of that backup; production re-stamped identical after every phase.
- Git: no destructive operation; baseline 223 → 229 only via the intentional new files listed in §1.

## 5. Remaining blockers (not fixed this phase)

- **DB-001 execution:** real v6→v13 production migration **awaits explicit operator approval** (backup + rehearsal proven; runbook: approve → re-run `backup_db.py create` → boot → re-baseline boundary canary).
- **MEDIUM:** BE-003 (guest self-registration has no rate bucket/cap) · DB-002 (`PRAGMA foreign_keys` off; guest-per-host check-then-insert race) · DB-003 (no `try/finally` connection close; busy-timeout leak at peak) · SEC-001 (cleartext LAN by design — needs TLS fronting or signed trust-boundary statement) · MOB-001 (scanner bearer + admin PIN in plaintext AsyncStorage) · MOB-002 (offline queue only on manual switch) · OPS-001 (no CI; ruff debt 1 143; no coverage) · BE-008* (`seed()` demo data into first-boot DB — potential).
- **LOW:** BE-004 (dev server, hardcoded host, no WSGI entry) · BE-005 (dashboard GET endpoints unauthenticated by design — documented as deferred risk in analytics design §4/§8) · BE-006 (JSON 500 handler / `MAX_CONTENT_LENGTH`) · BE-007 (config int-parsing inconsistency) · SEC-003 (LGU1 40-bit signature) · SEC-004 (in-process limiter keying; proxy collapse) · DB-004 (`add_students` swallows all exceptions) · DB-005 (ALTER non-idempotent, no self-heal) · OPS-002 (docs staleness — `app/README.md` PIN section refreshed; mobile README still stale) · OPS-003 (stale boundary canary — by design) · MOB-003 (403 flips UI offline) · MOB-004 (confirmed non-issue).
- **Environment:** Android SDK/AVD deleted → Phase 35 QR-through-camera still UNVERIFIED; SMTP UNVERIFIED.
- **Observation (this phase):** `X-Scanner-Token` intentionally **not** added to CORS allow-headers — native clients send no `Origin` (header always allowed cross-origin anyway), browser scanner does not exist, and several source tests pin the exact header string. Not a confirmed blocker.

## 6. Analytics plan (`docs/PHASE37_SHARED_ANALYTICS_DESIGN.md`)

No redesign performed — inspection of student portal, LiveBoard, and admin dashboard showed three views over the same helpers. Design consolidates on **one analytics core** (`dashboard_summary()`, `dashboard()`, readiness + publication snapshots) feeding two dashboard endpoints and the student feeds:

- **Metrics:** catalogued with helper/table/semantics (latest-scan-wins inside/outside, `attendance_set` never substituted, arrival %, occasion splits, throughput window, busiest gate, `generated_at`).
- **API contracts:** `GET /api/dashboard` (full: + `sync[]`, + 20-row `feed[]`) vs `/api/dashboard/summary` (lightweight); student readiness/event/announcements feeds unchanged.
- **Access controls:** dashboard unauthenticated **by design** (BE-005 residual explicitly deferred with remediation sketch), Bearer for students, staff session+CSRF, shared admin PIN gate, scanner token+ACL, echo-only CORS.
- **Refresh:** LiveBoard 5 s / 15 s stale / 30 s offline; web dashboard 5 s; student home focus + ≤30 s — cadence unchanged (no behavior change).
- **Query posture:** indexed helpers, cost notes (index on `scans` flagged as deferred), 5-step change-control rule, non-goals (no redesign; BE-005 read key, cadence change, arrival card all deferred).

## 7. Readiness verdict

**NOT production-ready — NO-GO stands.** Phase 37 closed the three P0 security blockers actionable without operator input (**BE-001, BE-002, SEC-002**) and fully prepared **DB-001** (verified backup + rehearsed, data-preserving v6→v13 migration on a disposable copy). All executed verification is **PASSED** (backend 13/13 suites + compile, mobile tsc/lint/scanner 74/API 0-failure); hardware-dependent camera validation remains **UNVERIFIED**. Remaining MEDIUM/LOW blockers (§5), CI absence, and the operator-gated production migration must close before any readiness claim. **No deployment performed; production data never written; stop point reached before all operator-approval operations.**
