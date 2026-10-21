# Phase 14 — Volunteer Scanner Access Control & Physical-Device Acceptance

**Brief:** Secure the real volunteer scanning endpoint, preserve both legacy (LGU1) and
convocation (LGU2) QR workflows, and verify the mobile experience on an actual Android
device where available.

**Execution rule followed:** inspect → establish existing security boundaries → implement
safe fixes → run the full regression battery. This report is written *after* the fixes and
the green battery, not as a substitute for them.

**Hard stop honored:** work stops at Phase 14. No Phase 15 work was begun. Nothing was
committed, pushed, reset, cleaned, stashed, amended, checked out, or deployed. All
uncommitted Phase 5–14 work is preserved (see §8).

---

## 1. Existing authentication architecture and findings

Before this phase, both admission endpoints trusted the client completely:

- `POST /api/scan` and `POST /api/sync` required **no authentication whatsoever**.
- The `volunteer` name written to the scans table was taken verbatim from the request
  body — a client could write any name (e.g. `FAKE ADMIN`) into the audit trail.
- The `gate_id` was taken verbatim from the body — a device could admit people through a
  gate it was never staffed at, and the dashboard/audit would attribute it to that gate.
- There was no per-volunteer identity, no per-gate authorization, and no session
  lifecycle (nothing to revoke when a device is lost or a volunteer's shift ends).

Other admission-adjacent boundaries that already existed and were left intact:
- Web-admin surfaces are PIN-gated (`_require_web_admin` / `_require_admin_pin`) with a
  per-IP rate limiter (master audit V-AUTH-01..04).
- Test/demo tooling is hidden in production via `config.is_production_db()`
  (master audit B1–B3).
- Legacy (LGU1) codes verify by HMAC signature (`ids.verify_payload`); convocation (LGU2)
  passes verify against the registration ledger (`convocation_qr.is_convocation_payload`).
  Both paths converge in `process_scan` and were **behaviorally unchanged** by this phase.

### Real product bug found and fixed (not just a test artifact)

`scanner_auth.resolve_session()` and `scanner_auth.authenticate()` compared a stored
timestamp to `now` with `datetime.fromisoformat(...) <= now`. A timezone-**naive** value
(a hand-edited or tampered `expires_at` / `locked_until`) raised
`TypeError: can't compare offset-naive and offset-aware datetimes` and crashed the scan
route with a **500** instead of denying the request. Fixed with an `_aware()` helper that
treats a naive timestamp as UTC, so a tampered timestamp is safely **denied/locked**
rather than crashing the route. This is a genuine robustness fix on the security path.

---

## 2. Credential / session design and gate enforcement

- **Per-account credential.** Each volunteer scanner is an individual `scanner_users`
  row with a **scrypt-hashed PIN** at rest (`exam_auth.hash_password`). No shared or
  default credential exists anywhere in source.
- **Provisioning only via local CLI.** Accounts are created solely by
  `app/scripts/manage_scanner_staff.py` (`create / list / gates / pin / revoke / activate`)
  or by the non-production test helper. The CLI prints the plaintext PIN **once**.
- **Short-lived session.** `POST /api/scanner/login` exchanges username+PIN for a bearer
  token. Only the **sha256 hash** of the token is stored (`scanner_sessions.token_hash`);
  the plaintext is returned once and never persisted or logged. Default TTL
  `SCANNER_SESSION_HOURS=12`. `POST /api/scanner/logout` revokes it. Revoked **and**
  expired rows are honoured on every scan (`resolve_session`).
- **Server-derived identity.** On `/api/scan` and `/api/sync` the recorded volunteer name
  is taken from the **authenticated session's** `display_name`. Any `volunteer` value in
  the request body is ignored.
- **Server-side gate authorization.** `scanner_gates` maps each scanner to the gates it
  may admit through. On `/api/scan` the requested `gate_id` is intersected with this set;
  a real gate the scanner is not authorized for returns **403 GATE NOT AUTHORIZED** and
  admits nothing. The client cannot pick an arbitrary gate by editing request data. On
  `/api/sync` the same check runs **per queued item**.
- **Fail-safe on unknown gates.** Authorization only guards **real** gates; a non-existent
  gate id falls through to `process_scan`, which answers **UNKNOWN GATE** (and admits
  nothing). There is no unauthenticated path to `process_scan`.
- **Lockout + rate limit (defence in depth).** Per-account lockout inside `scanner_auth`
  (`MAX_FAILED_ATTEMPTS=5`, `LOCK_MINUTES=15`) plus a per-client-IP limiter on the login
  route (`SCANNER_RATE_WINDOW_SECONDS=60`, `SCANNER_RATE_MAX_FAILS=5` → **429**) in a
  dedicated bucket so it never throttles the admin PIN limiter.
- **Test helper is production-hidden.** `POST /api/test-scanner-session` mints a random
  synthetic scanner + token and is guarded by `_test_tool_guard` (**404 on production**),
  so it can never create an account or mint a token against the production DB.

---

## 3. Files modified and migrations

**Migration:** `app/migrations.py` → **version 10** (latest `PRAGMA user_version`). Adds
three tables, created only on non-production-agnostic schema evolution:
- `scanner_users` (username unique nocase, `pin_hash`, `is_active`, `failed_attempts`,
  `locked_until`, `last_login_at`, timestamps)
- `scanner_gates` (`scanner_id` × `gate_id` composite PK, FK to `gates(id)`)
- `scanner_sessions` (`token_hash` unique, `expires_at`, `revoked_at`) + index on
  `(scanner_id, revoked_at, expires_at)`

**Backend (modified/new):**
- `app/scanner_auth.py` (new) — PIN hashing, authenticate+lockout, session
  create/resolve/revoke, gate listing, scanner CRUD; **`_aware()` datetime fix**.
- `app/config.py` — `SCANNER_SESSION_HOURS`, `SCANNER_RATE_WINDOW_SECONDS`,
  `SCANNER_RATE_MAX_FAILS`.
- `app/web/routes.py` — `_scanner_token`, `_require_scanner`, `_coerce_gate`;
  `POST /api/scanner/login`, `POST /api/scanner/logout`, `POST /api/test-scanner-session`;
  `/api/scan` and `/api/sync` now require a scanner session, derive the volunteer from it,
  and enforce per-gate authorization.
- `app/scripts/manage_scanner_staff.py` (new) — local CLI to provision/manage scanners.
- `app/scripts/test_phase14_scanner_access.py` (new) — 48-check acceptance suite.

**Mobile (modified/new):**
- `mobile/src/store/scannerSession.ts` (new) — scanner session persistence.
- `mobile/src/api/client.ts` — sends `X-Scanner-Token`, handles 401.
- `mobile/src/screens/ScannerScreen.tsx` — login gate + 401 re-auth handling.
- `mobile/scripts/api-test.mjs` — authenticates scans via the test helper; **teardown
  race fixed** (see §4).

**Docs:** `docs/PHASE14_FIELD_TEST_GUIDE.md` (device test procedure; states device
testing NOT performed), this report.

---

## 4. Exact test commands and results

**Python acceptance suite (Phase 14) — 48 checks, 0 failures, exit 0:**
```
cd app
..\.venv\Scripts\python.exe scripts\test_phase14_scanner_access.py
```
Covers: unauthenticated 401 (no row written); forged token 401; revoked/logout 401;
expired 401; 6 wrong PINs → 429 (correct PIN still 429); authorized gate admits / other
gate 403 / unknown gate UNKNOWN GATE; spoofed body volunteer ignored (server identity
recorded); LGU1 entry+exit; convocation setup + xlsx import + publish + guest pass +
admit; UNIQUE index (no duplicates) + legacy ALREADY INSIDE; bad/expired passes rejected;
failed scans create no row; deactivated scanner → 401; token stored as sha256 (≠
plaintext) and no token/PIN in audit_log or login response; `/api/sync` per-item auth;
bare-list body rejected; legacy endpoints intact.

**Full Python battery:** all 15 suites in `app/scripts/test_*.py` → **PASS, 0 failing**.

**Full mobile battery (clean env):** all 32 `mobile/scripts/*.mjs` → **32 PASS / 0 FAIL**.
```
cd mobile
$env:LGU_DB_PATH=$null   # see note below
node scripts\<name>.mjs   # × 32
```

**Typecheck / lint / whitespace:**
- `npx tsc --noEmit` → **exit 0**.
- `npx eslint .` → **exit 0** (only 2 pre-existing `no-unused-vars` warnings in
  `event-announcements-test.mjs`, `phase8-freshness-test.mjs`; **0 errors**).
- `git diff --check` → **exit 0** (only benign LF/CRLF notices).

### Two non-product issues surfaced and resolved while running the battery
1. **Leaked `LGU_DB_PATH` in the persistent terminal.** `api-test.mjs` reuses the path in
   `$env:LGU_DB_PATH` when set; a leaked value pointed at a persistent `cli_test.db`, so
   the "fresh" test DB was actually a reused file with a guest already registered →
   false "already has a guest" failures. Clearing the variable (`$env:LGU_DB_PATH=$null`)
   makes the test create its own fresh `mkdtempSync` DB. This was **environment leakage
   in the harness**, not a product defect.
2. **Real teardown race in `api-test.mjs` (fixed).** On Windows the Flask child could
   still hold the SQLite file handle a moment after `kill()`, so the immediate `rmSync`
   threw and printed `WARNING: could not remove test dir`. `db-isolation-test.mjs`
   asserts the clean `Test database removed.` message and failed deterministically. Fixed
   by making `stopTestServer()` **async** (awaits the child's `exit`, 3 s cap) and
   retrying the removal up to 5×. Both `api-test` and `db-isolation-test` are now green.

---

## 5. Legacy (LGU1) + convocation (LGU2) QR regression

Both workflows still route through `process_scan` and were **not** behaviorally altered:
- **LGU1** — HMAC-signed roster codes (`ids.verify_payload`). The Phase 14 suite admits a
  student, exits them, and confirms duplicate entry → **ALREADY INSIDE** and exit-without-
  entry → **NOT INSIDE**. Sync of a legacy item still works (authenticated).
- **LGU2** — version-prefixed convocation passes (`convocation_qr.verify_scan`). The
  suite runs staff setup, event save, xlsx import, both-attendee signup, publish, guest
  pass issue + admit, and confirms the **UNIQUE** pass index (no duplicates).
- **Guests** — single-use entry-only passes still enforced (`ALREADY USED`,
  `GUEST PASS IS ENTRY ONLY`); expired passes rejected.

The only change on these paths is *who is allowed to submit a scan* (an authenticated
scanner) and *whose name is recorded* (the scanner's, not the client's). The verification
and admission decisions themselves are unchanged.

---

## 6. Physical-device scanning — actually verified?

**NO — not performed, and this report does not claim otherwise.** No Android device,
`adb`, emulator, or Android SDK is present in this environment. What *is* proven is the
server + mobile-source behavior under real HTTP (the 48-check suite and 32 real-HTTP
`.mjs` fixtures) and the login/session/gate logic. Camera capture, on-device scanning,
and the Expo runtime on real hardware remain **outstanding**. The exact manual procedure
to close this gap is written up in `docs/PHASE14_FIELD_TEST_GUIDE.md` (cases T1–T9) for
someone with a physical device.

---

## 7. Production database integrity (before → after)

The production DB was **not used by any test** and is byte-identical:

| | Size (bytes) | mtime (ns) | SHA256 |
|---|---|---|---|
| Before | 278528 | 1791660921839278500 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` |
| After  | 278528 | 1791660921839278500 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` |

`api-test.mjs` and `db-isolation-test.mjs` independently stamp the production DB
before/after and report "Production DB unchanged by tests." Test tooling
(`/api/demo-payload`, `/api/test-scanner-session`, …) returns **404** when the production
DB is active, so it cannot mint a scanner against production.

---

## 8. Final git status and `git diff --check`

- `git diff --check` → **exit 0** (no whitespace errors).
- `git status --porcelain` shows the full Phase 5–14 working tree (modified + untracked),
  **all preserved**. **No** commit, push, reset, clean, stash, amend, checkout, or deploy
  was performed. Phase-14-specific additions include: `app/scanner_auth.py`,
  `app/scripts/manage_scanner_staff.py`, `app/scripts/test_phase14_scanner_access.py`,
  `mobile/src/store/scannerSession.ts`, `docs/PHASE14_FIELD_TEST_GUIDE.md`, and edits to
  `app/migrations.py`, `app/config.py`, `app/web/routes.py`, `mobile/src/api/client.ts`,
  `mobile/src/screens/ScannerScreen.tsx`, `mobile/scripts/api-test.mjs`.

---

## 9. Remaining security / institutional / device blockers

**Security**
- Brute-force PIN guessing is throttled (per-account lockout + per-IP 429) but a
  distributed attack across many IPs is not globally rate-limited; acceptable for a
  LAN/venue deployment, worth noting for internet exposure.
- Session tokens are bearer secrets; they are hashed at rest and revocable, but a token
  sniffed in transit must be over HTTPS in production (this env is HTTP loopback).
- The `_aware()` fix defends against naive-timestamp tampering; it does not add
  cryptographic tamper-proofing of the DB file itself (an attacker with DB-file write
  access is out of scope for the app layer).

**Device / acceptance (the main gap)**
- **Physical Android scanning is UNVERIFIED** — no device/emulator/SDK here. T1–T9 in the
  field guide still need to be executed on real hardware before any production claim.

**Institutional / operational**
- Scanner accounts must be provisioned per volunteer via the local CLI (a deliberate
  design choice — no default credential). Operational ownership of who issues/revokes
  PINs at event time needs to be assigned.
- All work remains **uncommitted** by design (hard stop). A later phase must review,
  commit, and deploy.

**Nothing here is claimed "production-ready" on the strength of passing tests alone.**
The automated evidence proves the endpoints are now authenticated, the volunteer/gate
values are server-derived, both QR workflows still behave, and the production DB is
untouched. Real-device acceptance and HTTPS/deployment hardening remain open.
