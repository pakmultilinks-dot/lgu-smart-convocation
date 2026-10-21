# PHASE 29 — Annual Convocation and Rehearsal Implementation

**Scope:** two distinct occasions per annual cycle (rehearsal + main convocation) with
separated dates, status, countdowns, attendance and reporting; end-to-end verification of
every student-dashboard option; independent rehearsal/ceremony attendance; staff reporting
split by occasion.

**Constraints honoured:** no reset / clean / stash / revert / commit / push / deploy;
production `app/lgu.db` never used by any test (disposable databases only); authentication,
signed QR validation, guest privacy, admission uniqueness and audit history preserved; no
invented guest-limit / eligibility / ticket policy (unsupported policy = university
configuration); no fake success states or sample data presented as real records.

---

## 1. Event data model and migrations

### 1.1 Model

One annual convocation row now carries **two occasions**, both owned by the same
convocation (no duplicate student identities, no conflicting registrations):

| Concept | Storage |
|---|---|
| Ceremony date / start time | `convocations.confirmed_date` (fallback `expected_date`) + `convocations.ceremony_time` (new) |
| Rehearsal date / start time | `convocations.rehearsal_date` + `convocations.rehearsal_time` |
| Rehearsal venue | `convocations.rehearsal_venue` (new) — falls back to `venue` when empty |
| Publication snapshot | `convocation_publications` mirrors `ceremony_time` + `rehearsal_venue` (new columns) |
| Admission occasion | `convocation_admissions.occasion TEXT NOT NULL DEFAULT 'ceremony'` (new) |

`convocation_events.py` derives the occasion view: `occasions(pub)` returns
`[{key: "rehearsal", state: "announced"|"not_announced"}, {key: "ceremony", state:
"confirmed"|"expected"}]`, each with `label, date, time, venue, phase, days_until,
starts_at`. `student_payload` exposes `ceremony_time`, `occasions`, `portal_tz`.

### 1.2 Migration 12 (project convention: versioned scripts + `PRAGMA user_version`)

```
ALTER TABLE convocations ADD COLUMN ceremony_time TEXT;
ALTER TABLE convocations ADD COLUMN rehearsal_venue TEXT NOT NULL DEFAULT '';
ALTER TABLE convocation_publications ADD COLUMN ceremony_time TEXT;
ALTER TABLE convocation_publications ADD COLUMN rehearsal_venue TEXT NOT NULL DEFAULT '';
ALTER TABLE convocation_admissions ADD COLUMN occasion TEXT NOT NULL DEFAULT 'ceremony';
DROP INDEX IF EXISTS idx_convocation_admissions_once;
CREATE UNIQUE INDEX IF NOT EXISTS idx_convocation_admissions_once
    ON convocation_admissions(convocation_id, registration_id, occasion);
CREATE INDEX IF NOT EXISTS idx_convocation_admissions_occasion
    ON convocation_admissions(convocation_id, occasion);
```

- **Backfill:** every pre-existing admission row becomes `occasion='ceremony'` (before
  Phase 29 a convocation had exactly one admission — for the convocation itself).
- **Uniqueness:** the UNIQUE index keeps its historical **name** while gaining the
  occasion column — one admission per (convocation, registration, occasion). A second
  index supports per-occasion dashboard counts.
- **Transactional:** the script runs inside `BEGIN; … PRAGMA user_version = 12; COMMIT;`
  — a failure rolls back schema and version together.
- **Proven:** `test_phase21_migration_v6_to_v11.py` now parameterises on the real ladder
  (`LATEST = 12`): v6 → 12 upgrade, v10 → 12 upgrade, fresh init, idempotent re-run,
  row-by-row preservation (projected onto baseline columns so `ADD COLUMN` backfill is
  not misread as mutation), fail-closed on newer schema, rollback of a failing migration
  — **91/91**.

### 1.3 Schedule validation

`_check_order` rejects contradictory schedules at save time:

- rehearsal date after ceremony date → *"The rehearsal must be scheduled before the main
  convocation."*
- same day with `rehearsal_time >= ceremony_time` → *"On the same day, the rehearsal must
  start before the main convocation starts."*

The ceremony side uses `confirmed_date`, falling back to `expected_date` — a contradictory
schedule is rejected whether or not it has been confirmed yet.

---

## 2. Rehearsal and ceremony lifecycle transitions

