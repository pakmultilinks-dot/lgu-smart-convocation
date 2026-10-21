# Phase 8 — Connect the Admin Portal, Student App and Live Operations

**Status:** COMPLETE. This phase inspected the working tree, implemented the
integration fixes, and verified the complete workflows end-to-end. No phase was
started afterward. Nothing was committed, amended, reset, stashed, cleaned or
pushed.

**Target:** `C:\Users\Lenovo\Documents\Code_PlayGround\LGU\lgu-smart-convocation`

---

## 1. Integration matrix — every data flow, audited

Ten flows were traced from the admin portal to the student app. All ten are
present and were verified server-side.

| # | Flow | Admin source | Student surface | Verified by |
|---|---|---|---|---|
| 1 | Convocation create / select / archive | `exam_event_routes` + `convocation_events` publication snapshot | `/api/student/event` | integration B |
| 2 | Registration import / correct / cancel / revoke / reinstate | `exam_reg_routes` + `exam_import` + `exam_registrations.ACTIONS` | `/api/student/me` | integration D |
| 3 | Student verify / claim / login | `student_routes` + `student_auth` | app session | integration D |
| 4 | Profile completion + photo | `/profile`, `/profile/photo` | profile screen | acceptance + freshness |
| 5 | Medalists draft / published | `medalist_routes` | public board + photo route | integration E |
| 6 | Expected vs confirmed dates distinct | `convocation_events.date_state` | `date_state_label` | integration B |
| 7 | Rehearsal date / time / venue + instructions | event snapshot | `/api/student/event` | integration B |
| 8 | Announcements draft / published / archived + audience + important | `announcements` | `/api/student/announcements` | integration C |
| 9 | Dashboard metrics (real COUNTs + issues) | `exam_routes.dashboard_metrics` | admin dashboard | integration G |
| 10 | Gates / scan / live board | `routes.process_scan` under `_SCAN_LOCK` | volunteer screens + LiveBoard polling | acceptance P |

## 2. One authoritative data flow, established

The rule the codebase now enforces everywhere:

- The **convocation row is the working draft**. Students only ever receive the
  `convocation_publications` snapshot written by an explicit `ev.publish()`.
  `ev.is_dirty()` reports unpublished changes.
- **Announcements** reach students only when `status = 'published'` **and**
  `audience = 'students'` (`ann.feed` is the sole student-facing query).
- **Medalists** reach the public board only when published; drafts and missing
  photos answer the same `404` so nothing leaks existence.
- The **student app reads the server on every focus** — there is no client-side
  source of truth that can outrank the server.

Proven, not assumed: the integration suite shows an unpublished draft never
reaches the app, a published snapshot does, and an edit keeps showing the last
**published** value until staff re-publish.

## 3. Automatic student-app updates — implemented

**The core defect:** all five student screens fetched only on mount. No focus
refetch, no resume refresh, no ≤30 s polling, and no `AppState` listener existed
anywhere in the app, so staff publishing never reached an open student app until
a full restart.

**Fix:** a shared hook, `mobile/src/hooks/useFreshServerData.ts`, wired into all
five student screens (`home`, `event`, `announcements`, `medalists`, `profile`):

- Fetches on **open**, on **focus refetch**, on **resume from background**, via
  **manual refresh**, and on a **periodic ≤30 s cadence while foregrounded**.
- **Stops when backgrounded** (AppState listener) and **never duplicates timers**
  (`startPolling` clears before setting; interval tick checks focus).
- **Overlap-safe** (`runningRef` skips a run already in flight; background guard
  refuses runs while not `active`).
- **Errors and retries:** a failed silent refresh keeps the last data and shows a
  stale badge; the next tick retries. **Network failure is never rendered as an
  authoritative rejection** — only a real `401` ends the session.
- **No WebSockets, no paid services, no new dependencies.**
- **No AsyncStorage shadow copy** — tokens live in SecureStore (native) or memory
  (web); screen data is re-fetched, not cached as truth.
- **Logout removes private cached data** (fixed: profile sign-out now revokes the
  session and clears the token).

