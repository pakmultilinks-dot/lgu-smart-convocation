# Phase 32 — Student Registration, Profile, Help & Readiness

**Repository:** `C:\Users\Lenovo\Documents\Code_PlayGround\LGU\lgu-smart-convocation`
**Date:** 2026-10-19
**Scope:** Mobile student app only (Expo/React Native + TypeScript). No backend code, no database schema, no production data changes.

## 1. Initial repository / working-tree state

- Branch `main` at `298c272` (`fix(scanner): UI revert - restore previous compact Entry/Exit presentation`), with the accumulated uncommitted working tree from Phases 8–31 (never committed, per standing constraint).
- Production database `app/lgu.db` SHA-256 before this phase: `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F`.
- Baseline at phase start: `npx tsc --noEmit` = 0 errors, `npx expo lint` = 0 errors, 37 mobile source-pin scripts passing, 42 backend tests passing.
- The Phase 32 spec attachment ("Pasted text #1") was not recoverable from the session transcript; work proceeded from the detailed continuation plan preserved in the prior session summary. Section numbering follows the required 11-section report structure.

## 2. Backend contract findings confirmed through code inspection

All four areas are read/compose surfaces over existing endpoints — **no backend file was modified**.

| Area | Contract found | Consequence for the UI |
|---|---|---|
| Registration | `GET /api/student/me` returns `registration` (nullable) + `completion`; corrections go through `POST /api/student/support` category `correction` | The correction button must always be available; a request never mutates the record |
| Profile | `POST /api/student/profile` requires `phone`, trims, enforces `PHONE_LIMIT = 32` → 400 "The phone number must be 32 characters or fewer."; `POST /api/student/photo` validates base64/JPEG-PNG-WebP and **stores** the file — there is **no verification concept anywhere in the backend** | Success copy is "Photo uploaded." — never "verified". Phone success only from the server response |
| Support | `validate_form` accepts only `category/subject/message`; rate limit 429 `rate_limited`; open-count limit 429 `too_many_open`; no idempotency key | Per-category guidance is client-side text; duplicate-submit prevention is the `sending` guard; the real `reference` (`SUP-XXXXXX`) is shown only after the server confirms |
| Readiness | `readiness_for` returns a **flat** item list; `source` field exists but is **never populated** by the backend; `rehearsal` is `kind="info"` (not mandatory); `entry_pass` carries the real blocker in `detail` | Grouping is by `item.key`; rehearsal stays informational; the entry-pass callout shows the server's actual reason — no invented policy, no false zeros |

## 3. Files changed and purpose

| File | Change |
|---|---|
| `mobile/app/(student)/registration.tsx` | Part A — honest missing fields (`official()` fallback), read-only correction explanation, correction button always shown |
| `mobile/app/(student)/profile.tsx` | Part B — state-reflective heading, photo load-failure state, phone dirty/saving/saved/failed states, duplicate-submit guards, no auto-navigate after save, explicit "Go to home" when complete; lint fixes (setState-in-effect, ref-in-render) |
| `mobile/app/(student)/support.tsx` | Part C — stacked full-width category selector (a11y radio), per-category `GUIDE`, server-confirmed reference confirmation card, confirmation cleared on new typing |
| `mobile/app/(student)/support-detail.tsx` | Part C — acknowledged vs decided distinction using `resolved_at` |
| `mobile/app/(student)/readiness.tsx` | Part D — Profile setup / Event readiness checklists, single entry-pass callout with real reason + "Get Entry Pass" action, `ITEM_LABEL` map, removed redundant Completed section |
| `mobile/scripts/phase32-student-profile-test.mjs` | Part F — new 19-check source-pin script |

## 4. Area A — My Registration implemented

- Official detail rows (registration number, name, roll number, department) render `Not provided on the official list` when the official record has no value — never a blank row.
- "Request a correction" is **always** shown (previously gated on `status !== "active"`), with the explanation: corrections are applied to the official record by the Examination Department — a request never changes the registration on its own.
- `REG_STATUS` vocabulary (active/cancelled/revoked) preserved; shared stale banner, 401 → welcome, `useFreshServerData` untouched.

## 5. Area B — Manage Profile implemented

- Heading: `Profile complete` when `completion.complete`, else `Complete your profile`.
- Sections: **Official record** (read-only + correction caveat + registration status row), **Photo**, **Contact**.
- Photo states: uploading / on file with date / display-failure message / none on file. Success note is **"Photo uploaded."** — the server stores the file and performs no verification; the UI never claims otherwise.
- Phone: client-side ≤32-char rule mirroring the server message, dirty tracking (render-safe state, not a ref read during render), Save disabled until dirty, success note only from the server response, typed value preserved on failure, **no navigation after save**.
- Duplicate-submit guards on both save and upload (`if (saving) return;`).
- A completed profile stays on screen (auto-redirect removed) with an explicit "Go to home" button.

