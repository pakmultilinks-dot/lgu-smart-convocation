# Phase 27 — Critical Security and Lifecycle Defect Closure

**Scope.** The four auditable FAILs carried out of the Phase 26 final
acceptance audit, closed in the order the directive set — both credential/data
exposure paths first (C2, C3), then the lifecycle defect (D3) and the silent
device-role switch (E3).

**Non-negotiable rules observed:** no reset / clean / stash / revert / amend /
commit / push / deploy; the production `app/lgu.db` was never opened as a test
database and was re-verified byte-identical at the end; authentication, role
authorization, signed-QR validation, admission uniqueness, rate limits and
audit history were never weakened to make a screen pass; no legitimate
functionality was deleted to remove an exposed route; no finding is labelled
fixed merely because a guard was added — every claim below is backed by a test
that also rejects the old insecure contract; no test is claimed as passed
unless it actually ran and passed.

**Production readiness: NO-GO** (reasons in the closing section).

**Verification-method legend**
- `TEST` — automated test ran and passed against a disposable database.
- `SOURCE` — enforced by reading the shipped source (no device available).
- `CODE` — code inspection / type-check only.
- `ANDROID` — requires a physical device; **not** claimed anywhere below.

---

## Verdict

| ID | Finding | Status | Evidence |
|----|---------|--------|----------|
| C2 | `GET /guests` rendered every guest's name, phone and host into public page source | **FIXED** | `TEST` 52 + 24 + 39 checks |
| C3 | `/guests/<gid>/pass` and `/api/guest-pass/<id>` minted a signed pass for any enumerable id | **FIXED** | `TEST` 52 + 24 + 39 checks |
| D3 | Every convocation reported `bucket="active"` forever; the `past` bucket was unreachable | **FIXED** | `TEST` 27 + 75 checks |
| E3 | Settings → switch mode cleared the stored mode so the picker skipped its confirm step | **FIXED** (source-verified only) | `SOURCE` 18 + 39 checks, `CODE` tsc 0 / lint 0 |

## Initial state (recorded before any change)

- HEAD `298c272d53485ba4473c2defe72db70c02733a2c`, branch `main`, stashes 0,
  186 dirty/untracked paths (all preserved).
- Production `app/lgu.db`: size **278528**, SHA-256
  **820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F**.

---

## C2 — The guest roster was public (FIXED)

**Root cause.** `GET /guests` called `models.all_guests()` and rendered the
whole roster — name, phone, host name and host roll number — into the HTML.
The page was the walk-up registration shell, so it carried no credential, and
an anonymous caller could enumerate every invited guest by refreshing it.

**Fix.**
- `app/web/routes.py`: `GET /guests` now renders **only** the registration
  form (no guest rows, no roster variable). The directory moved to a new
  `GET /guests/directory`, gated by `_require_web_admin()`, rendering
  `models.guest_directory()` — the minimum projection the desk needs, with no
  `qr_id` and no `created_at`.
- `app/web/templates/guests.html` stays a single shared template and now
  branches: `{% if guests is defined %}` (roster, staff only) `{% elif
  is_staff %}` (link to the directory) — so the public shell never receives the
  rows at all.
- `app/models.py`: `guest_directory()` is now documented as **the only roster
  projection any route may serve**. `all_guests()` (full `g.*`, including
  `qr_id`) is deliberately **kept** — the rules forbid removing legitimate
  functionality — but it no longer has a route caller. Re-exposing it would
  put the credential back in page source, which is exactly what C2 closed.
- `app/web/routes.py` `GET /api/guests` was already scanner-gated in Phase 26C
  and now serves `guest_directory()` instead of `all_guests()`.

**Result:** `app/scripts/test_phase27_guest_pass_authorization.py` —
**52 checks, 0 failures** (`TEST`); `test_phase26c_guest_list_security.py` —
**24 checks, 0 failures** (`TEST`); `test_phase20_authz_matrix.py` —
**39 checks, 0 failures** (`TEST`).

---

## C3 — An enumerable id minted a signed pass (FIXED)

**Root cause.** `/guests/<gid>/pass` (HTML) and `/api/guest-pass/<id>` (JSON)
looked the guest up by a plain integer and returned
`ids.make_payload(qr_id)` — the signed `LGU1:<qr_id>:<hmac>` bearer artefact
that the scanner accepts for admission. Ids are dense integers starting at 1,
so anyone could walk `1, 2, 3 …` and harvest working entry credentials. A bare
`qr_id` is an *identifier*, not a credential; handing out a payload signed
*from* it is what turned enumeration into an admission bypass.

