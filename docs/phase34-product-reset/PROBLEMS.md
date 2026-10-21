# PROBLEMS — Root-caused issues (evidence-linked, Phase 34A re-audit 2026-10-03)

Each problem: symptom → technical root cause (evidence) → disposition. P-01..P-12 dispositions re-verified TODAY; P-13..P-21 added by the Phase 34A forensic audit. **No application source was modified in Phase 34A.**

## P-01 — No attendee search anywhere (product weakness, §12)
- **Evidence**: `/api/search?q=ahmed` → **404 captured live**; no search/lookup route in `app/web/routes.py`; no search function in `mobile/src/api/client.ts`; no search screen in `mobile/app` tree.
- **Root cause**: feature was never built; recovery for damaged/missing QR has no destination.
- **Disposition**: **FIXED (Phase 34) — re-verified TODAY**: `GET /api/search?q=` LIVE (q=nasir → guest gid:1 used:true; q<2 → 400); SearchScreen is tab 3 (400ms debounce, requestSeq guard); guest → /guest-pass?gid=.

## P-02 — Navigation duplicates destinations (§29 violation)
- **Evidence**: `app/(volunteer)/_layout.tsx` tabs include **Dashboard** while `app/(liveboard)/index.tsx` is a top-level dashboard — two dashboard destinations; Broadcast is also a tab (not in §29 list).
- **Root cause**: IA accreted screen-by-screen across phases instead of being designed once.
- **Disposition**: **FIXED (Phase 34) — re-verified TODAY**: exact 5 tabs home/scanner/search/guests/settings + hidden admin/broadcast (href:null); single dashboard destination /liveboard; typed routes confirm /(volunteer)/search exists, NO /dashboard route.

## P-03 — Home feels like a dashboard/template (§11/§20 violation)
- **Evidence**: `HomeScreen.tsx` imports `fetchDashboard` + `DashboardData` (line 13) and loads `/api/dashboard` (line 88) — the volunteer home pulls the FULL operations payload and renders metric cards + link lists; screenshot evidence v2/v3 shows generic card-wall composition.
- **Root cause**: Home was built from the same data model as the dashboard; purpose (§9 Q1–Q7: move people through the gate) never drove composition.
- **Disposition**: **FIXED (Phase 34) — re-verified TODAY**: HomeScreen imports `fetchDashboardSummary` ONLY (13 keys, no feed/sync — P-12); 7-question composition (Assignment → progress → dominant Scan QR Code → Search recovery → Last scan → Status); density refactor −35 lines (uncommitted, pre-Phase 34A).

## P-04 — Hero imagery unverifiable / artificial (§18)
- **Evidence**: `mobile/assets/convocation-hero.jpg` 1920×1280 RGB, **EXIF NONE** (PIL capture) — no camera/date/source metadata; user reports it "looks artificial". No authentic LGU event photo exists in repo (repo image sweep: only launcher assets, this hero, logo variants, screenshots).
- **Root cause**: stock-style image adopted without provenance; §18 forbids fabricated/AI-looking imagery.
- **Disposition**: **FIXED (Phase 34) — re-verified TODAY**: convocation-hero.jpg retired; in-app identity = emerald system + LguMark (444×444 RGBA, alpha-verified); GuestPassScreen uses functional emerald/gold treatment only. No fake photography anywhere in mobile/src.

## P-05 — Hard-coded DHCP IPs (historical; §4/§42)
- **Evidence**: git log shows `5d52a59 "Update default API base URL to current DHCP lease (192.168.100.5)"`; past DEFAULT_API_BASE_URL pins caused permanent connection failures after lease changes.
- **Root cause**: discovery absent; source edits used as "fix" for every IP change.
- **Disposition**: **FIXED (Phase 33 architecture preserved verbatim) — re-verified TODAY**: getDiscoveredBackendUrl() hostUri discovery + probe + admin switch-back; source contains no pinned IP (Admin placeholder example only); live runtime host = 192.168.100.5 via discovered hostUri.

## P-06 — tzdata missing from requirements.txt
- **Evidence**: pip freeze shows `tzdata==2026.4` installed; `app/requirements.txt` lists Flask/pillow/qrcode only; without tzdata, `ZoneInfo("Asia/Karachi")` (models.now_str, dashboard time queries) crashes on Windows.
- **Root cause**: venv was provisioned ad hoc; dependency not captured.
- **Disposition**: **OPEN — additive only (re-verified TODAY)**: pip freeze still shows tzdata==2026.4 installed but absent from app/requirements.txt. Additive packaging fix during rebuild; zero business-logic change.

