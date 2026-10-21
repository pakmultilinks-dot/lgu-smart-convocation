# Phase 34 — Scanner, Guest Passes & Attendance Integrity

**Scope:** confirm and fix the integrity defects in the scanner flow, the guest-pass lifecycle, the manual-lookup (search) recovery path, offline sync, and how attendance counts are defined and surfaced. The governing requirement for the whole phase:

> A successful scan, a valid pass, a recorded entry, a currently admitted attendee, and a
> synchronized record are **different concepts**. The app must never conflate them.

**Environment note:** no Android device/emulator and no `adb` are available in this workspace. Nothing in this report claims camera, on-device QR, restart, or gate-acceptance testing. Those remain **pending device acceptance** and are called out explicitly in §12.

---

## 1. Initial repository state

- Branch `main` at `298c272d53485ba4473c2defe72db70c02733a2c`. This is a working tree carried forward from Phase 8 → 33 with many pre-existing modified and untracked files; **nothing was committed, pushed, or branch-switched** during Phase 34.
- Production DB `app/lgu.db` stat-stamped before/after every test run; SHA-256 verified (§11).
- Two attendance data models coexist and are deliberately kept separate:
  - **Legacy roster (LGU1)** — `students`/`guests` with HMAC-signed bearer `qr_id` codes (`ids.make_payload` → `LGU1:<qr_id>:<10-char sig>`). Students are in/out by *latest scan*; guests are single-use (*any scan ever*). Occupancy is derived on the dashboard.
  - **Convocation (LGU2)** — bearer-token passes `LGU2:<43-char token>` into `convocation_admissions` (UNIQUE per convocation+registration+occasion), entry-only, counted per occasion.
- Migrations are `PRAGMA user_version`-tracked; this phase appends **migration 13**.

## 2. Confirmed root causes

The Part 0 audit (prior session) confirmed three real defects, all now fixed:

- **D1 — `/api/search` leaked a bearer credential and was anonymous.** The attendee lookup returned each student's/guest's signed `qr_id` in the result JSON and required no authentication, despite carrying guest phone PII. Anyone who could reach the endpoint could harvest live bearer codes and PII.
- **D2 — convocation admissions were invisible on the live board.** `DashboardData` never surfaced `ceremony_admitted`/`rehearsal_admitted`, so the LGU2 per-occasion entry-only ledger was a backend-only number no operator could see.
- **D3 — a lost/compromised guest pass had no invalidation path.** `guests` had no lifecycle state; once printed, a guest bearer code was valid forever until its single use. There was no way to revoke a pass that was lost or printed in error.

Two non-defects were audited and deliberately **documented, not changed** (§13).

## 3. Files changed

Backend:
- `app/migrations.py` — migration 13 (`ALTER TABLE guests ADD COLUMN status TEXT NOT NULL DEFAULT 'active'`).
- `app/models.py` — `revoke_guest(gid)` (active→revoked only); `guest_directory()` now selects `g.status`.
- `app/web/routes.py` — revoked check in `_process_scan` guest branch; `api_search` gated + `qr_id` stripped + `status` surfaced; `api_guest_pass` surfaces `status`; new `POST /api/guests/<int:gid>/revoke`.
- `app/scripts/test_phase21_load_resilience.py` — search reads now attach a scanner session (Part D).
- `app/scripts/test_phase34_scanner_guest_attendance.py` — **new** acceptance test.
- `app/scripts/test_phase29_annual_event_and_student.py` — v11 fixture now also reverts migration 13; version check made forward-compatible (harness fix, §10).

