# Phase 17 — Cross-Role Product Acceptance & Data Integrity

**Status: COMPLETE — 1,064 Python checks + 33 mobile suites green, production DB byte-identical.**
No commit, push, or deploy was performed. All pre-existing uncommitted work (Phases 8–16) is preserved.

---

## 1. Baseline and architecture

- **Repo:** `lgu-smart-convocation`, branch `main`, HEAD `298c272`. Working tree carries the entire Phases 8–16 body of work uncommitted; Phase 17 adds to it without touching history.
- **Stack:** Flask 3.1.3 / Python 3.13.7 (`.venv` at repo root), SQLite via `database.py` + `migrations.py`, fake email provider (`LGU_EMAIL_MODE=fake`, `emailer.OUTBOX`), Expo/React Native mobile app under `mobile/`.
- **Roles and trust boundaries verified this phase:**
  - **Examination staff** — session cookie + CSRF on POSTs (`exam_routes.staff_required`, `_csrf_guard`), per-IP login rate limit (`EXAM_RATE_MAX_FAILS = 5`).
  - **Students** — Bearer token (`student_auth.account_for_token`), uniform `StudentError(status, code, message)` handling, per-bucket rate limits.
  - **Volunteers/scanners** — `X-Scanner-Token` header, server-side gate authorization, server-derived volunteer identity, PIN rate limit (`PIN_RATE_MAX_FAILS = 5` / 60 s).
  - **Admin** — PIN gate for `/admin`, `/broadcast`, `/api/settings` PUT, `/api/admin/verify` (401 `unlock.html`).
- **QR ledgers:** `LGU1:` legacy roster (`ids.py`) and `LGU2:` convocation passes (`convocation_qr.py`) are separate namespaces with separate ledgers (`scans` vs `convocation_admissions`); `process_scan` serializes under `_SCAN_LOCK`.
- **Test isolation:** the suite sets `LGU_TESTING=1`, a temp `LGU_DB_PATH`, fake email, temp photo dirs, pops SMTP/secret env vars, and calls `config.require_test_db()` before any DB access.

## 2. Acceptance scenarios and results

`app/scripts/test_phase17_cross_role_acceptance.py` runs 7 steps over real HTTP routes against a disposable DB:

| Step | Scope | Result |
|---|---|---|
| 1 | Boot, publish real event, import roster, sign-ups, conflict/duplicate/empty/overflow import handling | pass |
| 2 | Staff workflow: support queue, corrections, medalists, dashboard truth | pass |
| 3 | Student lifecycle: profile, published-only truth, email outage, cross-account isolation | pass |
| 4 | Volunteer scanner: provisioning, authorization, timestamps, sync idempotency | pass |
| 5 | Cross-role privacy, security headers, payload purity | pass |
| 6 | Pass integrity, admissions, 12-thread concurrency, migrations, 6,000-row scale | pass |
| 7 | Final consistency: ledgers agree, repo clean, production untouched | pass |

**156 checks, 0 failures.**

## 3. Examination staff results

- Staff sign-in, CSRF enforcement, and per-IP login lockout verified against source and exercised end-to-end.
- Support queue, registration corrections, medalist import and dashboard metrics all operate on authoritative records; dashboard totals mirror the ledger after every mutation including the 6,000-row scale import.
- **Product fix:** `GET /exam/medalists/import` raised `AttributeError` → HTTP 500 because `med.list_batches` does not exist; the function lives in `medalist_import`. Fixed in `app/web/medalist_routes.py` (`med.list_batches(...)` → `medalist_import.list_batches(...)`).
- Admin PIN brute force returns `401 × 5` then `429` (`PIN_RATE_MAX_FAILS + 1` attempts verified).

## 4. Student results

- Signup → verify → login → claim → profile → readiness → pass → history lifecycle all green; published-only truth enforced (unpublished event/announcements never leak).
- Email outage fails closed: with `EMAIL_MODE=disabled`, `/api/student/verify` returns `503 email_unavailable` and writes **no** `verification_challenges` row (verified with a fresh unclaimed registration, not an already-claimed one).
- Cross-account isolation: no pass token or personal record appears in another student's surfaces.
- **Product fix (privacy ordering):** `POST /api/student/readiness/reminders` validated the payload **before** authenticating, so an anonymous or forged caller received `400` instead of `401` — confirming route existence and shape to unauthenticated clients. `app/web/student_routes.py::readiness_reminder` now calls `current_account(db)` before payload validation. Every private student route now answers `401` to anonymous and forged callers.

