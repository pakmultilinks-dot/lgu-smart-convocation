# Phase 19 — Authenticated Scanner Administration & Operator Accountability

**Date:** 2026-10-10
**Branch:** `main` · **HEAD:** `298c272d53485ba4473c2defe72db70c02733a2c` (unchanged — nothing committed)
**Scope:** a staff-authenticated scanner management surface inside the existing
Examination Department portal, plus full lifecycle and audit attribution for
scanner accounts.
**Release discipline:** no commit, no push, no deploy, no destructive git, no
production credential change.

---

## 1. What existed before this phase, and what was actually missing

Phase 18's Finding 4 (`[Operational]`) established that scanner PIN
provisioning ownership "remains assigned to operations, not code": every
scanner lifecycle call was written to `audit_log` with `actor = "system"`
because `app/scanner_auth.py` defaulted `actor="system"` and
`app/scripts/manage_scanner_staff.py` never passed one. That was closed by
requiring an explicit `--actor` on every CLI subcommand.

That fix was necessary but it left the underlying product gap open: the only
way to create, gate-assign, reset or disable a scanner account was a shell on
the server host. Phase 19 closes that gap.

**What was genuinely missing at source, verified before any change:**

| Gap | Evidence |
|---|---|
| No management UI of any kind | The only routes touching `scanner_users` were `/api/scanner/login` and the `/api/scan` `/api/sync` consumers. No HTML route listed, created or mutated a scanner account. `docs/PHASE14_FIELD_TEST_GUIDE.md` stated it explicitly: *"There is no admin screen for scanner accounts; these are CLI commands run on the server."* |
| No authenticated actor for scanner lifecycle actions | `staff_required` existed and protected every `/exam/*` page, but nothing in the scanner lifecycle ever used it. |
| No protection against unauthenticated probing of a management surface | `_csrf_guard` returned 403 for any unauthenticated POST. A rejected write was indistinguishable from any other 403 — nothing recorded *that a management attempt had been made*. |
| No credential lifecycle state | `scanner_users` had `pin_hash` and `is_active` and nothing else. There was no way to represent "this account exists but has no usable credential yet", so an account could not be created before the volunteer arrived without inventing a PIN for them. |
| No management history that a human could read | `audit_log` rows existed, but only by grepping a table. |
| No index for the history query | `audit_log` has no index on `action`, so a management-history read scanned the whole table. |

**What already worked and was deliberately left alone:** PIN hashing (scrypt,
from Phase 14), per-account lockout, login rate limiting, session TTL and
revocation, and the server-side gate authorization intersection on `/api/scan`
and `/api/sync`.

## 2. The authorization rule, stated honestly

The spec required implementing *"the smallest defensible authorization rule
without inventing an institutional policy."*

`staff_users` was inspected first. Its schema is `id, username, display_name,
password_hash, is_active, failed_attempts, locked_until, last_login_at,
created_at, updated_at`. **There is no role or permission column.**

Inventing one — say, adding `role = 'scanner_admin'` — would have meant
inventing an institutional policy, and would have silently made every existing
staff account unauthorized on migration. Neither is defensible.

The rule implemented is therefore:

> **Any authenticated, active Examination Department staff account may
> manage scanner accounts.**

This is documented in `app/web/exam_scanner_routes.py`'s module docstring and
in `docs/PHASE14_FIELD_TEST_GUIDE.md` §2a, including the limitation that a
finer-grained permission requires a future schema and policy decision.

An authenticated-but-unauthorized staff account is realized in the test suite
as a **deactivated** staff account: it cannot log in, and deactivating an
account mid-session ends its management access immediately. A live scanner
session is also proved not to be a staff credential.

## 3. Files modified and behaviour changed

