# Phase 34B — Test Results & Evidence

Phase: 34B (targeted technical fixes, scanner decomposition & device readiness)
Date: 2026-10-03
Rules applied: targeted implementation only; no redesign; no push; API contract preserved
(`API_CONTRACT.md` authoritative); connectivity preserved (no new hardcoded host default);
QR / Entry-Exit / offline-queue semantics unchanged.

---

## 1. P-13 — LiveBoard gate-activity data source (FIXED)

File: `mobile/src/screens/LiveBoardScreen.tsx`

| Aspect | OLD (defect) | NEW (fix) |
|---|---|---|
| Source | `data.feed[]` — server's **last 20 scans, lifetime, no time filter** | `data.throughput[]` — server-side **entries per gate, last 15 minutes** (same metric as "Entries · 15 min") |
| Label | "Gate activity" (comment claimed "15-minute feed" — false) | "Gate activity · 15 min" |
| Meaning | Rows could include hours-old scans under a section operators read as recent | Rows are exactly the 15-minute throughput metric, labelled as such |

Why source and label now match: both the per-gate rows and the aggregate "Entries · 15 min"
MetricBlock below them derive from the same verified throughput metric
(`dashboard()["throughput"] = entries per gate, last 15 min`). `feed[]` is no longer consumed
by LiveBoard (`FeedItem` import removed). Empty state "No gate scans in the last 15 minutes
yet." is now truthful for this source.

Bundle proof: served Metro bundle contains
`children: "Gate activity \xB7 15 min"` (U+00B7 middle dot) and the
`data.throughput` derivation comment.

## 2. P-14 — ScannerScreen decomposition (FIXED, behavior identical)

Before: `mobile/src/screens/ScannerScreen.tsx` = **1127 lines** (state + engine + UI + styles).
After: **530 lines** + 9 focused modules under `mobile/src/scanner/`:

| Module | Lines | Responsibility |
|---|---|---|
| `scannerConstants.ts` | 28 | Timing/geometry constants + `localTimestamp()` (Asia/Karachi) |
| `useScannerZoom.ts` | 59 | Auto-zoom state, tick effect, QR-bounds tracking, camera layout |
| `useScanDedup.ts` | 35 | In-frame duplicate suppression (`claim`/`release`, 1200 ms release, 4000 ms frame dedupe) |
| `ViewfinderCorners.tsx` | 54 | Corner-bracket overlay |
| `ScannerOverlay.tsx` | 153 | Dim overlay, scan window, operational status strip, hint pill |
| `ScannerResult.tsx` | 130 | Result moment card (icon + title + name/sub/detail + gate/time) |
| `ScannerControls.tsx` | 234 | Gate setup card (gates, mode, torch, volunteer, offline, sync) |
| `ScannerTestPanel.tsx` | 127 | Test scan card (3 backend records + reset) |
| `CameraScannerView.tsx` | 211 | Camera view + web fallback + **mount-failure state** |

Constants preserved verbatim: `RESULT_DISMISS_MS=4000`, `ZOOM_MAX=0.45`, `ZOOM_STEP=0.025`,
`ZOOM_TICK_MS=80`, `QR_LEAVE_MS=1400`, `FRACTION_COMFORT=0.42`, `FRAME_DEDUPE_MS=4000`,
`DIM_COLOR`, `FRAME=260`; `SCAN_RELEASE_MS=1200` documented in `useScanDedup`.

§5 camera mount failure (new): `CameraView onMountError` → `cameraFailed` state renders
"Camera unavailable" / "Please check camera permission or restart the scanner." /
[Try Again] [Back]. No native error text is shown to users; the error message is logged
`__DEV__`-only; Try Again remounts the camera via `cameraKey` bump.

Test Scan flow preserved: Test Scan buttons call the same `handleBarcode` → real
`POST /api/scan` (Entry → duplicate → Exit semantics intact); "Reset test scans" calls
`POST /api/test-reset`. Offline queue, haptics, dedupe and result dismissal unchanged.

Verification: `npx tsc --noEmit` = 0; `npx eslint app src` = 0 (re-run after decomposition
and again after dependency removal). Metro bundle serves the scanner modules
(`require("../scanner/CameraScannerView")`, `ScannerControls`, `useScanDedup` all present,
HTTP 200, 8,549,613 bytes).

## 3. P-06 — tzdata pinned (FIXED)

- Installed version verified: `tzdata 2026.4` (`.venv\Scripts\python.exe -m pip show tzdata`).
- `app/requirements.txt`: `tzdata>=2024.1` → `tzdata==2026.4` (exact pin per env audit; no
  downgrade/upgrade performed — installed version already 2026.4).
- ZoneInfo verified: `from zoneinfo import ZoneInfo; ZoneInfo('Asia/Karachi')` → OK.
- Explanatory comment in requirements.txt kept.

