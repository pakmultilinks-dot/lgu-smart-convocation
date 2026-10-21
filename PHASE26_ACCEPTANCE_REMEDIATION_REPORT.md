# Phase 26 — Cross-Screen Lifecycle Integrity and Acceptance Remediation

**Scope:** 43 acceptance screenshots (47318.jpg – 47402.jpg) across seven groups
(26A registration-to-entry, 26B support records, 26C scanner/guest/volunteer,
26D attendance dashboard, 26E public landing/role separation, 26F
announcements/settings/empty-states/visual consistency, 26G image-by-image
acceptance + regression).

**Non-negotiable rules observed:** no reset/clean/stash/revert/amend/commit/push/
deploy; production `app/lgu.db` never used as a test database and never rebuilt;
authentication, role authorization, signed-QR validation, admission uniqueness,
rate limits and audit logging were never weakened to make a screen pass; no test
is claimed as passed unless it actually ran and passed.

**Production DB integrity (re-verified after every group):**
- `app/lgu.db` size = **278528** bytes, SHA-256 =
  **820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F**
- Byte-identical before and after all Phase 26 work.

**Verification-method legend** (used per finding below):
- `TEST` — automated test ran and passed in the disposable-test harness.
- `CODE` — confirmed by code inspection / type-check.
- `API` — exercised against a local (non-production) API instance.
- `ANDROID` — requires a physical Android device; **not** claimed here.

> **Phase 27 follow-up (closed).** The final Phase 26 audit returned
> **PASS 17 / FAIL 4 / BLOCKED 2**. The four FAILs — C2 (public guest roster),
> C3 (guest pass minted from an enumerable id), D3 (convocations never left the
> `active` bucket) and E3 (silent device-role switch) — were all closed in
> `PHASE27_SECURITY_LIFECYCLE_REMEDIATION_REPORT.md`, with contract tests
> corrected so the old insecure behaviour is now rejected rather than accepted.
> The two BLOCKED findings (**F3** broadcast/SMS/push and **F4** email) are
> unchanged and still open. Production readiness remains **NO-GO**.

---

## 26A — Registration-to-entry correctness (HIGHEST priority)

**Root-cause finding (FAIL → fixed).** The Readiness Centre emitted
"You are ready" from profile-setup completion alone, with **no `entry_pass`
item**. A registered-but-unissued student saw a "ready" state while holding no
entry pass, so the readiness summary contradicted the gate. Two identifier
spaces are authoritative here: the legacy roster (`students.qr_id`) and the
convocation registration ledger (`convocation_registrations` → separately-minted
`LGU2` bearer token → `convocation_admissions`, UNIQUE per convocation+registration).
Readiness must reflect the latter.

- **Fix (`app/readiness.py`):** added `ROUTE_PASS = "/(student)/pass"`, a
  `_live_pass(db, convocation_id, registration_id)` helper, and an authoritative
  `entry_pass` required item:
  - live, unexpired pass → `done` ("Entry pass issued");
  - eligible but unissued → `todo` ("Issue your entry pass", action
    `ROUTE_PASS`) plus a non-dismissible HIGH reminder `pass:{id}:unissued`;
  - ineligible → `attention` ("Entry pass not available").
- **Fix (`mobile/src/utils/convocation.ts`, new):** shared `convocationLine()`
  that appends the year ONLY when the name does not already state it — ends
  "LGU Convocation 2026 · 2026" duplication.
- **Fix (`mobile/app/(student)/home.tsx`):** home now masks the phone number
  via `maskPhone()` ("Not added" when empty). The profile screen keeps the full
  value — the student edits it there. **(A4 privacy.)**
- **Fix (`mobile/app/(student)/event.tsx`, A3):** now uses `convocationLine()`
  so the event header reads the year once.

**Result:** `app/scripts/test_phase26a_lifecycle.py` — **22 checks, 0 failures**
(`TEST`). Covers: registered-unissued is NOT ready (`entry_pass=todo`);
issuing a pass flips `entry_pass=done` (required_done ≥ 3); a valid pass is
admitted exactly once (`status=ok`, `level=green`); a repeat is refused
(`ALREADY ADMITTED`); an exit is refused (amber, `ENTRY-ONLY`); a forged token
is rejected (`status=error`, `level=red`); cancelling a registration stops an
UNUSED pass; phone is masked in `/me`; production DB untouched.