## 6. Area C — Help & correction requests implemented

- Five categories as full-width stacked selectable rows (`accessibilityRole="radio"`, `accessibilityState.selected`) — five options cannot be legible in one horizontal segmented row.
- Per-category guidance: what to include, what evidence helps, and the standing caveat that staff review is institutional — no request changes a record immediately.
- On success the server-confirmed request is shown with its real reference (`Request sent · SUP-XXXXXX`) and a "View this request" action; the confirmation clears when the student starts composing again.
- `support-detail` distinguishes **Acknowledged** (opened) from **Decided** (`resolved_at`) with an explicit state note.
- Documented backend limitation: the server accepts only `category/subject/message` — category-specific fields exist as guidance text, not separate inputs; dedup is rate-limit + open-count only (no idempotency key).

## 7. Area D — Convocation readiness implemented

- Flat server list grouped into **Profile setup** (`registration`, `profile_photo`) and **Event readiness** (everything else required); Information section keeps `kind="info"` items — **rehearsal is info-kind and is not presented as mandatory**.
- Entry pass gets a single callout while not done: the server's actual blocker reason (`item.detail`) plus one action — "Get Entry Pass" when todo/eligible, "Open invitation" otherwise. The reason appears exactly once (pinned by D2).
- Summary numbers come verbatim from `data.summary` — no client-computed zeros.
- All 29 `readiness-source-test.mjs` pins preserved (single-flight `act`, reminder actions, empty states, 401 handling, no local status state).

## 8. Area E — shared interaction consistency

- All four screens share the same patterns: stale banner text, `e.status === 401` → `/(student)/welcome`, `useFreshServerData(() => load(true))`, Loading/Error/Empty states from the shared UI kit, ghost "Refresh" button, and a duplicate-submit guard on every mutating action.
- No screen navigates away after a successful save (pinned by E2).

## 9. Tests run — exact commands and actual counts

| Command (from `mobile/` unless noted) | Result |
|---|---|
| `npx tsc --noEmit` | **0 errors** |
| `npx expo lint` | **0 errors, 0 warnings** |
| `node scripts/phase32-student-profile-test.mjs` (new) | **19 checks, 0 failures** |
| Full mobile regression: all `scripts/*.mjs` | **38 scripts, 0 failures** (37 existing + 1 new) |
| Backend (from `app/`): `..\.venv\Scripts\python.exe scripts\test_*.py` × 42 | **42 passed, 0 failed** |

**Legitimate contract changes (explained, not silent):**
1. `profile.tsx` no longer auto-navigates to home when the profile is complete — required so the state-reflective "Profile complete" heading can actually be seen; an explicit "Go to home" button replaces it (the `"/(student)/home"` pin is met by that button).
2. `registration.tsx` correction button is now unconditional (was gated on non-active status) — required so cancelled/revoked students can also request review.
3. `readiness.tsx` "Completed" section removed — done items now render inside their checklist groups, so completion is shown once, not twice.

No test was weakened or deleted; all pre-existing pins pass unchanged.

## 10. Remaining issues / manual Android verification (pending device acceptance)

No adb or emulator is available in this environment (`adb not found`, `emulator not found`), so **device acceptance is pending**. Manual checklist on a physical Android device:

1. Registration: open with an incomplete official record → missing fields show "Not provided on the official list"; correction button visible in every status.
2. Profile: heading flips to "Profile complete" after all steps; photo upload shows "Photo uploaded." (never "verified"); airplane mode → stale banner, typed phone preserved; double-tap Save → one request.
3. Support: pick each of the five categories → guidance changes; send → reference `SUP-XXXXXX` shown; start typing again → confirmation clears; open detail → Acknowledged vs Decided note.
4. Readiness: Profile setup vs Event readiness sections render; entry-pass callout shows the real server reason once; rehearsal appears under Information only; reminders Mark read/Dismiss work one at a time.
5. Freshness: background a screen >30s → silent refresh without clobbering edits; expired session → redirected to welcome.

## 11. Production database integrity & release status

- `app/lgu.db` SHA-256 **after** this phase: `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` — **identical to the baseline**; the production database was never opened for write (backend tests use disposable temp databases only).
- Nothing was committed, pushed, deployed, amended, reset, stashed, or branch-switched.

**Release status: NO-GO for device acceptance** — source-level verification is complete (tsc 0, lint 0, 38/38 mobile scripts, 42/42 backend tests), but physical Android acceptance (Section 10) remains pending.