| Stage | Rehearsal | Main convocation |
|---|---|---|
| Not scheduled | `state: "not_announced"`, no countdown, scanner answers **REHEARSAL NOT SCHEDULED** (records nothing) | `state: "expected"` (provisional) → never counts down |
| Announced / confirmed | `state: "announced"` once `rehearsal_date` saved + published | `state: "confirmed"` once `confirmed_date` saved + published |
| Upcoming | `phase: "upcoming"`, countdown from `starts_at` (UTC instant derived from `portal_tz`) or days-only | same |
| Live | `phase: "live"` — "Happening now" | same |
| Completed | `phase: "completed"` — "Completed", never a negative count | same |

Publication is separate from saving: an unpublished draft never reaches the student app
(existing publish/audit flow, unchanged). Both occasions always belong to the active
convocation — switching the active convocation moves the whole cycle together.

---

## 3. Countdown and event-status behaviour

Server computes per-occasion `{state, phase, days_until, starts_at}`; the client only
ticks. Honesty rules (pinned by `phase29-annual-event-source-test.mjs` §6):

1. Countdown appears **only** for an announced/confirmed occasion that is upcoming or
   live. `not_announced` and `expected` (provisional) never count down.
2. `starts_at` is an ISO-8601 UTC instant computed **server-side** from the configured
   date + time in `portal_tz` — the device never guesses a timezone.
3. No published start time → plain days ("3 days to go") — **never a fabricated clock**.
4. A passed occasion reads **"Completed"** — never a negative timer; a started instant
   reads **"Happening now"**.
5. The interval ticks only when there is something to show; `EventCountdown` renders
   nothing without an occasion or text.

Surfaces: **Home** (`EventCountdown` card, loaded in `Promise.all` with `/me`),
**Event Details** (countdown + "Annual cycle" section listing both occasions with
per-occasion StatusPill: Not announced / Provisional / Completed / Announced), **Pass**
(note states whether the pass applies to both occasions or only the main convocation —
wording flips only when rehearsal is actually announced), Readiness/History (event
snapshot carries `occasions`/`ceremony_time`/`portal_tz`).

---

## 4. QR / pass and event-scoped attendance rules

- **One bearer pass serves both occasions** — no second pass, no duplicate identity.
- Every scan request carries `occasion` (`"rehearsal" | "ceremony"`); absent →
  `'ceremony'` (backward compatible with old clients and queued rows); unknown →
  **400 UNKNOWN OCCASION** at `/api/scan`, per-item result at `/api/sync`.
- `verify_scan` order: parse → gate auth → mode → occasion → gate exists → pass valid →
  revoked → **used → ALREADY ADMITTED** → expiry → convocation available →
  **rehearsal without `rehearsal_date` → REHEARSAL NOT SCHEDULED (records nothing)** →
  registration → eligibility → per-occasion admitted pre-check → INSERT (IntegrityError →
  ALREADY ADMITTED) → **ceremony admission marks the pass used; rehearsal admission does
  not** → audit ("REHEARSAL ENTRY RECORDED" / "CONVOCATION ENTRY RECORDED").
- **Independence proven:** rehearsal check-in does not consume ceremony admission — a
  student admitted at rehearsal still enters the ceremony; duplicates are blocked
  *within* each occasion (UNIQUE `(convocation_id, registration_id, occasion)`), and the
  same pass queued for both occasions replays as two distinct legitimate admissions.
- Gate authorization, signed-QR validation, revoked/invalid rejection, offline queue
  reconciliation and audit rows are unchanged and re-tested.
- Scanner app: occasion is a first-class, **confirmed** choice — second segmented
  control (Main convocation / Rehearsal, amber for rehearsal), confirmation modal
  ("Switch to Rehearsal? …"), persisted (`lgu.ops_scan_occasion`), stamped on every
  payload, part of the cooldown key (same pass on a different occasion is not
  suppressed), part of the offline dedup key, and `REHEARSAL NOT SCHEDULED` /
  `UNKNOWN OCCASION` are permanent rejections (never retried offline).
- **No policy invented:** guest limits, eligibility and ticket allocation are untouched;
  unsupported decisions remain marked as requiring university configuration.

---

## 5. Student-dashboard options — inventory and results

Every visible option was traced route → permission → DB change → result → test:

