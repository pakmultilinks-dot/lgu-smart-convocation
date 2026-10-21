# FINAL_REPORT — Phase 34 (product reset & clean mobile rebuild)

Scope: mobile product experience rebuilt from a clean foundation per the Phase 34 mandate; backend/business logic preserved except one proven, additive gap (search). This report answers §46 A–G honestly, including what remains unverified.

## A. What was built

**Audit-first (§2):** 12 evidence documents written *before any source edit* (`CURRENT_STATE`, `ROUTES`, `API_CONTRACT`, `DATA_MODEL`, `DEPENDENCIES`, `DEVICE_RUNTIME`, `UI_INVENTORY`, `PROBLEMS` P-01…P-12, `REBUILD_PLAN`, `DESIGN_RESEARCH`, `IA`, `VISUAL_SYSTEM`), plus this report and `ACCEPTANCE_MATRIX`. Key root causes found: missing search endpoint (P-01, 404 captured), duplicated/contradictory navigation (P-02), Home dashboard-fetch (P-03), retired 148px logo (P-08), historical IPs in UI (P-05), generic identity (P-11).

**Clean mobile client (`mobile/`):**

- **Shell:** `app/_layout.tsx` (Stack, emerald headers, error boundary), `app/index.tsx` (branded launch → mode routing), `app/mode-picker.tsx`, `(volunteer)/_layout.tsx` with **exactly** Home / Scanner / Search / Guests / Settings (hidden Admin/Broadcast), `(liveboard)/` stack, `guest-pass.tsx`.
- **Design system:** `src/theme/*` tokens (emerald `#0F5132`/navy-green `#0A3622`/gold `#B8912A`, type scale, spacing, radii, letter-spacing) + `src/ui/index.tsx` kit (Screen, AppHeader, LguMark, MetricBlock, StatusPill/PillState, SegmentedControl, AppButton, Field, ListRow, SectionCard, ProgressTrack, Empty/Error/Loading states, OfflineBanner, clock/freshness helpers). Official logo: `assets/lgu-logo.png` **444×444 RGBA transparent** (PIL-audited) — the retired 148px jpg and EXIF hero are gone; no stock imagery, no fabricated hero (§18/§19).
- **Screens (9, each with §37 data states):** Home (§11 seven-question hierarchy, summary endpoint only), Scanner (continuous CameraView scan, auto-zoom ported with verified constants, dedupe, gate+mode visible, result moment = icon+text+level+haptics, offline queue enqueue + sync + test scan/reset), Search (debounced backend search, guest → Guest Pass via integer `gid`), Live Dashboard (§25 state view, no feed, freshness pills), Guests (register + list + pass navigation), Settings (volunteer name, mode, backend connection summary), Admin (inline connectivity probe, custom/auto backend, convocation details, operations), Broadcast (audience + history via `sent_at`), Guest Pass (QR + rules + invalid-link state).
- **Preserved verbatim (Phase 33/32 verified work):** `store/settings.ts` (auto discovery: session → `expoConfig.hostUri` → stored; `noteUnreachableBaseUrl` stale-URL recovery; custom URL validation/probe), `api/client.ts` core request path (own 20 s AbortController, sanitized `ApiError`, single stale-URL fallback retry, `__DEV__`-only diagnostics), `api/settingsApi.ts`, `store/offlineQueue.ts` (dedupe, reconcile-by-position, permanent-rejection set), `store/ops.ts`, `store/appMode.ts`, all locked dependency versions (Expo **57.0.25**, expo-camera 57.0.5, AsyncStorage **2.2.0** — untouched per §43).

**Old code removed:** Phase 32 screen shells, `src/components/*` (12 files), stale `DashboardScreen.tsx` — replaced by the 9-screen structure above. Route wrappers all point at the new screens; typed routes regenerated (`/(volunteer)/search` present, `/dashboard` absent).

## B. Backend changes (exhaustive)

Exactly **two additive changes**, both evidence-driven and both in `app/web/routes.py`:

1. **`GET /api/search?q=`** (P-01, was proven missing — 404 captured in audit): searches students (name, roll) + guests (name, phone, host roll, qr_id) with ESCAPE'd LIKE, `q<2` → 400, LIMIT 25 each, returns `{type, name, roll_no?, program?, gender?, qr_id, host_roll_no?, phone?, inside, used, last_scan}`.
2. **Additive `gid` field** on guest search results (integer PK) so the mobile Search screen can navigate to `/api/guest-pass/<gid>` — additive dict key only.

Nothing else touched: no endpoint modified, no business rule changed, no schema change, no dependency change. The P-09 guest-exit anomaly (unreachable `GUEST PASS IS ENTRY ONLY`) was **documented, not "fixed"** — behavior verified as guest-pass-is-entry-only in practice, which matches the event rule.

## C. Verification evidence (agent-side, this session)

