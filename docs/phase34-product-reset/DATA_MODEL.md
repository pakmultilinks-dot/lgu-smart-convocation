# DATA_MODEL — Schema + derived-state semantics (Phase 34A, 2026-10-03)

Evidence: `PRAGMA` + row counts via `.venv\Scripts\python.exe` against `app/lgu.db` TODAY (read-only); logic re-read from `app/database.py`, `app/models.py`, `app/ids.py`, `app/config.py`; business rules re-verified today via 11-scenario audit script (29/29 smoke from 2026-10-02, logic unchanged since).

## Schema (database.py SCHEMA — authoritative; PRAGMA confirmed today)

| Table | Columns | Constraints / indexes | Rows at Phase 34A audit end |
|---|---|---|---|
| students | id PK, roll_no UNIQUE NOT NULL, name, gender CHECK('Male','Female'), program, qr_id UNIQUE, created_at | UNIQUE autoindexes on roll_no + qr_id; **idx_students_qr non-unique duplicate (P-17)** | **40** (20 M / 20 F) |
| guests | id PK, name, phone, host_roll_no, qr_id UNIQUE NOT NULL, created_at | UNIQUE autoindex on qr_id; **idx_guests_qr non-unique duplicate (P-17)** | **6** (incl. 2 "Smoke Test Guest", "Phase Test Guest" used:true) |
| gates | id PK, code UNIQUE NOT NULL, label | UNIQUE autoindex on code; seeded G1–G7 | **7** |
| scans | id PK, qr_id, person_type CHECK('student','guest'), person_name, gate_id, mode CHECK('entry','exit'), volunteer, scanned_at, source DEFAULT 'online' | idx_scans_qr/_gate/_time/_gate_mode_time/_person_type | **1** (Phase Test Guest T5483B4R entry G3 online 2026-10-01) |
| broadcasts | id PK, audience, message, sent_by, sent_at | — | 2 |
| settings | key PK, value, updated_at | SETTING_KEYS: convocation_name, convocation_year, convocation_datetime, venue, expected_attendance | 5 (expected_attendance=2500) |

- **P-17 (new):** `idx_students_qr` + `idx_guests_qr` are NON-unique indexes duplicating the UNIQUE autoindexes on qr_id — redundant; drop candidates in the next implementation phase (no behavior change).
- No foreign keys declared — guest host integrity enforced in code (routes POST /api/guests checks students.roll_no).
- DB file `app/lgu.db` (config.py `DB_PATH`).

## Audit-time contents

students=40 (20 M / 20 F, roll LGU-2024-101…140 seeded roster), guests=4 (Nasir Khan, Shazia Bibi, Tariq Mehmood, Phase Test Guest), gates=7, scans=1 (guest T5483B4R entry G3 online), broadcasts=2, settings=5 keys. No counter tables — **all dashboard numbers are derived from the scans table on demand**.

## QR identity (ids.py + config.py)

- Format: `LGU1:<8-char id>:<hmac_sha256[:10]>`; alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no 0/O/1/I); HMAC secret env `LGU_HMAC_SECRET` (committed default = demo). `verify_payload` checks version + signature.
- Verified test payloads: male `LGU1:9W2GJHKT:cf694dbe9b` (Muhammad Ahmed, LGU-2024-102), female `LGU1:8G8YVTGC:1a4197baaf` (Ayesha Khan, LGU-2024-101), guest `LGU1:EDD7RZ2Q:85e00d593f` (Nasir Khan).

## Derived-state semantics (models.py — the single source of truth)

- `last_scan(qr_id)` = latest scan row by id. `student_inside` ⇔ last scan mode == "entry". **Not** a counter — re-entry allowed after exit (exit then entry records again; verified indirectly by flows 1→3→4: after exit, exit again → "NOT INSIDE").
- `guest_used` ⇔ ANY scan row exists for the guest qr_id → guests are strictly single-scan lifetime passes.
- `inside_total` (dashboard) = students whose latest scan is entry, grouped by gender (`_inside_by_gender`, one aggregate query). `guests_inside` = guests with ≥1 scan. **People Inside headline = students only; guests reported separately** — the mobile hero must present both correctly (§25: "People Inside" + Male/Female/Guests).
- `expected_attendance` (settings, int>0) drives `arrival_pct`; else roster total drives it. Roster expected_* fields = live student/guest counts.
- Throughput = entries (`mode='entry'`) per gate with `scanned_at >= now-15min` (string compare on `YYYY-MM-DD HH:MM:SS` — safe because fixed-format). Busiest = most entries today. Sync rows = lifetime per-gate count/entries/exits/last.
- `generated_at` stamped per dashboard call (`now_str`, Asia/Karachi, needs tzdata on Windows).

## Business rules — re-verified today (audit script; 29/29 smoke 2026-10-02)

| Rule | Outcome captured |
|---|---|
| Entry ok | green ENTRY RECORDED (server now, or client ts via sync) |
| Duplicate entry | red ALREADY INSIDE + last gate + time |
| Exit ok | green EXIT RECORDED |
| Exit without entry | amber NOT INSIDE |
| Guest entry | green GUEST ENTRY RECORDED + host + phone sub |
| Guest reuse / exit-after-any-scan | red ALREADY USED `One entry per guest.` (P-09 ordering) |
| Unused guest exit | amber GUEST PASS IS ENTRY ONLY (reachable only pre-scan) |
| Bad signature | red INVALID CODE (tampered/forged) |
| Missing / null / non-int gate | red NO GATE SELECTED |
| Unknown gate / mode / qr_id | red UNKNOWN GATE / NO MODE SELECTED / UNKNOWN CODE |
| Sync | preserves client scanned_at, source=queued, per-item results, max 500; permanent rejections surface as business errors |
| Settings PUT | validates types/ranges; test-reset removes only test scans (`removed:3` today) |

**Verdict: business rules correct and complete for gate operations (§36 — preserve).** Additions limited to search (shipped Phase 34, additive).

## Sync semantics (offline queue contract)

Server trusts client timestamps (bounded ≤32 chars else server-time fallback). Duplicate suppression is CLIENT-side (offlineQueue dedupe). Server applies normal duplicate/exit rules on replay — a queued entry that became invalid returns its business error inside `results`; client surfaces per-item outcomes (not just `synced`). `PERMANENT_REJECTIONS` (ALREADY INSIDE/USED/NOT INSIDE/INVALID CODE/UNKNOWN CODE/NO GATE/NO MODE/UNKNOWN GATE/GUEST PASS IS ENTRY ONLY) are dropped; transient failures re-queue. Reconcile is POSITIONAL (entry+exit same payload both legitimate — not payload-keyed).

## Test tooling

`TEST_ROLLS = (("male","LGU-2024-102"),("female","LGU-2024-101"))`, `TEST_GUEST_ID = 1`; `/api/test-records` exposes payloads; `/api/test-reset` deletes only test scans. Today's final reset `removed:3` — **audit left DB counts unchanged** (40/6/7/1/2/5 in schema table above).

## Audit integrity note (§18)

Phase 34A scripts were read-only except POST /api/scan, /api/sync, /api/test-reset (test-data paths); all audit-created scans cleaned by final test-reset; students/guests/gates/settings/broadcasts untouched; no schema change; no app source change.