| File | Change |
|---|---|
| `app/migrations.py` | **Migration 11.** `ALTER TABLE scanner_users ADD COLUMN credential_established INTEGER NOT NULL DEFAULT 1` and `CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action, id)`. |
| `app/scanner_auth.py` | `VIA_PORTAL` / `VIA_CLI` / `VIA_TEST` provenance tags; `MANAGEMENT_ACTIONS`; `generate_pin()`; `create_scanner(..., pin=None)` pending-credential mode; `revoke_sessions()`; `reset_pin()` returning `was_pending`; a `credential_pending` refusal in `authenticate()`; `list_scanners()` / `get_scanner()` / `history()` read models that never select `pin_hash` or `token_hash`. |
| `app/web/exam_routes.py` | `MGMT_PATH`; `_audit_mgmt_denied()` with a per-client bound; a hook in `_csrf_guard` that records rejected management writes. |
| `app/web/exam_scanner_routes.py` | **New.** `/exam/scanners`, `/exam/scanners/new`, `/exam/scanners/<id>` attached to the existing exam blueprint. |
| `app/web/routes.py` | Imports `exam_scanner_routes` in the blueprint tuple. |
| `app/web/templates/exam/scanners.html` | **New.** Account list + management history. |
| `app/web/templates/exam/scanner_new.html` | **New.** Create form with the three provisioning modes. |
| `app/web/templates/exam/scanner_detail.html` | **New.** Account, sessions, gates, credential, revoke/enable, history. |
| `app/web/templates/exam_dashboard.html` | "Scanner accounts" link in both branches of the Event publishing card. |
| `app/scripts/manage_scanner_staff.py` | `sessions` subcommand; `via=scanner_auth.VIA_CLI` on all mutating calls; `list` prints credential state. |
| `app/scripts/test_phase19_scanner_management.py` | **New.** 18 cases, 105 checks. |
| `app/scripts/test_phase17_cross_role_acceptance.py` | `/exam/scanners` and `/exam/scanners/new` added to the dashboard link allowlist (§6). |
| `docs/PHASE14_FIELD_TEST_GUIDE.md` | Rewritten for the portal path; §4c management runbook added. |

**The three credential-provisioning modes.** A create can be:

1. **PIN left blank** → a PIN is generated, stored only as a scrypt hash, and
   rendered **exactly once** on the next screen. That response is rendered
   directly from the POST and is **never** redirected. A refresh therefore
   re-POSTs, hits the `UNIQUE(username)` constraint, and lands on the
   duplicate-username error page — which renders no secret. Test case 5 proves
   this recovery is impossible.
2. **Staff types a PIN** → stored as a scrypt hash and never echoed back. The
   flow is a normal Post/Redirect/Get.
3. **"Create with no usable credential yet"** → `pin=None`,
   `credential_established = 0`, and `pin_hash` is set to a **real scrypt hash
   of an unverifiable random value**. The account exists and its gates can be
   set, but `authenticate()` refuses it with an audited `credential_pending`
   **without burning the failure budget**. The point of the unverifiable hash
   is that if the guard were ever removed by defect, the failure mode is "wrong
   PIN", never "success".

**Why `DEFAULT 1`.** Migration 11 backfills every pre-existing account as
already provisioned, so nothing already deployed changes behaviour. Only
accounts explicitly created through the pending mode start unusable.

**Session revocation is a separate action from PIN replacement.** Replacing a
PIN invalidates the old PIN immediately (the next auth attempt can only
succeed against the new value) but deliberately does **not** kill live
sessions; `revoke_sessions()` is the explicit action for that, and disabling
the account kills both. This split is documented on the account page and in
the guide because it is an operational decision, not an implementation detail.

**Audit attribution without a migration.** `audit_log` is
`(id, actor, action, detail, created_at)` from migration 2. The free-text
`detail` field carries a `via=portal` / `via=cli` prefix, so no audit migration
was needed. The actor for every portal action is taken from the server-side
staff session; submitted `actor` / `staff_id` form fields are never read. Test
case 11 posts forged fields and proves they are ignored.

`via=cli` is recorded as **local operator attestation, not verified identity** —
anyone with shell access can type any `--actor` string. This is stated in the
guide's provenance table so that an auditor reading `audit_log` can distinguish
the two.

## 4. Recording unauthorized management attempts

Two paths record `scanner_mgmt_denied`:

- `_mgmt_staff` records an **unauthenticated GET** of any management route
  before delegating to the real `staff_required` guard.
