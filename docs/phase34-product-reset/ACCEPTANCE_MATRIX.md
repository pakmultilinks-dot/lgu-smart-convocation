# ACCEPTANCE_MATRIX — Phase 34 rebuild, Phase 34A forensic re-verification (2026-10-03)

Filled per §46/§47 rules: **agent fills only what it personally verified**; anything requiring the physical phone is `PENDING-USER` until the user reports. Verification date: **2026-10-03 (Phase 34A audit — all rows re-captured today unless noted)**. Runtime today: **Flask PID 9788 on :5000** (single listener — P-07 resolved; **8081 = PID 7556 UniServe, foreign workspace — DO NOT kill**), **Metro PID 1640 on :8082**, Expo SDK **57.0.25** (unchanged; 57.0.26 notice ignored per §43).

Status legend: **VERIFIED** (agent evidence captured today) · **CODE-VERIFIED** (implemented; runtime on device not yet observed) · **PENDING-USER** (physical-device or cross-network test — user must run).

## Network

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| N1 | Backend reachable on LAN: `/api/health` returns `{"app":"LGU Smart Convocation","ok":true,"version":"LGU1"}` | **VERIFIED** | Live-captured today via python urllib: health 200 exact JSON; Flask PID 9788 |
| N2 | §41 backend-down behavior: backend stops → clients get network errors (no technical strings in UI paths); Retry works; restart → recovery | **VERIFIED (API side)** / **PENDING-USER (device side)** | Historical §41 test passed (connection-refused → clean errors → restart recovery); today re-verified single-listener state + human networkError strings in client.ts. Device UI states (OfflineBanner, ErrorState+onRetry, scanner catch → queue) implemented — must be observed on phone. |
| N3 | §42 DHCP change: stale saved backend URL must not pin the app; auto mode recovers via fresh discovery; no source edits for IP changes | **CODE-VERIFIED** / **PENDING-USER (device + DHCP switch)** | store/settings.ts Phase 33 architecture preserved verbatim (re-read today): auto = session → discovered (Constants.expoConfig.hostUri) → stored; noteUnreachableBaseUrl probes 5s; custom validated + probed. Live runtime host today = 192.168.100.5 via hostUri. Real DHCP switch unobserved (P5). |
| N4 | Metro/dev server serving this project on its dedicated port; other workspaces' processes not disturbed | **VERIFIED** | Metro PID 1640 on **8082** (`Waiting on http://localhost:8082`); 8081 = PID 7556 UniServe foreign workspace auto-respawner — untouched. Phone dev URL: `exp://192.168.100.5:8082`. |

## Data

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| D1 | Scan business rules preserved: entry green, duplicate red + last gate/time, exit green, exit-without-entry amber, guest entry green + host sub, guest any-scan red ALREADY USED, unused-guest exit amber entry-only, invalid code red, null gate NO GATE SELECTED, unknown gate/mode/code | **VERIFIED** | 11-scenario audit script re-run TODAY — all outcomes + exact strings captured; DB reset after (removed:3); rules identical to DATA_MODEL business-rules table |
| D2 | Offline queue + sync: `/api/sync` accepts queued items, preserves client `scanned_at`, marks source queued, max 500, per-item results | **VERIFIED (API)** / **PENDING-USER (device)** | Today: sync preserves client timestamps (source=queued), results array [{payload, result}]; store/offlineQueue.ts (dedupe + PERMANENT_REJECTIONS + positional reconcile) re-read, code-verified only |
| D3 | Search: backend-supported (name / student roll / guest phone / host roll), `q<2` → 400, empty → `[]`, guest results carry integer `gid` for pass navigation | **VERIFIED** | Live today: q=nasir → guest gid:1 used:true; q<2 → 400. SearchScreen tab 3 (400ms debounce, requestSeq guard) |
| D4 | Dashboard contract: 15 keys + live `generated_at` per request; summary has **no** `sync`/`feed` keys | **VERIFIED** | Live today: /api/dashboard captured 15 keys, generated_at ticking 13:16:12→13 per request; /api/dashboard/summary 13 keys, no feed/sync (P-12 fixed) |
| D5 | Guests CRUD + pass: register → integer `gid`; `/api/guest-pass/<gid>` returns matching pass; list contains guest | **VERIFIED** | Live today: POST /api/guests → {ok, gid, payload}; /api/guests list; /api/guest-pass/<gid> |
| D6 | Settings PUT round-trips and persists; keys validated vs SETTING_KEYS | **VERIFIED** | Live today: PUT echoes full settings object (NOT {ok:true}); expected_attendance 2500; GET after PUT identical |
| D7 | Test-data reset endpoint works (`/api/test-reset` → `{ok, removed}`) | **VERIFIED** | Today's audit: final reset `removed:3` — audit left DB counts unchanged (40/6/7/1/2/5) |

## Navigation

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| V1 | §29 volunteer tabs EXACTLY: Home, Scanner, Search, Guests, Settings — no dashboard destination, no duplicates | **CODE-VERIFIED** | app/(volunteer)/_layout.tsx Tabs exactly those five + hidden admin/broadcast (href:null); .expo/types/router.d.ts: /(volunteer)/search present, /dashboard ABSENT (P-02 fixed — re-checked today) |
| V2 | Home = §11 hierarchy — not a dashboard clone | **CODE-VERIFIED** | HomeScreen imports fetchDashboardSummary ONLY (re-verified today; P-03 fixed); 7-question composition; density refactor −35 lines (uncommitted, pre-Phase 34A) |
| V3 | Live Dashboard = §25 state view with no scan feed and no marketing text | **CODE-VERIFIED** | LiveBoardScreen renders LIVE, People Inside, Male/Female/Guests, Entries·15 min (from throughput[] — correct), Sync, Updated; **residual P-13: Gate activity rows derive from feed[] (lifetime) with misleading 15-min comment — targeted fix in Phase 34B** |
| V4 | Mode selection persists; launch routes to last mode or mode-picker | **CODE-VERIFIED** | store/appMode.ts (lgu.app_mode) preserved; app/index.tsx redirect logic re-read today |

