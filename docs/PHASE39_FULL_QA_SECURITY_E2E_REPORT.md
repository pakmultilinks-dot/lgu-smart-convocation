# Phase 39 ? Complete Repository QA, Bug Fixing, Security and Real E2E Testing

Date: 2026-10 (phase close). Branch: `main` @ `298c272`. Verdict at the end: **GO (conditional)**.

Actors: single engineer (lead QA / security reviewer / full-stack engineer). All testing ran in
disposable local environments (temp databases, ephemeral servers on free ports, synthetic
accounts). The production database was never opened for writing; no deploy, migration, commit,
push, reset, stash or checkout was performed.

---

## 1. Scope and method

Order of work, as required:

1. Baseline verification and safety stamps (this file, section 2).
2. Full source review of `app/` and `mobile/`; every reproducible issue logged with
   file/line, severity, root cause and proposed fix (section 4).
3. Functional test inventory discovered from the code itself: 101 route decorators in
   `app/web/`, 29 Jinja templates, the exam blueprint surface, and the Expo mobile surface
   (section 3).
4. Executable Playwright E2E tests against live local servers, with an honest coverage matrix
   derived from `app.url_map` (section 5).
5. Mobile testing: Android toolchain inspected first-hand; native execution BLOCKED
   (section 6). Source-level mobile batteries are reported separately and are NOT presented
   as device tests.
6. Security testing in a disposable environment with synthetic accounts (section 7).
7. Database testing on disposable databases, including migrations, backup/restore, FK,
   UNIQUE, races, rollback and connection hygiene (section 8).
8. Event-day load/performance testing against a real booted server, with measured numbers
   (section 9).
9. System design review; only clear wins proposed, Flask/Expo stack preserved (section 10).
10. Fixes applied in small, independently verified batches, each with a failing regression
    test before the fix (section 11).
11. Full regression batteries after all fixes (section 12).
12. Remaining accepted risks and the final verdict (section 13).

New test assets created by this phase (intentional additions, committed as untracked files
like the rest of the working tree): `app/scripts/test_phase39_e2e_web.py`,
`app/scripts/test_phase39_security.py`, `app/scripts/test_phase39_db.py`,
`app/scripts/test_phase39_load.py`.

---

## 2. Baseline and safety stamps

| Stamp | Phase start (baseline) | Phase close |
|---|---|---|
| `git status --porcelain` entries | 236 | 241 (236 + 4 new phase-39 scripts + `scanner.html` flipped clean -> modified) |
| Deleted vs baseline | 0 | 0 |
| `git stash list` | 0 | 0 |
| HEAD | `298c272` | `298c272` (unchanged) |
| Prod `app/lgu.db` sha256 | `820113702b02cb2ea87bd5bc8253ba8733f89696dded209465e94b5ee8cb915f` | identical |
| Prod `app/lgu.db` size | 278528 bytes | 278528 bytes |
| Prod `user_version` (read-only) | 6 | 6 |
| Prod `PRAGMA integrity_check` (read-only) | ok | ok |
| Prod row counts (read-only probe) | scans=0, students=40 | scans=0, students=40 |

Product files modified by Phase 39 fixes (only these three):

- `app/web/medalist_routes.py` (Q-1; file was already untracked in the baseline working tree)
- `app/web/routes.py` (Q-3, Q-4; file already carried pre-existing uncommitted changes)
- `app/web/templates/scanner.html` (Q-2; tracked file, clean at baseline -> modified now)

Every other "modified" entry in `git status` was already modified at baseline (uncommitted
work from earlier phases) and was not touched by this phase. The DB-001 operator-gated v6 -> v14
migration was deliberately NOT applied to the production database.

---

## 3. Functional test inventory (discovered programmatically)

- 101 route decorators across `app/web/routes.py`, `medalist_routes.py`, exam blueprints,
  support and event modules; 29 Jinja templates; JSON API surface (`/api/*`) for scanner,
  sync, search, gates, config, health, broadcasts, guest passes, dashboard, analytics.
- Mobile: Expo Router app with Home/Scanner/Search/Guests/Broadcast/More/Admin/Settings/
  LiveBoard/GuestPass screens plus 41 `mobile/scripts/*.mjs` test scripts.
