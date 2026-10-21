# DEVICE_RUNTIME — Network + runtime facts (Phase 34A, verified 2026-10-03)

Evidence: `ipconfig`, `netstat -ano`, `Get-CimInstance` process commands, live HTTP probes TODAY. §4: never confuse Wi-Fi with WSL/Hyper-V/virtual adapters.

## Host interfaces

| IP | Interface | Verdict |
|---|---|---|
| **192.168.100.5** | **Wi-Fi** | ✅ THE LAN ADDRESS — phone-facing (`exp://192.168.100.5:8082`, `http://192.168.100.5:5000`) |
| 192.168.192.1 | vEthernet (WSL Hyper-V) | ❌ virtual adapter — never publish |

History (P-05): past hard-coded IPs (192.168.18.79 etc.) were DHCP leases. App discovers host from `Constants.expoConfig.hostUri` → `http://<host>:5000` (Phase 33, preserved); no hard-coded IP in mobile source.

## Services (today)

| Service | Bind | PID | Phone path | State |
|---|---|---|---|---|
| Flask | 0.0.0.0:5000 | **9788** (`.venv\Scripts\python.exe app\run.py`) | `http://192.168.100.5:5000` | Working, SINGLE listener (P-07 resolved) |
| Metro lgu | 0.0.0.0:8082 | **1640** (`expo cli start --port 8082`) | `exp://192.168.100.5:8082` | Working |
| Metro UniServe (other workspace) | 0.0.0.0:8081 | **7556** (`expo start --web`) | — | Foreign auto-respawning watcher — **DO NOT kill or fight** |

Metro manifest (expo-platform: android): runtime `exposdk:57.0.0`, launchAsset `http://192.168.100.5:8082/node_modules/expo-router/entry.bundle?platform=android&dev=true&hot=false&lazy=true&transform.engine=hermes&transform.bytecode=1&transform.routerRoot=app&unstable_transformProfile=hermes-stable`.

**Bundle URL quirk**: `/index.bundle` → 404 ("Unable to resolve ./index" — main is `expo-router/entry`, no root index.js). Smoke URL that works: `http://192.168.100.5:8082/.expo/.virtual-metro-entry.bundle?platform=android&dev=true` (verified 200, ~8.5 MB, content markers expo-router/GuestPass/ViewfinderCorners/Lahore Garrison/Show guest pass).

## Launch procedures (verified patterns — reuse)

- Flask (detached): `cmd /d /s /c "cd /d <repo> && .venv\Scripts\python.exe app\run.py > flask.log 2>&1"` via Start-Process — PowerShell Set-Location FAILS inside cmd /c.
- Metro (detached): build `$cmd` variable FIRST, `set REACT_NATIVE_PACKAGER_HOSTNAME=192.168.100.5 && npx expo start --port 8082 > metro.log 2>&1` in mobile dir. Cold start 45–90 s. Always detached (VS Code terminal cleanup kills attached processes).
- Stale-hung Metro: `Stop-Process` + relaunch on 8082.
- Terminal quirks: variable-based commands and pipes sometimes mangled at session start — retry simple single-line commands; curl probes are reliable.

## Verification status matrix (device question L)

| Item | Status |
|---|---|
| Backend API contract (all endpoints, business rules) | **LAPTOP-VERIFIED** (live captures 2026-10-02 + 2026-10-03) |
| Metro serving this project (manifest + bundle 200) | **LAPTOP-VERIFIED** (8082) |
| tsc 0 / eslint 0 | **LAPTOP-VERIFIED** |
| DB schema/counts/derived metrics | **LAPTOP-VERIFIED** (read-only) |
| Expo Go connects to exp://192.168.100.5:8082, renders shell | **PENDING-USER** (P1) |
| Real camera scanning + auto-zoom + haptics on device | **NEVER-VERIFIED BY AGENT** (P2) |
| Offline queue behavior on device (airplane mode) | **NEVER-VERIFIED BY AGENT** (P4) |
| DHCP switch recovery on device | **NEVER-VERIFIED BY AGENT** (P5) |
| Live render/freshness pills on device | **PENDING-USER** (P6) |

## Phone-side requirements (user performs, §39/§47)

1. Phone on SAME Wi-Fi (192.168.100.x). 2. Expo Go → `exp://192.168.100.5:8082`. 3. Backend auto-resolves → health 200. 4. Camera permission. 5. Airplane-mode toggle for offline queue. 6. **Never label the product "working" from laptop HTTP tests alone.**

## Sweep rule (§7)

`192.168.*`, `:5000`, `Flask`, `127.0.0.1`, `Hyper-V`, `WSL` must NEVER appear in user-facing UI text. Allowed: code comments, Admin Backend Connection (config surface), docs. Today's grep: 5 hits — 2 user-facing (AdminScreen validation + placeholder, both allowed) + 3 code comments (store/settings.ts, not rendered).
