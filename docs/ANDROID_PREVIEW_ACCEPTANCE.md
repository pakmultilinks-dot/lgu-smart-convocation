# Android build verification

Run from `mobile/`:

```sh
npm ci
npm run tsc
npm run lint
npx expo export --platform android --output-dir dist-ci-android
node scripts/check-release-export.mjs dist-ci-android
```

The GitHub workflow **Android production JS bundle** runs these steps on
every PR that changes mobile source. Unlike TypeScript/source tests alone, it
actually invokes Metro for the Android production target, resolving the real
Expo Router imports and image/font assets.

**Limits:** A successful JS export is **not an APK**. It does not compile
Kotlin/Java, request Android camera permission, install on a real phone, or
verify camera QR scanning, network access, offline storage, or TLS. Those
must be tested with an actual Android preview APK in a separate staging
environment using synthetic records.

A preview APK can be built by an authorized developer who is signed into
the project's Expo account:

```sh
npx eas-cli@latest build --platform android --profile preview
```

Do not add `EXPO_TOKEN`, EAS credentials, keystores, or test user passwords
to this repository or CI logs. Never configure the mobile app against a
production student database for exploratory testing.

**Standalone connectivity:** A standalone Android build has no Metro host to
discover. The operator must configure a reachable HTTPS backend in
**Admin > Backend Connection**, or the app correctly reports that the
backend is not configured. Confirm the address and `/api/health` first,
then exercise authenticated login, QR scanning and offline sync on a device.