- The web E2E suite derives its coverage matrix from `app.url_map` so every registered rule
  is classified PASS / FAIL / NOT TESTED (section 5). API-side behavior is additionally
  covered by 54 backend suites (section 12).

---

## 4. Source review findings (reproducible)

| ID | Severity | Location | Root cause | Disposition |
|---|---|---|---|---|
| Q-1 | MEDIUM | `app/web/medalist_routes.py` edit / publication / upload_photo | `med.correct/set_publication/store_photo(database.get_db(), ...)` ? helpers commit but never close; `get_db()` has no teardown -> 3 leaked SQLite connections per staff action cycle (empirically confirmed via counting proxy) | FIXED (section 11, batch 1) |
| Q-2 | HIGH | `app/web/templates/scanner.html` | Since Phase 14, `/api/scan` + `/api/sync` require `X-Scanner-Token`; the page had no sign-in UI and sent no token -> every UI scan returned 401 with a blank title; `syncQueue` crashed (`r.results.filter` on a 401 body); `demoFill` produced a misleading state on deployments without demo data | FIXED (section 11, batch 3) |
| Q-3 | MEDIUM | `app/web/routes.py` roster upload | `f.read().decode("utf-8-sig")` unguarded -> binary upload raised `UnicodeDecodeError` -> HTTP 500 with raw exception text (confirmed twice: E2E-16 and security step 15) | FIXED (section 11, batch 2) |
| Q-4 | LOW | `app/web/routes.py` `_require_web_admin` | Wrong PIN rendered `unlock.html` with `error=None` -> the operator got zero feedback (confirmed E2E-07) | FIXED (section 11, batch 2) |

Design observations (documented, intentionally NOT changed this phase):

- O-DB-1: `scans.gate_id` has no `REFERENCES` clause; orphan gate ids are rejected at the API
  layer only. Schema left unchanged (no production migration outside operator gate).
- C-csrf: main-blueprint POSTs carry no CSRF token; backstops are `SameSite=Lax` + HttpOnly
  session cookie. Pinned in the security suite step 7; adding per-form tokens is future work.
- C-exam-lock: CLOSED as non-issue ? `exam_auth._utcnow()` returns an aware timestamp, the
  `locked_until` comparison is aware-vs-aware; production read-only probe found 0 locked rows.
- Public-by-design surfaces (`/dashboard`, `/api/dashboard` kiosk, `/api/gates`, `/api/health`,
  `/api/config`, `GET /api/broadcasts`) ? recommended future token-gating, not changed.

---

## 5. Web E2E testing (Playwright, headless chromium 156)

Suite: `app/scripts/test_phase39_e2e_web.py` ? boots `run.py` on a free port with a disposable
database, provisions synthetic accounts (exam staff, scanner gate account, student, support
fixture), runs 60 browser tests in groups A-H, writes `results.json` + failure screenshots.

Pre-fix baseline (locked, attempt 10): **60 tests: 51 PASS / 9 FAIL** ? the 9 failures were
exactly the designed reproductions: E2E-07 (Q-4), E2E-16 (Q-3), E2E-22/23/24/25/26/27/30 (Q-2).
Matrix then: PASS=46 FAIL=5 NOT TESTED=50.

Post-fix final: **60 tests: 60 PASS / 0 FAIL, exit 0.**
Matrix: **PASS=52 FAIL=0 NOT TESTED=49** (the full per-rule matrix table is appended below).

Honesty note: NOT TESTED=49 are url_map rules that no E2E test drives through a real browser
(mostly JSON endpoints and role pages exercised by backend API suites instead, and pages
requiring fixtures the E2E environment does not provision). They are listed as NOT TESTED, not
as passed. No button is claimed tested unless a test actually interacted with it.

Real bugs the E2E suite caught in its own harness while validating the Q-2 fix (test-side,
documented for transparency): (a) `#r-title:not(:empty)` matched the stale "CODE READY"
message -> replaced with title-change polling; (b) demo-fill advances to a NEW student each
click -> duplicate/exit tests reuse the captured payload; (c) reading the payload field raced
the async demo fetch -> explicit wait until the field is non-empty.

