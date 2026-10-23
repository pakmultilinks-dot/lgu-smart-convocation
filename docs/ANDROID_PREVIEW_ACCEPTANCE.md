# Android APK — first test with synthetic records

## Current status

An Android production JavaScript export is **not** a native APK and cannot
prove camera permission, QR scanning, offline storage, or real network access.

`.github/workflows/android-preview-apk.yml` builds a **separate installable
preview APK** using the GitHub-hosted Android SDK and Gradle; no Expo account,
EXPO_TOKEN, keystore upload, hosting bill, or Railway subscription is required.
Its preview-only package ID ends in `.preview`, so it will not replace a
future university-signed installation. It disables Android cleartext HTTP
and uses a per-build test signature, **not a university release signing key**.
Do not publish this APK to app stores or connect it to student records.

### Get the APK from GitHub

1. Open **GitHub repository → Actions → Free installable Android preview APK**.
2. Open a successful run for the reviewed preview branch.
3. Under **Artifacts**, download `LGU-Smart-Convocation-Preview-APK`.
4. Extract `LGU-Smart-Convocation-Preview.apk` and install it on an Android
   phone you control. APK installation should be done only from the official
   repository's own Actions artifact, not from forwarded unknown files.
5. Because the preview is signed with a temporary build key, uninstall an
   older preview package before installing a different Actions build if
   Android reports incompatible signatures.

The workflow checks TypeScript, lint, the Android JS bundle, actual
Gradle `assembleRelease`, and the APK signature; success does NOT mean the
APK has been installed or the camera/scanner was exercised on a device.

### First manual test: no backend required

Open the app on the phone. Confirm the welcome screen, mode picker,
student, scanner/volunteer and admin screens are visible. Offline status
and backend connection warnings must be understandable and must not crash.

### Full functional test requires a *synthetic staging* backend

In the app's **Admin > Backend Connection**, enter the HTTPS URL of a staging
Flask backend with disposable synthetic records. First verify
`https://<staging-host>/api/health` from the phone browser. Do not enter a
real PIN, production API URL, or student credentials. Arrange distinct
staging-only student, admin and scanner accounts with the staging operator.

Test and record:

- student signup/verification using a **test mail provider** (real SMTP
  delivery is a separate release gate);
- student login, QR pass display and logout;
- volunteer login, camera permission, valid QR check-in, repeated QR rejection,
  wrong/expired QR rejection, scanner identity and gate selection;
- queue a scan offline, reconnect, synchronize **once** and verify the ledger;
- admin dashboard updates, gate settings, registration reporting, navigation,
  error handling and restart persistence.

Save redacted bug reports (no QR signing secrets or student data). The tester
should record Android model/version, workflow build SHA, screen, action,
expected/actual result, and whether the device was online or offline.

### Alternative: official Expo free preview build

The project's existing `mobile/eas.json` profile named `preview` requests
an APK. Someone authorized for the Expo project (`owner` in app.json)
can use the Expo Free plan:

```powershell
cd mobile
npm ci
npx eas-cli@latest login
npx eas-cli@latest build --platform android --profile preview
```

This requires explicit Expo login/project authorization. Free quotas and
queues vary; do not upload Expo tokens or signing keys to GitHub.

## Existing JS-only verification

Run from `mobile/`:

```sh
npm ci
npm run tsc
npm run lint
npx expo export --platform android --output-dir dist-ci-android
node scripts/check-release-export.mjs dist-ci-android
```

The workflow **Android production JS bundle** runs these on relevant PRs,
but has no Android compiler and therefore produces no APK.

## No-go conditions

This APK is a **testing artifact**, never evidence of a campus-ready release.
The actual deployment needs university authorization, an approved v6→v14
migration on production *with verified backups*, HTTPS, real SMTP delivery,
a properly signed institutional APK tested on physical Android hardware, and
load/field tests on the event-day LAN.