## 5. Volunteer/scanner results

- Provisioning, scrypt PIN storage, login, session mint/expiry/logout-reuse all verified; volunteer name is server-derived (body spoof ignored).
- Per-gate authorization enforced identically online (`/api/scan` → 403 `GATE NOT AUTHORIZED`) and queued (`/api/sync`).
- **FIX-A (timestamps):** only real timestamps are stored; junk such as `"zzz"` normalizes to `None` (server clock) so no stored `scanned_at` can out-sort every dashboard window and permanently inflate throughput. Verified: zero non-conforming `scanned_at` rows remain.
- Sync idempotency: a replayed batch reports `ALREADY SYNCED` and never double-counts; batches over 500 items and non-list bodies are rejected `400`; rejected batches record nothing.
- **Product fix (truthful queued results):** in `app/web/routes.py::api_sync`, an item with no code at all fell through to the gate check and was reported as `GATE NOT AUTHORIZED` (an authorization verdict the server never made), and a missing gate was conflated with an unauthorized gate. The loop now validates the payload first (`INVALID CODE`), then reports `NO GATE SELECTED` for a missing gate and `GATE NOT AUTHORIZED` only for a real out-of-scope gate — matching `/api/scan` wording so a volunteer sees the same outcome online and queued.

## 6. Import, transaction, migration and scale integrity

- **Conflict-only import mutates nothing:** committing a batch whose rows already exist in the official records inserts 0, updates 0, and leaves the official row byte-identical (id, status, `updated_at`, `import_batch_id` unchanged, exactly one row). Assertion strengthened this phase to compare the record itself, not just counters.
- In-file duplicates stage as `duplicate` (first row `valid`); rows already in official records stage as `conflict`; empty first worksheet rejected; >6,500 data rows refused before staging; forced mid-commit failure rolls back with the batch marked failed.
- **Migrations:** a fresh schema migrates to the latest `user_version`; a copy rolled back one version migrates forward and gains `convocation_passes` + `convocation_admissions`; the production DB is never a migration target.
- **Scale:** a 6,000-row workbook uploads and previews in 1.68 s and commits in one transaction in 0.36 s (`inserted == 6000`), and the ledger really holds 6,000 new rows (prefix `P17-SCALE-%`, chosen to avoid colliding with fixture `P17-B001`).
- **Concurrency:** 12 concurrent scans of one pass produce exactly one admission; every losing scan reports `ALREADY ADMITTED`.
- **Pass integrity:** reissue revokes the previous token; forged/malformed payloads never create an admission; a blocking support request stops admission and resolving it restores eligibility; cancelled holders stop being advertised and their passes stop admitting (FIX-B), reinstatement restores the live-pass count exactly.

## 7. Privacy and security-boundary fixes

1. **`readiness_reminder` auth ordering** (fixed) — anonymous/forged POSTs now `401`, not `400`. Regression covered by the suite's `PRIVACY: every private student route is 401 anonymous and forged` check.
2. **`api_sync` verdict accuracy** (fixed) — the server no longer issues an authorization verdict (`GATE NOT AUTHORIZED`) for items it never evaluated (missing payload / missing gate).
3. **Medalist import 500** (fixed) — removed an unhandled `AttributeError` on a staff route.
4. Verified unchanged and green: no credential material in any student payload; no CORS grant to foreign origins; `nosniff` / `SAMEORIGIN` / `no-referrer` on every response; `/broadcast` and `/admin` PIN-gated (`401 unlock.html`) for anonymous callers; no anonymous request crashes the server; test helpers 404 on the production DB.

## 8. Exact commands and counts

```powershell
# Phase 17 acceptance suite (from app\)
& "c:\...\lgu-smart-convocation\.venv\Scripts\python.exe" scripts\test_phase17_cross_role_acceptance.py
#   → 156 checks, 0 failures (7 steps)

# Full Python regression battery (clean env: no LGU_TESTING / LGU_DB_PATH / LGU_EMAIL_MODE / SMTP / secret vars)
foreach ($t in Get-ChildItem scripts\test_*.py) { & $py scripts\$t.Name }   # 17 suites, all exit=0
#   convocation_migration 17 | event_announcements 58 | exam_auth 30 | exam_dashboard 31 |
#   exam_registration 104 | medalist_management 55 | phase10 52 | phase11 75 | phase12 41 |
#   phase13 53 | phase14 48 | phase16 52 | phase17 156 | phase8_acceptance 85 |
#   phase8_integration 57 | phase9 58 | student_accounts 92
#   TOTAL: 1,064 checks, 0 failures, 17/17 suites exit 0

# Mobile
cd mobile; foreach ($t in Get-ChildItem scripts\*.mjs) { node scripts\$t }   # 33/33 exit 0
npm run tsc     # exit 0
npm run lint    # exit 0 (expo lint)

# Whitespace / lint
git diff --check                       # exit 0 (only LF→CRLF notices on mobile/*.json)
ruff check app                         # 701 errors — pre-existing default-rule baseline, no ruff config in repo
ruff check <the 4 files changed this phase>  # only 2 hits, both in untouched pre-existing lines
```

