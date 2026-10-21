# DEPENDENCIES — Verified installed versions + usage (Phase 34A, 2026-10-03)

Evidence: `mobile/package.json`, **node_modules package.json version dump of all 28 direct deps TODAY**, grep of imports in `mobile/{app,src}`, `.venv` pip facts. §43: no upgrades.

## Mobile — installed versions (verified from node_modules)

| Package | Installed | Used in app code? |
|---|---|---|
| expo | 57.0.25 | SDK (manifest runtime `exposdk:57.0.0`) |
| expo-router | 57.0.23 | main entry `expo-router/entry`, Tabs/Stack/router |
| expo-camera | 57.0.5 | ScannerScreen `CameraView`, `useCameraPermissions`, `BarcodeScanningResult` |
| expo-constants | 57.0.19 | hostUri discovery (settings.ts) |
| expo-haptics | 57.0.3 | ScannerScreen result haptics |
| expo-splash-screen | 57.0.9 | `app/_layout.tsx` line 2 — preventAutoHide/hide |
| expo-status-bar | 57.0.1 | `app/_layout.tsx` line 4 |
| react | 19.2.3 | — |
| react-dom | 19.2.3 | web target only (no direct import) |
| react-native | 0.86.3 | — |
| react-native-web | 0.21.3 | web target only (no direct import) |
| @react-native-async-storage/async-storage | 2.2.0 | settings/ops/offlineQueue/appMode — **NEVER CHANGE** |
| react-native-qrcode-svg | 6.3.26 | GuestPassScreen QR |
| react-native-reanimated | 4.5.1 | transitive UI motion (worklets 0.10.1) |
| react-native-safe-area-context | 5.7.0 | Screen + tab layout insets |
| react-native-screens | 4.26.2 | expo-router requirement |
| react-native-svg | 15.15.5 | kit primitives |
| @expo/vector-icons | 15.1.1 | Ionicons everywhere |
| expo-font | 57.0.4 | **no direct import** — transitive requirement of vector-icons |
| expo-linking | 57.0.11 | **no direct import** — transitive requirement of expo-router |
| expo-symbols | 57.0.3 | **UNUSED — zero imports in {app,src}** (P-16) |
| expo-web-browser | 57.0.3 | **UNUSED — zero imports in {app,src}** (P-16) |

devDeps installed: @types/react 19.2.3 · **@types/react-native 0.72.8 (STALE legacy package — RN 0.86 ships its own types; deprecated package can shadow/conflict — P-15)** · eslint 9.39.5 · eslint-config-expo 57.0.2 · typescript 5.9.3.

package.json scripts: `start` · `test:api` (node scripts/api-test.mjs) · `lint` (expo lint) · `tsc`. Main: `expo-router/entry`.

Metro notices `expo update available 57.0.25 → 57.0.26` — **observed and ignored per §43**.

## app.json (read today)

version 1.3.0 / versionCode 4 · package `pk.edu.lgu.smartconvocation` · scheme `lgu-smart-convocation` · orientation portrait · userInterfaceStyle light · splash bg **#0B2447 navy (legacy vs emerald system — P-18)** · adaptiveIcon bg #0B2447 · plugins: expo-router, expo-splash-screen, expo-camera (permission text set) · `experiments.typedRoutes: true` · owner kominman · eas projectId d0246603-e0e3-4327-bbf8-801ca99e30eb.

## Backend (Python 3.13.7 venv)

pip facts: `Flask==3.1.3`, `pillow==12.3.0`, `qrcode==8.2`, `tzdata==2026.4`. **tzdata REQUIRED on Windows (ZoneInfo("Asia/Karachi")) but NOT in app/requirements.txt** — P-06 (open, additive). Stdlib otherwise (csv/io/sqlite3/hmac/hashlib — no cryptography package).

## Validation commands (from mobile/)

- `.\node_modules\.bin\tsc --noEmit` (bin path — npx arg-passing unreliable here)
- `.\node_modules\.bin\eslint app src`
- Backend smoke: `.venv\Scripts\python.exe` + HTTP against test-record payloads; cleanup via POST /api/test-reset
- Metro bundle check: curl.exe to temp file with `-w` code/size (PowerShell floods at 20 KB on ~8.5 MB bundles)

## Constraints (recorded)

- No Expo/React upgrades; manifest stays exposdk:57.0.0; AsyncStorage 2.2.0 untouched.
- No new npm dependencies expected; any unavoidable addition must be justified in FINAL_REPORT.md.
- Cleanup candidates for the next implementation phase (NOT done in 34A): remove @types/react-native, expo-symbols, expo-web-browser (P-15/P-16); add tzdata to requirements.txt (P-06).