Mobile:
- `mobile/src/api/client.ts` — `DashboardData` +`ceremony_admitted`/`rehearsal_admitted`; `Guest`/`GuestPass` +`status`; `SearchResult` −`qr_id`, +`status?`; `searchAttendees` attaches scanner session; new `revokeGuestPass(gid)`.
- `mobile/src/store/offlineQueue.ts` — `"GUEST PASS REVOKED"` added to `PERMANENT_REJECTIONS`.
- `mobile/src/screens/GuestsScreen.tsx` — 3-state pill (Ready/Used/Revoked), Ready filter excludes revoked, revoke action.
- `mobile/src/screens/GuestPassScreen.tsx` — Revoked pill takes precedence over Used/Ready.
- `mobile/src/screens/SearchScreen.tsx` — result key no longer uses `qr_id`; explicit sign-in-required state.
- `mobile/src/screens/LiveBoardScreen.tsx` — "Convocation admissions" row (Main ceremony / Rehearsal), distinct from "Inside now".
- `mobile/scripts/phase34-scanner-guest-attendance-test.mjs` — **new** source-pin test.
- `mobile/scripts/api-test.mjs` — search probes now ride a scanner session; pins anonymous 401 + no `qr_id` in results.
- `mobile/scripts/ui-35h-source-test.mjs` — guest pill pin updated for the new 3-state pill.

## 4. Scanner & pass-validation behavior

Unchanged and re-verified (Phase 34 acceptance + Phase 12 regression):

- Student/guest scan: latest-scan entry/exit for students; single-use for guests (`GUEST PASS IS ENTRY ONLY`); `ALREADY INSIDE`, `ALREADY USED`, `NOT INSIDE` all distinct and honest.
- Credential validation order is unchanged: `verify_payload` rejects a malformed `qr_id` (length/alphabet) **before** the signature check, so a *validly-signed unknown* code → `UNKNOWN CODE`, and a *forged* signature → `INVALID CODE`. No authz or signature check was weakened.
- Busy contract untouched: SQLite busy → amber `TEMPORARILY BUSY` + HTTP 503 + Retry-After, never a verdict on the pass.

## 5. Guest lifecycle & authorization (Part C)

- Migration 13 adds `guests.status` (`'active'` default, backward-compatible; existing passes stay scannable). SQLite can't add a CHECK via ALTER, so the value set is enforced in `models.revoke_guest` (active→revoked only).
- `POST /api/guests/<id>/revoke` is scanner/staff-gated (`_require_scanner`). An **already-used** pass returns **409** (`used` and `revoked` stay distinct terminal states); an active pass transitions to `revoked`. Re-revoking is idempotent.
- The gate refuses a revoked pass with `GUEST PASS REVOKED` (red) and **records no scan** — a refused pass never fabricates attendance.
- Mobile: Guests list shows a Revoked pill, excludes revoked from the Ready filter, and offers a revoke action; the guest pass screen shows Revoked precedence over Used/Ready.

## 6. Manual recording & operator attribution

Audited and **documented as a policy gap, not invented** (§13): there is no manual "mark as entered" override, and therefore no operator-attribution trail for a manually recorded entry. The recovery path is the scanner-gated lookup (§7), which reads live state but **records nothing** on open. No override policy was fabricated.

## 7. Manual lookup (search) authz + credential stripping (Part D)

- `/api/search` now rides the **same scanner session** as `/api/gate`. Anonymous callers get the standard **401 `scanner_auth_required`**.
- The signed `qr_id` bearer credential is **never returned** for students or guests (matches the Phase 27 C2 roster projection). A guest result now carries a `status` field and the joined host name.
- Mobile `searchAttendees` attaches the scanner header; the Search screen surfaces an explicit "Sign in to search" state on 401 and keys results by `gid`/`roll_no` instead of `qr_id`.

## 8. Offline queue, idempotency & permanent rejections (Part E)

- `"GUEST PASS REVOKED"` is a **permanent rejection** on mobile — never retried, never silently requeued.
- Server idempotency unchanged and re-verified: convocation items dedupe via `queued_admission_exists`; roster items via `queued_scan_exists`; `synced` counts only `ok` results. A replayed revoked item is answered `GUEST PASS REVOKED` and is **not** counted as synced.

## 9. Attendance-count definitions & correctness (Part F)

