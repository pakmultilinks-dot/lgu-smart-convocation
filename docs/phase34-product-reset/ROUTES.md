# ROUTES — Mobile route inventory (Phase 34A, verified 2026-10-03)

Evidence: `Get-ChildItem mobile\app -Recurse` + source reads TODAY. Expo Router (file-based), SDK 57. **15 route files, 9 screens** — the post-Phase-34 tree (P-02 fixed).

## Current route tree

| Route file | URL | Renders | Entry | Exit | Nav type | Duplicate/legacy |
|---|---|---|---|---|---|---|
| `app/_layout.tsx` | root | Stack (headerStyle greenDeep, ErrorBoundary exported, splash preventAutoHide/hide) | — | — | Stack | none |
| `app/index.tsx` | `/` | Launch → redirect by persisted mode or `/mode-picker` | cold start | mode-picker/volunteer/liveboard | redirect | none |
| `app/mode-picker.tsx` | `/mode-picker` | Volunteer vs Live Dashboard chooser | index, LiveBoard "Switch mode", Settings reset | sets appMode → replace | stack | none |
| `app/(volunteer)/_layout.tsx` | `(volunteer)/*` | Tabs EXACTLY home/scanner/search/guests/settings; admin+broadcast `href:null` (hidden), custom Back header button | mode-picker | — | Tabs | none (no dashboard tab — P-02 fixed) |
| `app/(volunteer)/home.tsx` | `/(volunteer)/home` | thin → `HomeScreen` | tab 1 | scanner/search/admin/broadcast (pushes) | tab | none |
| `app/(volunteer)/scanner.tsx` | `/(volunteer)/scanner` | thin → `ScannerScreen` | tab 2 + Home dominant CTA | — | tab | none |
| `app/(volunteer)/search.tsx` | `/(volunteer)/search` | thin → `SearchScreen` | tab 3 + Home recovery action | guest-pass (push gid) | tab | none |
| `app/(volunteer)/guests.tsx` | `/(volunteer)/guests` | thin → `GuestsScreen` | tab 4 | guest-pass (push gid) | tab | none |
| `app/(volunteer)/settings.tsx` | `/(volunteer)/settings` | thin → `SettingsScreen` | tab 5 | admin/broadcast/mode-picker | tab | none |
| `app/(volunteer)/admin.tsx` | `/(volunteer)/admin` | thin → `AdminScreen` | Settings + Home quick actions | back button | hidden tab + header | none |
| `app/(volunteer)/broadcast.tsx` | `/(volunteer)/broadcast` | thin → `BroadcastScreen` | Settings quick action | back button | hidden tab + header | none |
| `app/(liveboard)/_layout.tsx` | `(liveboard)/*` | Stack, headers hidden | — | — | Stack | none |
| `app/(liveboard)/index.tsx` | `/liveboard` | thin → `LiveBoardScreen` | mode-picker | Switch mode → mode-picker | stack | none |
| `app/guest-pass.tsx` | `/guest-pass?gid=` | thin → `GuestPassScreen` (titled "Guest Pass" header) | deep link, Search/Guests pushes | back | stack | none |
| `app/+not-found.tsx` | unmatched | `Redirect href="/"` | — | — | redirect | none |

## Facts verified today

- Tab bar: `tabBarHeight = 60 + insets.bottom`, active `greenDeep`, inactive `muted`, label 11 semibold; icons Ionicons home/qr-code/search/people/settings.
- Hidden screens keep `headerShown:true` + custom `BackHeaderButton` (canGoBack → back, else replace home) — visible escape path.
- `.expo/types/router.d.ts` (regenerated on Metro 8082): contains `/(volunteer)/search`; **no `/dashboard`** route — the old P-02 duplicate is gone from disk AND types.
- `unstable_settings.initialRouteName = "(volunteer)"` in root layout.

## Absences (recorded, not bugs)

- **No About route** — app info lives in SettingsScreen content (event title from config).
- **No ID-Printing route in mobile** — ID/roster printing is Flask-web only (`/admin/cards`, `/admin/vendor.csv`, `/admin` roster upload). Mobile AdminScreen has no ID printing section in the Phase 34 build.
- No `/dashboard` route anywhere (single dashboard destination = `/liveboard` mode, per §29).

## Compliance verdict

§29 satisfied: five volunteer tabs exactly; one dashboard destination (top-level mode); Admin and Broadcast reachable exactly once each (Settings quick actions + Home for admin); no legacy/duplicate route files; search route exists (P-01 fixed). No nav blockers found in Phase 34A.