## 4. P-18 — Splash / launcher emerald alignment (FIXED)

app.json (both verified on disk):
- `expo.android.adaptiveIcon.backgroundColor`: `#0B2447` → `#0F5132` (LGU emerald/greenDeep)
- `expo.splash.backgroundColor`: `#0B2447` → `#0F5132`
- Paths, resizeMode, plugin config unchanged → Expo Go compatible.

PNG regeneration (`mobile/scripts/recolor-launcher-assets.py`, replaces stale
`make-assets.py`):
- `adaptive-icon.png` 1024×1024: navy `(11,36,71)` background → emerald `(15,81,50)`;
  674,482 px shifted; crest pixels ≥90 RGB-distance untouched; artwork whites preserved
  (49,280 white px remain). Corners after = `(15,81,50,255)` on all four.
- `splash.png` 1242×2436: navy → emerald; 2,654,505 px shifted; emerald fraction 86.3 %;
  crest region intact (ASCII mask verification: center artwork block non-emerald,
  background fully emerald). Corners after = `(15,81,50,255)`.
- `icon.png` 1024×1024: **finding — corner background was white `(255,255,255)`, not navy**
  (the Phase 34A audit's "navy baked into all three PNGs" was inaccurate for icon.png).
  Corner-connected white flood-filled → emerald (167,722 px); interior artwork whites
  (motto ribbon) are not corner-connected and stay white (30,975+ white px remain).
  Corners after = `(15,81,50,255)`.
- Crest artwork was not redesigned: shield, gold frame, star/crescent, navy "LGU" banner
  (same navy as the old background by design — it reads as floating lettering and follows
  the background colour), white motto band all preserved.
- Single consistent green: all three launcher assets now use exactly `#0F5132`, matching
  app.json and the theme `greenDeep`.
- Idempotent: script skips assets whose corners are already within 6 RGB-distance of emerald.

## 5. §7 — Stale direct dependencies removed (FIXED)

- `mobile/package.json`: removed `expo-symbols`, `expo-web-browser` (dependencies) and
  `@types/react-native` (devDependencies). (Repo-wide import audit in Phase 34A found zero
  imports of all three.)
- `npm install` exit 0; `package-lock.json` updated.
- `npm ls @types/react-native expo-symbols expo-web-browser`:
  - `expo-web-browser` — absent (fully removed).
  - `@types/react-native` — absent (fully removed).
  - `expo-symbols@57.0.3` — remains **transitively via expo-router** (required indirectly
    by Expo; kept per mandate — not force-removed).
- `npx tsc --noEmit` = 0 and `npx eslint app src` = 0 after removal.
- No Expo/RN/dependency version upgrades performed.

## 6. §10 — Logo quality check (DOCUMENTED, artwork untouched)

- Source asset: `mobile/assets/lgu-logo.png` — **444×444, RGBA (transparent)**.
- Variant: `mobile/assets/lgu-logo.jpg` — 148×148, RGB (small JPEG copy).
- Launcher derivatives: icon.png / adaptive-icon.png 1024×1024, splash.png 1242×2436 —
  crest centered; only background pixels recolored (§4 above). No crest artwork edits.

## 7. §11 — Dead code cleanup (VERIFIED ONLY)

- `mobile/scripts/make-assets.py` **deleted** — stale generator that drew a gold "LGU" text
  monogram on navy via Linux-only DejaVu font paths; cannot reproduce the crest assets and
  would destroy them if run. No repository references to it. Replaced by the truthful
  recolor tool (§4).
- `DashboardScreen.tsx` kept (explicit Phase 34 rebuild mandate, §4.2 of REBUILD_PLAN).
- All `console.*` calls in `mobile/src` are `__DEV__`-gated (client.ts ×3, settingsApi.ts ×2,
  ScannerScreen.tsx ×1) — no production console noise.
- No other removals: tsc/eslint clean proves no dangling references.

## 8. §18 — Backend smoke (ALL PASS)

Flask PID 9788, `127.0.0.1:5000`. 29 checks passed / 0 failed (response shapes per
API_CONTRACT.md):

- GET /api/health → `ok:true, version:LGU1`
- GET /api/gates → 7 gates (G1–G7), wrapped `{gates:[...]}`
- GET/PUT /api/settings → `expected_attendance` echoes (2500) and **persists** (re-read
  equals written, end-to-end check after all operations)
- GET /api/dashboard → 15 keys; GET /api/dashboard/summary → 13 keys
- GET /api/test-records → 3 records
- **Scan cycle (male test payload):** entry → `ENTRY RECORDED` (green);
  duplicate → `ALREADY INSIDE` (red); exit → `EXIT RECORDED` (green);
  re-entry after exit → `ENTRY RECORDED` (green, student_inside reset semantics intact);
  exit-without-entry (after reset) → `NOT INSIDE` (amber); `/api/test-reset` clears all
  (`ok:true, removed:3` then `removed:0`)
- POST /api/sync {items:[1]} → `synced:1`, 1 result; test-reset after sync clears 2
- GET /api/search?q=Muhammad → 3 hits; `?q=a` → HTTP 400
- GET /api/guests → wrapped list (6); POST /api/guests {name, phone, host_roll_no} →
  `{ok, gid, payload}` (gid 7); GET /api/guest-pass/7 → payload present
- GET /api/broadcasts → wrapped `{log:[...]}` (3); POST /api/broadcasts → `ok:true`
  (demo mode note)
- GET /api/demo-payload → payload present; GET /api/does-not-exist → JSON 404 `{error, ok:false}`

No backend tests existed to run (none invented). API response contracts unchanged.

## 9. §19 — Metro / bundle check (PASS)

- Metro listener: PID **1640** on `:8082` (node) — alive. (8081 = foreign UniServe, untouched.)
- `GET http://192.168.100.5:8082/.expo/.virtual-metro-entry.bundle?platform=android&dev=true`
  → **HTTP 200, 8,549,613 bytes** (served after the scanner refactor → all new modules
  resolve).
- Expo dev root `http://192.168.100.5:8082/` → HTTP 200 (dev-client page).
- Scanner modules present in served bundle: `../scanner/CameraScannerView`,
  `../scanner/ScannerControls`, `../scanner/useScanDedup` requires + rendered
  `ScannerControls` call site; P-13 label "Gate activity · 15 min" present.
- No missing assets; the 5 "Unable to resolve module" string hits in the bundle are Metro
  runtime's own error-format constants (template literals + regex), not failures.
- Manifest runtime `exposdk:57.0.0` unchanged (no upgrade). Connectivity settings untouched —
  no new hardcoded host defaults.

## 10. §20–21 — Physical-device acceptance P1–P6 (THE gate)

Agent cannot operate a physical device. Per mandate — **no guessing**:

| ID | Scenario | Result |
|---|---|---|
| P1 | Live camera preview + QR detection on device | **NOT TESTED** (requires physical device) |
| P2 | Gate selection / Entry-Exit toggle / torch on device | **NOT TESTED** |
| P3 | Real scan → ENTRY RECORDED with haptics + result moment | **NOT TESTED** |
| P4 | Duplicate → ALREADY INSIDE; Exit semantics on device | **NOT TESTED** |
| P5 | Offline queue → back online → Sync on device | **NOT TESTED** |
| P6 | Camera permission denied / mount failure UI (Try Again / Back) | **NOT TESTED** |

Host-side evidence above (tsc/eslint/bundle/smoke) supports readiness; **device PASS cannot
be claimed until a human runs P1–P6 on hardware.**

## 11. §22 — Dev warnings vs app errors

- Expo/Metro dev-server warnings (e.g., Metro 57.0.26 upgrade notice) are toolchain notices,
  not app errors — not acted on (upgrade prohibited).
- All app-side logging is `__DEV__`-gated; production builds emit no console output.
- Camera mount failures surface only the friendly state (§2); native messages stay in dev
  logs.

---

## Summary of changes in this phase

- `mobile/src/screens/LiveBoardScreen.tsx` — P-13 truthful metric (throughput, 15 min).
- `mobile/src/screens/ScannerScreen.tsx` — 1127 → 530 lines; delegates to scanner modules.
- `mobile/src/scanner/` — 9 new focused modules (constants/zoom/dedup/overlay/result/
  controls/test panel/camera view/corners).
- `mobile/package.json` + `package-lock.json` — removed 2 unused deps + 1 stale types devDep.
- `app/requirements.txt` — `tzdata==2026.4` pin.
- `mobile/app.json` — splash + adaptive-icon backgroundColor `#0F5132`.
- `mobile/assets/{icon,adaptive-icon,splash}.png` — backgrounds recolored to emerald,
  crest preserved.
- `mobile/scripts/recolor-launcher-assets.py` — new truthful asset tool.
- `mobile/scripts/make-assets.py` — deleted (stale/dead).
- `docs/phase34-product-reset/PHASE34B_TEST_RESULTS.md` — this file.
- Plus the Phase 34A doc refresh set (uncommitted from 34A) and the two pre-existing
  modified screens (`GuestPassScreen.tsx`, `HomeScreen.tsx`) — all in one local commit.

Gates: tsc 0 / eslint 0 / backend smoke 29-29 / Metro bundle 200. Physical-device P1–P6 =
NOT TESTED (human gate). Commit is local only — **not pushed**.
