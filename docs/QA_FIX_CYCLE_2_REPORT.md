# Release QA Fix Cycle 2 — Final Report

Status: **COMPLETE** · 2026-10-09 · HEAD `298c272` (untouched, nothing committed, nothing pushed)

**Critical user override preserved throughout:** the compact neutral `Entry | Exit` segmented control is kept as-is. No giant mode banners anywhere.

## Mandated fixes — all 16 applied

| # | Fix | State | Verified by |
|---|-----|-------|-------------|
| 1 | Dialogs | ✅ | broadcast/diag titles pinned in navigation-broadcast + ui-35j/k tests |
| 2 | Gate picker | ✅ | chooseRow minHeight 48; gate-integrity G-series |
| 3 | Gate source-of-truth | ✅ | `ops.ts` single source (`lgu.ops_selected_gate`); Scan `disabled` when no gate (G14/G15/G16); live home screenshot shows Scan disabled until gate chosen |
| 4 | Entry/Exit compact UX | ✅ | control kept compact + neutral; toggle is a direct child of the hero (ui-35m item 1); **override honored** |
| 5 | Server address / HTTP | ✅ | Admin shows `Using: Custom (localhost:5000)`; `app.json` `usesCleartextTraffic`; live-verified Connected |
| 6 | Guest Pass | ✅ | name above QR; `Host` / `Phone` / `Valid` meta rows (layout-p7, ui-35l/m); no duplicate back button; live pass screenshot |
| 7 | Home alignment | ✅ | heroGateRow before the SegmentedControl, de-wrapped direct child; no `heroControl` wrapper (ui-35h/m) |
| 8 | Naming | ✅ | `Leave display` (display-admin-auth A2, layout-p5); sentence-case pills everywhere |
| 9 | Live Dashboard fit | ✅ | hero `fontSize: 64 / lineHeight: 58`; **320×568 fits entirely** (all 7 gates + footer visible, screenshot proof) |
| 10 | Pills / buttons / tabs / gold underline | ✅ | sentence-case pills; active tab = filled glyph + ink label + thin gold underline, inactive = outline glyph (`(volunteer)/_layout.tsx`); gate-text gold underline **gone** (G3/G12 inverted) |
| 11 | Scanner layout | ✅ | gateChipFull + loneTail (odd gate count spans full width); compact bottom status line: Switch + Online/Offline + N waiting + Sync |
| 12 | Announcement details | ✅ | demo banner "Demo mode — announcements are saved only. Nothing is sent."; Save/Send label variants; per-gate "· N inside now"; Select all gates; live broadcast screenshot |
| 13 | Settings | ✅ | `Change the name to save.` hint; sentence-case pills; Active pill; screenshot |
| 14 | Guest states | ✅ | eyebrow `Guest list · N registered · N ready · N used`; `No phone` fallback; `Pass #N` links; live guests screenshot |
| 15 | Search wording | ✅ | `Type at least 2 characters to search`; Used/Ready result pills; live search screenshot |
| 16 | Security / regression / DB proof / screenshots / report | ✅ | new S3–S5 + G14–G16; full battery; DB proof; 19 screenshots; this report |

## New regression coverage (gate integrity)

- **S3** — scan with `gate_id: null` → semantic rejection (`NO GATE SELECTED|UNKNOWN GATE`), never recorded.
- **S4** — forged signature (`LGU1:<qr>:0000000000`) → `INVALID|FORGERY|SIGNATURE`, never recorded.
- **S5** — gate row deleted, then scan → `UNKNOWN GATE` (gate list is server truth).
- **G14** — Home Scan is `disabled={gateId === null}`.
- **G15** — `ops.ts` is the single gate source (`KEY_SELECTED_GATE`, get/set exports, readJson/writeJson).
- **G16** — ScannerScreen passes `gateId === null` + `gateRequired`.

Note: the server answers HTTP 200 with a semantic title envelope for rejected scans — S3/S4 assert on the title and on "not recorded", not on HTTP status.

## Test battery — 24/24 green (tsc 0, eslint 0)

scanner-logic 58/0 · progress ✓ · ui-35h ✓ · ui-35i ✓ · ui-35j 83/0 · ui-35k 39/0 · ui-35l 13/0 · ui-35m 23/0 · ui-35r 11/0 · layout-p5 28/0 · layout-p6 23/0 · layout-p7 40/0 · layout-p8 40/0 · layout-p9 15/0 · display-admin-auth 16/0 · navigation-broadcast ✓ · camera-states 18/0 · admin-lockout ✓ · db-isolation 29/0 · gate-integrity 22/0 · api-test ✓ · data-truth 53/0 · release-safety ✓ · master-audit ✓

## Production DB proof

`app\lgu.db` — 81,920 bytes, SHA256 `AF4885DF7FF6C37C16F7AF136A169FA32AB5EC2DA960CB373760531546A1B919` — **byte-identical to the pre-cycle baseline**. Read-only proof; no writes, no commits.

## Screenshots — `screenshots/qa-cycle2/` (19 files)

- **360×800** (13): mode-picker, home (offline), more, admin PIN gate, admin connected, home live, scanner gate-required, guests, guest pass, search, broadcast, settings, live dashboard.
- **320×568** (4): live dashboard (fit proof — whole board incl. footer), home, scanner, guests.
- **800×360** (1): live dashboard wide — two-column layout engaged.
- **1280×720** (1): live dashboard wide at the realistic 16:9 display target — whole board + footer fit with no scrolling.

## Boundary observations (not blockers)

1. **Web-only click interception** — RN-web tab bar / PIN overlay intercept Playwright clicks on web; verified screens via direct URL navigation instead. Native Android (the target runtime) is unaffected.
2. **Physical-device items untestable on web** — camera permission states, live QR capture, Android nav-bar insets. Covered by source tests (camera-states 18/0) and require a device pass before release.
3. At 800×360 (extreme 2.2:1) the dashboard footer sits below the fold and is reached by scroll — by design ("genuinely scrollable"); the 16:9 target (1280×720) fits fully.
4. One cosmetic 404 on web (favicon/asset) — no functional impact.

## Scope discipline

27 modified files, all under `mobile/`. No backend changes. No git commits, no push. Production DB untouched.
