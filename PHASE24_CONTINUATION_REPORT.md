# Phase 24 Continuation — Scanner Integrity, Remaining Acceptance Gates

**Date:** 2026-10-03 · **HEAD:** `298c272` (unchanged — nothing committed or pushed)
**Verdict:** Release candidate remains **NO-GO** — see §7 for the real reasons.

Evidence classes used below:
- **[AUTOMATED]** — an executable test suite ran and printed its result.
- **[CODE-INSPECTION]** — source was read and traced; no runtime/device proof.
- **[DEVICE]** — physical-device verification. **Nothing in this phase qualifies.**

---

## 1. State preservation

| Check | Result |
|---|---|
| HEAD before/after | `298c272` — no commit, no push, no stash, no reset [AUTOMATED] |
| Production `app/lgu.db` | size **278528**, SHA-256 **820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F** — byte-identical to the Gate 1 stamp after every suite run [AUTOMATED] |
| Test databases | every suite ran against a disposable temp DB (`LGU_DB_PATH`); prod DB never opened for write [AUTOMATED] |
| Gate 1 fixture | not recreated; no passes consumed outside test requirements [CODE-INSPECTION] |
| Running processes | backend :5000 and Metro :8081 left running; no unrelated process terminated [CODE-INSPECTION] |

## 2. Replay defect (offline queued LGU2 scans) — **PASS**

**Defect:** a scan queued offline and replayed through `/api/sync` returned the red
`ALREADY ADMITTED` verdict, which is a *permanent* rejection the client never
acknowledged — the item re-queued forever.

**Fix (three parts):**
1. `app/convocation_qr.py` — new `queued_admission_exists()` mirrors the roster-side
   idempotency check: an identical queued CONVOCATION scan already recorded is detected
   before re-processing.
2. `app/web/routes.py` — the `/api/sync` convocation branch pre-checks and answers amber
   **`ALREADY SYNCED`** ("This scan was already recorded by an earlier sync.") instead of
   re-running the admission. **Label improvement only** — the server-side UNIQUE
   `(convocation_id, registration_id)` constraint and the `IntegrityError → rollback`
   backstop are untouched; a genuine duplicate still red-`ALREADY ADMITTED`s online.
3. `mobile/src/store/offlineQueue.ts` — `ALREADY ADMITTED` + `GATE NOT AUTHORIZED` added to
   `PERMANENT_REJECTIONS`, and a promise-mutex (`withQueueLock`) serialises
   `enqueueScan`/`reconcileSync`/`clearQueue` so a scan enqueued *during* a reconcile can
   no longer be dropped (AsyncStorage has no transaction).

| Evidence | Result |
|---|---|
| `test_phase24d_replay.py` | **16/16 PASS** [AUTOMATED] |
| `test_phase23_busy_contract.py` | PASS — busy items still admit exactly once on replay [AUTOMATED] |
| `test_phase17_cross_role_acceptance.py` | PASS — online second scan still `ALREADY ADMITTED` [AUTOMATED] |
| `scanner-logic-test.mjs` | **70/70 PASS** — includes the reconcile race + transient-busy-stays-queued [AUTOMATED] |

## 3. Gate 24D completion — **PASS**

Covered by §2. Client `PERMANENT_REJECTIONS` mirror in the Python test kept in sync with
`offlineQueue.ts` [AUTOMATED].

## 4. Gate 24E — guest passes + attendance dashboard — **PASS**

Code inspection found the dashboard already honest (Phase 35K work); no defect found.

- **Guest validity:** exit refused amber with no scan written; entry recorded with host
  context; second use red `ALREADY USED` with structured name/gate/time; exactly one scan
  row per guest [AUTOMATED, `test_phase24e_guest_dashboard.py` **25/25**].
- **Occupancy:** exit decrements `inside_total`; guests counted separately from the hero
  "Inside now" [AUTOMATED].
- **Arrival honesty:** `expected_attendance` unset → `attendance_set=false`,
  `arrival_pct=0` (explicit not-set state, **no roster fallback**); set → pct measured only
  against the expected value, clamped [AUTOMATED].
