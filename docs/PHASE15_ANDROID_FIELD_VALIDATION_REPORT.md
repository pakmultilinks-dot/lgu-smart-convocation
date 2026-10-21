# Phase 15 — Android Field Validation & Scanner Operational Readiness

**Objective:** Validate the secured volunteer scanner and student digital pass
on a real Android device, establish a reproducible local testing workflow, and
close any demonstrated operational defects.

**Outcome:** The §6 *device-unavailable fallback* path was executed. The
backend/scanner/server-side acceptance criteria were exercised end-to-end over
HTTP against a disposable database. **No physical Android device, emulator, or
Android SDK was available on this machine, so no camera-based scan was
performed and none is claimed.** No production data was touched.

---

## 1. Environment & tools detected

| Tool | Value |
|---|---|
| OS | Windows 11 (LAN IP `192.168.100.5`) |
| node | v24.14.0 |
| npm | 11.9.0 |
| Expo CLI | 57.0.27 (`npx expo --version`) |
| Expo SDK / RN | Expo 57 / React Native 0.86.3 / React 19.2.3 / expo-router |
| Python venv | repo-local `..\.venv` (from `app/`) |
| **adb** | **NOT FOUND** (`ANDROID_HOME=[]`, `ANDROID_SDK_ROOT=[]`) |
| **Android SDK** | **ABSENT** (no SDK dir) |
| **Emulator** | **NOT FOUND** |
| Ports in use before work | **3010 only** — UniServe Next dev server (pid 4692, *untouched*). Port **5000 free**. |

Because `adb`, the Android SDK, and an emulator are all absent, on-device
camera testing is **impossible** on this host. Per the brief, no large SDK was
installed and no system-wide change was made; the fallback path was taken.

## 2. Reproducible local field-testing workflow

**Backend (isolated, disposable DB) — the exact job that was run:**

```powershell
# from repo root
New-Item -ItemType Directory -Force $env:TEMP\lgu15-field | Out-Null
$env:LGU_TESTING='1'
$env:LGU_DB_PATH="$env:TEMP\lgu15-field\field.db"
$env:LGU_EMAIL_MODE='fake'
$env:LGU_PORT='5000'
Start-Job -ScriptBlock { Set-Location 'C:\Users\Lenovo\Documents\Code_PlayGround\LGU\lgu-smart-convocation\app'; ..\.venv\Scripts\python.exe run.py }
```

- Flask binds `0.0.0.0` (`app/run.py` → `app.run(host="0.0.0.0", port=port)`),
  so the phone reaches it at the laptop's LAN IP — verified
  `http://192.168.100.5:5000` → HTTP 200.
- `LGU_TESTING=1` makes startup call `config.require_test_db()`, which refuses
  to run if `LGU_DB_PATH` points at `app/lgu.db` (`is_production_db()`). This
  is the hard guard that keeps the test phone away from production.
- The disposable DB is seeded by `init_db()` + `seed()`: 7 gates (G1–G7,
  ids 1–7), 40 students (`LGU-2024-101`…`-140`), 3 guests at hosts 101/106/112.
- Teardown: `Stop-Job`/`Remove-Job` for the job **only** (UniServe's pid 4692
  was never touched), then the temp dir was deleted.

**Expo (for the phone) — NOT launched, since no device was available:**

```powershell
cd mobile
npm install
npx expo start        # press 'a' for emulator (none present) or scan QR in Expo Go
```

**How the phone finds the backend (no source edit).** In dev/Expo Go the app
reads Metro's own host from `Constants.expoConfig.hostUri` and targets
`http://<that-host>:5000` (`mobile/src/store/settings.ts`,
`getDiscoveredBackendUrl()`). It reuses the phone's live DHCP address, so a
Wi-Fi change needs no rebuild. A different server can be entered as a
**Custom server URL** in Settings/Admin (validated `http://` address,
persisted to AsyncStorage). `mobile/src/config.ts` holds **display-only**
fallbacks and no backend URL. This avoids the classic "phone's localhost"
trap.

**Test vs real separation (verified live):** the demo/test endpoints
(`/api/demo-payload`, `/api/test-records`, `/api/test-scanner-session`)
returned live data on the disposable DB and are configured to return **404**
on production (guarded; confirmed in prior phases).

## 3. Scanner provisioning & gate authorization (8/8 PASS)

Run through `app/scripts/manage_scanner_staff.py` + real `POST /api/scanner/*`
routes against the disposable DB. No secrets are reproduced here.

1. **Create** — created scanner id 1 (`gateA-ana`, "Ana Cruz"), gate 1. PIN
   printed **once** by the CLI (8 chars, `…` redacted in this report).