**Fix.**
- `app/ids.py`: new guest-scoped print capability — `make_print_token(gid,
  ttl_seconds)` / `verify_print_token(token, gid)`, HMAC-SHA256 over
  `PRINT:<ID_VERSION>:<gid>:<expires>` (first 20 hex chars), formatted
  `<gid>.<expires>.<sig>`. It is bound to **one** guest and **expires**; the
  TTL is deliberately not clamped so an expired token is testable.
- `app/config.py`: `GUEST_PRINT_TTL_MINUTES` from `LGU_GUEST_PRINT_TTL_MINUTES`,
  default **1440**.
- `app/web/routes.py`: new `_guest_print_allowed(gid)` accepts, in order — the
  registrant's own `session["guest_print"]` capability (verified, not
  trusted), an `X-Print-Token` header carrying that capability, a signed-in
  admin session, or a live scanner session. `POST /guests` (and
  `POST /api/guests`) mint the capability into the registrant's session /
  response body so a guest can still read back the pass they just registered
  for. **The token is never placed in a URL** — Werkzeug logs query strings.
- `guest_pass(gid)`: bounds check 404 → **`_guest_print_allowed` 401 →
  lookup 404**, so the 401/404 split cannot be used as an oracle for which
  guest ids exist.
- `api_guest_pass(gid)`: same gate, answering
  `{"ok": false, "code": "guest_pass_forbidden"}`.
- `mobile/src/api/client.ts` `fetchGuestPass` and `scripts/api-test.mjs`
  `guestPass` now ride the scanner session, matching the mobile app.

**Result:** the same three suites above — **52 / 24 / 39 checks, 0 failures**.

### Contract tests corrected, not weakened

| Suite | Old contract | Corrected contract |
|-------|--------------|--------------------|
| `test_phase26c_guest_list_security.py` | asserted the single-guest pass "stays public" with HTTP 200 | asserts an enumerable gid alone gets **401**, the refusal leaks **no signed payload**, and it uses the `guest_pass_forbidden` code; the signed payload is only reachable with the print token or a scanner session (**24 checks**) |
| `test_phase20_authz_matrix.py` | listed `main.api_guest_pass GET` and `main.guest_pass GET` in the PUBLIC allowlist | both moved out; `/guests` is justified as "public registration shell, renders the form only, no guest data"; four step-4 probes added for `/guests/directory`, `/guests/1/pass`, `/api/guest-pass/1`, `/api/guests` (**39 checks**) |
| `scripts/layout-p7-source-test.mjs` (E3) | pinned the fail-open guard `if (current && mode !== current)` | pins the shared fail-closed rule `needsModeConfirmation(current, mode)` (**39 checks**) |

No assertion was deleted to make a suite pass; each one now rejects the old
insecure behaviour instead of accepting it.

---

## D3 — Convocations never left the "active" bucket (FIXED)

**Root cause.** `models` wrote `convocations.status` once, as `'planned'`, and
**no route ever updates it** — the only `UPDATE ... SET status` statements in
the app target `convocation_registrations`, `convocation_passes`,
`announcements`, `import_batches` and `medalist_import_batches`. There is also
no admin status-transition screen (`exam_event_routes.py` only offers
`event_save`, `event_publish`, `event_create`, `event_activate`). Because
`convocation_history` bucketed on `status in ACTIVE_STATUSES`, *every*
convocation stayed `active` forever and the `past` bucket was unreachable — a
live "past convocations" list that could never show a past convocation.

**Fix — pure derivation, never a write.** Per the rule "do not update state as
a side effect of a read request" and "don't invent a lifecycle", nothing is
stored and no new status value is introduced. `app/convocation_history.py`
gains a pure `lifecycle(status, pub)` returning `(bucket, phase)`:

- a staff-declared terminal status (`completed` / `archived`) is authoritative
  and always wins → `("past", <status>)`;
- otherwise the event has ENDED only when the **published** snapshot's
  `confirmed_date or expected_date` is before today **in the portal timezone**
  (`ev.days_until`, `DISPLAY_TZ = Asia/Karachi`) → `("past", "ended")`. A date
  of today still counts as running, and only the announced convocation date
  counts — a rehearsal date alone does not prove the event is over;
- no usable date (never announced, unpublished draft, legacy full-ISO stamp or
  malformed string) → we cannot say. The entry reports `("active",
  "undated")` and stays in the live list rather than being falsely called past,
  so the uncertainty is **exposed rather than guessed at**.

