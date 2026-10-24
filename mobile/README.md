# Run LGU Convocation in Expo Go

After the one-time installation below, run `./Start-LGU.ps1` from the repository
root or `npm start` from `mobile`. The root script resolves this checkout even
when the terminal starts in another directory. See
[system design](../docs/SYSTEM_DESIGN.md) for navigation, dashboard access,
server boundaries, offline behavior and deployment requirements.

From this checkout, install the backend once:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r app/requirements.txt
cd mobile
npm ci
npm start
```

`npm start` starts the local backend, waits for its health check, then displays
Expo's QR code. Keep this terminal running. Connect your phone and laptop to
the same Wi-Fi, open Expo Go and scan the QR. Allow Python and Node through
Windows Firewall on your private network if Windows prompts.

The app discovers the backend on the Expo laptop at port 5000. A previously
saved custom server takes priority; use Settings to reset to Automatic when
returning to local testing. An installed APK has no Expo laptop to discover
and still needs a reachable server configured through Connect to server.

Local synthetic data and generated accounts persist in
`%USERPROFILE%\LGU-Local-Mobile`. Read `TEST-LOGIN-DETAILS.txt` there for the
student, scanner and admin logins. Nothing in that folder is committed.
The scanner test account is assigned to Gate 1. The local backend never opens
the university database. `npm run start:expo` starts only Metro when using an
independently managed backend.

---

# LGU Smart Convocation System (mobile)

Expo + React Native + TypeScript companion app for the LGU Smart Convocation
Flask backend at `~/workspace/lgu-smart-entry/app`. Volunteers scan QR-coded
student cards and guest passes at convocation gates; the control room watches
every gate live.

## Screens

- **Dashboard**: KPI cards (Inside Now, Male, Female, Guests, Busiest Gate),
  per-gate throughput bars, gate sync status chips, live scan feed.
  Auto-refreshes every 5 seconds, plus pull-to-refresh.
- **Scanner**: full-screen QR scanner (expo-camera) with viewfinder frame,
  torch toggle, gate chips, Entry/Exit toggle, persisted volunteer name,
  offline queue with "Sync now", and a Demo scan button that works without a
  camera.
- **Guests**: guest list with used badges, registration form (name, phone,
  host roll number), and a pass screen with a big single-use QR code.
- **Broadcast**: audience picker (all students or one gate), message composer,
  and the sent log.
- **Settings**: API base URL (default `http://10.0.2.2:5000` for the Android
  emulator), volunteer name, connection test, link to backend ID card
  printing, and About.

## Run

Backend (Flask, demo dev server):

```bash
cd ~/workspace/lgu-smart-entry/app
python3 run.py
# -> http://localhost:5000
```

App (Metro bundler):

```bash
cd ~/workspace/lgu-smart-entry/mobile
npx expo install
npx expo start --non-interactive
```

Then open the project in Expo Go, or press `a` for the Android emulator /
`i` for the iOS simulator. On a physical phone, set the API base URL in
Settings to the machine running the backend (for example
`http://192.168.1.10:5000`); `10.0.2.2` only works from the Android emulator.

Type check:

```bash
npx tsc --noEmit
```

Backend integration test (needs the Flask server running):

```bash
node scripts/api-test.mjs
# or: node scripts/api-test.mjs http://192.168.1.10:5000
```

Future APK build (configured, not run):

```bash
npx eas-cli@latest build --platform android --profile preview
```

## Architecture

```
app/                  expo-router routes (thin wrappers)
  (tabs)/             Dashboard, Scanner, Guests, Broadcast, Settings tabs
  guest-pass.tsx      stack screen for the guest QR pass
src/
  api/client.ts       typed fetch client, base URL from settings
  screens/            one screen component per tab
  components/         KpiCard, GateBar, ResultCard, LguLogo,
                      PrimaryButton, SegmentedControl, SectionCard, states
  store/              settings.ts (AsyncStorage), offlineQueue.ts
  theme/              colors, spacing, typography
assets/               icon, splash, adaptive icon, favicon — composited from
                      the real LGU seal by scripts/make-brand-assets.py
scripts/              make-brand-assets.py (brand assets), api-test.mjs
eas.json              EAS build profiles (APK for preview/production)
```

## Security notes

- The HMAC secret that signs QR payloads lives only on the server
  (`app/config.py` inside the backend repo). It is never bundled into
  this app; payloads are opaque strings and every scan is verified
  server side by `POST /api/scan`. A source-level regression test
  (`scripts/ui-35k-source-test.mjs`) scans this app for any secret-like
  constant and fails if one ever appears.
- The admin PIN (default `2026`) is stored in AsyncStorage
  (`lgu.admin_pin`) exactly as typed and resent as the `X-Admin-Pin`
  header on every settings write — `PUT /api/settings` and gate renames
  reject requests without the correct PIN. This is the honest current
  state: the PIN protects against casual access on the volunteer phone
  but is not equivalent to a real authentication session. Production
  hardening (HTTPS + PIN rotation) is required before live use.
- This app does client-side input validation only (phone format, required
  fields). The backend re-validates everything.
- Production checklist before real convocation use: serve the backend over
  HTTPS, rotate the HMAC secret and the Flask secret key, run the backend
  behind gunicorn (the dev server is demo-only), and restrict the admin
  pages to staff.

## Server-driven configuration (Phase 35K)

Operational surfaces read live values from `GET /api/config` — event name,
year, university, venue, expected attendance, gate list, gate-activity
window (minutes), message character limit, and broadcast mode. The
constants in `src/config.ts` are startup fallbacks for the first render
only; do not add event numbers there. Broadcast mode `demo` shows the
"logged, not sent" banner; `real` uses send wording but the server
response is still honest that no SMS gateway is wired up yet.

## Operational gaps and gate UX (Phase 35L)

The guest pass can be shared through the device share sheet and saved as
an image (white-matted capture, photo-library permission requested at
save time; web gets an honest note instead of a broken flow). The QR
renders on a pure `#FFFFFF` plate with a wide quiet zone — never the
cream paper tint — so any gate scanner reads it at full contrast. The
scanner gains a torch-aware Flash control (disabled with "Flash
unavailable" where the platform has no torch), a permission-recovery
state that is never a dead screen (re-ask while possible, "Open
settings" otherwise, plus "Find manually"), full-screen scan result
states (valid / guest entry / already-used with an explicit explanation
/ invalid) with the 35K timing preserved, distinct success/warning/error
haptics with a graceful no-op, a ≥2-letter volunteer-name rule enforced
before any scan is stamped, a "Choose a gate" sheet that pauses the
camera while open, and search helper text that reads exactly
"Type 2+ characters" below the minimum. Validation lives in
`scripts/ui-35l-source-test.mjs` (13 checks) plus an additive 35L
section in `scanner-logic-test.mjs`.