## P-07 — Duplicate Flask listeners on :5000
- **Evidence**: netstat shows PIDs **8068 and 8008** both LISTENING on 0.0.0.0:5000; endpoints respond (health 200).
- **Root cause**: detached launch pattern sometimes re-runs while an old process holds the port (Windows allows dual bind in some cases); stale process from a previous session.
- **Risk**: request routing between two app instances on one SQLite file — currently consistent (verified same data), but operationally fragile; two instances = two `now` clocks, potential WAL contention.
- **Disposition**: **RESOLVED operationally (re-verified TODAY)**: single Flask listener PID **9788** on :5000 (health 200). **8081 = PID 7556 UniServe — foreign workspace auto-respawner, DO NOT kill**; Metro = PID 1640 on :8082. No code change needed (run.py fine).

## P-08 — 148px logo JPEG / low-res asset misuse (§19)
- **Evidence**: `lgu-logo.jpg` 148×148 RGB 7.7KB (PIL); earlier phases referenced it as "enhanced" — resizing a 148px JPEG is not enhancement.
- **Disposition**: **FIXED (Phase 34) — re-verified TODAY**: lgu-logo.jpg retired; in-app crest = lgu-logo.png 444×444 RGBA (alpha corners 0 / center 255 re-verified via PIL); launcher assets NOT used as app logo; LguMark component is the only crest surface.

## P-09 — Guest exit message unreachable (minor, backend honesty)
- **Evidence**: business-rule test 8: guest EXIT → "ALREADY USED" (red), not "GUEST PASS IS ENTRY ONLY" (amber) — because `guest_used()` counts any scan and runs first (models.py).
- **Impact**: message slightly less precise for the exit-on-unused-guest case (that case DOES show entry-only amber — test not run against unused guest exit... actually unused guest exit hits the amber branch; used guest exit hits ALREADY USED). Semantics correct; wording fine. NO backend change (§36: rule is correct).
- **Disposition**: **DOCUMENTED — no backend change (re-verified TODAY via 11-scenario audit)**: guest entry green + host/phone sub; any-second-scan red ALREADY USED (guest_used counts ANY scan first — ordering correct for passes); unused-guest exit (pre-scan) amber GUEST PASS IS ENTRY ONLY confirmed reachable. SearchScreen pill communicates PASS USED / PASS READY before scanning.

## P-10 — Live data "not appearing" historically (§6)
- **Evidence**: backend live-captured correct + fresh (`generated_at` changes per request, all KPI values correct at 22:28:36/37); client DashboardScreen polls /api/dashboard 2500ms with real freshness logic; Phase 33 fixed stale-URL pinning.
- **Root cause chain**: (1) hard-coded IPs (P-05) → phone talked to dead/wrong host → sanitized errors → empty screens; (2) LogBox console.warn surfacing technical errors in UI (fixed Phase 32: __DEV__ console.log only).
- **Disposition**: **FIXED — root cause was NOT backend data bugs**: historical chain = (1) hard-coded IPs (P-05) → phone hit dead host → empty screens; (2) LogBox technical errors shown raw (fixed Phase 32: __DEV__ console.log only). TODAY: backend generated_at live per request (captured 13:16:12→13); all KPIs derived on demand from scans; physical-device confirmation still = user test P1-P6.

## P-11 — Generic visual identity (§14/§15)
- **Evidence**: screenshots/v2 + v3 show card-wall layouts, template-like composition; app.json splash/icon navy #0B2447 vs product emerald identity — brand mismatch across surfaces.
- **Disposition**: **ADDRESSED (Phase 34) — residual genericity re-verified TODAY and tracked as P-18 (navy splash) + P-21 (system font, uniform SectionCard rhythm, LguMark 36dp)**. Emerald-forward identity shipped in rebuild; no gradients-as-decoration (guest-pass functional gradient retained per Phase 32 rule); targeted polish only in Phase 34B — no redesign.

## P-12 — Dashboard duplicate + scan feed temptation (§25/§26)
- **Evidence**: DashboardData carries `feed` (20 scans) and both DashboardScreen + LiveBoardScreen consume dashboard payloads.
- **Disposition**: **FIXED (Phase 34) — re-verified TODAY**: Home consumes /api/dashboard/summary (13 keys, NO feed/sync); LiveBoard is sole /api/dashboard consumer; **LiveBoard does NOT render the scan feed — but note P-13: its "Gate activity" rows derive from feed[] (lifetime last-20) with a misleading 15-min comment; throughput[] correctly powers "Entries · 15 min". Feed remains available in API, not rendered on the operations console.**

