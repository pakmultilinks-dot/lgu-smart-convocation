# LGU Smart Convocation System

A working demo web application for Lahore Garrison University: QR-coded student
cards, a volunteer gate scanner, a live VC dashboard, single-use guest passes,
and a broadcast module. Built to be demonstrated to the Vice Chancellor.

## Install

```bash
cd app
pip install -r requirements.txt
```

Requires Python 3.10+. Dependencies: `flask`, `qrcode[pil]`, `pillow`.

## Run

```bash
cd app
python run.py
```

Open http://localhost:5000. The SQLite database (`app/lgu.db`) is created and
seeded automatically on first run: 40 sample students, 7 gates, 3 sample guests.

## Demo QR helper: development only

The `GET /api/demo-payload` endpoint can reveal a **valid signed student QR
pass**, so it is disabled by default and never available in production mode.
For a controlled, private demo only, explicitly set both variables:

```bash
LGU_APP_ENV=development LGU_ENABLE_DEMO_QR=1 python run.py
```

PowerShell:

```powershell
$env:LGU_APP_ENV = "development"
$env:LGU_ENABLE_DEMO_QR = "1"
python run.py
```

For production, set `LGU_APP_ENV=production` and **never** enable the demo QR
helper. A disabled helper responds with JSON HTTP 404; the scanner UI explains
that no demo code is available. Actual scanning of an assigned QR code is
unchanged. Keep all demo servers private and use synthetic student records.

## 5-minute VC demo script

1. **Home** (`/`): show the six modules.
2. **Admin** (`/admin`): click "Generate IDs" (already seeded), open the
   **printable card sheet** (name + roll number + QR per card) and download the
   **vendor CSV**, the exact file handed to the card printer.
3. **Gate Scanner** (`/scan`): pick Gate 1, ENTRY mode, click
   "Demo: fill next student's code", press SCAN. Green card appears with the
   student's name, program, gender, gate, and timestamp.
4. Scan the **same code again**: red "ALREADY INSIDE" alert. This is the
   real-time duplicate detection across all gates.
5. Switch to EXIT mode and scan again: "EXIT RECORDED". Scan exit once more:
   amber "NOT INSIDE".
6. Type a tampered code (change one character): red "INVALID CODE", signature
   check failed.
7. **Live Dashboard** (`/dashboard`): KPI tiles (inside now, male/female,
   guests, busiest gate), per-gate throughput bars, live scan feed. It refreshes
   every 5 seconds. Open it on a second screen while scanning.
8. **Offline demo**: on the scanner, turn on "Simulate offline", scan twice,
   see the scans queue on the phone. Turn it off, press "Sync now": the queued
   scans land on the dashboard with their original timestamps.
9. **Guests** (`/guests`): register a guest, print the single-use pass, scan it
   at a gate (paste the payload from the pass page source or retype it), then
   scan it again: red "ALREADY USED".
10. **Broadcast** (`/broadcast`): compose a gate-change notice, send it, show
    the sent log. (Demo mode: logged, not actually sent by SMS.)

## Renaming the gates

Admin page, section 4: edit any gate label and press Save. The scanner and the
dashboard pick up the new labels immediately.

## Loading a real roster

Admin page, section 3: upload a CSV with columns
`roll_no, name, gender, program` (header row optional). New students are added,
duplicates are skipped, and signed QR IDs are assigned automatically. Then
re-download the vendor CSV and reprint the card sheet.

## How the QR security works

Each QR holds only an opaque 8-character code plus a 10-character HMAC-SHA256
signature, e.g. `LGU1:K9P2M7Q4:a1b2c3d4e5`. No name, roll number, or gender is
encoded in the code; a photo of a card reveals nothing. The scanner verifies
the signature before anything else, so forged or edited codes are rejected.
Gender counts on the dashboard come from the exam department roster, matched
at scan time.

## Project layout

```
app/
  run.py            entry point
  config.py         secrets, paths, branding constants
  database.py       schema, seed data (40 students, 7 gates, 3 guests)
  models.py         all database queries
  ids.py            ID generation, HMAC signing and verification
  qrgen.py          QR PNG generation as data URIs
  requirements.txt
  web/
    routes.py       pages and JSON APIs
    templates/      Jinja pages (LGU navy/white/green theme)
    static/css/     stylesheet
```

## Honest demo labels

- The scanner accepts typed/pasted payloads plus a demo-fill helper. A real
  deployment reads codes with the phone camera (needs `pyzbar` or a JS
  scanner library).
- Broadcasts are logged in the demo, not sent through a real SMS gateway.
- Change `HMAC_SECRET` and `SECRET_KEY` in `config.py` before any real use.

## Phase 35K — dynamic configuration and identity integrity

### HTTP / HTTPS boundary

Development and the on-site Expo demo run over plain HTTP on the local
network (`http://<lan-ip>:5000`). This is a deliberate development choice,
not an oversight. A production deployment MUST terminate TLS in front of
the Flask process (reverse proxy or platform load balancer) and the mobile
app's API base URL MUST be switched to `https://`. The admin PIN, guest
phone numbers, and scan payloads would otherwise travel in clear text on
the same LAN.

### Admin PIN architecture

`PUT /api/settings`, `POST /api/gates/<id>/rename`, `POST /api/broadcasts`
and `POST /api/admin/verify` require the admin PIN via the `X-Admin-Pin`
header (or the unlock form in the browser admin). All of them share one
gate — `_require_admin_pin()` in `web/routes.py` — which compares the PIN
in constant time (`hmac.compare_digest` via `_pin_ok`) and rate-limits
wrong attempts per client IP (429 after `PIN_RATE_MAX_FAILS`; Phase 37
BE-001/SEC-002). Default PIN `2026`, override with `LGU_ADMIN_PIN`. The
mobile app stores the PIN in `AsyncStorage` (`lgu.admin_pin`) exactly as
the administrator types it and attaches the header on every settings
write; the PIN never travels the network except inside the request to the
plain-HTTP LAN server (TLS fronting via `LGU_COOKIE_SECURE` + reverse
proxy is the documented hardening path). There is no server-side session
or token; a future hardening step is to replace the static PIN with
short-lived signed tokens.

