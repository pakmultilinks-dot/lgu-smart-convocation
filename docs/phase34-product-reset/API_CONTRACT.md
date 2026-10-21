# API_CONTRACT — Verified backend contract (Phase 34A live captures, 2026-10-03)

Evidence: live HTTP captures TODAY (Flask PID 9788; python urllib scripts for JSON bodies — curl bodies unreliable in this terminal) + business-rule audit script (11 scenarios, 2026-10-03) + client import map read today. Smoke suite 29/29 from 2026-10-02 (business logic unchanged). Backend: `app/web/routes.py` (620 lines), CORS `*`, JSON 404 for `/api/*`. Consumers: `src/api/client.ts` (14 fns) + `src/api/settingsApi.ts`.

## Endpoints (all LIVE-captured today)

### GET /api/health
```json
{"app":"LGU Smart Convocation","ok":true,"version":"LGU1"}
```

### GET /api/settings
```json
{"convocation_datetime":"2026-12-12T09:00:00+05:00","convocation_name":"LGU Smart Convocation 2026","convocation_year":"2026","expected_attendance":"2500","venue":"Lahore Garrison University, Lahore"}
```
Note: `expected_attendance` is a STRING; keys validated against `database.SETTING_KEYS`; GET on PUT-only method → 405 (captured).

### PUT /api/settings
Body subset of settings keys; validation (routes.py 109–140): unknown key → 400 `{"ok":false,"error":"Unknown setting: X"}`; datetime must parse via `datetime.fromisoformat`; year 4 digits; expected_attendance int 0–1,000,000 stored as string. **Success returns the full updated settings object — NOT `{ok:true}`** (verified 2026-10-02 `PUT_OK=True`; path unchanged). USED BY: AdminScreen (`settingsApi.updateSettings`).

### GET /api/gates
```json
{"gates":[{"code":"G1","id":1,"label":"Main Gate"},{"code":"G2","id":2,"label":"East Gate"},{"code":"G3","id":3,"label":"West Gate"},{"code":"G4","id":4,"label":"North Gate"},{"code":"G5","id":5,"label":"South Gate"},{"code":"G6","id":6,"label":"Auditorium Gate"},{"code":"G7","id":7,"label":"Sports Complex Gate"}]}
```
Wrapper `{"gates":[...]}`. USED BY: ScannerScreen (dynamic import `fetchGates`, line 170).

### POST /api/gates/<gid>/rename
Body `{"label":"..."}`; empty → 400; success → `{"ok":true,"gate":{...}}` (gate management UI on Flask web admin).

### GET /api/dashboard — 15 keys (live capture today)
`arrival_pct, busiest_gate, expected_attendance, expected_female, expected_guests, expected_male, expected_total, feed, female, generated_at, guests_inside, inside_total, male, sync, throughput`.
Captured values: expected_total=40 (roster), expected_male=20, expected_female=20, expected_guests=6, inside_total=0, male=0, female=0, guests_inside=1, arrival_pct=0, busiest_gate="No scans yet", **generated_at LIVE per request** (13:16:12 → 13:16:13 consecutive calls).
- `throughput`: entries per gate LAST 15 MIN. `sync`: per-gate LIFETIME count/entries/exits/last. `feed`: last 20 scans desc **NO time filter** — never conflate with throughput (P-13).
- Semantics: `inside_total` = students inside only; guests separate in `guests_inside`; `arrival_pct` vs `expected_attendance` when set (>0), else roster total (P-20 dual semantics).
USED BY: LiveBoardScreen via `fetchDashboard` (2500 ms poll).

### GET /api/dashboard/summary — 13 keys
Same keys MINUS `feed` and `sync` (P-12 fixed; live capture today). USED BY: HomeScreen via `fetchDashboardSummary` only.

### POST /api/scan — core business operation
Request `{"payload":"LGU1:<qr_id>:<hmac10>","gate_id":<int>,"mode":"entry"|"exit","volunteer":"<name>"}`. Response = **result object** (success: status/level/title/name/sub/gate/time; failure: status/level/title/detail). **HTTP 200 always** — clients branch on `status`/`level`, never HTTP code.
Outcomes re-captured today (audit script):

| # | Scenario | Response captured (today) |
|---|---|---|
| 1 | Male entry | ok/green "ENTRY RECORDED", sub `LGU-2024-102, BS Computer Science, Male` |
| 2 | Duplicate entry | error/red "ALREADY INSIDE", detail `already entered at <gate>, <time>` |
| 3 | Exit after entry | ok/green "EXIT RECORDED" + gate |
| 4 | Exit when not inside | error/amber "NOT INSIDE" |
| 5 | Guest entry | ok/green "GUEST ENTRY RECORDED", sub `Guest of LGU-2024-101 (0300 1112233)` |
| 6 | Guest reuse | error/red "ALREADY USED", `One entry per guest.` |
| 7 | Guest exit (any) | error/red "ALREADY USED" — `guest_used` counts ANY first scan (P-09) |
| 8 | Invalid signature | error/red "INVALID CODE", `Signature check failed. This code is tampered or forged.` |
| 9 | Missing gate | error/red "NO GATE SELECTED", `Choose a gate before scanning.` |
| 10 | Null/non-int gate | error/red "NO GATE SELECTED" |
| 11 | Exit-not-inside variant | amber "NOT INSIDE" |
Also implemented (2026-10-02 smoke): UNKNOWN CODE, UNKNOWN GATE, NO MODE SELECTED; unused-guest exit → amber "GUEST PASS IS ENTRY ONLY"; blank volunteer → "Volunteer". USED BY: ScannerScreen `postScan` + offline flush.