Artifacts: `%TEMP%\p39_e2e_*` (results.json + FAIL screenshots per run; final run
`p39_e2e_safur7hn`).

---

## 6. Mobile testing ? NATIVE DEVICE TESTING BLOCKED

**NATIVE DEVICE TESTING BLOCKED.** Evidence (re-verified this phase):

- `adb` not found on PATH (`False`)
- `emulator` not found on PATH (`False`)
- `ANDROID_HOME` empty, `ANDROID_SDK_ROOT` empty
- No physical device bridge (no `adb devices` possible without the SDK)

Per the phase rules this claim is NOT replaced with source-code regex tests, and no source
check is presented as a device test. `expo run:android` / `expo run:ios` / EAS builds were
NOT run (they require the missing SDK and signing credentials).

Supplementary mobile checks that DID run (source-level, labeled as such):

| Battery | Result |
|---|---|
| `npm run tsc` | exit 0 |
| `npm run lint` | exit 0 |
| `npm run test:scanner` | 74 passed, 0 failed |
| `npm run test:api` | 0 failures, 0 skipped (against a live local backend) |

Pre-deployment operator action: run a real device smoke test (camera QR scan, offline queue,
push to `/api/scan`) on physical hardware once an Android SDK/device is available.

---

## 7. Security testing

Suite: `app/scripts/test_phase39_security.py` ? 16 steps, **139 checks**, disposable DB,
synthetic accounts, fresh Flask clients where session isolation matters.

Pre-fix: 139 checks / 2 failures = both the designed Q-3 reproduction (binary roster upload ->
HTTP 500 + raw `UnicodeDecodeError` text). Post-fix: **139 checks / 0 failures.**

Domains covered (all PASS at close):

1. Anonymous access matrix (32 routes) ? every gated route refuses without credentials.
2. Admin PIN gates: correct-PIN controls and wrong-PIN 401s on JSON and web surfaces.
3. Rate limits: admin PIN 429 shared bucket (JSON+web), scanner login 429, guest-reg limiter.
4. Input bounds: guest caps, settings caps, broadcast 160 chars, roster line cap, sync >500,
   search query <2 chars.
5. SQL injection probes (guests, search, login) ? parameterized everywhere, no injection.
6. XSS: stored and reflected payloads escaped in HTML; JSON content-type enforced.
7. CSRF posture documented (tokenless main-blueprint POSTs accepted by design; SameSite=Lax +
   HttpOnly pinned via a fresh client).
8. QR security: forged/tampered/garbage payloads rejected; print-token expiry enforced.
9. Guest pass authorization: anonymous 401, cross-id 401, expired 401, capability-scoped 200.
10. Scanner lifecycle: account provisioning, session create/revoke, per-account lockout.
11. Secret leakage: full-string scan of public pages for the HMAC secret ? zero leaks; PIN not
    scan-able by substring (default length < 5), documented.
12. Debug endpoints: 404 on production-mode monkeypatch (no test-reset on prod).
13. CORS: foreign origin gets no ACAO header; loopback allowed; no wildcard.
14. Production isolation: read-only stamp (hash/size/user_version) unchanged by all suites.
15. Roster upload robustness (Q-3 regression, section 11).
16. Error hygiene: no raw tracebacks in responses post-fix.

---

## 8. Database testing (disposable DBs)

Suite: `app/scripts/test_phase39_db.py` ? 11 steps, **38 checks**.

Pre-fix: 1 failure = the designed Q-1 reproduction (counting proxy measured 3 leaked
connections per medalist edit/publish/photo). Post-fix: **38 checks / 0 failures.**

Covered: fresh init + migration chain to v14 and re-run no-op; `PRAGMA integrity_check` +
`foreign_key_check`; backup create/verify via the real CLI and restore-refusal gate (a
restore targeting a production path is refused BEFORE any write ? verified in-process with a
sentinel file that is never created; no CLI restore was ever pointed at a production path);
restore-to-new-file row counts and user_version; declared FK enforcement (scanner_gates ->
gates, positive and negative ? with the O-DB-1 note that `scans.gate_id` has no REFERENCES);
UNIQUE constraints (settings PK, `idx_guests_host_once`); rollback-on-exception leaves no
partial row; connection hygiene (20 context managers + exception path + 5 `get_db()` calls ->
0 open connections); same-host guest registration race: 4 threads -> exactly 1 winner, 3
duplicate answers, 1 row; 120 contended writes across 6 threads: all landed, measured 3275 ms
total, 27.3 ms/write average; attendance aggregation latest-wins (delta=2 vs gross=3 ? people
not events); production DB stamp unchanged.