### Broadcast modes

`LGU_BROADCAST_MODE` controls the announcement delivery story:

- `demo` (default) — announcements are recorded in the database only. The
  server response note and the mobile confirm sheet say so explicitly.
- `real` — announcements are recorded with a note that a delivery gateway
  is not yet wired up. When a gateway (e.g. SMS provider) is integrated it
  should send from this branch; the UI already uses "Send announcement"
  labels so no client change will be needed.

`/api/config` exposes the active mode so the volunteer screens can label
honesty accurately.

### QR sharing limitation (honest statement)

Duplicate or reused QR codes are DETECTED server-side: a scan whose payload
was already accepted returns `ALREADY SYNCED` (sync path) or `ALREADY
USED` (camera path), and the phone shows the exact reason. However, a
guest sharing a photo of a VALID, unused pass cannot be prevented by the
software alone — the pass is a bearer credential by design (no photo, no
face recognition, no OCR in this build; none was invented). Gate
volunteers are the defence layer: they read the printed name, host and
pass ID on the screen and visually confirm the person presenting it. Any
future photo-based identity check would need a separate consent and
privacy review before it could ship.

### Email verification (Phase 16)

Student signup and password recovery mail a 6-digit code through
`app/emailer.py`, which is **fail-closed**: with `LGU_EMAIL_MODE` unset
(default `disabled`) those routes answer `503 email_unavailable` and no
account is created. Delivery modes, SMTP/TLS settings, the no-send
validation (`scripts/check_email_config.py check`), the connectivity
`probe`, and the explicitly requested `test-send --to <mailbox>` are
documented in `docs/EMAIL_CONFIGURATION.md`, with a placeholder template at
`../.env.example`. Settings come from the process environment — there is no
`.env` loader.

### Data truth

`expected_attendance` is an editable event target (Admin → Convocation
details), not a claim that the roster holds that many students.
`student_roster_count` is the number of rows in the students table
(24 seed students in the shipped database). `announcement_audience_count`
is the roster size used as the broadcast audience when sending to all
gates; per-gate audiences derive from live scan history (who is currently
inside at the selected gates). Progress percentages on the mobile screens
are computed against `expected_attendance` only and show an explicit
"Not set" state when it is zero — the roster is never silently substituted
as an attendance target.

### Regression tests

Phase 35K validation lives in the `mobile/scripts/` test battery:
`data-truth-test.mjs` (server-level proof: settings change, gate rename,
event metadata change, broadcast audience, sync idempotency), plus
source-pin tests `ui-35k-source-test.mjs`, `ui-35j-source-test.mjs`,
`navigation-broadcast-test.mjs`, and `progress-test.mjs`. They boot their
own isolated Flask instances (temp DB, production DB untouched — Phase 35I
isolation guard).

### Phase 35L

No backend behavior changed in 35L — it is a mobile-only phase (guest
pass sharing/save, QR white plate, scanner flash + permission recovery,
full-screen result states, haptics, name validation, gate sheet UX,
search helper). The production database is untouched: settings,
broadcasts, guests, and dashboard read identically before and after the
phase (verified by before/after stamps). Validation: `ui-35l-source-test.mjs`
(13 checks) and the full `mobile/scripts/` battery.

### Phase 38 — shared analytics and event reliability

One analytics core feeds every surface. `dashboard_summary()` and
`dashboard()` both return the shared keys `remaining_attendance` (null
until `expected_attendance` is set — never a fabricated 0), `rejected_count`
and `duplicate_count` (today's `scan_rejections` log; duplicate ⊆
rejected by one flag; busy verdicts are never logged), `trends` (hourly
entries/exits/cumulative — scan *events*, while occupancy keeps the
latest-scan-wins dedupe), `poll_interval_ms` (server cadence clamped to
2000–30000 ms, env `LGU_DASHBOARD_POLL_MS`, default 5000), and
`admissions_by_occasion`. `?occasion=ceremony|rehearsal` scopes the
admission keys at the routes layer (400 on invalid values). The student
portal reads counts only from `GET /api/student/attendance` (Bearer
student session): `registered / verified / remaining / percentage /
expected / attendance_set / generated_at` — no names, gates, feed,
throughput, or rejection detail cross the privacy boundary.

Reliability changes in the same phase: SQLite foreign keys are enforced
on every connection (DB-002, plus a unique index so one host can mint at
most one guest pass), settings/connection helpers always close their
handles (DB-003), guest self-registration is rate-limited per IP window
with a daily cap (BE-003, env `LGU_GUEST_RATE_*`), and the mobile app
stores scanner sessions/admin PIN in the OS keystore
(`expo-secure-store`; web keeps memory only), auto-queues scans when the
network is down (MOB-002), and classifies only transport failures as
offline — a 4xx/5xx never flips the device offline (MOB-003).

Validation: `app/scripts/test_phase38_db_reliability.py` (23),
`test_phase38_guest_rate_limit.py` (13), `test_phase38_analytics.py`
(58 — payload parity, privacy boundary, zero-write polls, 4×5 writers +
4×5 readers concurrency, clamps, pre-v14 honest zeros, prod stamp), and
`mobile/scripts/phase38-reliability-test.mjs` (38) in the full battery.
The migration (`v14`) runs on disposable databases only — production
stays at user_version 6 until the operator approves DB-001.
