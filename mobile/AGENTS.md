This is an Expo/React Native mobile application. Prioritize mobile-first patterns, performance, and cross-platform compatibility.

## Expo has changed — do not trust your training data

Expo ships breaking changes every SDK release. APIs you remember are likely renamed, moved, or removed. Before writing any code that touches an Expo, EAS, or React Native API:

1. Read the major version of the `expo` package in `package.json`.
2. Fetch the matching versioned docs: `https://docs.expo.dev/versions/v<major>.0.0/`
3. For anything else, fetch https://docs.expo.dev/llms.txt — an index of all Expo docs with corrections to common LLM misconceptions. Follow its links to the specific page you need; never answer from memory.

## Commands

Use `bunx` instead of `npx` if the project uses bun (`bun.lock` present).

```bash
npx expo install <package>  # ALWAYS use instead of npm/yarn/pnpm/bun add — resolves SDK-compatible versions
npx expo start              # start the dev server
npx expo lint               # lint
npx tsc --noEmit            # typecheck
npx expo-doctor             # diagnose dependency and config issues
npx expo install --fix      # fix incompatible package versions
```

Run lint and typecheck before declaring any task done.

## Navigation & Routing

- Use **Expo Router** for all navigation. Routes live in `src/app/` — every file there is a screen, `_layout.tsx` files define navigators. Keep non-route code (components, hooks, utils) outside `src/app/`.
- Import `Link`, `router`, and `useLocalSearchParams` from `expo-router`.
- Docs: https://docs.expo.dev/router/introduction.md

## Building with EAS

Use EAS to build, sign, and submit the app in the cloud (`eas build`, `eas submit`) and to ship over-the-air updates (`eas update`) — no local Xcode or Android Studio required. Run EAS CLI as `bunx eas-cli <command>` in Bun projects, or `npx eas-cli@latest <command>` otherwise; substitute that for bare `eas` in docs examples.
Docs: https://docs.expo.dev/eas/index.md

## Rules

- If `ios/` and `android/` directories do not exist, they are generated (Continuous Native Generation). Never create or edit them by hand — configure native behavior in `app.json` and config plugins.
- Expo Go only includes its bundled native modules. After adding a library with native code, the app needs a development build: `npx expo run:ios|android` locally, or `eas build --profile development`.
- Prefer recommended Expo modules over third-party libraries, and check your available skills before adding dependencies. Docs: https://docs.expo.dev/versions/latest/index.md

## Typography (35M item 18)
- Type scale (typography.ts): **11 / 13 / 15 / 24 / 46 / 64–88**. Sanctioned exceptions with documented reasons: 32 (Home heroGate, ui-35m pin), 72 (LiveBoard hero, 33-QA I8/I10, inside 64–88), 21 (GuestPass passTitle, 35M item 2 wrap-balance). The scanner mode label was snapped to 24 in the 33-QA P9 pass.- DM Mono (`fonts.mono` / `fonts.monoMedium`) is allowed ONLY for: status chips/pills (LIVE, STALE, OFFLINE, CONNECTING, ONLINE, READY, PASS USED, Connected, ENTRY/EXIT action pills), gate identifiers (G1–G7), scanner ops readouts (notice sub/meta lines), QR payload lines, and ticket identifier lines (the guest-pass `Host …` line).
- EVERYTHING else — section titles, field labels, captions, error sentences, helper text — uses the Bricolage families (`fonts.display` / `fonts.displayMedium`). Never set `fontWeight` on a custom family; the family encodes the weight.
- Accidental mono fixed in the targeted fix cycle: scanner top-bar gate caption, name-prompt error sentence, bottom-bar offline hint, test-panel notices, guest-pass university eyebrow + action notes, admin calendar weekday letters.

## Android system navigation bar (35M item 11)

- The scanner gate sheet is an RN Modal. On Expo Go (SDK 57) the app does not ship `expo-navigation-bar`, so the Android system navigation bar keeps its default dark treatment while the sheet is open. This is OS behaviour, documented in `src/scanner/ScannerSheet.tsx`; a standalone dev build could re-style the bar via a native dependency. Not a missed style — do not "fix" it by adding an `androidNavigationBar` config claim.

## Scanner layout (35M item 7)

- `ScannerScreen` computes `cameraHeight` from a chrome budget — `Math.max(260, Math.min(Math.round(windowH * 0.58), windowH - 330))` — so the Flash + Find manually controls stay visible below the camera without blind scrolling. Keep the budget if the camera area or surrounding chrome changes.
