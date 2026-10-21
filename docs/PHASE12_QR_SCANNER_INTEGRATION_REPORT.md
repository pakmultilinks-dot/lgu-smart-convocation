# Phase 12 — Secure QR Pass Issuance & Convocation Scanner Integration

Status: **COMPLETE** (backend + mobile + tests, uncommitted). This phase solves
the §2 blocker — convocation registrations were never linked to the legacy
operational roster, so a registration could not produce a gate-scannable code —
WITHOUT weakening roster/registration separation and WITHOUT touching the legacy
scanner.

---

## 1. Summary

A student whose invitation state is `eligible` can now mint a **scannable
convocation entry QR**. The QR carries a high-entropy bearer token; the gate
verifies it **server-side against the authoritative registration/account
ledger** and records a single admission. The legacy operational path
(`students.qr_id` → `models.find_person` → `scans`) is preserved byte-for-byte
and continues to serve real roster students and guests. Convocation entry is a
**separate, parallel path** keyed by a version prefix (`LGU2:`), not a new link
between the two identifier spaces.

## 2. The §2 blocker and how it was resolved

The volunteer scanner's legacy path resolves a QR payload to an **operational
roster row** (`students`). A convocation registration carries no `qr_id` and
shares no key with that roster; there is no approved roster-synchronization
workflow. Phase 11 deliberately issued **no** QR and reported the blocker.

Phase 12 resolves this **without inventing a roster link**:

- A convocation entry pass is its own record (`convocation_passes`), bound to
  the claimed registration + account + convocation. It is verified by
  `convocation_qr.verify_scan`, which reads the registration ledger — **not**
  the roster.
- Issuing or scanning a convocation pass **never** inserts a `students` row and
  **never** writes to `scans`. The two identifier spaces stay separate by
  design; the scanner simply dispatches on the payload's version prefix.
- The legacy roster diagnostic (`qr_prerequisite`) remains `satisfied=False` and
  is still reported honestly — registrations are still not roster-linked; the
  convocation QR simply does not depend on that link.

## 3. Architecture & flow

**Issuance (student, authenticated):**
`POST /api/student/pass/issue` → recompute eligibility via
`convocation_pass.pass_for_account` (same source as the read-only invitation) →
if `eligible`, revoke any prior active pass, mint a token
(`secrets.token_urlsafe(32)`), store only its sha256 hash, audit `pass_issue`
(no token), return `{payload:"LGU2:…", pass_id, issued_at, expires_at, …}`.
Any non-eligible state → HTTP 403 with the state code; no token is minted.

**Verification (volunteer gate):**
`POST /api/scan` → `routes._process_scan` dispatches on `LGU2:` →
`convocation_qr.verify_scan`: parse token → look up by hash → check status
(revoked→invalid, used→already admitted) → **recompute eligibility at scan
time** → entry-only (exit→amber) → check not already in `convocation_admissions`
→ insert admission (UNIQUE backstop) → mark pass `used` → audit `pass_admit`.
Returns a `ScanResult`-shaped dict the mobile scanner already renders.

## 4. Security model

- **Token:** 256-bit URL-safe token, minted once, returned only to the owning
  student. **Only its sha256 hash is stored**; the plaintext never touches the
  DB, logs, or audit trail (proven by test).
- **Binding:** the token resolves to exactly one registration/account/convocation;
  it can never admit a different registration.
- **Eligibility is recomputed on every scan,** so a cancelled/revoked
  registration or an open blocking review stops validating the moment it changes.
- **Single admission:** the caller's `_SCAN_LOCK` serializes in-process, and a
  `UNIQUE(convocation_id, registration_id)` index is the atomic cross-process
  backstop — two gates scanning the same pass near-simultaneously cannot admit
  twice.
- **Separation preserved:** no `students` insert, no `scans` write, no shared key.
- **No client verdict:** the mobile scanner posts the raw payload; only the
  backend decides validity.
- **PII:** the gate response carries the student's name so the volunteer can
  confirm identity; the audit trail stores gate/pass/registration ids, never the
  token.

## 5. Data model (migration 9)

- `convocation_passes` — `token_hash UNIQUE`, `convocation_id`,
  `registration_id`, `account_id`, `status` (`active|revoked|used`),
  `issued_at`, `expires_at`, `revoked_at`. Indexes on live passes per
  registration and per account.
- `convocation_admissions` — `pass_id`, `convocation_id`, `registration_id`,
  `gate_id`, `volunteer`, `admitted_at`, `source` (`online|queued`).
  **`UNIQUE(convocation_id, registration_id)`** is the double-admission
  backstop. Indexes on `(convocation_id, admitted_at)` and `(gate_id, admitted_at)`.
- The ladder is now at **version 9**; fresh DBs and legacy upgrades both reach 9,
  idempotently.

## 6. API contract