`_entry()` computes `bucket, phase = lifecycle(conv_status, pub)` and the
payload now carries an additive `"lifecycle"` key beside the unchanged
`"bucket"`. `mobile/src/api/passApi.ts` types `bucket: "active" | "past"` and
`app/(student)/history.tsx` filters on `e.convocation.bucket`, so both keep
working unchanged; `lifecycle` is additive and type-safe.

**Read-only proof.** `app/scripts/test_phase27_convocation_lifecycle.py`
(**27 checks, 0 failures**) hashes the temp database file, counts audit rows,
captures convocation rows and stored statuses, and records `PRAGMA
user_version` — all byte-identical across two history reads.

**Result:** `test_phase27_convocation_lifecycle.py` **27/27** and the
regression `test_phase11_pass_history.py` **75/75** (its seeded convocation has
a future published date and is still `bucket == "active"`).

---

## E3 — One stray tap silently changed the device role (FIXED)

**Root cause.** `SettingsScreen.switchMode` called `clearAppMode()` *before*
navigating to the picker. The picker's I21 guard was
`if (current && mode !== current)` — with `current === null` after the clear,
the guard fell through and `commit()` ran on the first tap. The
Confirm/Cancel bar (33-QA I21) was therefore skipped on the most common route
into the picker: the device role changed on one stray tap, with no
confirmation and no authentication.

**Fix — one shared rule that fails closed.**
- `mobile/src/store/appMode.ts`: new
  `needsModeConfirmation(current, next) → current !== next`. Confirmation is
  required unless the device is **provably** already on `next`; an unknown
  current mode (`null` — cleared, wiped, erroring or first run) asks as well.
- `mobile/app/mode-picker.tsx`: the guard now calls that shared rule, so the
  picker cannot be walked past by any entry point arriving with nothing
  stored. `commit()` is unchanged and remains the **only** writer of the
  stored mode: it writes (`await setAppMode(mode)`) *then* navigates
  (`router.replace`).
- `mobile/src/screens/SettingsScreen.tsx`: `switchMode` navigates **only** —
  the stored mode is left intact so the picker can compare against it and
  confirm an actual change.

Because the rule is shared and lives in the store module rather than in the
screen, a second entry point cannot bypass the first: any caller that reaches
`pick` still goes through the same comparison, and the only path that
commits is the confirmed one.

**Result:** `mobile/scripts/phase27-mode-switch-test.mjs` — **18 checks, 0
failures** (`SOURCE`), covering the fail-closed rule; `commit` writing before
navigating and being the picker's only `setAppMode`; Cancel touching only
pending state; Settings, launch, student-home and student-welcome all reaching
the picker with **no** `clearAppMode`; LiveBoard's single `clearAppMode`
sitting inside `finishExit`, which is only reachable after `verifyAdminPin`;
and the picker importing no auth/session module. Plus
`layout-p7-source-test.mjs` — **39 checks, 0 failures**. Gates:
`npm run tsc` → **0**, `npm run lint` → **0**.

**Honest limitation.** These are `SOURCE`-level checks. No Android device or
emulator was available in this environment, so the physical Confirm → mode-changed
tap-through has **not** been verified on hardware. That is stated rather than
papered over; `ANDROID` verification remains outstanding.

`LiveBoardScreen.finishExit()` still clears the mode, but only after an armed
confirm **and** a valid admin PIN — an authenticated exit flow, documented as
deliberate, not a silent bypass.

---

## Regression evidence (everything re-run, all green)

**Backend** — **40 of 40** `app/scripts/test_*.py` suites re-run from `app/`
against their own disposable databases: **every suite exit 0, `FAILED=` empty**.

| Suite | Result |
|-------|--------|
| `test_phase27_guest_pass_authorization.py` (new) | 52 checks, 0 failures |
| `test_phase27_convocation_lifecycle.py` (new) | 27 checks, 0 failures |
| `test_phase26c_guest_list_security.py` | 24 checks, 0 failures |
| `test_phase20_authz_matrix.py` | 39 checks, 0 failures |
| `test_phase11_pass_history.py` | 75 checks, 0 failures |
| `test_phase13_e2e_acceptance.py` | 53 checks, 0 failures |
| `test_phase14_scanner_access.py` | pass — "production database untouched" |
| `test_phase16_lifecycle.py` | 52 checks, 0 failures |
| `test_phase17_cross_role_acceptance.py` | 156 checks, 0 failures (7 steps) |
| `test_phase19_scanner_management.py` | 105 checks, 0 failures |
| `test_phase20_config_audit.py` | 84 checks, 0 failures |
| `test_phase20_backup_restore.py` | 40 checks, 0 failures |
| `test_phase20_migration_rehearsal.py` | 51 checks, 0 failures |
| `test_phase10_readiness.py` | 52 checks, 0 failures |
| `test_phase12_qr_scanner.py` | 41 checks, 0 failures |
| `test_exam_dashboard.py` | 31 checks, 0 failures |
| `test_medalist_management.py` | 55 checks, 0 failures |
| `test_event_announcements.py` | 58 checks, 0 failures |
| `test_convocation_migration.py`, `test_exam_auth.py`, `test_exam_registration.py`, `test_phase18_residual_closure.py` | pass |

