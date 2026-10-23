# Get a real Android preview build — LGU Smart Convocation

## The short version

Use **an authorized Expo account** to run this command in the latest
`mobile/` directory:

```powershell
npx eas-cli@latest build --platform android --profile preview
```

The Expo CLI will give you the **actual EAS build URL** after it starts. A
cloud build is not started by opening GitHub. The EAS account currently
configured in `mobile/app.json` is `kominman`; anyone building must have
access to the existing project on Expo. Do not paste Expo login passwords or
access tokens into issues, a chat, or the repository.

A Windows helper is included as `mobile/scripts/build-eas-preview.ps1`, for
users who prefer to run one script from PowerShell:

```powershell
cd mobile
powershell -ExecutionPolicy Bypass -File .\scripts\build-eas-preview.ps1
```

Expo Free has limited cloud builds. EAS account login and signing key creation
may need a one-time interactive confirmation. An EAS link is not available
until the authenticated command actually queues a build. No Expo build URL
has been created by this code change alone.

## What changed in the APK configuration

- `preview` EAS profile builds an installable Android `.apk`.
- Preview has **its own Android package**:
  `pk.edu.lgu.smartconvocation.preview`; it does not replace a university
  production install.
- Preview refuses cleartext HTTP and uses **HTTPS only** when installed.
- The app carries **no login, PIN, API host, Expo access token, or real student
  database** inside its build.
- "Connect to demo server" is reachable from the mode picker, Student welcome,
  Scanner sign-in, Admin PIN screen, and Volunteer settings **before login**.
  Only network configuration is accessible without a PIN; protected operations
  still require the backend to authenticate each role.
- A saved connection must answer with a valid LGU `/api/health` payload,
  rather than merely returning HTTP 200.
- Switching servers clears saved Student/Scanner/Admin credentials. It refuses
  to change if offline scans remain queued, preventing accidental replay to a
  different server.

## Test on Android

1. Install the freshly generated `.apk` on your phone. If Android reports
   signing conflict with a previous package, uninstall ONLY the separately
   named preview app before retrying; this removes local preview data.
2. Tap **Connect to demo server** and enter an *authorized, synthetic-only*
   HTTPS demo backend URL. The backend must first be deployed separately.
3. Check connection. Only after it succeeds, use the generated synthetic
   Student, Scanner and Admin accounts from the **same demo server**.
4. Test registration claim, QR display, camera scan, duplicate scan, offline
   queue and sync, then Admin stats and reports. Record screenshots and
   device/Android version for each actual failure. No student data is needed.

## What's still not done

This PR cannot authenticate to a user's Expo account, create an EAS cloud
build, host a backend, or validate a real phone. Production launch requires
separate institution approval, backup/restore validation, migration approval,
real SMTP, HTTPS, hardware camera checks, and event-day LAN testing.