## UI

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| U1 | Distinct LGU identity: official 444×444 RGBA transparent logo used in-app; emerald/gold system; no stock imagery | **CODE-VERIFIED** / **PENDING-USER (visual on device)** | PIL re-verified today: lgu-logo.png 444×444 RGBA (corner alpha 0 / center 255) via LguMark; hero + jpg retired; residual P-18 (navy launcher splash vs emerald) + P-21 documented — polish in Phase 34B |
| U2 | Sweep rule: no IPs, `:5000`, Flask, `127.0.0.1`, "fetch failed" in user UI | **VERIFIED** | Greps re-run TODAY: technical strings ×5 = **2 allowed** (Admin validation msg + placeholder `e.g. http://192.168.1.10:5000`) + **3 code comments** (store/settings.ts — not rendered); console.log ×5 all __DEV__-gated; placeholders ×8 = legit input hints |
| U3 | §37 data states on every screen: loading/success/empty/stale/offline/error+retry — never `- / -` | **CODE-VERIFIED** | UI kit exports re-counted today: LoadingState, EmptyState, ErrorState+onRetry, OfflineBanner, StatusPill, freshnessState; all 9 screens branch on these |
| U4 | Scan result moment: text + icon + level (not color alone), haptics, 4 s display, dedupe 4 s, gate+mode visible | **CODE-VERIFIED** / **PENDING-USER (device)** | ScannerScreen constants re-verified today (RESULT_DISMISS 4000, FRAME_DEDUPE 4000, ZOOM_MAX 0.45, STEP 0.025, TICK 80, QR_LEAVE 1400); expo-haptics by outcome; CameraView line 669; **P-14: file is 1127 lines — split required in Phase 34B (behavior preserved)** |
| U5 | Offline presentation: honest offline copy + genuine Retry; no Flask/IP/error internals | **CODE-VERIFIED** / **PENDING-USER (device)** | OfflineBanner + scanner enqueue path (ALREADY QUEUED / SCAN QUEUED amber); sanitized ApiError in client.ts (own AbortController 20s); networkError human strings re-read today |

## Build / process

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| B1 | §44: `tsc --noEmit` 0 errors | **VERIFIED** | `.\node_modules\.bin\tsc --noEmit` → `TSC_EXIT=0` at HEAD f51d0d1 (Phase 34 close); re-run required after any Phase 34B change |
| B2 | §44: `eslint app src` 0 errors | **VERIFIED** | `.\node_modules\.bin\eslint app src` → `ESLINT_EXIT=0` at HEAD f51d0d1; re-run required after any Phase 34B change |
| B3 | Metro Android bundle builds for this project (200 + real app code) | **VERIFIED** | `GET http://192.168.100.5:8082/.expo/.virtual-metro-entry.bundle?platform=android&dev=true` → **200, ~8.5MB**; markers: expo-router, GuestPass, ViewfinderCorners, Lahore Garrison; `/index.bundle` → 404 (main=expo-router/entry — expected) |
| B4 | §43: NO Expo upgrade — SDK 57.0.25, AsyncStorage 2.2.0 untouched | **VERIFIED** | package.json pins unchanged; Metro update notice 57.0.25→57.0.26 observed and IGNORED per §43 |
| B5 | §45: git safety — local commit only, **no push**, state recorded | **VERIFIED (Phase 34 close)** | HEAD **f51d0d1** (Phase 34 rebuild + docs); origin/main ee838a0 → **7 ahead, 0 behind, NOT pushed**. Phase 34A: **no commit made** — working tree contains only the 2 PRE-EXISTING uncommitted density files (GuestPassScreen.tsx, HomeScreen.tsx, +23/−52 — authored BEFORE Phase 34A) + Phase 34A doc refreshes; **application source unchanged by Phase 34A (§18)** |

## Device (physical phone)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| P1 | Expo Go connects to `exp://192.168.100.5:8082` and renders the 5-tab shell | **PENDING-USER** | Metro serves lgu on 8082 (bundle verified today); phone-side connection unobserved |
| P2 | Real QR scanning: camera preview, continuous detection, auto-zoom where bounds justify, result moments with haptics | **PENDING-USER** | ScannerScreen implements all on expo-camera 57.0.5 CameraView (props verified against installed types today); requires physical camera |
| P3 | Search on device: type ≥2 chars, results, guest → Guest Pass navigation via `gid` | **PENDING-USER** | Endpoint live-verified today; navigation wired + typed routes confirmed |
| P4 | Offline on device: disable Wi-Fi mid-shift → correct states, scans queue, Retry/Sync recovers after reconnect | **PENDING-USER** | §41 API-side + code-side verified only |
| P5 | DHCP switch on device: router reboot / new IP → app recovers without reinstall or source edit | **PENDING-USER** | Auto-discovery code preserved (re-read today); real network switch unobserved |
| P6 | Live Dashboard on device: fresh values, LIVE/STALE pills, gate activity, no feed | **PENDING-USER** | Screen code-verified against live-captured endpoints today; P-13 residual noted in V3 |

**Overall (Phase 34A):** every agent-verifiable row is green (VERIFIED or CODE-VERIFIED) — re-captured 2026-10-03. The acceptance gate (§47) closes only after the user reports P1–P6 — the rebuild is **not** declared complete until the physical phone works. Known open items (P-06, P-13..P-19, P-21) are documented in PROBLEMS.md and deferred to the §20M recommendation — **not implemented in Phase 34A**.