---

## 9. Performance and event-day load (measured, real server)

Suite: `app/scripts/test_phase39_load.py` ? boots `run.py` on a free port, drives it with
urllib + threads. **13 checks, 0 failures.** All numbers below are measured, not estimated.

| Scenario | Result |
|---|---|
| Baseline health | p50 = 5 ms |
| S1 concurrent scanners: 6 sessions x 30 scans = 180 scans | all HTTP 200; avg 157 ms, p50 156 ms, p95 195 ms, max 218 ms; wall 4.8 s = 37 req/s; **rows added = 12 = distinct persons (no double-count under concurrency)** |
| S2 duplicate check-ins x10, same student | first "ENTRY RECORDED", 9x "ALREADY INSIDE"; exactly 1 row added; p50 = 31 ms |
| S3 dashboard viewers: 8 clients polling 6 s | 24 polls, all 200; avg 27 ms, p50 29 ms, p95 40 ms; server advertises and honors `poll_interval_ms = 2000` |
| S4 spike: 120 mixed reads back-to-back | all 200; avg 19 ms, p50 18 ms, p95 39 ms, max 45 ms; wall 0.5 s |
| S5 20 client sockets closed mid-request | server stays healthy; dashboard still serves |

Conclusion: at simulated gate-day load (6 scanners + 8 dashboard viewers + spikes) the Flask +
SQLite stack stays well inside interactive latency budgets; the attendance aggregation is
correct under concurrency (latest-scan-wins, no double counting).

---

## 10. System design review

Stack preserved (Flask + SQLite + Expo). Clear wins identified, none requiring architecture
change:

1. Q-1..Q-4 fixes (applied) ? they remove the only reproducible defects found.
2. Future (documented, not applied): CSRF per-form tokens on main-blueprint POSTs; token-gate
   the public kiosk surfaces if the deployment model changes; O-DB-1 FK hardening during the
   operator-gated migration (DB-001); JSON 500 handler + `MAX_CONTENT_LENGTH` (BE-006);
   structured logging/CI (OPS-001).

Nothing in this phase required a framework or stack change.

---

## 11. Fixes applied (smallest safe change, failing regression test first)

Batch 1 ? Q-1 (`app/web/medalist_routes.py`): wrapped `med.correct`, `med.set_publication`,
`med.store_photo` in `with database.connection() as db:` (helpers commit; the context manager
closes). Regression: DB suite step "connection cleanup" flipped 3 leaked -> 0;
`test_medalist_management.py` 55/0; medalist E2E group stayed PASS.

Batch 2 ? Q-3 (`app/web/routes.py`): roster upload decode wrapped in
`try/except UnicodeDecodeError` -> friendly message "The roster file could not be read. Upload
a UTF-8 text CSV file." on the normal 200 page path. Regression: E2E-16 flipped FAIL -> PASS;
security suite step 15 flipped FAIL -> PASS (139/0).

Batch 2 ? Q-4 (`app/web/routes.py`): wrong PIN now passes
`error="Incorrect administrator PIN. Try again."` to `unlock.html` (renders `.notice.bad`).
Regression: E2E-07 flipped FAIL -> PASS.

Batch 3 ? Q-2 (`app/web/templates/scanner.html`): added a sign-in card
(`#signin-card` with `#s-user`, `#s-pin`, `#signin-msg`, `#signin-btn`); the scan card
(`#scan-card`) and offline card are hidden until sign-in; the scanner token is stored in
`sessionStorage` (`lgu_scanner_token`) with the authorized gate list; `authHeaders()` attaches
`X-Scanner-Token` on scan/sync/logout; after sign-in the gate `<select>` is rebuilt to exactly
the scanner's authorized gates (labels from the public `/api/gates`); a 401 anywhere clears the
session, shows "SIGN-IN REQUIRED" and returns to the sign-in card; non-OK responses without a
title render "SCAN FAILED (<code>)" instead of a blank/`undefined` title; `syncQueue` guards
`r.results || []` and handles 401 (no more TypeError); `demoFill` handles 404 with
"DEMO UNAVAILABLE"; a Sign out button revokes the session server-side. Regression: E2E
22/23/24/25/26/27/30 flipped FAIL -> PASS; final E2E run 60/60.