- `_csrf_guard` records an **unauthenticated or bad-token POST** to any path
  under `/exam/scanners`, for reasons including a missing or mismatched CSRF
  token.

The actor is recorded as `scanner_auth.UNKNOWN_ACTOR`, because by definition
the caller had no verified identity.

**Bounded deliberately.** An anonymous flood must not be able to grow
`audit_log` without limit, so the record is capped at **20 per client per
300 seconds**. The bound is generous enough that a genuine probe is always
captured. This cap is a real, stated trade-off: a determined attacker can
suppress further denial records for their own IP for five minutes by flooding,
but cannot erase what has already been written. The alternative — unbounded
rows from an unauthenticated source — is the worse failure mode.

`scanner_mgmt_denied` is in `MANAGEMENT_ACTIONS`, so denied attempts appear in
the management history a staff member actually reads.

**Login success and failure rows are deliberately excluded** from
`MANAGEMENT_ACTIONS`. They remain in `audit_log` for investigation (guide §4c
step 2) but do not crowd out lifecycle events in the history table. They are
excluded by explicit name, not by a pattern match, so a future action name
cannot silently fall into or out of the history.

## 5. Migration 11 — what it does and what it does not

```sql
ALTER TABLE scanner_users ADD COLUMN credential_established INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action, id);
```

- `NOT NULL DEFAULT 1` means every pre-existing row reads as provisioned. No
  backfill statement is required and no existing account can become
  un-authenticatable by migration.
- The index serves `history()`, which filters `action IN (...)` and orders by
  `id`. Without it, every management-page render scanned the entire
  `audit_log`.
- **No audit-log migration.** The `detail` field already carries arbitrary
  text, which is sufficient for the `via=` provenance tag.

## 6. Test results — 105 checks, 0 failures

`app/scripts/test_phase19_scanner_management.py`, run from `app/` on a
disposable temp DB against the real routes, sessions, persistence and audit
trail. Production `app/lgu.db` is stat-stamped before and after and is never
opened.

| # | Case | Result |
|---|---|---|
| 1 | Unauthenticated callers denied every management operation; denials recorded | pass |
| 2 | Authenticated-but-unauthorized staff account cannot manage scanners | pass |
| 3 | Authorized staff create an account; supplied PIN never echoed; one-time PIN rendered once | pass |
| 4 | Gate assignments shown accurately and replaceable; empty set is explicit | pass |
| 5 | A pending account cannot authenticate; refusal audited; failure budget untouched; PIN unrecoverable by refresh | pass |
| 6 | Establishing then replacing a PIN invalidates the previous one; short PIN refused without changing anything | pass |
| 7 | Scanner authenticates with the new PIN and holds a real session | pass |
| 8 | Disabling blocks sign-in and kills every session; re-enabling restores the *same* credential | pass |
| 9 | Revoking sessions signs the device out but keeps the account usable | pass |
| 10 | Out-of-scope gate refused server-side; newly authorized gate takes effect | pass |
| 11 | A tampered submitted `actor` never changes the recorded actor | pass |
| 12 | Audit identifies the actual authenticated actor for every action; provenance tags correct | pass |
| 13 | Failed operations leave no half-created account or bad gate set | pass |
| 14 | No PIN, PIN hash, token or token hash reaches a page, the audit trail or a log | pass |
| 15 | Racing/repeated requests cannot create conflicting identities; lockout still holds | pass |
| 16 | CLI path still works and is distinguishable (`via=cli`) | pass |
| 17 | Legacy LGU1 and convocation LGU2 flows unchanged | pass |
| 18 | Student-facing surfaces intact; management created no authorization bypass | pass |

**One existing suite needed a change, and it was an extension, not a
weakening.** `test_phase17_cross_role_acceptance.py` carries a dashboard link
inventory — every rendered `href` must resolve without a 404/500 *and* must
appear in an explicit `KNOWN` allowlist, so that a new or broken link fails
loudly. The Phase 19 nav link legitimately added two targets. They were added
to `KNOWN`; the resolving half of the check was untouched and still proves both
return 200 for a staff session. No assertion was relaxed, removed or made more
permissive anywhere.