### POST /api/sync — offline queue flush
Request `{"items":[{"payload","gate_id","mode","volunteer","scanned_at"}]}`; spec of record = `items` (legacy `scans` shape also accepted); max 500 → 400 beyond.
Response `{"synced":N,"results":[{"payload":...,"result":{...}}]}`.
Verified: client `scanned_at` preserved EXACTLY (2026-10-02: `2026-10-02 22:30:00` recorded verbatim), source=`queued`. Today: re-sync of already-used guest → `synced:0`, result red ALREADY USED (permanent rejection honored — offlineQueue drops it). USED BY: ScannerScreen.

### GET /api/test-records
```json
{"records":[{"key":"male","kind":"student","label":"Muhammad Ahmed (LGU-2024-102)","payload":"LGU1:9W2GJHKT:cf694dbe9b"},{"key":"female","kind":"student","label":"Ayesha Khan (LGU-2024-101)","payload":"LGU1:8G8YVTGC:1a4197baaf"},{"key":"guest","kind":"guest","label":"Nasir Khan (guest pass)","payload":"LGU1:EDD7RZ2Q:85e00d593f"}]}
```

### POST /api/test-reset
`{"ok":true,"removed":N}` — today `removed:3` (cleaned all audit scans). USED BY: SettingsScreen + audit scripts.

### GET /api/guests
`{"guests":[{id,name,phone,host_roll_no,qr_id,created_at,"used":bool} × N]}` newest first; `used` = any guest-type scan (LEFT JOIN DISTINCT scans). Today: 6 rows. USED BY: GuestsScreen.

### POST /api/guests — register
Body `{"name","phone","host_roll_no"}`; missing → 400; host roll must exist → 400 `"No student found with roll number X."`. Success `{"ok":true,"gid":<int N>,"payload":"LGU1:..."}`. USED BY: GuestsScreen register.

### GET /api/guest-pass/<gid>
`{"ok":true,"gid":N,"name","phone","host_roll_no","used":bool,"payload":"LGU1:..."}` or 404 `{"ok":false,"error":"Guest not found."}`. USED BY: GuestPassScreen + SearchScreen (guest navigation via gid).

### GET /api/broadcasts / POST /api/broadcasts
GET `{"log":[{id,audience,message,sent_by,sent_at} × ≤20 desc]}` — wrapper key is **`log`**. POST `{"message","audience"?,"sent_by"?}` (message required → 400) → `{"ok":true,"note":"Logged. Demo mode: not sent by SMS."}` — **broadcast is a LOG, not SMS delivery (P-19)**. USED BY: BroadcastScreen.

### GET /api/search?q= (ADDED Phase 34 — P-01 fixed, live today)
q < 2 chars → **400** `{"ok":false,"error":"Enter at least 2 characters to search."}`.
→ `{"ok":true,"query":"nasir","results":[{"type":"guest","name":"Nasir Khan","qr_id":"LGU1:EDD7RZ2Q:85e00d593f","gid":1,"host_roll_no":"LGU-2024-101","phone":"0300 1112233","inside":true,"used":true,"last_scan":{"gate":"West Gate","time":"...","mode":"entry"}}]}`.
Search fields: students(name, roll_no) + guests(name, phone, host_roll_no, qr_id); guests carry integer `gid`; LIMIT 25 per group; students carry roll_no/program/gender, no gid. USED BY: SearchScreen `searchAttendees` (400 ms debounce + requestSeq race guard).

### GET /api/demo-payload (helper)
`{"payload":"LGU1:..."|"hint":"Everyone is inside already."}` — not used by mobile client.

## Contract notes (consumer rules)
- HTTP **200 for business rejections** — red results are data; client renders them.
- `expected_attendance` round-trips as STRING — parse defensively (progress falls back to roster when 0/unset, P-20).
- `generated_at` = server local `YYYY-MM-DD HH:MM:SS` (Asia/Karachi) per request — freshness anchor; health has NO timestamp (client tracks `lastOkAt`).
- `feed` = last 20 scans LIFETIME; `throughput` = entries per gate LAST 15 MIN — never conflate (P-13).
- Client never surfaces IP/Flask/stack — `ApiError` sanitized; two human network strings; one-time fallback probe via `noteUnreachableBaseUrl`.