2. **Single explicit gate** — the account is bound to gate 1 only.
3. **Secure credential** — PIN is stored **scrypt-hashed** by the CLI; the
   plaintext is never persisted.
4. **Authenticate** — real `POST /api/scanner/login` → `ok:true`, a one-time
   bearer token (43 chars), `DISPLAY=Ana Cruz`, `GATES=1`.
5. **No secret leakage** — the login response contains **only** the one-time
   token; no `pin_hash`, PIN, or session secret is returned.
6. **Revocation** — `revoke 1` → sessions invalidated; the still-live token
   then returns **401**.
7. **Second scanner** — created scanner id 2 (`gateC-bilal`, "Bilal Aslam"),
   gate 3; PIN rotated via `pin 2`.
8. **Server-side gate enforcement** — scanner 1 at gate 2 → **403**; scanner 2
   at gate 1 → **403**; scanner 2 at gate 3 → **ENTRY RECORDED**. Gate
   authorization is enforced server-side, not by the client.

## 4. Student-to-gate acceptance (server-side, over HTTP)

> These are **HTTP-level** results against the real routes and DB. They do
> **not** involve a device camera and are not claimed as camera evidence.

| Check | Result |
|---|---|
| Volunteer-name spoof (scan body `volunteer:"SPOOFED NAME"`) | Recorded volunteer = **"Ana Cruz"** — server derives it from the token; spoofing blocked. |
| Duplicate entry (same student QR again) | **ALREADY INSIDE** — "Ali Raza (LGU-2024-104) already entered at West Gate, 2026-10-12 01:26:19". |
| Forged QR `LGU1:FORGED00:deadbeef00` | **INVALID CODE** — "Signature check failed. This code is tampered or forged." |
| Legacy guest pass (valid sig) | First scan → **GUEST ENTRY RECORDED**; second → **ALREADY USED** ("One entry per guest."). |
| `/api/dashboard/summary` | Matches the disposable DB exactly: `inside_total=4`, `guests_inside=1`, male=2 / female=2, busiest gate = "West Gate", throughput G1=2 / G3=3, roster=40, guest_registrations=3. |

## 5. Android device / emulator / camera evidence

**NONE AVAILABLE — nothing fabricated.** No physical Android device was
connected, no emulator exists, and no Android SDK/`adb` is installed on this
host. Therefore:

- No QR was ever scanned through a device camera.
- No photo/screenshot evidence exists for the on-device UI (T1 sign-in prompt,
  T3 on-device admission, T5 on-device 403).
- The offline→sync path was validated only by **unit tests of the queue
> logic** (`mobile/scripts/scanner-logic-test.mjs`), not on real hardware.

## 6. Regression & integrity battery (all green)

Clean environment (leaked `LGU_*` env vars cleared first).

| Battery | Command | Result |
|---|---|---|
| Python suites (15) | `cd app; ..\.venv\Scripts\python.exe scripts\test_*.py` | **15/15 PASS** |
| Mobile suites (32) | `cd mobile; node scripts\*.mjs` | **32/32 PASS** |
| TypeScript | `npx tsc --noEmit` | **0 errors** |
| ESLint | `npx eslint .` | **0 errors**, 2 pre-existing `no-unused-vars` warnings |
| Whitespace | `git diff --check` | exit 0 — only benign LF/CRLF notices |

Python suites: convocation_migration, event_announcements, exam_auth,
exam_dashboard, exam_registration, medalist_management, phase10_readiness,
phase11_pass_history, phase12_qr_scanner, phase13_e2e_acceptance,
**phase14_scanner_access**, phase8_acceptance, phase8_integration,
phase9_support, student_accounts.

The Phase 14 scanner-access suite (48 checks) and the mobile
`scanner-logic-test.mjs`/`gate-integrity-test.mjs`/`release-safety-test.mjs`
suites all pass, confirming the security and integrity guarantees that §3–§4
re-verified live.

## 7. Defects closed

- **Fixed — `docs/PHASE14_FIELD_TEST_GUIDE.md` §3 (documented defect).** The
  guide claimed "Backend must be reachable at the URL configured in
  `mobile/src/config.ts`" — factually wrong, since `config.ts` contains no
  backend URL. Rewritten to describe the real behavior: the app auto-discovers
  the backend host from Metro's `hostUri` (no source edit), Flask binds
  `0.0.0.0` so the phone uses the laptop's LAN IP, the firewall must allow
  inbound TCP 5000 on the Wi-Fi/private profile, and a Custom server URL is
  settable in Settings/Admin. Added a **"Keeping test and real environments
  separate"** subsection (`LGU_DB_PATH` disposable + `LGU_TESTING=1` vs. unset
  for production; test endpoints 404 on prod; never point the phone at
  `app/lgu.db`).
