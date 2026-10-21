# VISUAL_SYSTEM — Locked design tokens + component roles (Phase 34 rebuild)

Derived from DESIGN_RESEARCH.md synthesis. These tokens replace the Phase 32 theme file in the rebuild (same philosophy, refined values, emerald-forward LGU identity).

## Color tokens (src/theme/colors.ts)

```ts
// Institutional core
greenDark:  "#0A3622"  // deepest emerald — hero fields, Live Board header
greenDeep:  "#0F5132"  // primary brand — buttons, active states
emerald:    "#157347"  // brand mid — accents, progress fill
emeraldSoft:"#E8F5E9"  // tonal container on light
mint:       "#A7D9BC"  // brand light — progress on dark, subtle fills

// Surfaces
background: "#F6F8F7"  // app canvas (slightly green-tinted paper)
card:       "#FFFFFF"
tint:       "#EDF3EE"  // quiet secondary container
overlay:    "rgba(10, 54, 34, 0.55)"  // result-moment backdrop

// Ink
text:       "#0F172A"
muted:      "#64748B"
border:     "#E2E8F0"  // hairlines on inputs/dividers only — never card borders

// Accent (institutional restraint)
gold:       "#B8912A"  // venue/institutional moments ONLY
goldSoft:   "#F6EED6"

// States
green (accept)  = emeraldDeep family: use greenDeep text on emeraldSoft fill
red    #B3261E / redSoft    #F9E4E2   // invalid, duplicate, error
amber  #9A6B1A / amberSoft  #FBF0D9   // offline, stale, queued, warnings
```

State pills: Live=emeraldSoft/greenDeep/emerald-dot; Stale=tint/muted/slate-dot; Offline=amberSoft/amber/amber-dot; Queued=amberSoft/amber; Accept=emeraldSoft/greenDeep; Duplicate=redSoft/red; Invalid=redSoft/red.

## Typography (src/theme/typography.ts) — SYSTEM font (reliability, §16)

| Role | Size/Weight/Tracking | Use |
|---|---|---|
| metric | 40/700/-0.8 | People Inside, gate count — the one number that matters |
| display | 32/700/-0.8 | secondary hero numbers (expected, progress count) |
| title | 24/700/-0.4 | screen titles, gate name on Home |
| heading | 20/700/0 | section values |
| subheading | 17/600/0 | row titles, button labels |
| body | 15/400/0 | descriptions, detail text |
| label | 13/600/0.2 | quiet operational labels |
| eyebrow | 11/700/1.2 | small-caps section eyebrows ("ASSIGNMENT", "LAST SCAN") |
| caption | 12/400/0 | timestamps, metadata |

Large numbers feel designed: metric/display + tight tracking + greenDeep or text ink; operational labels quiet: eyebrow/label + muted + caps tracking. Numbers never italic, never gradient-filled.

## Spacing + shape (spacing.ts)

`xs 4 · sm 8 · md 16 · lg 24 · xl 32 · xxl 48`; screen horizontal padding 20 (between md and lg — phone ergonomics); section gap 24; card padding 16–20.
Radius: `sm 8 · md 12 · lg 16 · full 999`. NO other radii.
Elevation: `soft {#0A3622, 0.06, r12, (0,4), e2}` · `raised {0.12, r16, (0,6), e5}`. Cards = tonal/white on tint background, borderless; inputs get hairline border only.

## Surface system

- App background = background token (tinted paper) everywhere except dark-hero screens (Live Board header block, Guest Pass).
- Cards = white + elevation.soft OR tint (no border). Section cards carry an eyebrow + content, not decorative headers.
- Primary button: greenDeep fill, white 17/600 label, minH 56 (Scan) / 54 (forms), radius md, pressed scale 0.98, disabled tint/muted.
- Secondary button: tint fill, greenDeep label. Ghost: text-only greenDeep. Danger: redSoft fill/red label (guest delete contexts only).
- Inputs: white, hairline border, minH 48, radius sm; focus → emerald border (no glow).
- Pills: full radius, 28 height, eyebrow-type label + 6px state dot.

## Status system (shared vocabulary — STATUS COPY IS LAW)

| Situation | Pill/title | Body copy (exact) |
|---|---|---|
| Connecting | CONNECTING | "Contacting the convocation server…" |
| Connected | LIVE | "Live data" |
| Stale | STALE | "Showing last synchronized data · HH:MM" |
| Offline | OFFLINE MODE | "Offline mode · Local scans remain available" |
| No data yet | NO DATA | "No scans recorded yet" |
| Retry offer | — | "Tap Retry to try again" (button: Retry) |

Scan result classes (titles exact, per API): ENTRY RECORDED · GUEST ENTRY RECORDED · EXIT RECORDED · ALREADY INSIDE · ALREADY USED · NOT INSIDE · INVALID CODE · NO GATE SELECTED · QUEUED OFFLINE. Each = icon + title + name/detail + gate + time; color reinforces, never carries meaning alone (§24).

Error copy never contains: URLs, IPs, "Flask", "fetch failed", exception names (§27). Admin Backend Connection screen is the single exception surface for host configuration.

## Motion

Functional only: result moment — backdrop fade 160 ms + card rise 12 px/200 ms; press — scale 0.98/100 ms; pill dot — static (no pulsing); progress bar — width transition 400 ms on data change; camera freeze-frame — instant. No looping animation, no parallax, no bouncing.

## Imagery + logo (§18/§19)

- In-app logo: `assets/lgu-logo.png` 444×444 RGBA (alpha verified: transparent corners, opaque crest), rendered contain at 28/40/48/56 dp by context. NEVER upscaled beyond 64 dp. The 148px JPG is retired; launcher icons are not app logos.
- Branded abstract treatment (replaces unprovenanced hero JPG): dark emerald field (greenDark→greenDeep vertical, functional not decorative), LGU crest centered-left at 96–120 dp, typographic block "LGU CONVOCATION 2026 / Lahore Garrison University" in white/mint, thin gold rule (2 dp × 64) as the single accent. Used on: Launch screen, Mode Selection header, Live Board header. No photography, no blobs, no neon.
- Guest pass keeps its functional emerald gradient + perforation (marks object type — allowed per Phase 32 rule).

## Component roles (src/ui/*)

| Component | Role | Notes |
|---|---|---|
| Screen | Safe-area wrapper + background token + optional dark header | one per screen file |
| AppHeader | Title + optional crest + right slot (pill/avatar) | no back-chrome duplication with router |
| SectionEyebrow | 11/700 caps muted label | section rhythm anchor |
| MetricBlock | eyebrow + metric number + caption | the "designed number" primitive |
| StatusPill | state dot + eyebrow label | shared status vocabulary |
| PrimaryButton / SecondaryButton / GhostButton | actions | 54–56 minH |
| Field (TextInput) | labeled input | 48 minH, hairline |
| ListRow | icon-less row: title + subtitle + trailing | rows inside SectionCard |
| SectionCard | tonal/white container, borderless, elevation.soft | replaces old SectionCard role |
| ResultMoment | full-screen overlay card for scan verdicts | icon+title+detail+time, class-colored field |
| EmptyState / ErrorState | designed states | title + body + optional action |
| OfflineBanner | amber strip, §27 copy + Retry | pinned under header |
| ProgressTrack | 8 dp mint/emeraldSoft track + emerald fill | dashboard + home progress |

Icons: @expo/vector-icons Ionicons only (one family = consistency); every icon paired with text on operational surfaces.