## 7. Full battery — 2026-10-10

Clean environment: `LGU_DB_PATH`, `LGU_TESTING` and `LGU_EMAIL_MODE` all
removed before the run.

### Python (19 suites, 0 failures)

| Suite | Checks |
|---|---|
| `test_convocation_migration.py` | pass |
| `test_event_announcements.py` | 58 |
| `test_exam_auth.py` | pass |
| `test_exam_dashboard.py` | 31 |
| `test_exam_registration.py` | pass |
| `test_medalist_management.py` | 55 |
| `test_phase10_readiness.py` | 52 |
| `test_phase11_pass_history.py` | 75 |
| `test_phase12_qr_scanner.py` | 41 |
| `test_phase13_e2e_acceptance.py` | 53 |
| `test_phase14_scanner_access.py` | 48 |
| `test_phase16_lifecycle.py` | 52 |
| `test_phase17_cross_role_acceptance.py` | **156** |
| `test_phase18_residual_closure.py` | pass |
| **`test_phase19_scanner_management.py`** | **105** |
| `test_phase8_acceptance.py` | 85 |
| `test_phase8_integration.py` | 57 |
| `test_phase9_support.py` | 58 |
| `test_student_accounts.py` | 92 |

### Mobile (33 suites, 0 failures)

All of `mobile/scripts/*.mjs` pass, including `master-audit-regression.mjs`
and `release-safety-test.mjs`.

### Tooling

| Check | Result |
|---|---|
| `npm run tsc` | exit 0 |
| `npm run lint` | exit 0 |
| `git diff --check` | exit 0 (3 pre-existing LF/CRLF warnings on `mobile/app.json`, `mobile/package-lock.json`, `mobile/package.json` — unchanged from Phase 18) |

## 8. Production database — before and after

| | Size | SHA-256 | mtime |
|---|---|---|---|
| Before | 278528 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | 2026-10-10T19:35:21.8392785Z |
| After | 278528 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | 2026-10-10T19:35:21.8392785Z |

**Byte-identical.** Every suite self-sets `LGU_TESTING=1` and a temp
`LGU_DB_PATH`, then calls `config.require_test_db()`. Migration 11 therefore
applies to disposable databases only and has **not** been applied to
`app/lgu.db`. It must be applied by a deliberate, backed-up migration run
before this feature reaches a real deployment.

## 9. Final git state

- Branch `main`, HEAD `298c272d53485ba4473c2defe72db70c02733a2c` — **unchanged**.
- `git diff --check` exit 0.
- 148 dirty entries at the working tree (was 146 at the Phase 19 baseline;
  the two additions are the new test suite and the new routes module, both
  currently untracked). Nothing was committed, pushed or stashed.
- Untracked-by-design: `app/scanner_auth.py`, `app/web/exam_scanner_routes.py`,
  `app/scripts/test_phase19_scanner_management.py` and the three new exam
  templates are new files; `git diff --stat` shows nothing for them.

## 10. Remaining defects, limitations and what this phase does **not** prove

**Declared honestly — automated tests passing is not production readiness.**

### Limitations of this phase

1. **Single-tier staff authorization.** Any active staff account can create,
   disable or reset any scanner account. This is the smallest defensible rule
   given that `staff_users` has no role column (§2), but it means a staff
   credential compromise is also a scanner-management compromise. A
   least-privilege model requires a future schema and policy decision.
2. **`via=cli` is attestation, not authentication.** The CLI records whatever
   `--actor` string the operator types. It is distinguishable in the audit
   trail precisely because it is tagged `via=cli`, but it cannot prove who
   was at the keyboard. Portal actions are the only cryptographically
   attributable path.
3. **The denial-audit cap is a real trade-off.** 20 records per client per
   300 s (§4). An attacker can suppress their own subsequent denial records
   for five minutes by flooding.
4. **No device verification.** No Android device, `adb`, emulator or SDK is
   present in this environment. The Phase 19 portal was exercised only through
   Flask's test client. Human device walkthroughs are listed in
   `docs/PHASE14_FIELD_TEST_GUIDE.md` §7 and remain unticked.