| Option | Route / mechanism | Result |
|---|---|---|
| Registration lookup / claim | `POST /api/student/verify`, `/resend`, `/complete` | ✅ claims matching registration; CSRF/limits intact |
| Sign-in / sign-out | `POST /api/student/login`, `/logout` | ✅ token issued/revoked; logout → 401 afterwards |
| Session state | `GET /api/student/me` | ✅ account/profile/registration + 3-step completion (verified/claimed/photo) |
| Profile / phone save | `POST /api/student/profile` | ✅ persists, visible in `/me` |
| Photo upload / view | `POST|GET /api/student/profile/photo` | ✅ base64 upload → stored, served back |
| Corrections | staff registration actions (cancel/reinstate; revoke permanent) | ✅ served honestly to open session |
| Event information | `GET /api/student/event` | ✅ two occasions + ceremony_time + portal_tz |
| Readiness | `GET /api/student/readiness` | ✅ items + reminders from real data |
| Reminder dismiss | `POST /api/student/readiness/reminders` | ✅ dismissible key → `state: "dismissed"`; unknown/non-dismissible → 400 fail-closed |
| Digital pass | `GET /api/student/pass`, `POST /pass/issue` | ✅ ineligible (e.g. cancelled) → 403; issued pass serves both occasions |
| History | `GET /api/student/history` | ✅ `{ok, total, history}` with event occasion snapshot |
| Announcements | `GET /api/student/announcements` | ✅ published student rows only; drafts/staff/archived never leak |
| Medalist results | `GET /api/student/medalists` (+ photo) | ✅ published only, no PII/reference numbers |
| Help / support | `POST|GET /api/student/support`, `/support/<id>` | ✅ create/list/detail; staff resolve path tested |
| Recovery | `POST /api/student/recovery/request`, `/complete` | ✅ fail-closed flow (Phase 16 suite) |
| Refresh / retry | client `Promise.all` + `.catch(() => null)` on event | ✅ stale banner, no crash on event failure |
| Settings (staff/admin surfaces) | `/api/settings` GET+PUT PIN-gated; `/exam/*` staff_required; `/guests/directory` admin-gated | ✅ anonymous → 401/302 (fresh-client checks) |

No broken or misleading action found in this pass; no fake success state exists.

---

## 6. Staff dashboards and event operations

- **Exam dashboard** (`/exam/dashboard`, staff_required): two new KPI tiles —
  "Admitted — main convocation" and "Admitted — rehearsal" — fed by
  `_admitted_by_occasion` (per-occasion `GROUP BY`), template now 24 `kpi-tile`s.
- **Live dashboard** (`/dashboard`): `#k-ceremony` / `#k-rehearsal` tiles reading
  `ceremony_admitted` / `rehearsal_admitted` from `dashboard_summary()`.
- Counters verified against raw SQL in the acceptance suite (summary == raw GROUP BY).
- Event form (`exam/event.html`) exposes `ceremony_time` + `rehearsal_venue` inputs with
  the ordering validation messages.
- Occupancy/throughput wording unchanged — no gate activity is called "current
  occupancy" unless entry/exit records support it (pre-existing discipline preserved).
- Staff authorization enforced backend-side (fresh anonymous client: scan/sync/settings
  401, exam pages 302, guest directory gated).

---

## 7. Tests actually run and results

### Backend — 42/42 suites exit 0 (disposable DBs only)

Key counts (all `0 failures`):

| Suite | Result |
|---|---|
| **test_phase29_annual_event_and_student.py (new)** | **66/0** |
| test_phase12_qr_scanner | 41/0 |
| test_phase8_integration | 57/0 |
| test_phase8_acceptance | 85/0 |
| test_phase9_support | 58/0 |
| test_phase10_readiness | 52/0 |
| test_phase11_pass_history | 75/0 |
| test_phase13_e2e_acceptance | 53/0 |
| test_phase14_scanner_access | 50/0 |
| test_phase16_lifecycle | 52/0 |
| test_phase17_cross_role_acceptance | 157/0 (7 steps) |
| test_phase19_scanner_management | 105/0 |
| test_phase20_authz_matrix / backup / config / migration | 40 / 40 / 84 / 52 |
| test_phase21_migration_v6_to_v11 (now v6→12) | 91/91 |
| test_phase21 load / guardrails / limits | 26 / 15 / 10 |
| test_phase22 contention / journal | 65 / 25 |
| test_phase23 busy contract | 27/0 |
| test_phase24b/d/e/f | states / 16 / 25 / 16 |
| test_phase26a/b/c | 22 / 9 / 24 |
| test_phase27 lifecycle / guest authz | 27 / 52 |
| test_phase28 authorization closure | 34/0 |
| test_event_announcements | 58/0 |
| test_exam_dashboard | 31/0 |
| test_medalist_management | 55/0 |
| test_student_accounts | 92/0 |
| remaining suites (exam_auth, exam_registration, convocation_migration, …) | all exit 0 |