- **Denominator rule:** `progressDenominator()` returns the expected attendance only when
  finite and > 0 — a roster count never silently substitutes as the event target
  [CODE-INSPECTION, `mobile/src/utils/progress.ts`].

## 5. Gate 24F — announcements + permissions — **PASS**

| Check | Result |
|---|---|
| Broadcast never claims a delivery it did not perform | demo-mode note states it was **not sent by SMS**, recorded in log only; real mode says gateway not configured [AUTOMATED, `test_phase24f_broadcast_authz.py` **16/16**] |
| `POST /api/broadcasts` without / wrong admin PIN | **401** [AUTOMATED] |
| `PUT /api/settings` without PIN | **401**; with PIN accepted; `expected_attendance` bounded [AUTOMATED] |
| Oversized (>160) / empty broadcast | **400** [AUTOMATED] |
| Staff announcements page anonymous | redirects to `/exam/login` [AUTOMATED] |
| Staff POST without CSRF token | **403** [AUTOMATED] |
| Student feed scoping | only `status='published' AND audience='students'` rows served; drafts and staff-audience rows never appear [AUTOMATED] |
| Gear/settings + tab-bar accessibility | `SectionRow` → `accessibilityRole="button"` + `accessibilityLabel`; tab bar role/`selected`/label [CODE-INSPECTION — **not** device-verified] |

## 6. Gate 24B re-audit — five student registration states — **PASS**

Each state traced to **authoritative backend data** (`convocation_registrations.status`,
the active convocation row, and event config) — never inferred from profile completion.
`test_phase24b_states.py` **29/29 PASS** [AUTOMATED]:

| Student-facing state | Authoritative source | Verified |
|---|---|---|
| Registered | `status='active'` row for the active convocation → `/me` serves `active` | ✅ |
| Action needed | `cancelled` / `revoked` row → verify **410** with the status word; claimed `/me` reports it | ✅ |
| Not found on list | **404 `unmatched`** — no row matches all four identifiers (unknown reg no. *and* wrong roll both 404) | ✅ |
| Registration not open | **409 `no_convocation`** — no active convocation configured | ✅ |
| Registration closed | **410** on a non-active row at verify time; reinstate → no longer 410 (409 `claimed` for the already-linked account) | ✅ |

**Core mandate proven:** wiping the student profile leaves `registration.status == 'active'`
while `completion.complete` flips false — the status is never derived from profile
completion [AUTOMATED].

Mobile `REG_STATUS` in `mobile/app/(student)/home.tsx` maps `active/cancelled/revoked`
with a labelled fallback for unknown words; verify-screen errors surface the backend's own
message verbatim [CODE-INSPECTION].

## 7. Final regression (24G) + release verdict

**Backend suites — all PASS** [AUTOMATED]:
`24d_replay` · `24e_guest_dashboard` · `24f_broadcast_authz` · `24b_states` ·
`23_busy_contract` · `20_authz_matrix` · `17_cross_role_acceptance` · `16_lifecycle` ·
`event_announcements` · `8_integration` — 10/10 green.

**Mobile** [AUTOMATED]: `tsc` exit 0 · `lint` exit 0 · `scanner-logic-test` 70/70 exit 0.

**Integrity** [AUTOMATED]: HEAD `298c272` (no commits), prod DB hash byte-identical.

### Real NO-GO reasons

1. **No physical-device verification exists for this phase.** Every result above is
   automated backend tests, type-checking, lint, or static source inspection. Camera
   scanning, QR decode, offline queue behaviour on a real handset, and accessibility
   labels have **not** been exercised on hardware. [DEVICE — BLOCKED, pending user report]
2. **Release Gate 1 field evidence (P1–P6) is still user-reported only** — the acceptance
   gate closes only when the physical phone passes; the agent cannot certify it.
3. Prior-phase open items (P-06, P-13..P-19, P-21) remain deferred per the Phase 34
   §20M recommendation — unchanged by this phase.

### What this phase did NOT do
No reset/clean/stash/commit/push; no unrelated repo touched; `app/lgu.db` never used as a
test or migration target; no validation or authorization weakened; the server-side
duplicate-admission constraint untouched; no credentials printed.
