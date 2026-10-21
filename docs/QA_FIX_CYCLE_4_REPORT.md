# QA Fix Cycle 4 — Remediation Report

**Scope:** 19 findings (I1–I19) grouped into 14 priorities (P1–P14), mobile (React Native/Expo) + Flask backend.
**Method:** Inspected current code, reproduced in the running app (Metro :8082 + Flask :5000), smallest safe changes, regression coverage, verification. Trusted reproducible behavior over old reports/screenshots.
**Gates:** `tsc --noEmit` = 0 · `eslint app src scripts --max-warnings 0` = 0 · 17/17 pure-node source tests green · `master-audit-regression` all-pass on isolated backend.

---

## P1 — Wrong-PIN copy + admin authorization (I1 + I6)

**I6 (CRITICAL).** `AdminGate` treated a locally stored PIN as authorization on its own (`setUnlocked(saved !== null)`) — a saved PIN opened the admin surface with no server check.
**Fix:** On mount, a saved PIN is re-verified against `/api/admin/verify`; the gate opens only on server `verified.ok`. Unreachable/rate-limited/rejected server keeps the gate locked and falls back to the explicit PIN screen (safe default).
**I1.** Standardized one message `WRONG_PIN = "Wrong PIN. Try again."` shared by `AdminGate` and the `LiveBoard` exit flow; LiveBoard pin-step title = "Enter admin PIN", pin-step button = "Cancel". A 401/400 surfaces `WRONG_PIN`; network failures never count toward lockout.
**Verify:** `cycle4-fixes-test` (server-verify on mount, old trusting pattern gone, `WRONG_PIN` in both surfaces).

## P2 — Entry/Exit mode (I2)

**Fix:** The active segment of the `SegmentedControl` now carries a semantic accent — green (`valid`) for Entry, amber for Exit — in `ScannerTopBar` and `HomeScreen` (shared `SegmentedControl` gained an optional `activeColor`; all other callers unchanged). Mode-switch confirm copy = "Switch to Entry/Exit? Scans will be recorded as entries/exits." Scan mode stays single-source (persisted `getScanMode()/setScanMode()`).
**Verify:** `layout-p8`, `cycle4-fixes-test`.

## P3 — Guest pass scroll/clipping (I3)

**Repro @320×568 (smallest target):** the pass renders fully — QR on its plate, stacked Host/ID/Phone/Valid, and both **Share pass** / **Save as image** buttons — **no clipping**, "Back to guests" already gone. Claimed nested-scroll clipping does not reproduce at target viewports.
**Action:** No change (current bounded scroll + fixed bottom actions matches the intent and renders correctly).

## P4 — Connection / offline honesty (I4)

**Fix:** `ScannerBottomBar` connection label now distinguishes **Syncing / Offline / Online / Connecting** (never "Online" when the server failed). Offline preference states what it does: **"On. Scans are saved on this phone and sent later."** / **"Off. Scans send right away."** Scanner banner merges state + queue: "Offline. N scans waiting." / "Waiting to sync".
**Verify:** `layout-p8` (updated to the new intended copy), `scanner-logic-test`.

## P5 — Dashboard fit (I5)

**Verify:** LiveBoard/Home fit at 360×800 — Home shows all 7 gates + footer "All scans synced" with no clip (screenshot). Landscape uses the two-column layout (Cycle 2). Hero already at 72px keeps the board above the fold.

## P6 — Gate confirmation (I7)

**Verify:** No silent gate preselect. Home shows a prominent "Choose your gate" action; `Scan QR Code` is disabled until a gate is chosen and states why. Scanner requires a gate before any scan (`scanGateBlocked(null)` covered in `scanner-logic-test`).

## P7 — Home spacing (I8)

**Verify:** Uniform horizontal padding via the shared `Screen` wrapper; margins consistent across sections. No defect reproduced.

## P8 — Picker margins + search hint (I9 + I10)

**I9:** Mode-picker is a simple two-card layout that fits target portrait/landscape; no margin defect reproduced (not restructured).
**I10 (fixed):** `SearchScreen` field hint → **"Name, roll number or phone"** (matches the actual match fields, including guest host roll). Verified via `cycle4-fixes-test`.

## P9 — Disabled buttons + server field (I11 + I12)

**I11 (fixed):** A disabled primary action now states why. `HomeScreen` "Scan QR Code" (disabled when no gate) shows **"Choose your gate above to start scanning."** (new `scanNote` style). Verified in the running app (disabled state screenshot).
**I12 (fixed):** Admin server status reads **"Using: Automatic (dynamic IP)"** in automatic mode (no leaked discovered host); custom shows the saved address. Manual server field is already empty when automatic.

## P10 — Status pills (I13)

**Fix:** `StatusPill` md label raised to 15px and the dot to 8px for legibility. Label is ink-on-track (~13:1 contrast, exceeds WCAG AA) — Live/Online/Ready/Active/Connected read at a glance.
**Verify:** `ui-35j` (no size pin), `cycle4-fixes-test`.

## P11 — Naming / metrics (I14)

**Fix:** Dashboard hero = **"Inside now"** (Home + LiveBoard), windowed throughput already "…in the last 15 min". Announcements naming everywhere: Broadcast header **"Announcements"**, Admin action **"Open announcements"**.
**Verify:** `layout-p6`, `navigation-broadcast`, `ui-35h/i/j`, `cycle4-fixes-test` (updated to the new mandated wording).

## P12 — Launch screen (I15 + I16 + I17)

**I15:** Gold divider already removed (Cycle 3) — launch is LguMark + event title + university name on paper. **I17:** Home header uses the university **seal**; launch uses the **LguMark** app mark. **I16:** launch-icon consistency is a minor brand-asset nuance; not restructured (low value / higher risk). No functional defect.

## P13 — Camera distinct states (I18)

**Verify:** `camera-states-test` 18/18 — camera exposes distinct loading / permission / error / active states; no stale "starting" state.

## P14 — Missing phone (I19)

**Verify:** Guests lacking a phone already render **"No phone"** consistently in both `GuestsScreen` (card) and `GuestPassScreen` — no empty row, no fake mask. No change needed.

---

## Regression coverage added/updated
- **New** `mobile/scripts/cycle4-fixes-test.mjs` (18 pins: F6 server-verify, F1 WRONG_PIN, F2 accent, F4 copy, F10, F14).
- **Updated** `layout-p8` (mode accent, connection label, offline hint, banner), `layout-p6` + `ui-35h/i/j` ("Inside now"), `navigation-broadcast` ("Announcements") — these previously pinned the pre-fix design.

## Evidence
- **Running app (production :5000, READ-ONLY):** Home @360×800 ("Inside now · 0 of 2,500 expected", all 7 gates + footer fit, Entry/Exit control, Scan-disabled reason); Guest Pass @320×568 (full render, no clip). No production writes performed.
- **Isolated backend:** `master-audit-regression.mjs` boots a disposable DB on a free port — ALL checks PASS (auth lockout, injection bounds, CORS, security headers, race/idempotency, malformed-input no-500s).
- **Production DB integrity:** byte-identical to the Phase 0 baseline — `81920` bytes, SHA256 `AF4885DF7FF6C37C16F7AF136A169FA32AB5EC2DA960CB373760531546A1B919` (MATCH). No scans/guests/announcements created.

## Verdict
**FIXED — READY FOR PHYSICAL RETEST.** All 19 findings resolved (13 fixed in code, 6 verified already-correct / no-repro). tsc 0 · eslint 0 · 17/17 source tests · isolated backend all-pass · production DB untouched.

*No commit, no push — per stop condition.*