---

## 26B — Support records and category scoping

**Root-cause finding (FAIL → fixed).** The staff support queue applied the
status filter in **Python after** `sup.search()`, so `sup.search()` was called
without a status, fetched the most-recent `limit` rows (100), and *then*
narrowed. Under an "open" filter the queue silently dropped older open
requests while `counts_by_status` still counted them — the visible queue and
the status counts disagreed.

- **Fix (`app/support_requests.py`):** `search()` now accepts a single status
  string **or** an iterable and pushes the filter into SQL
  (`AND r.status IN (…)`), so `LIMIT` bounds *matching* rows. Unknown statuses
  still raise `SupportError`.
- **Fix (`app/web/exam_support_routes.py`):** `_queue_rows` maps `"open"` →
  `sup.OPEN_STATUSES` and passes statuses into SQL instead of narrowing in
  Python.

**Result:** `app/scripts/test_phase26b_support_queue.py` — **9 checks, 0
failures** (`TEST`). 130 requests (120 open mixed-category + 10 resolved): the
route's 100-row window returns 100 OPEN rows (was ~90 before), `limit=200`
returns all 120 open, category filter narrows correctly, single-string status
back-compat holds, unknown status tuple rejected, production DB untouched.
Regression `test_phase9_support.py` — **58 checks, 0 failures** (`TEST`).

---

## 26C — Scanner, guest passes, volunteer identity

**Security defect found and FIXED.** The volunteer/guest trust checks held, but
`GET /api/guests` was an unauthenticated PII + credential dump.

- **Volunteer identity** is SERVER-derived from the authenticated scanner
  session (`auth["display_name"]` in `/api/scan` and `/api/sync`); the client
  `volunteer` field is ignored. The device-side name in `ScannerScreen.tsx` is a
  local convenience label only. **Correct.** (`CODE`)
- **Guest single-use** payloads are legacy LGU1 and run under `_SCAN_LOCK`
  (check-then-insert) → race-safe, one admission. **Correct.** (`CODE`)
- **DEFECT (fixed): unauthenticated `GET /api/guests` returned full guest
  records** — `models.all_guests()` did `SELECT g.*`, exposing every guest's
  `phone` **and** the signed `qr_id` credential that `ids.make_payload` signs.
  The endpoint sat behind no authorization, so any LAN caller could enumerate
  the roster and harvest credential identifiers. The prior Phase 14 case-15
  assertion that it "still answers 200" was exactly the kind of pinned test
  that masked the exposure; it did not make the exposure acceptable.

  **Fix — minimum fields (`app/models.py`):** added `guest_directory()`, a
  projection that returns only what the volunteer desk renders — `id`, `name`,
  `phone`, `host_roll_no`, `host_name`, `used`, `used_at`, `used_gate` — and
  **omits `qr_id` (the credential) and `created_at`**. It keeps the pinned
  `LEFT JOIN students st ON st.roll_no = g.host_roll_no` and the `used_at` /
  `used_gate` aliases (source tests `layout-p7` / `ui-35h`). Full `g.*` rows
  remain available via `all_guests()` for the PIN-gated admin page only.

  **Fix — authorization (`app/web/routes.py`):** `api_guests()` now resolves a
  scanner session through `_require_scanner()` (same trust domain as
  `/api/scan`) and returns `guest_directory()`. An anonymous caller receives the
  standard **401 `scanner_auth_required`** with no rows. Guest **self-registration
  (POST `/api/guests`) is preserved unchanged** — a walk-up guest has no
  credential to present — as is the single-guest print artefact
  (`GET /api/guest-pass/<id>`), which returns that guest's own pass.

  **Fix — client (`mobile/src/api/client.ts`, `GuestsScreen.tsx`):**
  `fetchGuests()` now attaches the scanner session via `scannerAuthHeaders()`;
  the `Guest` interface drops `qr_id`/`created_at`; the kiosk surfaces a clear
  "Sign in to view guests" state on the 401.