Pre -> post evidence summary:

| Issue | Pre-fix | Post-fix |
|---|---|---|
| Q-1 leaked connections | DB suite 38 checks / 1 failure (leaked=3) | DB suite 38/0 |
| Q-3 binary roster 500 | Security 139 checks / 2 failures + E2E-16 FAIL | Security 139/0 + E2E-16 PASS |
| Q-4 silent wrong PIN | E2E-07 FAIL | E2E-07 PASS |
| Q-2 scanner page | E2E 51/60 (7 scanner FAILs) | E2E 60/60 |

## 12. Full regression batteries (after all fixes)

Backend: every `app/scripts/test_*.py` sorted, run against disposable DBs ?
**TOTAL=54 suites, FAILED=0** (2,331 checks summed across suites with numeric summaries;
5 suites assert qualitatively without numeric counts; all 54 exited 0). This includes the four
new Phase 39 suites (E2E 60/60, security 139/0, DB 38/0, load 13/0) and the historical
suites (phases 8-38) that guard migrations, authz, busy-contract, contention, backup/restore
and analytics.

Mobile (source-level, re-run after backend fixes): `tsc` 0, `lint` 0, `test:scanner` 74/0,
`test:api` 0 failures.

---

## 13. Remaining risks and verdict

Remaining risks (accepted, documented in earlier phases ? none are new findings of this phase):

- **DB-001 (operator-gated)**: production `app/lgu.db` stays at user_version 6; the v14
  migration must be applied by the operator via the rehearsed path (`test_phase21_migration`
  rehearsal green) before features that need newer schema run against production data.
- **SEC-001 (MEDIUM, accepted)**: cleartext HTTP on the LAN; TLS termination is a deployment
  concern (documented, out of code scope this phase).
- **Environment**: NATIVE DEVICE TESTING BLOCKED (no Android SDK/device) ? a real-device smoke
  test is required before field deployment. SMTP delivery UNVERIFIED (no mail server in test
  env); email configuration doc exists.
- **OPS-001**: no CI/ruff/coverage pipeline yet. **OPS-002/003**: operational runbook gaps.
- **BE-004/005/006/007 (LOW)**: JSON 500 handler, `MAX_CONTENT_LENGTH`, raw int parsing ?
  known, documented, not fixed this phase (no reproducible failure observed).
- **SEC-003/004 (LOW)**: 40-bit demo ID alphabet, in-process limiter keying ? accepted for the
  single-node deployment model.
- **BE-008***: seed demo data must not ship to production (startup guard enforces fail-closed).
- **Design backlog**: CSRF per-form tokens, token-gating kiosk endpoints, O-DB-1 FK (fold into
  DB-001 migration).

**VERDICT: GO (conditional).** All four reproducible defects found by this phase's full-source
review and real E2E/security/DB/load testing are fixed and regression-proofed (54/54 backend
suites, 60/60 browser tests, 139/139 security checks, 38/38 DB checks, 13/13 load checks, all
mobile source-level batteries green). Deployment may proceed ONLY after the operator completes
the pre-deployment gate: (1) apply DB-001 migration to production via the rehearsed backup +
restore-refusal-safe path, (2) enable TLS or accept documented LAN risk, (3) run the physical
device smoke test required by the NATIVE DEVICE TESTING BLOCKED finding, (4) verify SMTP or
accept email as non-critical, (5) confirm demo/seed data is not shipped.

Appendix A ? full coverage matrix (every `app.url_map` rule, final run):

