# Phase 28 — Remaining Authorization Closure

**Scope.** The five concerns carried out of the Phase 27 report's
"Remaining endpoint-authorization concerns (open)" list, in the order the
directive set — starting with `GET /api/settings` — plus the stale mobile
source-test S8 failure, full regressions, and reports.

**Classification (corrected by read-only reconciliation audit).** Only
concern 1 was an actual **endpoint-authorization** defect. Concerns 2 and 3
are **client UX** fixes (a missing confirmation step and a missing placeholder,
neither involving any server route or credential), concern 4 was a
**report-wording** item resolved by review with no code change, and concern 5
is **test hygiene** (a stale assertion over already-correct behaviour). They
were carried under an "endpoint-authorization" heading in the Phase 27 report
that over-classified them; all five items are dispositioned below with their
true nature stated. No commit, push, stash, reset, revert or deploy was
performed; the production `app/lgu.db` was never opened as a test database and
is re-verified byte-identical at the end.

**Non-negotiable rules observed:** every issue is judged on behaviour, not on
whether a route returns 401 or a test was edited; no test was weakened to pass
— where only an assertion was stale it was replaced with a meaningful
behavioural contract; every suite was run before and after and the actual
result is reported; production readiness stays **NO-GO** until the remaining
security, provider-configuration and physical Android acceptance gates are
resolved; unresolved items are listed as **FAIL** or **BLOCKED**, never
silently dropped.

**Verification-method legend**
- `TEST` — automated test ran and passed against a disposable database.
- `SOURCE` — enforced by reading the shipped source (no device available).
- `CODE` — code inspection / type-check only.
- `ANDROID` — requires a physical device; **not** claimed anywhere below.

---

## Verdict

| # | Concern (as carried from Phase 27) | Status | Evidence |
|---|-------------------------------------|--------|----------|
| 1 | `GET /api/settings` served the settings JSON to anonymous callers | **FIXED** | `TEST` 34 checks + negative control (8 fail with the gate removed) |
| 2 | `HomeScreen.tsx` toggled Entry/Exit with no confirmation | **FIXED** (source-verified only) | `SOURCE` 35 checks, `CODE` tsc 0 / lint 0 |
| 3 | `event.tsx` venue had no "Not announced" placeholder | **FIXED** | `SOURCE` 35 checks, `CODE` tsc 0 / lint 0 |
| 4 | `scanResultLogic.ts` `.action` "never read" | **REVIEWED — no change** (report wording corrected) | `SOURCE` 35 checks |
| 5 | Stale `student-screens-test.mjs` S8 assertion | **FIXED** (test upgraded, not weakened) | `TEST` 39 checks, 0 failures |

**Regression evidence:** all **41** backend suites pass (`FAILING=0`), all
**35** mobile source-test suites pass (`FAILING=0`), `npm run tsc` = 0,
`npm run lint` = 0.

---

## Initial state (recorded before any change)

- HEAD `298c272d53485ba4473c2defe72db70c02733a2c`, branch `main`, stashes 0,
  192 dirty/untracked paths (all preserved).
- Production `app/lgu.db`: size **278528**, mtime_ns as printed by the capture
  command `639272577218392785`, SHA-256
  **820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F**.

---

## 1 — `GET /api/settings` was ungated (FIXED)

### What was actually wrong (and what was not)

Reproduced **before** the fix against a disposable database:

```
ANONYMOUS GET /api/settings -> 200
FIELDS: ['convocation_datetime', 'convocation_name', 'convocation_year',
         'expected_attendance', 'university_name', 'venue']
```

Being exact about the impact: **all six fields were already published** by the
anonymous `GET /api/config` (`models.app_config_payload()`), which is the
documented public configuration endpoint for the kiosk, the landing page and
mobile connectivity discovery. So the ungated read leaked nothing *uniquely*
secret — a response being 200 is not proof it is unsafe, and equally a 401 is
not proof the old one was leaking a secret.

The defect was **structural**: `PUT /api/settings` accepts any key in
`database.SETTING_KEYS`, while `GET /api/settings` served all of them with no
gate. The settings table is administrator-editable, so an operational key
added later would have been public the moment it was written. The read half of
one resource was governed by a different policy than its write half, and the
two halves could drift apart again.