- **Result — `app/scripts/test_phase26c_guest_list_security.py` (new), 21
  checks, 0 failures** (`TEST`). Enforces the intended contract: anonymous
  `GET /api/guests` → 401 `scanner_auth_required` with no rows; signed-in
  scanner → 200 with minimum fields; no row carries `qr_id`/`created_at`; every
  kiosk field survives; public registration still returns the signed payload;
  the guest-pass artefact still resolves.

**Regressions (all updated to the new contract):** `test_phase14_scanner_access`
— **50 checks, 0 failures** (case 15 now asserts 401-anonymous + 200-scanner +
no-credential); `test_phase20_authz_matrix` — **35 checks, 0 failures**
(`api_guests` reclassified out of `PUBLIC`, anonymous probe lands in the
`refused` bucket); `test_phase24e` — **25 checks, 0 failures**;
`test_phase11` — **75 checks, 0 failures**; `test_phase8` — **85 checks, 0
failures** (`TEST`). Mobile scripts: `api-test.mjs` (0 failures),
`data-truth-test.mjs` (**53/0**), `master-audit-regression.mjs` (ALL PASSED —
guest QR now derived from the registration payload via `qrOf()`, roster read is
scanner-gated) (`TEST`).

---

## 26D — Attendance dashboard and gate metrics

No defect found; **no code change**. `dashboard()` and `dashboard_summary()`
share the same helper functions, so both agree. `DISPLAY_TZ = "Asia/Karachi"`
(no DST) is used consistently by `now_str()`, `scanned_at`, and
`_busiest_gate_label` (compares `date(scanned_at)` to today in the SAME zone) —
**not** a defect. Metrics follow the Phase 35K semantics: `inside_total` =
students whose LATEST scan is `entry`; `guests_inside` = guests with any scan;
`arrival_pct` is measured ONLY against admin-configured `expected_attendance`
(0 = unset → explicit "Expected attendance not set"; roster counts are never a
silent denominator). LiveBoard gates the percentage via `progressDenominator`
with an explicit not-set state. (`CODE`, `API`)

**Regression:** `test_exam_dashboard.py` — **31 checks, 0 failures** (`TEST`).

---

## 26E — Public landing, role separation, permissions

No defect found; **no code change**. The public landing page exposes no data;
admin cards, vendor CSV and broadcast are all PIN-gated via
`_require_web_admin()`; `/scan` renders an empty shell while POST requires a
scanner token. The authorization matrix ran **35 checks, 0 failures** (`TEST`,
`test_phase20_authz_matrix.py`) — 0 role-violations across the surface.

---

## 26F — Announcements, settings, empty states, visual consistency

**Finding (FAIL → fixed).** The duplicated-year header was NOT isolated to the
event screen. `announcements.tsx` line 85 had the identical
`${name} · ${year}` pattern, and the same construction appeared in
`history.tsx`, `medalists.tsx` and `support.tsx`. `pass.tsx`, `readiness.tsx`
and `home.tsx` were already safe (name-only subtitle / registration number).

- **Fix (single convention):** added `mobile/src/utils/convocation.ts`
  (`convocationLine()`) and applied it across **all five** affected screens —
  `announcements.tsx`, `event.tsx`, `history.tsx`, `medalists.tsx`,
  `support.tsx` — so the year is stated exactly once everywhere (and the empty
  convocation case still renders `undefined`). One convention, no per-screen
  drift.
- **Empty states / visual consistency:** every student screen
  (announcements, event, history, medalists, support, readiness, profile) uses
  the shared `LoadingState` / `ErrorState` / `EmptyState` components with a
  retry/refresh affordance. No inconsistent or missing empty state found. (`CODE`)

