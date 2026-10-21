# IA — Information architecture + screen contracts (locked)

Per §10/§9/§29/§11/§12/§25. This is the single navigation + purpose contract for the rebuild.

## Mode model

```
Launch (app/index) ──► Mode Selection
                          ├─ Volunteer Operations ──► /volunteer (Tabs)
                          └─ Live Dashboard ─────────► /liveboard (top-level)
```

- Launch shows LGU identity + last-used mode shortcut (recognition, not re-interrogation) → routes to mode-picker on first run or after mode clear.
- `store/appMode.ts` keys the mode (existing contract preserved).

## Volunteer tabs — EXACTLY five (§29)

| Tab | Route | Purpose (§9 Q-set) | Primary data |
|---|---|---|---|
| Home | /volunteer/home | "Move people through the gate" — assignment, progress, ONE dominant Scan action, search recovery, last scan, connection | /api/gates (assignment), /api/dashboard/summary or lightweight counts for today's gate, health, last scan (local ops store) |
| Scanner | /volunteer/scanner | The scan loop: continuous QR, gate+mode visible, instant result moment | camera + POST /api/scan + POST /api/sync (queue) |
| Search | /volunteer/search | Recover from damaged/missing QR: find attendee/guest by name/roll/phone, act (show pass context, guide manual resolution) | GET /api/search?q= (NEW) |
| Guests | /volunteer/guests | Register guest + issue pass | GET/POST /api/guests, GET /api/guest-pass/<gid> |
| Settings | /volunteer/settings | Volunteer identity, connection status entry, about, sign-out/mode switch | local store + /api/health |

Secondary (NOT tabs — single entry points):
- **Admin** ← Settings → "Admin" row → /admin (Backend Connection, Convocation details, Expected attendance, ID printing, Gates, Broadcast entry).
- **Broadcast** ← Admin → /broadcast.
- **Guest pass (public)** ← /guest-pass (deep link from registration + launch route for guests).
- **Live Board** reachable from Home footer link + mode switch (top-level destination, not a tab).

Forbidden (explicit): duplicate destination in tab+card+gear+header; fake navigation cards; Home showing full dashboard grid; scan feed on Live Board; marketing text on operational screens.

## Home composition law (§11 hierarchy, top → bottom)

1. **Header**: LGU crest (48) + "LGU Convocation 2026" + "Lahore Garrison University" (once, small) + connection pill.
2. **Assignment block**: "You are at" → Gate G1 Main Gate (large) · Entry mode chip (or Exit). Editable via row → Scanner gate picker.
3. **Event progress**: "12 of 2,500 inside" style — ONE metric strip (checked-in vs expected), no charts, no gender split (that's the Live Board's job).
4. **PRIMARY**: "Scan QR Code" — 56dp emerald button, full width, with scan icon. Dominates the fold.
5. **Recovery row**: "Find attendee" (Search) — secondary button/row.
6. **Last scan**: result pill (title, name, gate, time) or "No scans yet this session".
7. **Status**: last sync time + OfflineBanner when offline (amber, §27 copy only).

## Scanner composition law (§21–24)

- Persistent header strip: "G1 Main Gate" + Entry/Exit segmented control (icons + labels).
- Camera surface dominant; corner-bracket guidance only (no decorative frame); torch toggle; auto-zoom when barcode bounds justify (bounded, hysteresis).
- Continuous scanning: decode → freeze-frame + haptic → result moment (full-contrast card: icon, TITLE, name, sub detail, gate, time) → auto-dismiss 4 s → resume. Duplicate-frame suppression 4 s per qr_id.
- Outcome classes (structurally distinct, not color-only):
  - ACCEPTED (entry/guest entry) — check icon, emerald field.
  - ALREADY INSIDE / ALREADY USED — repeat icon, red field + last-gate detail.
  - INVALID / UNKNOWN — shield-off icon, red field + recovery hint pointing to Search.
  - EXIT RECORDED — exit icon, emerald field.
  - QUEUED (OFFLINE) — cloud-off icon, amber field + queue count.
- Offline: scan still works → queued locally; banner "Offline mode — local scans remain available" (§27). On reconnect: flush queue, show per-item outcomes.

## Search contract (§12, NEW endpoint F)

`GET /api/search?q=<query>` → `{"results":[{"type":"student"|"guest","name","roll_no"?,"program"?,"gender"?,"qr_id","host_roll_no"?,"phone"?,"inside":bool,"used":bool,"payload":"LGU1:..."}]}` (q ≥ 2 chars; matches name LIKE, roll_no LIKE, phone LIKE, host_roll_no LIKE, qr_id exact-ish; limit 25; students AND guests merged, newest activity first). UI: search field, filter chips (All/Students/Guests/Inside/Outside), result rows with state pill (Inside/Outside · Pass used/Available), tap → detail sheet with signed payload context + "Registered at gate X at HH:MM:SS" when inside (from last scan). Empty state = designed ("No attendee matches '<q>' — check spelling or scan their pass"), NOT a dummy dump. This doubles as QR-recovery: damaged QR → search name → verify identity visually → proceed per gate policy (volunteer confirms visually; pass payload shown for re-print paths in Admin context only).

## Live Board composition law (§25 hierarchy)

LIVE pill + freshness → **People Inside** (metric 40) → "1,240 / 2,500 expected" + progress bar → Male · Female · Guests row → **Gate activity** (7 rows: label, entries·15min, entries/exits totals, last activity) → Sync status → "Updated HH:MM:SS". NO scan feed. NO marketing. Poll 2.5 s live / backoff when stale; offline → amber banner + last synchronized values retained (§27).

## Data-state law (§37) — applies to EVERY screen

| State | Rule |
|---|---|
| Loading | Skeleton or labeled spinner in the final layout position (no layout jump) |
| Success | Real values only; numbers formatted; never render raw JSON |
| Empty | Designed explanation + next action (no `- / -`) |
| Stale | Amber "Showing last synchronized data · HH:MM:SS" |
| Offline | §27 copy + genuine Retry + local actions still enabled |
| Error | Human sentence + Retry that actually retries; technical detail in __DEV__ log only |

## Screen inventory for build order (Step D)

1. app/_layout.tsx + index (launch) 2. mode-picker 3. (volunteer)/_layout (5 tabs) 4. Home 5. Scanner 6. Search (+ backend F) 7. LiveBoard 8. Guests 9. Settings 10. Admin 11. Broadcast 12. GuestPass 13. +not-found.