## 9. tsc / lint / source-test / whitespace results

| Gate | Result |
|---|---|
| `npm run tsc` (mobile) | **0 errors** |
| `npm run lint` (expo lint) | **0 errors** |
| Mobile `.mjs` source tests | **33/33 pass** (incl. `master-audit-regression`, `release-safety-test`, `data-truth-test` 53, `scanner-logic-test` 58, `ui-35j` 83) |
| Python suites | **17/17 pass, 1,064 checks, 0 failures** |
| `git diff --check` | **clean** (exit 0) |
| `ruff check app` | 701 — pre-existing baseline (no repo ruff config); files changed this phase introduce no new violations in edited lines |

## 10. Production DB stamps (before / after)

| | Size | mtime_ns (UTC) | SHA-256 |
|---|---|---|---|
| Before | 278528 | 2026-10-10T19:35:21.8392785Z | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` |
| After | 278528 | 2026-10-10T19:35:21.8392785Z | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` |

Byte-identical (size + mtime + SHA-256), asserted by the suite itself in Step 7 and re-verified independently after the full battery.

## 11. Files changed in Phase 17

| File | Change |
|---|---|
| `app/scripts/test_phase17_cross_role_acceptance.py` | Harness repairs (route sweep, `Sign out` label, `/broadcast` 401, ZipFile buffer, request-context metrics, body-only `scan()`, PIN-limit `MAX+1`, fresh-registration email-outage fixture, conflict-batch record comparison, `P17-SCALE-%` prefix) |
| `app/web/student_routes.py` | **Product fix:** authenticate before payload validation in `readiness_reminder` (401 before 400) |
| `app/web/routes.py` | **Product fix:** `api_sync` validates payload, then distinguishes `NO GATE SELECTED` from `GATE NOT AUTHORIZED` |
| `app/web/medalist_routes.py` | **Product fix:** `med.list_batches` → `medalist_import.list_batches` (500 → 200) |

A throwaway diagnostic (`app/scripts/_p17_probe.py`) was created and deleted; it is not part of the tree. All other modified/untracked files predate Phase 17 and are untouched.

## 12. Unverified / external checks

- **Physical Android device scanning** — camera scan, offline→sync on hardware, Wi-Fi handover, permission dialogs remain UNVERIFIED (the standing gap since Phases 13–15; no adb/emulator/SDK available).
- **Real SMTP delivery** — not performed; no SMTP variables configured on this machine. Outage behavior verified only through the fake/disabled provider paths.
- **Distributed multi-IP PIN brute force** — not globally rate-limited (accepted for LAN deployment, documented in Phase 14).
- **HTTPS** — bearer tokens and scanner tokens require TLS in production; this environment is HTTP loopback only.
- **`ruff check app`** — 701 pre-existing default-rule findings are not gated (no repo ruff config); only the files touched this phase were inspected, and no new violations were introduced in edited lines.

## 13. Prioritized remaining defects

1. **[Low — config hygiene] `PASS_ISSUE_RATE_WINDOW_SECONDS` is shadowed.** `student_routes._limited()` always reads `config.STUDENT_RATE_WINDOW_SECONDS`, so the pass-issue bucket cannot have its own window. Known since Phase 13, documented-not-fixed; not a security gap (the bucket still rate-limits, just with the shared window).
2. **[Low — UX only] `readiness.tsx::act()` swallows mark failures silently.** Truthful (no optimistic mutation — the reminder simply stays), but the student gets no feedback that "mark read" did not persist.
3. **[Low — cosmetic, pre-existing] `layout-p9-source-test.mjs` badge contrast** `.badge.queued` `#9a6a00` vs wanted `#6b4c00` — deferred since Phase 8, awaiting a product decision.
4. **[Operational] Scanner PIN provisioning ownership** and **physical field test T1–T9** remain assigned to operations, not code.

**Release discipline:** no commit, push, or deploy. Stop here for review.