### The fix

`app/web/routes.py` — `api_get_settings()` now calls the **same**
`_require_admin_pin()` helper as `api_put_settings()`, and the two routes are
kept adjacent in the file so they cannot silently diverge:

```python
@bp.route("/api/settings")
def api_get_settings():
    denied = _require_admin_pin()
    if denied:
        return denied
    return jsonify(database.get_settings())
```

- **Protected by default:** an unclassified key is now refused on read unless
  it is explicitly published elsewhere. Read-authz matches write-authz.
- **Public configuration unchanged:** `GET /api/config` still answers
  anonymously with the same event identity — no legitimate workflow was gated,
  and no IP was hard-coded anywhere (connectivity discovery is untouched).
- **No new secret:** the gate is the existing PIN path with its existing
  rate limit; nothing was added to the payload.

### Client half

`mobile/src/api/settingsApi.ts` — `getSettings()` now attaches the stored
`X-Admin-Pin`, exactly as `updateSettings()` already did. This is safe because
`AdminGate` re-verifies the stored PIN against `POST /api/admin/verify` before
it mounts `AdminScreen`, and `unlock()` persists the PIN only after the server
accepts it — so a valid PIN is always present at call time, and a stale or
rejected PIN keeps the gate closed (no 401 ever surfaces to the operator). The
module's header comment was corrected: the public Live Board reads
`/api/config` via `fetchAppConfig`, not this admin module.

### Test-contract updates (not weakening)

Three existing tests asserted the old ungated contract and were updated to the
new one, each keeping its original intent:

| Test | Old assertion | New assertion |
|------|---------------|---------------|
| `test_phase20_authz_matrix.py` | `api_get_settings` in the `PUBLIC` allowlist | removed from `PUBLIC`; added to step 4's protected list as `("admin settings read", "/api/settings", "GET")` |
| `test_phase17_cross_role_acceptance.py` | `/api/settings` in the "LAN-trust GETs stay public" tuple | removed; replaced with an explicit `401` check |
| `test_phase8_integration.py` | `client.get("/api/settings")` | `client.get("/api/settings", headers={"X-Admin-Pin": config.ADMIN_PIN})` |
| `mobile/scripts/data-truth-test.mjs` | `api(B1, "GET", "/api/settings")` | `api(B1, "GET", "/api/settings", { pin: ADMIN_PIN })` |

### New suite — `app/scripts/test_phase28_authorization_closure.py` (34 checks)

Proves denial **and** that legitimate workflows still work, on an isolated
temp database:

- anonymous `GET` → **401** with no settings keys in the body and the standard
  `Administrator access required.` contract;
- wrong-PIN `GET` → **401**; a signed-in **scanner**, a **bearer** credential
  and a **web staff session** all → **401** (wrong-role probes);
- correct-PIN `GET` → **200** with the key set **exactly** equal to
  `database.SETTING_KEYS`, and no field matching `pin|secret|token|password|
  hash|salt|key`;
- anonymous and wrong-PIN `PUT` → **401**, correct-PIN `PUT` → **200**, and
  the write is visible to the next authorized read (write path unchanged);