- `POST /api/student/pass/issue` (Bearer auth) → `{ok, pass:{payload, pass_id,
  issued_at, expires_at, convocation, registration, event}}` or 403/429.
  Rate-limited (default 10 / 60 s, `PASS_ISSUE_RATE_*`). GET `/pass` is
  **unchanged** (read-only invitation, `qr_available:false`, `qr:null`).
- `POST /api/scan` (and `/api/sync`) accept an `LGU2:` payload unchanged; the
  backend dispatches internally. Response uses the existing `ScanResult` shape:
  `CONVOCATION ENTRY RECORDED` (green), `ALREADY ADMITTED` (red), `PASS
  INVALID` (red), `REGISTRATION NOT ELIGIBLE` (red), `CONVOCATION PASSES ARE
  ENTRY-ONLY` (amber).

## 7. Legacy preservation (regression guarantees)

- Legacy `LGU1:` student + guest scanning is **untouched** (verified: entry,
  already-inside, exit, forged-code rejection).
- The legacy `scans` ledger is **not written** by a convocation entry.
- The operational `students` roster is **never mutated** by issuance or scanning.
- The dashboard keeps **exactly 22 KPI tiles**; the invitation card now shows
  convocation-QR status alongside the honest legacy-roster prerequisite note.

## 8. Testing & verification evidence (automated)

All run on disposable temp DBs; `app/lgu.db` is byte-identical before/after
(sha256 `82011370…15F`).

- **Python (13 suites, all pass):** phase12 **40/0**, phase11 75/0,
  phase8_acceptance 85/0, phase8_integration 57/0, phase9 58/0, phase10 52/0,
  dashboard 31/0, event_announcements 58/0, medalist 55/0, student_accounts
  92/0, plus exam_auth / exam_registration / convocation_migration.
- **`test_phase12_qr_scanner.py` (40 checks)** proves: issuance requires a
  session; eligible issues, ineligible (cancelled/revoked/pending/unpublished)
  denied; only the hash is stored; reissue revokes the prior token; a replaced
  token is refused; a valid scan records exactly one admission and marks the
  pass used; repeat scan is a safe duplicate; the UNIQUE index blocks a second
  admission atomically; fabricated tokens record nothing; entry-only + gate
  validation; a token stops validating after eligibility is lost; the audit
  trail never leaks a token; legacy QR/attendance intact; no fabricated
  `students` row; migration reaches 9 idempotently.
- **Mobile:** tsc **0** errors, eslint **0** errors. All **33 `.mjs`** source
  tests pass, incl. new `qr-pass-source-test.mjs` (10/0) and updated
  `pass-history-source-test.mjs` (31/0).
- **Fixed pre-existing staleness** (not Phase 12 regressions): three suites
  hard-coded `user_version == 6` (ladder is now 9) and one hard-coded 15 KPI
  tiles (dashboard grew to 22 in Phase 9). Updated to be version-agnostic /
  current — assertions strengthened, not weakened.

## 9. Known limitations & honest caveats

- **Roster link is still absent.** `qr_prerequisite` remains `satisfied=False`;
  the legacy scanner still cannot resolve a convocation registration. That is
  intentional and unchanged.
- **Automated vs device testing.** Everything above is proven by automated
  server + source-level tests. A real camera scan on a physical Android device
  was **not** exercised in this phase; the mobile scanner required no code
  change (it posts the raw payload and already classifies `ALREADY ADMITTED` as
  the already-used state), but on-device camera behaviour should be confirmed
  separately before operational use.
- **Offline/queued convocation scans** flow through the existing `/api/sync`
  path and reuse the same `verify_scan` (with `source="queued"`); the
  double-admission backstop makes a later online replay safe.
- **TTL** defaults to 72 h (`CONVOCATION_PASS_TTL_HOURS`); an expired pass is
  reported via its `expires_at` and reissuance refreshes it.

## 10. Files changed

Backend: `app/config.py` (TTL + issue-rate knobs), `app/migrations.py`
(migration 9), `app/convocation_qr.py` (new — issuance + verification),
`app/convocation_pass.py` (honest QR/roster narrative; GET /pass still
read-only), `app/web/routes.py` (`LGU2:` dispatch), `app/web/student_routes.py`
(`POST /pass/issue` + limiter), `app/web/exam_routes.py` + `exam_dashboard.html`
(issued/admitted counts).

Mobile: `mobile/src/api/passApi.ts` (`issuePass` + `IssuedPass`),
`mobile/app/(student)/pass.tsx` (render QR when eligible; auto-issue; explicit
"Refresh QR"; QR cleared if eligibility is lost), `mobile/scripts/qr-pass-source-test.mjs`
(new), `mobile/scripts/pass-history-source-test.mjs` (updated).

Tests: `app/scripts/test_phase12_qr_scanner.py` (new, 40 checks); honest
version/tile updates to `test_phase11_pass_history.py`,
`test_event_announcements.py`, `test_medalist_management.py`,
`test_student_accounts.py`.

**Next:** stop for review. Phase 13 not started.