**Mobile** — gates `npm run tsc` = **0** and `npm run lint` = **0**; source
tests: `phase27-mode-switch-test.mjs` 18/18, `layout-p7-source-test.mjs`
39/39, `db-isolation-test.mjs` 29/29 (it drives `api-test.mjs` end-to-end and
re-stamps the production database), and 33 further `scripts/*.mjs` suites all
pass.

**One pre-existing mobile source-test failure was reported honestly and was
NOT fixed here:** `student-screens-test.mjs` failed **S8 — "profile photo is
fetched with the auth header (owner-only route)"** (38 checks, 1 failure). The
check demanded the literal `studentApi.photoSource(token)` in
`app/(student)/profile.tsx`, while the screen calls
`studentApi.photoSource(load.token)`. Both files were outside this phase's
priority list and neither was touched by Phase 26 or 27 — the assertion was a
stale string pin, not a security regression, and the underlying call already
passed the token. Left as an open finding rather than silently re-pointed.
**Resolved in Phase 28** (concern 5 below): the assertion was upgraded to a
behavioural contract — the endpoint must carry `headers: auth(token)` and the
call site must pass the session token — and the suite now passes 39/39.

---

## Public guest surface that remains **by design**

These are intentionally anonymous, and none of them discloses an existing
guest's data:

| Route | Method | Returns to an anonymous caller | Why it must stay public |
|-------|--------|--------------------------------|--------------------------|
| `/guests` | GET | the registration **form only** (`name`, `phone`, `host_roll_no` fields; no rows) | a walk-up guest has no credential yet |
| `/guests` | POST | redirect to *their own* pass; mints their own `guest_print` capability | the guest has nothing to present before registering |
| `/api/guests` | POST | `{ok, gid, payload, print_token}` for the guest **just created** | same kiosk flow for the Expo app |
| `/api/search` | GET | name lookup for the kiosk | pre-existing public kiosk contract (Phase 20 matrix) |
| `/api/health`, `/api/gates`, `/api/config`, `/api/feed`, `/api/announcements`, `/api/gates/...` read paths | GET | liveness, gate labels, public config, feed, announcements | public product surface, no guest or student data |

Everything else guest-shaped is now gated: `GET /guests/directory` (web admin),
`GET /api/guests` (scanner session), `GET /guests/<gid>/pass` and
`GET /api/guest-pass/<id>` (print capability, scanner or admin session).

## Remaining concerns — all five dispositioned in Phase 28

Recorded here as they stood at the end of Phase 27 (under a heading that
over-classified them as "endpoint-authorization" — see the correction below),
with their Phase 28 disposition. Full evidence in
`PHASE28_AUTHORIZATION_REMEDIATION_REPORT.md`. Classification after the
Phase 28 reconciliation audit: **1 is a genuine endpoint-authorization
fix**, 2 and 3 are client UX fixes, 4 is a review correction with no code
change, and 5 is a test-contract fix. None of the five remains open.

1. **`GET /api/settings` was ungated** (`app/web/routes.py`), returning the
   site settings JSON to anonymous callers. It was not in the Phase 27
   priority list and carries no guest/student records, so it was left
   untouched — but it is an authorization gap worth closing before release.
   → **CLOSED (Phase 28).** The read now goes through the same
   `_require_admin_pin()` as the write. Being exact about what this does and
   does not buy: at the time of the audit **all six fields were already
   published** by the anonymous `GET /api/config`, so the ungated read leaked
   nothing uniquely secret. The defect was structural — `PUT /api/settings`
   accepts any key in `database.SETTING_KEYS` while `GET` served all of them,
   so an operational key added later would have been public the moment it was
   written. Gating the read makes "protected" the default for a key nobody has
   classified yet, and puts both halves of one resource under one policy.
   Proven by a negative control: with the gate removed the new suite fails 8
   checks (including anonymous, wrong-PIN, scanner, bearer and staff reads
   all returning 200); restored, it passes 34/34.