5. **No concurrent-staff conflict test.** Two staff editing the same account
   simultaneously is resolved by SQLite's last-write-wins. The suite proves
   that racing *creates* cannot duplicate an identity; it does not model two
   staff members racing a gate change.
6. **The one-time PIN is delivered in an HTTP response body.** It is shown
   exactly once and never stored or re-rendered, but it is not protected in
   transit beyond whatever TLS terminates in front of Flask. On a shared LAN
   without TLS a passive observer could capture it. This is unchanged from
   Phase 14's CLI behaviour and is called out in the guide.
7. **Migration 11 has never run against a real database.** See §8.

### Not in scope

- No mobile app change. The volunteer scanner flow, screens and API contracts
  are untouched — proved by 33/33 mobile suites.
- No change to `/api/scan`, `/api/sync`, `/api/gates`, convocation pass
  verification, student surfaces or readiness.
- No email, SMTP or notification work.

## 11. Exact commands

```powershell
# Phase 19 suite (from app/)
cd app
& "..\.venv\Scripts\python.exe" scripts\test_phase19_scanner_management.py

# Every Python suite
Get-ChildItem "app\scripts\test_*.py" | Sort-Object Name | ForEach-Object {
  $t = $_; & $py ("scripts\" + $t.Name); $LASTEXITCODE }

# Every mobile suite, then tooling
cd mobile
Get-ChildItem "scripts\*.mjs" | Sort-Object Name | ForEach-Object {
  $t = $_; & node ("scripts\" + $t.Name); $LASTEXITCODE }
npm run tsc
npm run lint

# Boundary checks
git diff --check
(Get-Item app\lgu.db).Length
(Get-FileHash app\lgu.db -Algorithm SHA256).Hash
```

### Staff portal workflow (the actual commands)

```
/exam/login                          -> staff session
/exam/dashboard                      -> "Scanner accounts" link
/exam/scanners                       -> account list + management history
/exam/scanners/new                   -> create (3 provisioning modes)
/exam/scanners/<id>                  -> gates, PIN, revoke sessions, disable/enable, history
```

### CLI (break-glass, attested operator — from `app/`)

```
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py create --username gateA-ana --name "Ana Cruz" --gates 1,2
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py list
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py gates <id> --gates 2,3
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py pin <id>
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py sessions <id>
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py revoke <id>
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py activate <id>
```

### Rehearsal on a disposable database

```powershell
$env:LGU_TESTING = "1"
$env:LGU_DB_PATH = "$env:TEMP\lgu-p19-rehearsal.db"
$env:LGU_EMAIL_MODE = "fake"
& ".\.venv\Scripts\python.exe" app\run.py
```

Startup refuses to run against `app/lgu.db` when `LGU_TESTING=1`.

## 12. Status and what must happen before deployment

**Phase 19 is complete and server-verified. It is NOT production-ready.**

Before this reaches a real deployment:

- [ ] Apply migration 11 to the real database deliberately, with a backup taken
      first. It has never run against anything but disposable databases.
- [ ] Decide whether the single-tier staff rule (§10.1) is acceptable for the
      institution, or whether a least-privilege permission model is required.
- [ ] Terminate TLS in front of Flask before any staff or volunteer uses this,
      so the one-time PIN and staff passwords are not readable in transit
      (§10.6).
- [ ] Run the human device walkthrough in
      `docs/PHASE14_FIELD_TEST_GUIDE.md` §7, including the new portal cycle:
      create with no credential → Establish PIN → sign in on the device →
      Replace PIN → confirm the old PIN fails → Revoke sessions → confirm the
      device is signed out but can sign in again → Disable account → confirm
      sign-in is refused.
- [ ] Confirm the denial-audit cap (§4) is acceptable, or replace it with a
      persistent store if `audit_log` completeness under attack matters more
      than bounded growth.

**Release discipline observed:** nothing was committed, pushed or deployed;
no destructive git operation was run; no production credential was read or
modified; no unrelated project was touched. **Phase 20 was not started.**