Verified by `mobile/scripts/phase8-freshness-test.mjs` (33 checks, 0 failures) and
the upgraded `event-announcements-test.mjs` (25 checks, 0 failures); `tsc` and
`expo lint` clean.

## 4. Complete admin → app publishing workflows — fixed and verified

`app/scripts/test_phase8_integration.py` (57 checks, 0 failures) proves each
workflow round-trips:

- **Convocation publish → app:** draft never reaches the app; publish pushes the
  snapshot; switching the active convocation empties/restores the feed.
- **Event edits → app:** an edit keeps the last published value; re-publish
  carries the revision.
- **Corrections / cancellations / revocations → app session:** an admin correction
  reaches the student immediately; a cancellation is served honestly; a stale
  claim surfaces as a dashboard issue; a revocation reaches the open session and
  **cannot be reinstated**.
- **Medalists / announcements → app:** publishing without a picture is refused;
  the draft never reaches the board; withdraw removes it and the photo 404s;
  announcement drafts, staff-audience rows and archived rows never reach the
  student feed.

## 5. Security and permissions — verified

- Exam screens require a staff session; exam POSTs without CSRF are `403`.
- Student endpoints without a token are `401`; a wrong student password is `401`.
- Settings mutations without a PIN are `401`; a wrong PIN is `401`; the correct
  PIN passes; **PIN attempts are rate-limited `429`**.
- **Public payloads leak no registration or account fields** (no
  `registration_number`, `university_email`, or `REG-…` values).

## 6. Admin dashboard — intelligent and real

`dashboard_metrics` computes per-request, read-only metrics from real COUNTs:
registration totals, claimed vs unclaimed, incomplete profiles (photo gaps),
latest import, medalist counts with coverage gaps, and event state / dirty /
announcements / milestones. Every issue links to the authorized screen that
resolves it; the template renders the **15 KPI tiles**. Verified in integration G.

## 7. Regression, E2E tests and database safety

**Backend (9/9 green):** convocation migration, exam auth, exam registration,
event announcements (58), exam dashboard (31), medalist management (55), student
accounts (92), phase-8 acceptance (85), **phase-8 integration (57, new)**.

**Mobile:** freshness (33, new), event/announcements (25, upgraded),
student-screens (39), medalist-board (22), layout-p8 (44/0) and the rest — all
0 failures. `npm run tsc` and `npx expo lint` clean.

**Database safety — `app/lgu.db` never opened, copied, reset or mutated:**

```
size   = 278528
mtime  = 2026-10-10T19:35:21.8392785Z
sha256 = 820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F
```

Identical to the before-stamp. Every suite runs on a disposable temp database
guarded by `config.require_test_db()`.

`git diff --check` clean. The working tree was **preserved** — 103 prior
uncommitted changes and previous-phase files remain untouched.

### Defects fixed this phase

1. **Student app stale until restart** — the central defect; fixed with the
   freshness hook above.
2. **False acceptance failure** — the acceptance suite's production-database
   boundary check hardcoded `st_size == 81920` while the real database is
   278528 bytes, so it reported a violation that never happened. Replaced with
   an honest before/after stat-stamp comparison (size + `mtime_ns`) that is
   strictly stronger and does not read the file.
3. **Profile sign-out left the token behind** — now revokes the session and
   clears the token.
4. **Vacuous "no polling" test** — `event-announcements-test.mjs` asserted the
   screens contain no `setInterval` (they never did; the hook owns timing). The
   check was upgraded to assert the real controlled-freshness contract rather
   than weakened.

### Known, pre-existing, out of scope (reported, not touched)

`mobile/scripts/layout-p9-source-test.mjs` reports 13/2. It reads
`app/web/static/css/style.css`, where `.badge.queued` uses `--amber` (`#9a6a00`)
while the check wants an AA-contrast `#6b4c00`. This is a cosmetic contrast
adjustment in an uncommitted QA file, unrelated to integration. The brief scopes
this phase to integration, so it was left as-is and is surfaced here for an
explicit follow-up decision.

---

**Prioritized student-app feature list** — see `STUDENT_APP_FEATURE_PRIORITY.md`
(implemented / incomplete / not implemented, with a recommended next-phase order).

**This integration phase is complete. Stopping here as instructed — no further
phase was begun.**