2. `HomeScreen.tsx` still toggles between the entry and exit display without a
   confirmation step (E3's rule is scoped to the **device role**, not this
   display toggle).
   → **CLOSED (Phase 28).** The toggle is gated by
   `needsScanModeConfirmation()`, the same fail-closed shape as E3's
   `needsModeConfirmation()`. The tap only arms a pending mode; nothing is
   persisted until the operator confirms, so one stray tap can no longer flip
   a gate from admitting to releasing guests.
3. `event.tsx`'s venue section has no "Not announced" placeholder when the
   field is empty.
   → **CLOSED (Phase 28).** The section now always renders and shows
   `Not announced` when no venue is published, matching the date rows.
4. `scanResultLogic.ts` computes an `.action` field that no consumer reads.
   → **REVIEWED — no code change (Phase 28).** The field is typed, used by
   the scanner logic suite, and deliberate: the **render** derives its Entry/
   Exit label from the device's current `mode` rather than the scanned text,
   so a stale `.action` can never disagree with what the operator sees. The
   `.action` value is a classification hint carried for callers, not dead
   code by accident. The earlier wording ("no consumer reads") was imprecise —
   the scanner logic tests read it. Left as-is; noted for accuracy.
5. The stale `student-screens-test.mjs` S8 assertion above.
   → **CLOSED (Phase 28).** Upgraded from a literal string pin to a
   behavioural contract; suite passes 39/39.

## External delivery and configuration blockers — still BLOCKED

- **F3 broadcast / SMS / push: BLOCKED.** There is no delivery implementation.
  `config.BROADCAST_MODE = real` is a configuration state, not an SMS gateway,
  and `docs/phase34-product-reset/PROBLEMS.md` P-19 is still OPEN. No fix was
  attempted in Phase 27 and none is claimed.
- **F4 email: BLOCKED but fail-closed.** `LGU_EMAIL_MODE` defaults to
  `disabled`, `emailer.py` refuses to send, and `student_routes` answers 503
  rather than silently dropping. Correctly refusing rather than silently
  "succeeding" is not the same as working.

Neither blocker was weakened or faked to improve a verdict.

## Git and production database integrity (re-verified at the end)

- HEAD unchanged: `298c272d53485ba4473c2defe72db70c02733a2c` on `main`;
  stashes **0** (none created, none popped).
- No commit, push, stash, reset, revert or amend was performed; all pre-existing
  tracked modifications, untracked files and unfinished work are preserved
  (tracked dirty paths 186 at Phase 27 start → 192 at its end → **196** now —
  the three Phase 28 source files plus the Phase 28 report, none lost;
  `app/lgu.db` is gitignored and excluded from this count).
- The two pre-existing dev servers (PIDs 7064 and 8620) were left running and
  untouched throughout.
- Production `app/lgu.db`: size **278528**, SHA-256
  **820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F** —
  byte-identical to the state recorded before Phase 27 and before Phase 28
  (Git also reports it unmodified). Every backend suite ran its own
  before/after stat-stamp, and `db-isolation-test.mjs` re-stamped it across a
  full `api-test.mjs` run.
  *Note:* the mtime_ns the Phase 28 start log printed (`639272577218392785`)
  was captured in a different time-encoding than Python's `st_mtime_ns`
  (`1791660921839278500`) for the same file; the two share the identical
  sub-second component (`…218392785`), confirming it is a representation
  artefact of the capture command, not a write. Size, SHA-256 and the Git
  diff are authoritative and all agree the file was never written.

## Production readiness: **NO-GO**

C2, C3, D3 and E3 are closed with tests that reject their old contracts, but
readiness stays NO-GO on the remaining evidence:

- **F3 (broadcast) and F4 (email) remain BLOCKED** — external delivery does not
  exist and cannot be demonstrated.
- **E3 is source-verified only.** No physical device or emulator was available,
  so the confirm-before-role-change flow has not been exercised on hardware.
- **All five carried concerns** — the ungated `GET /api/settings` (the one\n  genuine **endpoint-authorization** defect), the HomeScreen toggle (client\n  UX), the venue placeholder (client UX), the `scanResultLogic.ts` `.action`\n  characterization (report wording) and the stale S8 assertion (test\n  contract) — are **dispositioned in Phase 28** — see\n  `PHASE28_AUTHORIZATION_REMEDIATION_REPORT.md`. That is a Phase 28 status;\n  this Phase 27 verdict was written before that work and is intentionally\n  left describing the state as of Phase 27.

The Phase 26 audit's two other findings — **F3 and F4** — were carried forward
unchanged, as directed. This report closes C2, C3, D3 and E3 only.