The Phase 29 acceptance suite covers: two-occasion configuration + publish, ordering
errors, status transitions (live/past/no-time/venue fallback), xlsx import, registration
independence (cancel/reinstate), rehearsal scan, ceremony scan, same-occasion duplicates
(IntegrityError), cross-occasion legitimacy, REHEARSAL NOT SCHEDULED (records nothing),
unknown occasion 400 (scan + per-item sync), gate 403, cancelled-registration issue 403,
offline queue with occasion + legacy no-occasion replay, full student dashboard walk
(profile/photo/pass/history/readiness/reminders/support/announcements/medalists/event/
logout), fresh-client authorization, true v11→v12 migration, dashboard counter parity,
and the production-DB boundary check.

### Mobile — tsc 0, eslint 0 errors (3 pre-existing warnings), 36/36 suites

| Suite | Result |
|---|---|
| **phase29-annual-event-source-test.mjs (new)** | **39/0** |
| scanner-logic-test | 74/0 |
| student-screens-test | 39/0 |
| data-truth-test | 53/0 |
| phase28-authorization-source-test | 35/0 |
| phase27-mode-switch-test | 18/0 |
| ui-35k (claim signature) | 39/0 |
| pass-history-source-test | 31/0 |
| event-announcements-test | 25/0 |
| medalist-board-test | 22/0 |
| all remaining suites | exit 0 |

Pins updated for Phase 29: exam dashboard 24 KPI tiles (3 backend + 3 mobile pins),
`claim(scan.data, mode, gateId, occasion)`, migration ladder parameterised to 12.

---

## 8. Android / device tests still required — **BLOCKED (checklists only)**

**No physical Android verification occurred in this phase and none is claimed.**
Required on-device (checklist, not executed):

1. Occasion segmented control renders and confirms on a real device (amber rehearsal).
2. Occasion persists across app restart / scanner lock-unlock.
3. Camera scan of a rehearsal QR while occasion = Rehearsal → "REHEARSAL ENTRY RECORDED";
   same QR with occasion = Main convocation → ALREADY ADMITTED (or ceremony rules).
4. Offline: queue a rehearsal scan, replay after reconnect → two distinct admissions.
5. Countdown card ticks correctly across timezone change and midnight rollover.
6. Home / Event / Pass / History screens show both occasions consistently.
7. Photo upload + readiness reminder dismiss on device network conditions.
8. Torch / permission / gate-sheet regressions (existing Phase 14/15 checklists).

---

## 9. External dependencies and unresolved blockers

- **F3 broadcast / SMS / push: BLOCKED.** No delivery implementation exists; readiness
  reports it honestly as not working (fail-closed — never a fake "sent" state).
- **F4 email: BLOCKED but fail-closed.** `LGU_EMAIL_MODE` defaults to a non-sending
  mode; verification/resend flows never claim delivery they cannot perform.
- **University configuration required (not invented):** guest limits, eligibility rules,
  ticket allocation policy.
- Expo/EAS device builds and store distribution remain external (unchanged).

---

## 10. Final release readiness: **NO-GO**

Code-level readiness for the annual-cycle feature is complete and green (backend 42/42,
mobile 36/36, tsc 0, lint 0 errors), but production readiness stays **NO-GO** on the
carried-forward evidence:

- **F3 (broadcast) and F4 (email) remain BLOCKED** — external delivery does not exist
  and is not simulated.
- **Physical Android verification has not occurred** — §8 checklist outstanding.

Integrity: HEAD unchanged (`298c272d53485ba4473c2defe72db70c02733a2c`), 0 stashes, no
reset/commit/push/deploy performed, production `app/lgu.db` byte-for-byte untouched
(278528 bytes, SHA-256
`820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` — verified by the
acceptance suite's boundary check and re-checked at phase end).
