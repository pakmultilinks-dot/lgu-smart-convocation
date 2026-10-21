# UI_INVENTORY — Current mobile UI (Phase 34 state, re-audited 2026-10-03)

Evidence: file reads + greps + exact line counts TODAY against the Phase 34 rebuild (`f51d0d1`). 2 uncommitted density refactors (GuestPassScreen/HomeScreen) predate Phase 34A.

## Theme tokens (src/theme/* — read today)

- `colors.ts`: greenDark #0A3622, greenDeep/green #0F5132, emerald #157347, emeraldSoft #E8F5E9, mint #A7D9BC, tint #EDF3EE, background #F6F8F7, card #FFFFFF, text #0F172A, muted #64748B, border #E2E8F0, overlay rgba(10,54,34,0.55), gold #B8912A, goldSoft #F6EED6, red #B3261E, redSoft #F9E4E2, amber #9A6B1A, amberSoft #FBF0D9.
- `typography.ts`: metric 40 / display 32 / title 24 / heading 20 / subheading 17 / body 15 / label 13 / caption 12 / small 11; weights 400–700; letterSpacing tight −0.8 / normal 0 / caps 1.2. **System font — no typeface identity (P-21 factor; §16 decision kept).**
- `spacing.ts`: xs 4 / sm 8 / screen 20 / md 16 / lg 24 / xl 32 / xxl 48; radius sm 8 / md 12 / lg 16 (+full 999).
- `elevation.ts`: soft {greenDark 0.06, r12, {0,4}, e2} · raised {0.12, r16, {0,6}, e5}. Depth = tonal + elevation.
- Freshness semantics: live=emeraldSoft/greenDeep/emerald dot · stale=tint/muted · offline=amberSoft/amber — preserved, evidence-driven, correct.

## UI kit (src/ui/index.tsx — 815 lines, 19 exports, read today)

Screen, AppHeader, LguMark, SectionEyebrow, MetricBlock, StatusPill, SegmentedControl, AppButton, Field, ListRow, SectionCard, ProgressTrack, EmptyState, ErrorState, LoadingState, OfflineBanner, formatClock, formatServerClock, freshnessState.

## Screens (9) + composition evidence (exact total lines today)

| Screen | Lines | Composition verified today |
|---|---|---|
| ScannerScreen | **1127** | Constants (RESULT_DISMISS 4000, ZOOM_MAX 0.45, STEP 0.025, TICK 80, QR_LEAVE 1400, FRACTION_COMFORT 0.42, FRAME_DEDUPE 4000); useCameraPermissions; dynamic fetchGates import (line 170); auto-zoom tick effect; handleBarcode bounds→targetZoomRef; ops persistence; test-scan section; CameraView at line 669 (facing="back", enableTorch, zoom, autofocus="off", barcodeScannerSettings={{barcodeTypes:["qr"]}}) — **P-14 density violation; camera logic itself sound** |
| AdminScreen | 406 | Backend Connection card (auto/custom mode chip + probe + switch-back), Convocation Details, Expected Attendance, Volunteer, Gates |
| LiveBoardScreen | 343 | polls fetchDashboard 2500ms + STALE_MS×3 + 1s freshness clock; dark SectionCards; People Inside metric + ProgressTrack; Male/Female/Guests split; **"Gate activity" derives from data.feed[] (last-20-scans LIFETIME) filtered to entries — comment claims "live 15-minute feed" but feed has NO time filter (P-13); throughput[] IS the 15-min data and correctly powers "Entries · 15 min"**; Updated=formatServerClock(generated_at); Switch mode button |
| HomeScreen | 340 (326 non-empty) | imports fetchDashboardSummary ONLY; 7-question composition (Assignment → progress → dominant Scan QR Code → Search recovery → Last scan → Status); single refresh callback (uncommitted density refactor, −35); OfflineBanner onRetry |
| SearchScreen | 279 | 400ms debounce, requestSeq race guard, 4 phases idle/loading/error/done, stateForHit pills (PASS USED / PASS READY / INSIDE / NOT INSIDE YET), guest → /guest-pass?gid=, footer note "search only shows status, the gate records the scan" |
| GuestsScreen | 277 | filter all|active|used, 300ms debounce, register form → guest-pass navigation |
| SettingsScreen | 239 | volunteer name save, mode display+switch, backend connection summary (hostHint only — never raw URL), queue count pill, quick actions Broadcast + Reset mode |
| BroadcastScreen | 225 | audience + message + send → demo-mode note (P-19) |
| GuestPassScreen | 186 (177 non-empty) | greenDark→greenDeep field, perforation, monogram, QR size 200 via react-native-qrcode-svg (uncommitted density refactor, −10) |