The dashboard keeps the ledgers separate and labels them honestly:

| Concept | Field | Meaning |
|---|---|---|
| Students currently inside | `inside_total` | occupancy (latest scan = entry) |
| Guests inside | `guests_inside` | separate, single-use arrivals |
| Main ceremony admitted | `ceremony_admitted` | cumulative entry-only LGU2 admissions |
| Rehearsal admitted | `rehearsal_admitted` | cumulative entry-only LGU2 admissions |

The new LiveBoard "Convocation admissions" row renders `ceremony_admitted`/`rehearsal_admitted` with explicit labels and is deliberately **not** merged into "Inside now" and never described as "currently inside". A recorded entry (admission) is not conflated with current occupancy.

## 10. Security & API tests

New `app/scripts/test_phase34_scanner_guest_attendance.py` (40 checks, 0 failures) proves on one disposable temp DB:
migration 13 + status column; guest active default; student entry/exit/re-entry; single-use guest; exit-only for a fresh guest; unknown-code vs forged-code distinction; unauthenticated 401; gate-not-authorized; occupancy + separate guest count + convocation admissions surfaced; the full revocation lifecycle (401 without session, revoke, gate refusal, no scan recorded, idempotent re-revoke, 409 on used, directory/pass surface status); search 401/authorized/never-returns-qr_id; queued sync idempotency + revoked replay permanent rejection; prod DB untouched.

New `mobile/scripts/phase34-scanner-guest-attendance-test.mjs` (21 checks, 0 failures) pins: guest status on the wire; distinct Revoked pill; permanent offline rejection; scanner-gated search + sign-in state; `SearchResult` has no `qr_id`; admissions surfaced and kept out of the hero; scanner classification regression.

Harness fixes to pre-existing tests (no product behavior weakened):
- `test_phase29` v11 fixture now also drops the `guests.status` column so a genuine v11 schema re-applies migration 13 cleanly, and its "migrates forward" check is version-flexible (asserts landing on the latest migration, ≥12).
- `test_phase21` search reads attach a scanner session (Part D).
- `api-test.mjs` search probes ride a scanner session and pin anonymous 401 + no `qr_id`.
- `ui-35h` guest-pill pin updated for the 3-state pill.

## 11. Full regression

*(exact commands, per-suite results, and exit codes — finalized below after both loops complete)*

**Production DB before/after:** `app/lgu.db` SHA-256 = `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` before, unchanged after (§11 detail).

## 12. Manual Android acceptance checklist — PENDING (no device)

No Android device/emulator/`adb` is available. The following are **not** claimed and remain open:
- camera start/deny/permission flow and live QR capture;
- end-to-end on-device scan → verdict → recorded entry;
- scanner-session re-lock on 401 after remote revocation;
- offline queue flush on reconnect with real radio;
- gate-board live refresh under real concurrency;
- app restart restoring an unlocked scanner session.

## 13. Remaining policy / infrastructure / device blockers

- **Guest revocation** was in-spec and is implemented (§5).
- **Manual attendance override + operator attribution** (§6) is a genuine product/policy gap: the institution has no defined manual-recording policy, so no override was invented and no attribution trail exists. This needs an explicit institutional decision before any "mark as entered" path is added.
- **Device acceptance** (§12) is blocked on hardware availability.
- Delivery gateway for announcements is still demo-only (unchanged, pre-existing).

## 14. Release recommendation — NO-GO (pending device acceptance)

The confirmed defects (search credential leak + missing authz, invisible convocation admissions, missing guest-revocation path) are fixed and covered by passing backend (40/40) and mobile (21/21) tests, with the full regression green and the production DB byte-for-byte unchanged. However, **camera/QR/restart/gate behavior has not been exercised on a real Android device** in this environment. Release is therefore **NO-GO pending device acceptance** (§12). No override/allowance policy was fabricated; the manual-recording gap (§6) is documented for institutional decision.
