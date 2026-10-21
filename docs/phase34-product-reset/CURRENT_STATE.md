# CURRENT_STATE — Phase 34A forensic baseline (2026-10-03)

All statements verified by terminal capture or file inspection TODAY (2026-10-03). **Phase 34A modified no application source code** (§18; the 2 modified files below predate this phase).

## Repository

- Branch `main`, HEAD **`f51d0d1`** — "feat: Phase 34 product reset — clean mobile rebuild, search endpoint, audit docs".
- `origin/main` = `ee838a0` (v1.3.0). `git rev-list --left-right --count origin/main...HEAD` → **`0 7`** — 7 local commits, 0 behind, **NOT pushed** (§45 kept).
- History: `f51d0d1` (Phase 34) · `02b207e` (Phase 33) · `801e7d0` (32) · `48acbe1` (31) · `91c8821` (30) · `5d52a59` · `238d77f` · `ee838a0` (origin) · `29020df` · `9b53dd4`.

## Working tree at Phase 34A start AND end (unchanged by this phase)

```
 M mobile/src/screens/GuestPassScreen.tsx
 M mobile/src/screens/HomeScreen.tsx
```
- `git diff --stat` = **2 files, +23 insertions, −52 deletions**.
- Pre-existing **density refactor** (single `refresh` callback pattern, −45 net lines) made BEFORE Phase 34A began — legitimate prior work, **not a Phase 34A violation**. Not committed in this phase (audit is read-only + docs).

## Live runtime (verified today)

| Process | Evidence | State |
|---|---|---|
| Flask on 0.0.0.0:5000 | netstat PID **9788** (`.venv\Scripts\python.exe app\run.py`), single listener | Working; `GET /api/health` → `{"app":"LGU Smart Convocation","ok":true,"version":"LGU1"}` |
| Metro lgu on 0.0.0.0:8082 | PID **1640** (`expo cli start --port 8082`) | Working; manifest 200, runtime `exposdk:57.0.0`, launchAsset `http://192.168.100.5:8082/node_modules/expo-router/entry.bundle?platform=android...` |
| Port 8081 | PID 7556 = **UniServe** (`expo start --web`, other workspace, auto-respawner) | Foreign project — lgu NEVER uses 8081; do not kill |
| Wi-Fi IPv4 | `192.168.100.5` | THE phone-facing address (`exp://192.168.100.5:8082`) |
| vEthernet WSL Hyper-V | `192.168.192.1` | Virtual adapter — never publish |

- Flask debug=False — no auto-reload; restart manually after backend edits.
- Metro update notice `57.0.25 → 57.0.26`: **DO NOT upgrade** (§43).

## Product layout (post-Phase 34)

1. `app/` — Flask 3.1.3 + SQLite backend (config/database/ids/models/qrgen/run + `web/routes.py` + templates/static). Business logic re-verified today (11 scenario captures; 29/29 smoke from 2026-10-02).
2. `mobile/` — Expo SDK 57 / RN 0.86.3 / React 19.2.3 expo-router app, **clean rebuild committed in `f51d0d1`**: 15 route files, 9 screens in `src/screens/`, shared kit `src/ui/index.tsx` (815 lines, 19 exports), theme tokens (`colors/typography/spacing/elevation`), connectivity layer preserved verbatim (Phase 33). `src/components/` deleted in Phase 34.
3. `docs/phase34-product-reset/` — this audit set (11 required docs, refreshed today) + IA.md / VISUAL_SYSTEM.md / FINAL_REPORT.md (Phase 34 originals, left as-is).

## Database at audit time (read-only PRAGMA + counts)

students=**40** (20 Male / 20 Female, rolls LGU-2024-101…), guests=**6** (incl. 2 "Smoke Test Guest" rows + "Phase Test Guest" used:true), gates=**7** (G1 Main … G7 Sports Complex Gate), scans=**1** (guest T5483B4R entry G3, source=online, 2026-10-01; audit scripts cleaned their own scans via final `test-reset`), broadcasts=2, settings=5 (`expected_attendance=2500`, name "LGU Smart Convocation 2026", year 2026, datetime `2026-12-12T09:00:00+05:00`, venue "Lahore Garrison University, Lahore").

## Codebase metrics (exact, today)

