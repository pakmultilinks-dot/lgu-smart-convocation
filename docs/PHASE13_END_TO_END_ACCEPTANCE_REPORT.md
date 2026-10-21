# Phase 13 — Full End-to-End Product Acceptance & Mobile Verification

Status: **COMPLETE** (verification + one real defect found & fixed, uncommitted).
This phase verifies the product as an **integrated system** — student account →
registration claim → live convocation pass → gate scan → admission → exam
admin dashboard — and audits the QR security. It follows the execution rule:
inspect first, reproduce the defect, fix it, and retest. It does **not** begin
Phase 14, commit, push, or deploy.

---

## 1. Baseline & architecture

Baseline captured before any change:

- **Git**: extensive uncommitted work from Phases 5–12 present (all preserved).
  No commit/push/reset/clean/stash/amend performed.
- **Production DB** (`app/lgu.db`): SIZE = **278528**, SHA-256 =
  **820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F**.
- **Phase 12 artifacts present**: `LGU2:` payload dispatch at the top of
  `_process_scan` (`app/web/routes.py`); `POST /api/student/pass/issue`
  (`app/web/student_routes.py`); migration 9 (`convocation_passes` +
  `convocation_admissions`); student QR render (`mobile/app/(student)/pass.tsx`).

Architecture verified end-to-end this phase (unchanged from Phase 12): a pass
is its own record bound to claimed registration + account + convocation, keyed
by a `LGU2:` version prefix. Gate verification runs **server-side** against the
registration ledger (never the legacy `students` roster) and writes exactly one
`convocation_admissions` row per entry. Legacy operational QR (`LGU1:`) is
dispatched below the prefix check and is byte-for-byte untouched.

## 2. Defects found & fixed