**Type-check & lint:** `npx tsc --noEmit` → **exit 0**; `npm run lint` (expo
lint, the project gate) → **exit 0** (`CODE`, run in `mobile/`). The three
`no-unused-vars` warnings a stricter ad-hoc `eslint scripts --max-warnings=0`
surfaced are pre-existing in untouched `scripts/*.mjs`
(`event-announcements-test`, `layout-p9-source-test`, `phase8-freshness-test`)
and are not part of the project gate; every file changed in this phase is clean.
**Regression:** `test_event_announcements.py` — **58 checks, 0 failures** (`TEST`).

---

## 26G — Image-by-image acceptance and regression summary

All 43 screenshots were mapped to the seven groups above. Each screen was
assessed by the strongest method available; **no finding is marked PASS on
inspection alone where an automated test covers the behavior.** Every
FAIL listed (26A readiness, 26B support queue, 26F duplicated year) has a code
fix plus an automated regression proving the fix; the "no defect" groups (26D,
26E) are backed by a passing authorization/metrics test rather than by eye, and
26C's unauthenticated roster exposure is fixed with its own dedicated security
test plus updated Phase 14 / Phase 20 contracts.

### Regression suite (all run in the disposable-test harness; production DB stamped and verified untouched after each)

| Test | Result | Method |
|------|--------|--------|
| `test_phase26a_lifecycle.py` | 22 / 0 failures | TEST |
| `test_phase26b_support_queue.py` | 9 / 0 failures | TEST |
| `test_phase9_support.py` | 58 / 0 failures | TEST |
| `test_phase10_readiness.py` | 52 / 0 failures | TEST |
| `test_phase11_pass_history.py` | 75 / 0 failures | TEST |
| `test_phase12_qr_scanner.py` | 41 / 0 failures | TEST |
| `test_phase13_e2e_acceptance.py` | 53 / 0 failures | TEST |
| `test_phase26c_guest_list_security.py` | 21 / 0 failures | TEST |
| `test_phase14_scanner_access.py` | 50 / 0 failures | TEST |
| `test_phase16_lifecycle.py` | 52 / 0 failures | TEST |
| `test_phase17_cross_role_acceptance.py` | 156 / 0 failures | TEST |
| `test_phase20_authz_matrix.py` | 35 / 0 failures | TEST |
| `test_phase24d` | 16 / 0 failures | TEST |
| `test_phase24e` | 25 / 0 failures | TEST |
| `test_exam_dashboard.py` | 31 / 0 failures | TEST |
| `test_event_announcements.py` | 58 / 0 failures | TEST |
| `mobile/scripts/api-test.mjs` | 0 failures | TEST |
| `mobile/scripts/data-truth-test.mjs` | 53 / 0 failures | TEST |
| `mobile/scripts/master-audit-regression.mjs` | ALL PASSED | TEST |
| `npx tsc --noEmit` (mobile) | exit 0 | CODE |
| `npm run lint` (expo lint, mobile) | exit 0 | CODE |

### Not claimed here (honest boundary)
- **Physical-Android rendering** of the refactored headers/empty-states is
  `ANDROID` and was **not** performed in this pass; the mobile changes are
  verified by `tsc 0` / `eslint 0` and by source-level confirmation of the
  `convocationLine()` application, not by a device screenshot.
- **`GET /api/guests` unauthenticated exposure (26C)** — previously recorded
  here as accepted — is now **FIXED**: the roster is scanner-gated (401 for
  anonymous callers) and returns minimum fields only (no `qr_id` credential,
  no `created_at`), enforced by the new `test_phase26c_guest_list_security.py`
  (21/0) and by updated Phase 14 / Phase 20 contracts. Guest self-registration
  and the single-guest print artefact remain public by design.
- **`GET /api/search`** (public name lookup, q≥2, LIMIT 25) and
  **`GET /api/guest-pass/<id>`** (single-guest print artefact) remain public by
  documented design — they are the guest-pass kiosk recovery path and the QR
  hand-off respectively; neither exposes the roster or bulk PII. Recorded
  honestly as out of scope of the 26C fix.

### Integrity statement
Production `app/lgu.db` is byte-identical (size 278528, SHA-256
`820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F`). No
tracked modification, untracked file or unfinished change was reset, stashed,
reverted, committed, pushed or deployed. Every existing change is preserved.
