# Phase 31 — Student App Navigation & Home Redesign

**Status: implementation complete, automated verification green, release remains NO-GO pending Android device acceptance.**

---

## 1. Initial repository / working-tree state

- The working tree already carried substantial uncommitted work from earlier phases (backend modules, mobile `(student)` screens, test scripts, reports — 207 changed/untracked paths at start). **Nothing was committed, stashed, reset, or pushed during Phase 31.**
- Pre-existing modified files (e.g. `app/*.py`, `app/web/*`, `mobile/app.json`, `mobile/app/_layout.tsx`, `mobile/app/mode-picker.tsx`, `package.json`) were preserved untouched except where Phase 31 explicitly required changes.
- Production database `app/lgu.db` was opened **read-only** for verification only; no writes were performed.
- Baseline SHA-256 of `app/lgu.db` before work: `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F`.

## 2. Root causes confirmed through code inspection

1. **No persistent student navigation.** The `(student)` group was a plain stack: every screen re-implemented its own header/back affordance, destinations were reachable only through ad-hoc links, and there was no persistent way to move between Home, Registration, Pass, Updates and More.
2. **Home conflated distinct concepts.** Registration status, official-list inclusion, account claim date, profile completion and event readiness were presented without clear separation; secondary destinations (medalist board, history, support) crowded the primary actions.
3. **Rehearsal and main convocation shared presentation.** A single countdown component rendered both occasions, inviting confusion between the two dates.
4. **Stale typed routes.** `mobile/.expo/types/router.d.ts` (gitignored generated artifact, `typedRoutes: true`) predated the new `/(student)/registration` route, producing a single `TS2345` error until regenerated.
5. **Floating gear: not an application defect.** A repo-wide trace found only two `settings-outline` icons — `ScannerScreen.tsx:801` ("Open settings" permission button) and `SettingsScreen.tsx:219` ("Connection settings" button) — both inline `AppButton`s in normal document flow inside **volunteer** screens. No `position: "absolute"` control exists anywhere in `mobile/app/**`; the only absolute styles in `src/` are scanner viewfinder overlays, a gate marker, and a live-board element. Conclusion: the observed gear belongs to a development overlay or external test environment (e.g. Expo Go's dev menu), **not** the application, so no application component was changed.

## 3. Files changed and purpose

| File | Change |
|---|---|
| `mobile/app/(student)/_layout.tsx` | Rewritten as a persistent `Tabs` shell (`expo-router/js-tabs`): five visible destinations (`home` first so default `backBehavior: "firstRoute"` never lands on the entry gate), 13 hidden routes registered with `href: null`, custom `StudentTabBar` with parent-route active mapping, a11y role/label/selected state and ink underline (gold reserved for launch screens). |
| `mobile/app/(student)/registration.tsx` | **New** "My Registration" tab: status pill + meaning, official-list row, account-claim row, honest hint that the API exposes no last-status-check time, official details card, profile progress, correction request. |
| `mobile/app/(student)/more.tsx` | **New** "More" tab: Convocation / Account / Device groups (event, readiness, history, medalists, profile, support, mode change, sign out). |
| `mobile/app/(student)/home.tsx` | Rebuilt hierarchy: compact app bar, status section with four distinct concepts, primary actions (View Entry Pass first), two separate `OccasionCard`s (rehearsal / ceremony) driven by server occasions + `useCountdown`, separate profile and readiness counts, secondary destinations moved to More/Registration, honest loading/error/stale/empty states. |
| `mobile/scripts/phase31-student-nav-test.mjs` | **New** — the ten Part F checks (see §6). |
| `mobile/scripts/readiness-source-test.mjs` | Check 22 contract change (see §6). |
| `mobile/scripts/event-announcements-test.mjs` | Check R2 contract change. |
| `mobile/scripts/pass-history-source-test.mjs` | Checks R2/R3 contract changes. |
| `mobile/scripts/medalist-board-test.mjs` | Check H1 contract change. |
| `mobile/scripts/phase29-annual-event-source-test.mjs` | Countdown pin updated for per-occasion cards. |

## 4. Navigation and screen behavior implemented

- **Persistent shell:** Home · My Registration · Entry Pass · Updates · More, always visible; child screens (`profile`, `event`, `readiness`, `history`, `medalists`, `support`, `verify`, `code`, `recovery`, `welcome`, `login`, `index`) stay registered but hidden (`href: null`) and resolve normally.
- **Active navigation:** the tab bar maps child routes to their parent tab for the selected/underline state; back from any child resolves to the first tab (Home), never to the entry gate.
- **Home hierarchy:** status → meaning → official list / reference / claim → primary actions → two occasion cards → profile count → readiness count → More links → refresh/sign-out/mode change.
- **Concept separation:** registration status, official-list inclusion, account claim date, profile completion and event readiness each render as their own labeled element; no element infers one from another.
- **No staff operations:** student navigation contains zero volunteer/staff destinations or actions (pinned by test check 4).

## 5. Event-date source-of-truth findings

- **Production truth:** `app/lgu.db` (read-only query) reports `convocation_datetime = 2026-12-12T09:00:00+05:00`, one convocation row; `app/database.py:162` seeds the same value. The client hardcodes **no** date — Home renders whatever `/api/student/event` publishes.
- **The apparent Oct 20 vs Dec 12 conflict is not a defect:** `2026-10-20` appears only in `PHASE30_ANDROID_ACCEPTANCE_REPORT.md` and `app/scripts/_gate1_field_setup.py`, both describing a **disposable field-test database** ("Release Gate 1 Field Test", temp dir since cleaned). Production and the seed remain Dec 12 2026.
- Countdown honesty is inherited from `EventCountdown` (`pickNextOccasion`/`countdownText`): provisional dates never count down, no published time yields days only, past occasions read "Completed" — never a negative or fabricated clock.

## 6. Tests run — exact commands and actual counts

All commands run from `lgu-smart-convocation/mobile/` unless noted.

**TypeScript / lint**

| Command | Result |
|---|---|
| `npx tsc --noEmit` | exit 0 (after regenerating `.expo/types/router.d.ts` via `npx expo start --port 8127`) |
| `npx expo lint` | exit 0 |

**New Phase 31 test**

| Command | Result |
|---|---|
| `node scripts/phase31-student-nav-test.mjs` | **10 checks, 0 failures** |

**Full mobile regression — every script in `mobile/scripts/*.mjs` (37 files)**

| Command | Result |
|---|---|
| `node scripts/<name>.mjs` for all 37 scripts | **37 PASS, 0 FAIL** (includes `readiness-source-test` 29/29, `student-screens-test` 39/0, `phase27-mode-switch-test` 18/0, `event-announcements-test` 25/0, `pass-history-source-test` 31/0, `medalist-board-test` 22/0, `phase29-annual-event-source-test` 39/0, `phase8-freshness-test` 33/0) |

**Backend — from `lgu-smart-convocation/app/`, disposable temp databases only**

| Command | Result |
|---|---|
| `..\.venv\Scripts\python.exe scripts\test_*.py` (42 files) | **42 PASS, 0 FAIL** |

**Legitimate contract changes (explained, not weakened):**

1. `readiness-source-test` check 22 — Home no longer pushes `medalists`; the board moved to More. Pin now asserts Home keeps profile/event/announcements/support **and** `more.tsx` carries `"/(student)/medalists"`. Reachability of all five prior destinations is preserved.
2. `event-announcements-test` R2 — Home's entry points are now the `Event details` and `Updates` rows (old `label=` buttons removed by Part B §6); medalist ordering pinned on More instead.
3. `pass-history-source-test` R2/R3 — pass remains Home's primary action; history moved to More and is pinned there.
4. `medalist-board-test` H1 — board link pinned on `more.tsx`.
5. `phase29` countdown pin — Home renders two `<OccasionCard>`s via `useCountdown` instead of one `<EventCountdown>` list; the "countdown comes from the fetched event" guarantee is preserved.

No assertion was removed; each change redirects the pin to the destination that now owns the behavior.

## 7. Remaining issues

- **Android device acceptance not performed** — no `adb`, no emulator, no physical device available in this environment (verified: `adb not found`, `emulator not found`). All UI claims above are source-level; see §8 checklist.
- The generated `.expo/types/router.d.ts` is gitignored and must be regenerated (`npx expo start`) on a fresh clone before `tsc` passes — pre-existing project characteristic, unchanged by Phase 31.
- Expo package drift warning (`expo 57.0.25 → 57.0.30`) is pre-existing and out of scope.

## 8. Manual Android verification steps (pending device acceptance)

1. Launch in Expo Go on a physical device; confirm the five-tab bar persists across Home → Registration → Pass → Updates → More.
2. From Home tap **View Entry Pass**; press hardware back — expect return to Home (never the entry gate).
3. Open **Event details** (child screen); back returns to the tab that opened it; the tab bar shows the parent as active with underline.
4. Home: verify status pill + meaning, official-list row, reference row, claim row, and the "no last-status-check time" hint are four separate elements.
5. Verify **two separate occasion cards** (Rehearsal / Main convocation) with independent pills and countdowns; with no schedule published, verify "No schedule published" empty state.
6. Enable airplane mode → pull to refresh: expect the stale badge ("Offline — showing your last loaded details"), never a false approval or zeroed counts; retry recovers.
7. Sign out mid-session (401 path): expect redirect to Welcome, not an error loop.
8. Small-width device (360 dp): check no clipped labels, no horizontal overflow, tab labels fully visible.
9. Keyboard open on any input screen: confirm submit actions remain reachable (Screen uses `automaticallyAdjustKeyboardInsets`).
10. Android system back/gesture navigation: confirm safe-area padding top/bottom and that the last content row (Sign out / Change device mode) is reachable by scrolling.
11. Confirm no floating gear appears anywhere in the student app (expected: none — it is not an app component).

## 9. Production database integrity

```
(Get-FileHash app\lgu.db -Algorithm SHA256).Hash
820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F
```

Matches the original baseline exactly. All backend integration tests ran against disposable temp databases; `test_phase21_prod_db_boundary.py` (which stat-stamps the production DB) passed.

## 10. Release status

**NO-GO.** The Phase 31 implementation and all automated checks are green (tsc 0, lint 0, 37/37 mobile scripts, 42/42 backend tests, DB hash intact), but release requires **actual Android device acceptance**, which has not been executed — no device or emulator was available. Device-level checks in §8 remain pending, and external-provider prerequisites (email delivery configuration) remain as previously documented. No feature is claimed fixed beyond what the implementation and verification above support.