- repeated wrong-PIN reads are throttled **429** (the read inherits the
  write's rate limit);
- `GET /api/config` and `GET /api/health` still answer **200** anonymously
  with the same public event identity (public workflow preserved);
- Phase 27 contracts still hold: anonymous `/guests/directory` → 401,
  anonymous `/api/guests` → 401, anonymous `/api/guest-pass/<id>` → 401 with
  no signed payload, anonymous `/guests/<id>/pass` → 401, anonymous
  `POST /api/guests` → **200** (public registration preserved), scanner and
  staff reads → 200;
- production DB stat-stamp unchanged and no phase-28 row written to it.

### Negative control (the fix is proven, not assumed)

With the gate temporarily removed, the same suite **fails 8 checks** —
anonymous, wrong-PIN, scanner, bearer and staff reads all return **200** and
the rate-limit check sees `[200 × 7]`. Restored, it passes **34/34**. The
suite genuinely detects the defect it claims to close.

---

## 2 — HomeScreen Entry/Exit toggle had no confirmation (FIXED, source-verified)

`mobile/src/screens/HomeScreen.tsx` committed every tap straight to storage —
one stray tap silently turned the device from admitting guests to releasing
them. E3's Phase 27 rule was scoped to the **device role**, not this display
toggle.

**Fix:** a shared, fail-closed rule `needsScanModeConfirmation(current, next)`
in `mobile/src/store/appMode.ts`, deliberately the same shape as E3's
`needsModeConfirmation` so the two surface switches cannot drift apart:

- the tap only **arms** a pending mode (`setPendingMode`); nothing is written
  to storage;
- a confirmation prompt names the direction being entered and offers
  Cancel / Switch;
- only `confirmModeChange` calls `persistScanMode`, so cancelling leaves the
  current direction and its persisted value untouched;
- `current === next` (re-tap) is not a change and confirms nothing; an unknown
  stored direction (`null`) asks as well — fail-closed.

Direction is an operating choice, not a credential: this gate stops an
accidental switch, it does not grant access. `CODE` tsc 0 / lint 0.

---

## 3 — `event.tsx` venue had no "Not announced" placeholder (FIXED)

`mobile/app/(student)/event.tsx` dropped the entire Venue section when
`event.venue` was empty, so a student could not tell "not yet published" from
a bug. The section now always renders and shows `Not announced` when the field
is empty — matching the existing date rows (`Not announced` /
`Not officially confirmed yet`). `SOURCE` pinned in the Phase 28 suite.

---

## 4 — `scanResultLogic.ts` `.action` "never read" (REVIEWED — no change)

The Phase 27 wording was imprecise. Review of the actual consumers:

- `mobile/src/scanner/scanResultLogic.ts` types `action?: "Entry" | "Exit"` on
  the classification result and populates it from the scanned text.
- `mobile/scripts/scanner-logic-test.mjs` **asserts** `.action` — it is a
  typed, test-asserted field of the classification contract, not dead code.
- The render path (`mobile/src/scanner/ScannerResult.tsx`) deliberately
  derives its label from the **device mode**
  (`const action = mode === "exit" ? "Exit" : "Entry"`), never from the
  payload's `.action`.

**Conclusion:** a display-accuracy nuance with **no authorization impact** —
the classifier labels from the server title while the UI shows the device
mode, and the UI is the operator's source of truth. Deleting the field would
remove tested contract surface for no security gain. **No code change**; the
Phase 27 report's characterization was corrected. Pinned in the Phase 28
suite so the reviewed state is reproducible.

---

## 5 — Stale `student-screens-test.mjs` S8 (FIXED — test upgraded, not weakened)

**Before:** `38 checks, 1 failure` — `FAIL S8: profile photo is fetched with
the auth header (owner-only route)`. The check pinned the literal source text
`studentApi.photoSource(token)`; the screen actually calls
`studentApi.photoSource(load.token)`. The app behaviour was already correct
(the token is passed and `headers: auth(token)` is attached) — the assertion
was a stale string pin.

**Fix (in the test, per the directive):** replaced the brittle literal with a
behavioural contract — the endpoint must be declared as
`photoSource(token: string)`, must attach `headers: auth(token)`, the call
site must pass the **session token** (`load.token`), and the result must reach
`setPhoto(`. This is stricter than the old pin in the ways that matter (it
checks the header and the token source, not just a name) while no longer
breaking on a harmless variable rename.

**After:** `39 checks, 0 failures` (`EXIT=0`).

---

## Regression evidence (everything re-run, all green)

**Backend — all 41 suites, `FAILING=0`** (each on its own disposable DB, each
re-stamping production):

| Suite | Result |
|-------|--------|
| `test_phase28_authorization_closure.py` | 34 checks, 0 failures |
| `test_phase27_guest_pass_authorization.py` | 52 checks, 0 failures |
| `test_phase27_convocation_lifecycle.py` | 27 checks, 0 failures |
| `test_phase26c_guest_list_security.py` | 24 checks, 0 failures |
| `test_phase20_authz_matrix.py` | 40 checks, 0 failures |
| `test_phase17_cross_role_acceptance.py` | 157 checks, 0 failures |
| `test_phase11_pass_history.py` | 75 checks, 0 failures |
| `test_phase8_integration.py` | 57 checks, 0 failures |
| `test_phase8_acceptance.py` | 85 checks, 0 failures |
| `test_phase24e_guest_dashboard.py` | 25 checks, 0 failures |
| `test_phase24f_broadcast_authz.py` | 16 checks, 0 failures |
| …and 30 further suites | all `EXIT=0` |

**Mobile — all 35 source-test suites, `FAILING=0`**, including
`phase28-authorization-source-test.mjs` (35 checks),
`student-screens-test.mjs` (39 checks — S8 green),
`data-truth-test.mjs`, `display-admin-auth-test.mjs`, `scanner-logic-test.mjs`
and `ui-35k-source-test.mjs` (39 checks — the `_require_admin_pin` ordering
assertion still holds with the new GET gate in place).

**Type gates:** `npm run tsc` = **0**, `npm run lint` = **0**.

---

## Unresolved concerns — FAIL / BLOCKED

- **F3 broadcast / SMS / push: BLOCKED.** No delivery implementation exists;
  `config.BROADCAST_MODE = real` is a configuration state, not a gateway;
  `docs/phase34-product-reset/PROBLEMS.md` P-19 is still OPEN. Not weakened,
  not faked.
- **F4 email: BLOCKED but fail-closed.** `LGU_EMAIL_MODE` defaults to
  `disabled`, `emailer.py` refuses to send, and `student_routes` answers 503
  rather than silently dropping. Correctly refusing is not the same as working.
- **Original concerns 1–5: all dispositioned, none open.** Stated precisely:
  1 = **CLOSED** (authorization, `TEST`, includes negative control);
  2 = **CLOSED** (client UX confirmation, `SOURCE` only);
  3 = **CLOSED** (client UX placeholder, `SOURCE` only);
  4 = **CLOSED as reviewed — no code change** (report wording corrected);
  5 = **CLOSED** (test contract, `TEST`). Concerns 2, 3 and 5 are not
  authorization defects and are not counted toward authorization closure —
  concern 1 is the only authorization fix this phase made.

---

## Git and production database integrity (re-verified at the end)

- HEAD unchanged: `298c272d53485ba4473c2defe72db70c02733a2c` on `main`;
  stashes **0** (none created, none popped).
- No commit, push, stash, reset, revert or amend; all pre-existing tracked
  modifications, untracked files and unfinished work preserved — tracked dirty
  paths **196** (192 at Phase 28 start + the 3 new Phase 28 files + this
  report, all untracked; `app/lgu.db` is gitignored and excluded from this
  count).
- The two pre-existing dev servers were left running and untouched.
- Production `app/lgu.db`: size **278528**, SHA-256
  **820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F** —
  byte-identical to the state recorded before Phase 28; Git reports it
  unmodified. Every backend suite ran its own before/after stat-stamp.
  *Note:* the start log's mtime_ns (`639272577218392785`) and Python's
  `st_mtime_ns` (`1791660921839278500`) are the same instant in two
  time-encodings (identical sub-second component `…218392785`) — a capture
  artefact, not a write. Size, SHA-256 and the Git diff are authoritative and
  all agree the file was never written.

---

## Production readiness: **NO-GO**

All five carried concerns are dispositioned — the single authorization
defect (concern 1) is closed by a gate that a negative control proves the
suite detects, and concern 5 by a behavioural contract — but readiness stays
**NO-GO** on the remaining evidence:

- **F3 (broadcast) and F4 (email) remain BLOCKED** — external delivery does
  not exist and cannot be demonstrated.
- **Concerns 2 and 3 are source-verified only.** No physical device or
  emulator was available, so the Entry/Exit confirmation and the venue
  placeholder have not been exercised on hardware.
- **Physical Android acceptance** (Phase 15 field validation) is still an open
  gate.

The Phase 26 audit's F3 and F4 findings were carried forward unchanged, as
directed. This report closes concerns 1–5 only.