| Check | Result |
|---|---|
| `tsc --noEmit` (from `mobile/`) | **0 errors** (`TSC_EXIT=0`) |
| `eslint app src` | **0 errors** (`ESLINT_EXIT=0`) |
| Metro bundle (lgu on **:8082**, virtual entry, android) | **HTTP 200, 8,535,236 bytes**; markers `expo-router`, `GuestPass`, `ViewfinderCorners`, `Lahore Garrison`, `Show guest pass` present |
| Backend smoke suite (health, gates, dashboard 15 keys, summary no-feed, 11 scan outcomes incl. null-gate & unknown-gate, sync timestamp preservation, 4 search cases incl. `gid` integers, guests CRUD + pass, settings PUT persist, test-reset) | **29/29 PASS** |
| §41 network failure | Flask stopped → port 5000 free, health connection-refused; restarted (PID 3404) → health 200 + search with `gid:1` — **API-level recovery verified** |
| §42 stale-URL | Phase 33 architecture preserved verbatim (auto mode prefers fresh discovered host; unreachable-base-URL probe/fallback intact; Admin custom URL validated + probed before save) — **code-level verified** |
| Sweep (no IPs/`:5000`/Flask/`127.0.0.1`/`fetch failed` in UI) | 6 grep hits: 2 allowed Admin placeholders (`e.g. http://192.168.1.10:5000`), 4 non-rendered code comments → **clean** |
| §43 no Expo upgrade | Manifest/lockfile pins unchanged (57.0.25 / AsyncStorage 2.2.0); Metro's "57.0.26 available" notice **ignored** |
| §45 git | Start recorded: HEAD `02b207e`, origin/main 0 behind **6 ahead**; this phase commits locally only — origin/main must stay 6 ahead |

Runtime snapshot at report time: Flask **PID 3404** (single :5000 listener, `debug=False` — manual restart after backend edits), Metro **PID 17560** on **:8082** (`exp://192.168.100.5:8082`). Note: port 8081 is permanently off-limits — a *different* workspace (UniServe) squats it with an auto-respawning watcher; all lgu Metro traffic uses 8082.

## D. What was deliberately NOT changed

- Backend business rules, seed data, ID/signature scheme, HMAC env contract, timezone setup (tzdata already in requirements — P-06 was already fixed).
- Connectivity/discovery architecture, offline-queue semantics, dependency versions, `app.json` identity (package id, scheme, permissions), AsyncStorage version.
- No Expo SDK upgrade, no component-library introduction, no re-litigation of locked design decisions (VISUAL_SYSTEM.md / IA.md), no push to GitHub.

## E. Known gaps and honest limitations

1. **Physical device is untested by the agent** — the §47 gate explicitly requires the phone to work; until the user reports P1–P6, the rebuild is *not* declared complete.
2. **§42 on a real DHCP change** can only be proven by switching networks on the phone; agent evidence is code-level plus the preserved, previously Phase-33-verified behavior.
3. **P-09** remains an unreachable backend branch (`GUEST PASS IS ENTRY ONLY`); guest exit returns `ALREADY USED` (red). Documented, intentional non-change — if gate policy later requires a distinct guest-exit message, that is a scoped backend change (new smoke cases), not a mobile fix.
4. **Demo/test data** exists in the DB (test student/guest records, "Smoke Test Guest" from smoke runs, Phase Test Guest scan history) — expected for a demo environment; `/api/test-reset` clears scan history, guest rows persist by design.
5. **Metro on 8082** means the phone URL differs from the default 8081; anyone on the network must use `exp://192.168.100.5:8082` (documented here and in repo memory).
6. Web/admin Flask templates were out of scope for the reset (backend preserved); they still render the admin views.
7. Search LIMIT is 25 per type — intentional for gate-ops latency; large halls would need pagination later (not required by current specs).

## F. Explicitly UNVERIFIED on the physical device (user-side, PENDING-USER)

- Expo Go loading `exp://192.168.100.5:8082` and rendering the new shell (P1).
- Real camera scanning: continuous detection, auto-zoom behavior, result moments + haptics, dedupe feel (P2).
- Search flow end-to-end on device incl. Guest Pass navigation via `gid` (P3).
- Offline mid-shift behavior: correct states, local queueing, Sync recovery after reconnect (P4).
- DHCP/router-IP switch recovery without reinstall (P5).
- Live Dashboard freshness/pills rendering on device (P6).

## G. Next actions

1. **User:** connect the Android phone to the same Wi-Fi, open Expo Go → `exp://192.168.100.5:8082`, run P1–P6 from `ACCEPTANCE_MATRIX.md`, and report results (photos/errors welcome).
2. **Agent (on reported failures only):** fix verified failures — no speculative patching (§48).
3. On passing P1–P6: mark device rows VERIFIED, then Phase 34 closes; local commit + memory notes already prepared at Step I (no push, origin/main stays 6 ahead).

Commit note: this phase is committed locally as a descriptive commit after the acceptance docs above; **nothing was pushed to origin** per §45.