## P-13..P-21 — NEW findings (Phase 34A forensic audit, 2026-10-03)

| ID | Finding | Severity | Evidence (today) | Root cause | Disposition |
|---|---|---|---|---|---|
| P-13 | LiveBoard "Gate activity" mislabeled as 15-min feed | Med | LiveBoardScreen derives gate rows from `data.feed[]` filtered to entries; models.py feed = **last 20 scans, NO time filter**; throughput[] IS the 15-min window (already powers "Entries · 15 min") | Phase 31 comment/label mismatch; time filter never implemented | **OPEN — targeted fix**: drive Gate activity from throughput/sync or relabel "Recent activity"; preserve LiveBoard architecture |
| P-14 | ScannerScreen = 1127 lines | **High (density mandate)** | Exact count today; contains constants + zoom engine + persistence + test panel + CameraView at line 669 | feature accretion across phases 29–33 in one file | **OPEN — MUST split** (zoom engine / result presentation / camera shell / test panel modules); behavior preserved |
| P-15 | @types/react-native 0.72.8 stale devDep | Low | package.json vs react-native@0.86.3 (types ship with RN) | SDK 51-era template leftover | **OPEN — remove** |
| P-16 | Unused deps expo-symbols + expo-web-browser | Low | zero imports across mobile/** | template bloat | **OPEN — remove**; expo-font/expo-linking transitive-only (keep) |
| P-17 | Redundant indexes idx_students_qr / idx_guests_qr | Low | PRAGMA index_list — duplicate UNIQUE autoindexes on qr_id | over-indexing at schema authoring | **OPEN — cosmetic**; safe later removal; keep idx_scans_* ×5 |
| P-18 | Splash/adaptive bg #0B2447 navy vs emerald system | Med | app.json colors vs theme tokens (emerald #157347 / greenDeep #0F5132) | launcher assets authored pre-emerald identity | **OPEN — align to emerald family** in Phase 34B; no other app.json change |
| P-19 | Broadcast = demo-mode LOG, not SMS | Med (product truth) | POST /api/broadcasts → `{ok, note:"Logged. Demo mode: not sent by SMS."}`; 2 rows in broadcasts table; no gateway | no SMS provider integrated (by design for demo) | **OPEN — product decision**: integrate provider (out of rebuild scope) or make demo-mode explicit in BroadcastScreen copy |
| P-20 | Dual expected-attendance semantics | Med | settings expected_attendance=2500 vs roster 40; models.py progress_expected = attendance OR roster; LiveBoard labels "of 2,500 expected" correctly | admin setting + roster defaults coexist | **DOCUMENTED — correct as-is**; both numbers labeled honestly; acceptance uses same convention |
| P-21 | Residual generic feel | Med | system font (typography.ts); navy splash (P-18); uniform SectionCard rhythm; LguMark 36dp | identity layer incomplete in rebuild v1 | **OPEN — targeted polish** (Phase 34B): crest presence, splash, section rhythm; type scale already good; NO redesign |

## Unresolved / deferred (Phase 34A snapshot)

- **P-06** tzdata in requirements.txt (additive packaging).
- **P-13** LiveBoard gate-activity source (targeted fix).
- **P-14** ScannerScreen density split (refactor-only).
- **P-15/P-16** dependency hygiene (removals only).
- **P-17** index cleanup (optional).
- **P-18/P-21** identity polish (splash + crest presence).
- **P-19** real-SMS broadcast (product decision, not code).
- **Physical-device acceptance P1–P6**: pending user — blocks final sign-off.
- **Docs IA drift**: docs/ia/IA.md is Phase 32-era; rebuild navigation = 5-tab (Phase 34) — documentation reconciliation only.

## Audit integrity (§18)

Phase 34A modified **no application source**. Working tree: `git status --short` shows only the 2 PRE-EXISTING uncommitted density files (GuestPassScreen.tsx, HomeScreen.tsx, +23/−52 — authored BEFORE Phase 34A); no new source changes; **not committed; not pushed**. All Phase 34A writes = documentation under docs/phase34-product-reset/ + memory files only.