- **Added — operator runbook (`§4b`) for failed passes / backend-down.** The
  brief asked whether the operator instructions explain what to do when a
  pass is invalid/expired/already-used and when the backend is unavailable.
  They didn't, so a concise runbook table was added covering the real screen
  titles and actions (`ALREADY INSIDE`, `ALREADY USED`, `NOT INSIDE`,
  `INVALID CODE`, `UNKNOWN CODE`, `GUEST PASS IS ENTRY ONLY`,
  `GATE NOT AUTHORIZED`, 401 re-auth, 429 rate-limit) plus offline-queue
  behavior and backend-connection troubleshooting. Every row was checked
  against the actual app source (offline queue in `offlineQueue.ts`, 401
  session-clear in `ScannerScreen.tsx`, offline toggle in
  `ScannerBottomBar.tsx`) — **no invented capability**.
- **No new automated regression test was required.** The brief conditions a
  new test on a provisioning step that "exposes secrets unnecessarily, bypasses
  authorization, or leaves an account ambiguously configured." No such defect
  occurred — provisioning, auth, revocation, and gate authorization all behaved
  correctly (§3). The fix was documentation accuracy per §5.

## 8. Production DB integrity (before → after)

| | SIZE | SHA256 | MTIME (UTC) |
|---|---|---|---|
| **Before** | 278528 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | 2026-10-10T19:35:21.8392785Z |
| **After** | 278528 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | 2026-10-10T19:35:21.8392785Z |

Byte-for-byte **identical** — production `app/lgu.db` was never opened for
writing. All Phase 15 HTTP work ran against the disposable temp DB, which has
been deleted.

## 9. Final git status & whitespace

- **No git destructive commands were run** (no commit/push/deploy/reset/clean/
  stash/discard). The parent umbrella repo and unrelated projects were not
  operated on; UniServe (pid 4692, port 3010) was never touched.
- **All Phase 5–15 work is preserved, uncommitted.** Working tree: **51
  modified tracked files** and **81 untracked new paths**, spanning backend
  modules (`app/*.py`, `app/web/*_routes.py`, migrations), the 15 test scripts,
  mobile screens/store/scanner/scripts, `docs/` reports and evidence, and
  `screenshots/`.
- New in this phase: `docs/PHASE14_FIELD_TEST_GUIDE.md` (§3 fixed, §4b added)
  and this report.
- `git diff --check` → exit 0, only benign LF/CRLF conversion notices
  (`mobile/app.json`, `mobile/package.json`, `mobile/package-lock.json`).

## 10. Remaining prerequisites (verified vs unverified)

**Verified (automated / server-side — reproducible on this host):**
- Scanner provisioning, scrypt PIN hashing, login, revocation, session TTL —
  live HTTP + `test_phase14_scanner_access.py`.
- Server-side gate authorization (403 cross-gate) and server-derived volunteer
  name (spoof blocked) — live HTTP.
- Duplicate-entry, forged-QR, guest-single-use guards — live HTTP.
- Dashboard/live-board counts sourced from the real scan ledger — live HTTP.
- Offline-queue logic (dedup, per-item re-auth on sync) — unit tests.
- Mobile base-URL auto-discovery and Custom-server-URL path — source + tests.
- Test/prod separation (demo endpoints 404 on production) — guard verified.

**Unverified — requires a real Android device / camera (NOT performed here):**
- **Actual camera scan of a student QR through Expo Go on Android.**
- On-device sign-in prompt (T1), admission confirmation (T3), on-device
  GATE-NOT-AUTHORIZED (T5), and their photo/screenshot evidence.
- Offline → reconnect → queue-sync end-to-end on real hardware (T6).
- Real Wi-Fi DHCP handover (phone re-follows the laptop's changed IP) and the
  firewall inbound-TCP-5000 step on the actual Windows firewall profile.
- Camera-permission grant/deny dialogs and backgrounded/resumed camera state
  on a physical device.

**To complete the device phase later:** install Android Studio / `adb`
(optionally a system image), connect a device (or start an emulator) on the
same Wi-Fi, run the isolated backend from §2, `cd mobile && npx expo start`,
open in Expo Go, and walk T1–T9 in `docs/PHASE14_FIELD_TEST_GUIDE.md`,
capturing the §5 evidence. No code change is required to do this — the app
already auto-discovers the backend.

---

**Stop point.** No commit, push, deploy, or Phase 16 start. All earlier work is
preserved; the results above are presented for review.
