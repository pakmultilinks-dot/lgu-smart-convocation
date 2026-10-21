# REBUILD_PLAN — Clean product architecture report (Phase 34A, 2026-10-03)

Status: **audit COMPLETE; rebuild recommendation DEFERRED to §20M** (Phase 34A rule: do not implement). Phase 34 already rebuilt the mobile shell (committed `f51d0d1`); this plan now defines what the clean architecture IS (evidence-backed) and what Phase 34B must fix — targeted changes, NOT a redesign.

## Product architecture (as built Phase 34 + as-audited Phase 34A)

- **Shell**: expo-router — root Stack → mode routing (launch index, mode-picker) → `(volunteer)` 5-tab shell (Home/Scanner/Search/Guests/Settings + hidden Admin/Broadcast) + top-level `(liveboard)` + `guest-pass` + `+not-found`. Single dashboard destination. Typed routes verified.
- **State**: `store/settings.ts` (discovery + modes, Phase 33 verbatim), `store/ops.ts` (gate/mode/last-result), `store/offlineQueue.ts` (dedupe + permanent rejections + positional reconcile), `store/appMode.ts` (volunteer|liveboard). No other global state.
- **Data**: `api/client.ts` (14 functions, per-module AbortController 20s, sanitized ApiError, fallback probe) + `api/settingsApi.ts`. All screens bound to verified API_CONTRACT endpoints only.
- **Presentation**: `src/ui/index.tsx` kit (19 exports) + `src/theme/*` tokens (emerald system, system font, 4/8/16/24/32/48 spacing, soft/raised elevation, freshness semantics).
- **Backend**: Flask routes.py (620 lines) + models.py derived-state KPIs + ids.py HMAC payloads + SQLite scans-as-source-of-truth. Business rules verified correct (DATA_MODEL §business rules).

## Five product areas — preserve / fix disposition

| Area | Preserve verbatim (verified) | Fix in Phase 34B (targeted) |
|---|---|---|
| Volunteer Operations | connectivity (settings/client/offlineQueue), ops store, test-scan tooling, offline queue reconcile, camera constants + auto-zoom/dedupe/haptics logic | **ScannerScreen split** (P-14: 1127 lines → zoom engine / result presentation / camera shell / test panel modules; behavior identical) |
| Live Dashboard | 2500ms poll + STALE_MS×3 + 1s clock + freshness pills + ProgressTrack + dark cards + mode switch; no scan-feed rendering | **P-13 fix**: Gate activity rows from throughput[]/sync (15-min truth) or relabel "Recent activity" — comment/label mismatch only |
| Admin | single entry point (hidden tab) + settingsApi probe + validation messages + gate rename + hostHint-only connectivity surface | none |
| Recovery/Search | 400ms debounce + requestSeq guard + 4 phases + state pills + gid navigation + "search only shows status" footer | none |
| Guest Pass | emerald treatment + perforation + monogram + QR 200 + title + search deep-link | none (density refactor already applied, uncommitted) |

## File disposition (maps to §20 J/K)

**Rebuild-candidates (targeted edits only):**
- `mobile/src/screens/ScannerScreen.tsx` — split per P-14 (density mandate).
- `mobile/src/screens/LiveBoardScreen.tsx` — gate-activity data source per P-13.
- `mobile/app.json` — splash/adaptive bg navy→emerald family per P-18.
- `mobile/package.json` — remove @types/react-native (P-15), expo-symbols, expo-web-browser (P-16).
- `app/requirements.txt` — add tzdata==2026.4 (P-06, additive).
- Optional (cosmetic): `app/database.py` drop idx_students_qr/idx_guests_qr (P-17).
- Optional (product decision): BroadcastScreen copy for demo-mode honesty (P-19).

**Untouched (verified clean; preserve):**
- All of `app/**` business logic (routes.py endpoints, models.py rules, ids.py, config.py, database.py schema except optional P-17).
- Connectivity layer: `store/settings.ts`, `api/client.ts`, `api/settingsApi.ts`, `store/offlineQueue.ts`, `store/ops.ts`, `store/appMode.ts`.
- UI kit `src/ui/index.tsx` + `src/theme/*` tokens.
- Route tree structure (`app/**` router files, tabs, redirects).
- Screens: HomeScreen, SearchScreen, GuestsScreen, SettingsScreen, AdminScreen, BroadcastScreen, GuestPassScreen (post-density state).
- All backend endpoints + business rules + API contract.
- AsyncStorage pin 2.2.0, SDK 57.0.25 — NO upgrades (§43).

## Non-regression checklist (carried into Phase 34B)

1. Backend endpoints/business rules unchanged (re-run audit script; search live; 29/29 smoke class outcomes).
2. AsyncStorage 2.2.0 untouched; discovery architecture preserved (no IP in source).
3. No Expo upgrade; manifest stays exposdk:57.0.0; Metro :8082.
4. Sweep rule: no technical strings in UI (Admin placeholder example only).
5. No push; local commit only after user device acceptance P1–P6.
6. Home ≠ Dashboard; five volunteer tabs; no duplicated destination; Search stays tab 3.
7. Scan result moment = text + icon + level + haptics (not color alone) — preserved in Scanner split.
8. Every undefined state has a designed state — never `- / -`.
9. tsc 0 / eslint 0 (bin paths) after every change.
10. LiveBoard still renders: LIVE, People Inside, Male/Female/Guests, Entries·15 min, Sync, Updated — no marketing text, no scan feed.

## Risk register

- **ScannerScreen split**: highest regression risk of Phase 34B — port logic verbatim into modules; behavior diff = none (constants preserved: RESULT_DISMISS 4000, ZOOM_MAX 0.45, STEP 0.025, TICK 80, QR_LEAVE 1400, FRACTION_COMFORT 0.42, FRAME_DEDUPE 4000).
- **P-13 data-source change**: throughput[] is 15-min truth; sync rows are lifetime — choose per-row semantics deliberately and label honestly.
- **expo-camera 57.0.5 API drift**: already verified against installed typings (props used: zoom/facing/autofocus/enableTorch/barcodeScannerSettings/onBarcodeScanned; unused: active/animateShutter/onMountError — add onMountError during split).
- **Dep removals (P-15/P-16)**: zero-import verified today; removal cannot break bundle — still re-run tsc/eslint/bundle.
- **Splash color (P-18)**: only app.json color values; regenerate launcher assets consistently (icon + adaptive + splash same bg).
- **Physical device results**: cannot be agent-verified — matrix marks P1–P6 PENDING-USER; acceptance closes only on user report.

## Deliverables index (Phase 34A set — 11 required docs refreshed today)

CURRENT_STATE, ROUTES, API_CONTRACT, DATA_MODEL, DEPENDENCIES, DEVICE_RUNTIME, UI_INVENTORY, PROBLEMS, REBUILD_PLAN (this file), DESIGN_RESEARCH, ACCEPTANCE_MATRIX — all in docs/phase34-product-reset/, all 2026-10-03 dated. (IA.md, VISUAL_SYSTEM.md, FINAL_REPORT.md remain Phase 34-era — not in the Phase 34A required set.)
