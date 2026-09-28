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