Total mobile/src = **3662 lines** (screens) + 815 (kit) + ~1200 (stores/api/theme) — phase-34 rebuild density.

## Assets (PIL-verified dimensions + alpha)

| File | Dimensions | Mode | Verdict |
|---|---|---|---|
| lgu-logo.png | **444×444** | **RGBA** | ✅ Official crest via `LguMark`; corner alpha=0, center 255 — genuinely transparent, high enough resolution for ≤64dp display |
| lgu-logo.jpg | 148×148 | RGB | ❌ Retired (tiny JPEG, white bg) |
| convocation-hero.jpg | 1920×1280 | RGB | ⚠️ **EXIF NONE** — no provenance; retired per §18 |
| icon/adaptive-icon | 1024×1024 | RGB | Launcher only; bg **#0B2447 navy (legacy — P-18 vs emerald system)** |
| splash.png | 1242×2436 | RGB | Launcher splash |
| favicon.png | 48×48 | RGB | Web only |

## Connectivity architecture (Phase 33 — PRESERVED VERBATIM, re-read today)

- `store/settings.ts` (156 lines): keys lgu.api_base_url / lgu.api_base_url_mode / lgu.volunteer_name; BACKEND_PORT 5000; `getDiscoveredBackendUrl()` reads Constants.expoConfig.hostUri (standalone/__DEV__ guards, host regex `^[A-Za-z0-9.\-]+$`); auto mode = session → discovered → stored; custom mode only on admin save; `probeBackend()` 5s AbortController /api/health; `noteUnreachableBaseUrl` (custom never replaced); `resetToAutomaticBackend` (non-use* name — eslint react-hooks rule).
- `api/client.ts` (348 lines, 14 functions): per-module send() with own AbortController (REQUEST_TIMEOUT_MS 20000), sanitized ApiError, two human networkError strings, one-time fallback via noteUnreachableBaseUrl, `__DEV__` console.log only.
- `api/settingsApi.ts`: getSettings/updateSettings → AdminScreen.
- `store/offlineQueue.ts` (109): key lgu.offline_scan_queue; dedupe same payload+mode; PERMANENT_REJECTIONS set; positional reconcile (entry+exit same person both kept).
- `store/ops.ts` (62) + `store/appMode.ts` (16): scanner writes/reads gate+mode+result; volunteer|liveboard mode.

## Sweep evidence (greps today)

- "placeholder" ×8 = legitimate input hints (Admin URL example, search/guests/broadcast fields) + 2 code comments — no fake content.
- `console.log` ×5 — all `__DEV__`-gated in client.ts/settingsApi.ts (LogBox discipline).
- Technical strings ×5 = **2 user-facing** (AdminScreen validation msg + placeholder `e.g. http://192.168.1.10:5000` — allowed config surface) + **3 code comments** in store/settings.ts (not rendered).

## Product-question coverage (§9/§11/§25 vs today)

| Required question | Where answered today | Gap |
|---|---|---|
| Which gate / entry-exit | Scanner chips + Home assignment block + ops store | ✅ |
| Online? | OfflineBanner + health probe | ✅ |
| Processed count | Home event progress (summary) | ✅ (dashboard-flavored duplication gone — P-03 fixed) |
| How to scan | Home dominant CTA | ✅ |
| Last scan result | Home last-scan strip | ✅ |
| QR fail recovery | Scanner errors → **Search tab exists (tab 3) + Home recovery action** | ✅ P-01 fixed |
| Inside/expected/male/female/guests | LiveBoard (attendance progress + roster split) | ✅ P-20 semantics: attendance-vs-roster labeled honestly |
| Active gates / synced / updated | LiveBoard sync + updated | ✅ |
| Attendee search | SearchScreen (name/roll/phone/host) | ✅ P-01 fixed |

## Residual "generic feel" factors (P-21 — feeds §20C)

1. **System font** — hierarchy from scale/weight only; no typographic brand identity.
2. **Splash/adaptive bg #0B2447 navy** vs emerald product system (P-18) — brand mismatch on every cold start.
3. **Uniform SectionCard rhythm** across Settings/Search/Guests/Admin — consistent but low-distinction.
4. **LguMark small (36dp)** on most screens — crest under-used as identity anchor.
5. ScannerScreen length (1127) is a maintainability problem (P-14), not a visual one.