**D1 — Pass expiry was stored but never enforced at scan time (FIXED).**
`convocation_qr.issue_pass` recorded `expires_at`, and the student UI reported
expiry, but `verify_scan` never compared `expires_at` to now. An active pass
past its TTL would therefore still admit a student — a real security gap
("live pass TTL" was a claimed control that wasn't enforced on the gate path).

Fix (in `app/convocation_qr.py`, inside `verify_scan`, after the `used` check
and before the account lookup): parse `expires_at`, normalize naive stamps to
UTC, and reject with `PASS EXPIRED` when `now >= expires_at`.

Second-order bug fixed while hardening D1: the first version compared the aware
`utc_now()` against a naive `expires_at` → `TypeError` → the `except` treated
the pass as not-expired. The fix now replaces naive `exp` with
`exp.replace(tzinfo=timezone.utc)` before comparing. Validated by the E2E check
"an expired pass is rejected at scan (PASS EXPIRED)".

**No other functional defects** were found in the integrated workflow. One
cosmetic/hygiene item was addressed: the E2E test printed unicode step labels
(`→`, `§`), which tripped a `UnicodeEncodeError` only when the script's output
was piped through a cp1252 console. `sys.stdout.reconfigure(encoding="utf-8")`
was added so the deliverable test is encoding-robust; no assertion was weakened.

## 3. Student-to-gate sequence (10-step backend workflow)

All 10 required steps pass against real routes on a **temp DB** (production DB
never opened for writes; stat-stamped before/after). Source:
`app/scripts/test_phase13_e2e_acceptance.py` (53 checks, 0 failures, EXIT=0).

| # | Step | Result |
|---|------|--------|
| 1 | Import registrations via real `/exam/registrations/import` (xlsx) | 3 rows committed |
| 2 | Students sign up (verify → code → complete) & claim registrations | 3 claims |
| 3 | Publish the convocation event | published |
| 4 | Student GET `/pass` → eligible, `qr_available=False` (none yet) | ✓ |
| 5 | Issue pass → `LGU2:` payload; hash-only storage; bound to account/conv/reg; no `students` row | ✓ |
| 6 | Gate `POST /api/scan` with the payload → `CONVOCATION ENTRY RECORDED` | ✓ |
| 7 | Exactly 1 `convocation_admissions` row; pass → `used`; legacy `scans` unchanged | ✓ |
| 8 | Repeat scan → `ALREADY ADMITTED`, still 1 row (idempotent) | ✓ |
| 9 | Dashboard shows live pass/admitted counts + badge (see §8) | ✓ |
| 10 | Cancel registration → scan `REGISTRATION NOT ELIGIBLE`; reissue 403; reinstate | ✓ |

## 4. Security & duplicate-admission audit

20 security/integrity checks, all passing:

- **Token**: ≥32 bytes (`secrets.token_urlsafe(32)`), high entropy.
- **No plaintext at rest**: DB stores only the sha256 hash; the plaintext token
  appears in zero rows; the computed hash appears in the pass row.
- **No leakage**: invalid-token responses, audit rows, and scan logs never
  contain the token.
- **Binding**: Bob's pass admits only Bob's registration; a pass is bound to its
  account + convocation + registration.
- **Eligibility recomputed at scan**: cancelling a registration after issuance
  stops admission (`REGISTRATION NOT ELIGIBLE`) with no admission row.
- **Blocking review**: an open blocking support request stops admission.
- **Reissue revokes prior**: the old (revoked) token → `PASS INVALID`.
- **Expiry enforced** (D1): forced-expired pass → `PASS EXPIRED`, no admission.
- **Revoke is permanent**: reinstating a *revoked* registration is a no-op
  (`ACTIONS` only allows reinstate from `cancelled`); the pass still 403s.
- **Failed scans** record no admissions; unknown/non-numeric gate rejected.
- **Rate limiting**: unauthenticated issue → 401; after `PASS_ISSUE_RATE_MAX`
  issues in the window → 429.
- **No cross-path coupling**: issuing/scanning a convocation pass never writes
  `students` or `scans`.

## 5. Mobile student & volunteer verification

Automated (source-level) verification only — see §6 for the device caveat.

- **32/32** `mobile/scripts/*.mjs` suites pass (incl. `qr-pass-source-test`,
  `pass-history-source-test`, `student-screens-test`, `scanner-logic-test`,
  `master-audit-regression`, `release-safety-test`).
- `npx tsc --noEmit` → **exit 0**; `npx eslint` on the changed files
  (`app/(student)/pass.tsx`, `src/scanner/scanResultLogic.ts`,
  `src/scanner/scanCooldown.ts`) → **exit 0**.
- Student flow (`pass.tsx`) inspected: auto-issues only when state is
  `eligible`, clears the QR whenever the server stops reporting `eligible`,
  recovers on 401, refreshes invitation data — no QR is shown when the server
  denies. No hardcoded success.
- Volunteer flow (`scanResultLogic.ts`) inspected: maps server results to
  outcomes — admission, `ALREADY ADMITTED` → `already-used`, other errors →
  `invalid`, exit → amber. Driven entirely by server responses; no local
  success fabrication. No scanner change was required.

## 6. Was real camera scanning tested on a device/emulator?

**No — not verified in this environment, and not claimed.** `adb` is not on
PATH and absent from the standard Android SDK locations; `ANDROID_HOME` /
`ANDROID_SDK_ROOT` are unset; no emulator tool is available. No physical device
or emulator is attached, so a real camera scan of a live `LGU2` QR could not be
exercised. Everything above is backend + source-level verification. The single
device-level step that remains unverified is: **pointing the volunteer camera at
a real `LGU2` QR and observing the admission result on hardware** (see §11).

## 7. Full regression battery

**Python** (from `app/`, run directly with `../.venv/Scripts/python.exe`):

| Suite | Result |
|-------|--------|
| test_convocation_migration | ok (re-migrate is a no-op) |
| test_event_announcements | 58 checks, 0 failures |
| test_exam_auth | ALL PASSED |
| test_exam_dashboard | 31 checks, 0 failures |
| test_exam_registration | ok |
| test_medalist_management | 55 checks, 0 failures |
| test_phase10_readiness | 52 checks, 0 failures |
| test_phase11_pass_history | 75 checks, 0 failures |
| test_phase12_qr_scanner | 40 checks, 0 failures |
| **test_phase13_e2e_acceptance** | **53 checks, 0 failures** |
| test_phase8_acceptance | 85 checks, 0 failures |
| test_phase8_integration | 57 checks, 0 failures |
| test_phase9_support | 58 checks, 0 failures |
| test_student_accounts | 92 checks, 0 failures |

**14/14 Python suites pass** (≈656 numeric checks across 11 suites + 3
non-numeric pass suites), **0 failures, 0 pre-existing failures**. No assertion
was weakened; no suite was skipped.

**Mobile**: 32/32 `.mjs` pass. **tsc** exit 0. **eslint** exit 0.
**`git diff --check`** exit 0 (only benign LF→CRLF notices on
`mobile/app.json`, `mobile/package.json`, `mobile/package-lock.json`).

## 8. Dashboard & legacy scanner

Dashboard is server-rendered HTML (no separate metrics API). Verified (step 9):
the invitation card renders the **live** counts —
`"%d live entry pass(es) issued"` and `"%d attendee(s) admitted so far"` —
computed from `convocation_passes` / `convocation_admissions`, not hardcoded.
The `"Convocation QR entry active"` badge appears **iff** `passes_issued_active
> 0`, and the honest `"Legacy operational-QR prerequisite not satisfied"`
paragraph is retained. Exactly 22 KPI tiles render. Re-rendering the dashboard
after a later admission shows the updated count (re-verified, not a stale
snapshot).

Legacy scanner path verified untouched and functional: legacy **guest entry**,
legacy **student entry**, `ALREADY INSIDE`, and **exit** all behave exactly as
before (covered in the integrity section of the E2E test), confirming the `LGU2`
dispatch did not perturb `LGU1`.

## 9. Production DB protection (before / after)

| | Size | SHA-256 |
|---|------|---------|
| **Before** | 278528 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` |
| **After** | 278528 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` |

**Byte-identical.** All tests ran on temp DBs via `LGU_DB_PATH` +
`config.require_test_db()`; each suite stat-stamped the production DB
before/after. `app/lgu.db` was never opened for writes.

## 10. Final git status & changed files

`git diff --check` → **exit 0** (no whitespace/conflict markers). All Phase 5–12
work remains uncommitted and preserved; nothing was committed, pushed, reset,
stashed, or amended.

Files touched **this phase** (isolated from the pre-existing uncommitted work):

- `app/convocation_qr.py` — **modified** (D1 expiry enforcement). This file was
  already untracked from Phase 12; the fix lives inside it.
- `app/scripts/test_phase13_e2e_acceptance.py` — **new** (untracked).
- `docs/PHASE13_END_TO_END_ACCEPTANCE_REPORT.md` — **new** (this file).

The broader working tree (`git status --short`) still lists the many modified /
untracked files from Phases 5–12 (routes, student routes, convocation modules,
mobile screens, earlier tests, earlier reports) — all untouched by this phase
except the two files above.

## 11. Remaining blockers & evidence needed

1. **Device-level camera scan (only open item).** Real hardware/emulator camera
   scanning of a live `LGU2` QR is **unverified** — no `adb`, no emulator, no
   Android SDK on this machine (§6). *Evidence needed:* run Expo from this LGU
   project on a connected device/emulator (respecting the existing port
   arrangement; do **not** kill the unrelated `next dev` on :3010) and capture a
   volunteer scan of a real `LGU2` QR resolving to `CONVOCATION ENTRY RECORDED`
   on the device, plus an `ALREADY ADMITTED` repeat.
2. **Minor (documented, not fixed):** `PASS_ISSUE_RATE_WINDOW_SECONDS` is
   shadowed by the shared `STUDENT_RATE_WINDOW_SECONDS` inside `_limited()`.
   Rate limiting is still enforced by the per-bucket max count, so this is a
   config-hygiene nuance, not a security gap; noted for a future cleanup.

Everything else in the §2 workflow, §3 security audit, §5 data integrity, §6
regression battery, §7 production-DB protection, and the dashboard/legacy paths
is verified and passing. **Phase 13 stops here.**