| File | Total lines | Note |
|---|---|---|
| ScannerScreen.tsx | **1127** | Longest screen — violates the user's density mandate (P-14) |
| AdminScreen.tsx | 406 | |
| LiveBoardScreen.tsx | 343 | |
| HomeScreen.tsx | 340 (326 non-empty) | Post-density-refactor (uncommitted) |
| SearchScreen.tsx | 279 | |
| GuestsScreen.tsx | 277 | |
| SettingsScreen.tsx | 239 | |
| BroadcastScreen.tsx | 225 | |
| GuestPassScreen.tsx | 186 (177 non-empty) | Post-density-refactor (uncommitted) |
| src/ui/index.tsx | 815 | 19 exports |
| src/api/client.ts | 348 | 14 functions + types |
| src/store/* | 16/109/62/156 | appMode/offlineQueue/ops/settings |

- Quality gates at HEAD: `tsc --noEmit` **0**, `eslint app src` **0** (re-verified after the density refactor).

## Phase 34 problem dispositions (re-verified today)

| # | Problem | Phase 34A status |
|---|---|---|
| P-01 | `/api/search` 404 | **FIXED** — live: `q=nasir` → guest hit `gid:1`; `q=a` → 400 |
| P-02 | Duplicate dashboard nav | **FIXED** — tabs exactly home/scanner/search/guests/settings; no dashboard route on disk |
| P-03 | Home pulled full dashboard | **FIXED** — HomeScreen imports `fetchDashboardSummary` only |
| P-04 | EXIF-less hero | **FIXED** — hero retired; abstract branded treatment |
| P-05 | Hard-coded IPs | **FIXED** — discovery architecture; only allowed UI string = Admin placeholder |
| P-06 | tzdata not in requirements.txt | **OPEN (additive)** — venv has tzdata 2026.4; backend edit deferred per audit rule |
| P-07 | Duplicate Flask PIDs | **RESOLVED operationally** — single PID 9788; 8081 is UniServe (separate, do-not-touch) |
| P-08 | 148px logo | **FIXED** — `lgu-logo.png` 444×444 RGBA transparent via `LguMark` |
| P-09 | Guest exit amber unreachable | **DOCUMENTED, no change** — `guest_used` counts any scan first; re-captured today |
| P-10 | Live-data root cause | **FIXED** — mobile connectivity (Phase 32/33) preserved verbatim in Phase 34 |
| P-11 | Generic identity | **ADDRESSED** — emerald system + crest + state-complete kit; residual factors = P-18/P-21 |
| P-12 | Feed on dashboard | **FIXED** — summary has no `feed`/`sync` keys (live capture today) |

New findings from this audit: **P-13..P-21** (see PROBLEMS.md).

## Live product verdict (Phase 34A read)

- **Backend: working** — all endpoints live-captured today; business rules re-verified via 11-scenario audit script (entry green, duplicate red w/ gate+time detail, exit green, guest entry + host sub, guest reuse red, invalid signature red, null gate red, sync of used guest → synced:0 permanent rejection, final test-reset cleaned audit scans).
- **Live data path: sound end-to-end** — SQLite → models.dashboard() → /api/dashboard (generated_at live per request, 13:16:12→13 captured) → client.ts fetchDashboard (20s AbortController, sanitized errors, one-time fallback) → LiveBoard poll 2500ms w/ freshness. The historical live-data failure was mobile connectivity (P-05/P-10), fixed; physical-device confirmation remains user-side (P1–P6).
- **Mobile product: post-Phase-34 clean rebuild committed (`f51d0d1`)** — 5 exact volunteer tabs, search live, summary-only Home, connectivity verbatim. Residual issues are P-13..P-21 (see PROBLEMS.md): feed/label mismatch on LiveBoard, scanner density, stale devDep, unused deps, redundant indexes, navy splash, demo-mode broadcast honesty, dual expected semantics, residual genericity factors.

## Hard constraints carried forward

- Backend preserved unless endpoint proven missing/broken (§36). Search (the only proven gap) shipped in Phase 34 as additive GET /api/search.
- No Expo upgrade (exposdk:57.0.0; 57.0.26 notice ignored). No push. AsyncStorage 2.2.0 untouched.
- No hard-coded DHCP IP in mobile source; discovery architecture preserved verbatim.
- Phase 34A = audit only; next implementation phase executes REBUILD_PLAN.md targets (P-13/P-14/P-15/P-16/P-17/P-18 + device acceptance).