COVERAGE MATRIX (derived from app.url_map; every rule listed)
====================================================================================================
PASS       | /                                                    | GET         | E2E-01
PASS       | /admin                                               | GET,POST    | E2E-16
PASS       | /admin/cards                                         | GET         | E2E-10
PASS       | /admin/vendor.csv                                    | GET         | E2E-11
NOT TESTED | /api/admin/verify                                    | POST        | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
NOT TESTED | /api/broadcast/audience                              | GET         | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
NOT TESTED | /api/broadcasts                                      | GET         | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
NOT TESTED | /api/broadcasts                                      | POST        | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
PASS       | /api/config                                          | GET         | E2E-05
PASS       | /api/dashboard                                       | GET         | E2E-04
NOT TESTED | /api/dashboard/summary                               | GET         | NOT TESTED (UI): mobile KPI summary - covered by test_phase38_analytics.py
PASS       | /api/demo-payload                                    | GET         | E2E-24
PASS       | /api/gates                                           | GET         | E2E-23
NOT TESTED | /api/gates/<int:gid>/rename                          | POST        | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
NOT TESTED | /api/guest-pass/<int:gid>                            | GET         | NOT TESTED - no E2E interaction in this suite
NOT TESTED | /api/guests                                          | GET         | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
NOT TESTED | /api/guests                                          | POST        | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
NOT TESTED | /api/guests/<int:gid>/revoke                         | POST        | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
PASS       | /api/health                                          | GET         | E2E-57
PASS       | /api/scan                                            | POST        | E2E-24
PASS       | /api/scanner/login                                   | POST        | E2E-28
PASS       | /api/scanner/logout                                  | POST        | E2E-29
NOT TESTED | /api/search                                          | GET         | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
NOT TESTED | /api/settings                                        | GET         | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
NOT TESTED | /api/settings                                        | PUT         | NOT TESTED (UI): JSON admin/PII API - covered by test_phase39_security.py
PASS       | /api/student/announcements                           | GET         | E2E-52
PASS       | /api/student/attendance                              | GET         | E2E-54
NOT TESTED | /api/student/complete                                | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
PASS       | /api/student/event                                   | GET         | E2E-51
NOT TESTED | /api/student/history                                 | GET         | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
PASS       | /api/student/login                                   | POST        | E2E-56
NOT TESTED | /api/student/logout                                  | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
PASS       | /api/student/me                                      | GET         | E2E-53
PASS       | /api/student/medalists                               | GET         | E2E-50
NOT TESTED | /api/student/medalists/photo/<int:medalist_id>       | GET         | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/pass                                    | GET         | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/pass/issue                              | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/profile                                 | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/profile/photo                           | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/profile/photo                           | GET         | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
PASS       | /api/student/readiness                               | GET         | E2E-55
NOT TESTED | /api/student/readiness/reminders                     | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/recovery/complete                       | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/recovery/request                        | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/resend                                  | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/support                                 | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/support                                 | GET         | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/support/<int:request_id>                | GET         | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
NOT TESTED | /api/student/verify                                  | POST        | NOT TESTED (native app): student JSON API - Android NATIVE DEVICE TESTING BLOCKED; covered by API suites test_student_accounts/test_phase9_support/test_phase17
PASS       | /api/sync                                            | POST        | E2E-27
NOT TESTED | /api/test-records                                    | GET         | NOT TESTED (UI): test-only helper - covered by suites test_phase8_integration/test_phase12_qr_scanner
NOT TESTED | /api/test-reset                                      | POST        | NOT TESTED (UI): test-only helper - covered by suites test_phase8_integration/test_phase12_qr_scanner
NOT TESTED | /api/test-scanner-session                            | POST        | NOT TESTED (UI): test-only helper - covered by suites test_phase8_integration/test_phase12_qr_scanner
PASS       | /broadcast                                           | GET,POST    | E2E-12
PASS       | /dashboard                                           | GET         | E2E-04
PASS       | /exam/                                               | GET         | E2E-31
PASS       | /exam/announcements                                  | GET         | E2E-45
PASS       | /exam/announcements/<int:ann_id>                     | GET         | E2E-45
NOT TESTED | /exam/announcements/<int:ann_id>/<action>            | POST        | NOT TESTED (UI): announcement edit/publish - covered by test_event_announcements.py
NOT TESTED | /exam/announcements/<int:ann_id>/save                | POST        | NOT TESTED (UI): announcement edit/publish - covered by test_event_announcements.py
PASS       | /exam/announcements/create                           | POST        | E2E-45
PASS       | /exam/dashboard                                      | GET         | E2E-33
PASS       | /exam/event                                          | GET         | E2E-43
NOT TESTED | /exam/event/activate                                 | POST        | NOT TESTED (UI): event lifecycle - covered by test_phase16_lifecycle/test_convocation_migration
NOT TESTED | /exam/event/create                                   | POST        | NOT TESTED (UI): event lifecycle - covered by test_phase16_lifecycle/test_convocation_migration
PASS       | /exam/event/publish                                  | POST        | E2E-44
PASS       | /exam/event/save                                     | POST        | E2E-49
PASS       | /exam/login                                          | GET,POST    | E2E-33
PASS       | /exam/logout                                         | POST        | E2E-34
PASS       | /exam/medalists/                                     | GET         | E2E-38
PASS       | /exam/medalists/<int:medalist_id>                    | GET         | E2E-41
PASS       | /exam/medalists/<int:medalist_id>/<action>           | POST        | E2E-40
PASS       | /exam/medalists/<int:medalist_id>/edit               | POST        | E2E-42
PASS       | /exam/medalists/<int:medalist_id>/photo              | POST        | E2E-41
NOT TESTED | /exam/medalists/import                               | GET         | NOT TESTED (UI): medalist import - covered by test_medalist_management.py
NOT TESTED | /exam/medalists/import                               | POST        | NOT TESTED (UI): medalist import - covered by test_medalist_management.py
NOT TESTED | /exam/medalists/import/<int:batch_id>                | GET         | NOT TESTED (UI): medalist import - covered by test_medalist_management.py
NOT TESTED | /exam/medalists/import/<int:batch_id>/commit         | POST        | NOT TESTED (UI): medalist import - covered by test_medalist_management.py
NOT TESTED | /exam/medalists/import/template                      | GET         | NOT TESTED (UI): medalist import - covered by test_medalist_management.py
PASS       | /exam/medalists/new                                  | GET,POST    | E2E-39
PASS       | /exam/registrations                                  | GET         | E2E-35
NOT TESTED | /exam/registrations/<int:reg_id>                     | GET         | NOT TESTED (no seeded registration row): covered by test_exam_registration.py
NOT TESTED | /exam/registrations/<int:reg_id>/correct             | POST        | NOT TESTED (no seeded registration row): covered by test_exam_registration.py
NOT TESTED | /exam/registrations/<int:reg_id>/status              | GET,POST    | NOT TESTED (no seeded registration row): covered by test_exam_registration.py
NOT TESTED | /exam/registrations/history                          | GET         | NOT TESTED (UI): registration import/history - covered by test_exam_registration.py
PASS       | /exam/registrations/import                           | GET,POST    | E2E-37
NOT TESTED | /exam/registrations/import/<int:batch_id>            | GET         | NOT TESTED (UI): registration import/history - covered by test_exam_registration.py
NOT TESTED | /exam/registrations/import/<int:batch_id>/commit     | POST        | NOT TESTED (UI): registration import/history - covered by test_exam_registration.py
PASS       | /exam/registrations/template                         | GET         | E2E-36
PASS       | /exam/scanners                                       | GET         | E2E-34
PASS       | /exam/scanners/<int:scanner_id>                      | GET,POST    | E2E-47
PASS       | /exam/scanners/new                                   | GET,POST    | E2E-48
PASS       | /exam/support                                        | GET         | E2E-46
PASS       | /exam/support/<int:request_id>                       | GET         | E2E-46
PASS       | /exam/support/<int:request_id>/respond               | POST        | E2E-46
PASS       | /exam/support/<int:request_id>/status                | POST        | E2E-60
NOT TESTED | /exam/support/registration/<int:reg_id>              | GET         | NOT TESTED (UI): registration support view - covered by test_phase9_support.py
PASS       | /guests                                              | GET,POST    | E2E-21
PASS       | /guests/<int:gid>/pass                               | GET         | E2E-19
PASS       | /guests/directory                                    | GET         | E2E-20
PASS       | /scan                                                | GET         | E2E-22
----------------------------------------------------------------------------------------------------

E2E TOTAL=60 PASS=60 FAIL=0 | matrix: PASS=52 FAIL=0 NOT TESTED=49
