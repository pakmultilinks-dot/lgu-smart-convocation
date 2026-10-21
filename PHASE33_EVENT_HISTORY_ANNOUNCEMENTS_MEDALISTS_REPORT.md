# Phase 33 — Event Consistency, History, Announcements & Medalist Board

Student-facing event information made consistent, trustworthy and honestly
labelled across four screens (Event Details, Convocation History,
Announcements, Medalist Board), plus the shared language on Home,
Registration and Entry Pass. Scope was limited to those areas; all
pre-existing changes were preserved. No commits, pushes, deploys or
production-database writes were made.

## 1. Initial state (what the working tree already held)

- Branch `main` @ `298c272`, ~210 changed/untracked paths accumulated across
  Phases 9–32 (nothing committed since Phase 8). Phase 33 built on top.
- Production `app/lgu.db` hash before Phase 33:
  `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F`
  (matches the long-standing baseline).
- Baseline green: 38 mobile source-pin scripts, `tsc --noEmit` 0 errors,
  `expo lint` 0 problems, 42 backend test scripts.
- Known Phase-33-era issues found during inspection (the ones this phase
  fixed):
  - `event.tsx` rendered one combined "Date" card + a flat Annual-cycle
    table; the rehearsal venue sat in a truthy-only branch
    (`{event.rehearsal.venue ? ...}`) and the ceremony venue lived in a
    separate card — venue/occasion association was easy to misread.
  - `history.tsx` used a bare `Confirmed 2026-12-12` line (ambiguous —
    ceremony date vs registration confirmation), never showed the
    account-claim date alongside it, and linked nowhere.
  - `announcements.tsx` rendered the stale badge only inside the non-empty
    branch (invisible when the feed was empty), had no distinction between
    "no active convocation" and "nothing published", and showed no
    audience/edit information.
  - `medalists.tsx` had ONE generic "No medalists to show" empty title for
    every empty case (unpublished board, no match for filters, filter the
    board no longer carries).
  - `home.tsx` / `registration.tsx` described an active registration as
    "Your registration is confirmed — you are on the convocation list"
    (merging "active" into a generic "confirmed").
  - `pass.tsx` labelled the ceremony date row simply "Date" with subtitle
    "Confirmed <date>".

## 2. Authoritative schedule source (Part A — verified, no changes needed)

The single source of truth for event information is the server-side
publication snapshot: `convocation_events.student_payload(db)` serves the
**published** `convocation_publications` row (via `eventApi.fetchEvent()` →
`/api/student/event`). Verified this phase:

- No hardcoded schedule date exists in any live mobile code. The only
  `2026-…` literals in the tree are ISO-format examples inside
  `AdminScreen.tsx` doc comments and scanner test fixtures — neither is a
  schedule source of truth (pinned by check 1.1, which strips comments).
- Timezone: the countdown/phases are computed server-side in
  `Asia/Karachi` (`config.DISPLAY_TZ`) and shipped as `event.portal_tz`;
  the client renders only that value (check 1.4).
- Production database has NO publication row — the event is unpublished
  (draft-only `expected_date` 2026-12-12T09:00:00+05:00 on the
  `convocations` row). The October 20 date seen in older screenshots was a
  disposable Phase-30 fixture DB, not production. No screen invents a
  date; the published-state distinction is preserved end-to-end.
- Negative countdowns impossible: `EventCountdown.countdownText` returns
  `"Completed"` for `phase === "completed"` (server-computed), never a
  negative number; live tick is a cleaned-up interval.

## 3. Conflicting-date findings

No source-level date conflicts exist: the app renders exactly what the
published snapshot says (confirmed → use it; expected → always labelled
"(provisional)"; nothing → "Not announced"/"Not published"). The
confusions users reported were **presentation** ambiguities, now fixed:

| Before | Ambiguity | After |
| --- | --- | --- |
| history: `Confirmed 2026-12-12` | could read as registration confirmation | `Ceremony date · Confirmed 2026-12-12` + separate `Account claim · Claimed <date>` line |
| pass: row titled `Date` + `Confirmed <date>` | same | row titled `Ceremony date` (subtitle unchanged, now unambiguous) |
| home/registration: "registration is confirmed" | merged "active" into "confirmed" | "Your registration is active and usable for entry." |
| event: combined Date card | rehearsal vs ceremony dates read as one schedule | separate occasion cards (each own pill/date/time/venue) + explicit `Expected date` / `Confirmed date` rows |

## 4. Root causes and fixes, per screen

### 4.1 Event Details (`mobile/app/(student)/event.tsx`) — Part B

- **Root cause**: occasions rendered as a flat table inside one card with
  venue string-concatenated into the subtitle; rehearsal venue was a
  truthy-only branch; the publication stamp used a `space-between` row
  that could overflow narrow screens; the stale badge lived inside the
  non-null branch; long screens lost page context on scroll.
- **Fix**:
  - Each occasion now renders as its **own** `SectionCard`
    (`key={o.key}`) — label, state pill, date/time with portal timezone,
    and its own venue line (`o.venue || "Venue not published"`). A venue
    can never be read as belonging to the other occasion.
  - Explicit `Expected date … (provisional)` / `Confirmed date …` /
    `Start time` rows keep the publication states separate and honest.
  - Empty/unpublished fields say so: "Date and time not published",
    "Venue not published", "Not officially confirmed yet".
  - Publication stamp row now `flexWrap`s (no overflow); `Screen` gained a
    `stickyHeader` option so the AppHeader stays visible while the
    schedule scrolls (header background made opaque paper).
  - Stale badge renders in every ready state (before the `event === null`
    check) and names the last loaded information.
  - Legacy fallback: if a server ever predates the occasions payload, the
    pinned `Venue` card with `event.venue || "Not announced"` still renders
    (Phase 28 contract kept).
  - No dead buttons: no directions/add-to-calendar anywhere (no
    authoritative data, no working implementation).

### 4.2 Convocation History (`mobile/app/(student)/history.tsx`) — Part C

- **Root cause**: `eventLine()` produced a bare `Confirmed <date>` with no
  meaning label; the account-claim date was never surfaced; the screen
  offered no route to the current registration/pass.
- **Fix**:
  - `eventLine` → `ceremonyLine`: every line states its meaning —
    `Ceremony date · Confirmed <date>` / `Ceremony date · Expected <date>
    (provisional)` / `Ceremony date · Not announced` /
    `… Event details not published`.
  - New labelled lines: `Account claim · Claimed <date>` (distinct from
    ceremony date — the API carries no registration-confirmation
    timestamp, and we do not invent one) and `Registration number · …`.
  - Active entries link to `View entry pass` and `My registration`
    (existing valid routes, active convocation only).
  - Empty state explains the claim condition ("Once your account claims an
    active registration…"), not "confirmed registration".
  - Authz preserved: token-gated load, 401 → welcome; backend remains
    account-scoped (`WHERE c.account_id = ?`). 401 never renders as empty.

### 4.3 Announcements (`mobile/app/(student)/announcements.tsx`) — Part D

- **Root cause**: only two states existed (populated / "No announcements
  yet"); the stale badge was inside the non-empty branch; no audience or
  edit information; a failed request already fell to an error state but
  the empty/offline distinctions did not exist.
- **Fix** — states now distinguish loading / no active convocation /
  nothing published yet / populated / offline-over-data / failed:
  - Stale badge renders in **every** ready state and names the last
    successful load time (`Offline — showing announcements loaded at
    HH:MM. Retrying automatically.`).
  - `convocation === null` → "No active convocation" (different copy);
    empty feed → "No announcements yet" + a `View event schedule` button
    so event info stays reachable.
  - Per-card meta line: `Students · Published <date>` (+ ` · Updated
    <date>` only when edited), from the same `published_at`/`updated_at`
    the server already had; count line shows the latest publication date.
  - A failed background refresh keeps the last feed on screen (stale
    badge) — cached announcements are never swapped for an empty page; a
    non-silent failure is an error state with retry, never an empty
    success. Event-association-per-announcement and replacement chains do
    not exist in the API (documented in §7; not fabricated client-side).

### 4.4 Medalist Board (`mobile/app/(student)/medalists.tsx`) — Part E

- **Root cause**: a single `EmptyState "No medalists to show"` covered all
  empty outcomes; active filters were not displayed; no reset affordance.
- **Fix** — the six outcomes are now distinct:
  1. no convocation configured → "No convocation configured" (unchanged);
  2. loaded → grid + count line;
  3. no match for the active filters → "No medalists match these
     filters" + `Reset filters` action;
  4. filter the board no longer carries (selected value not in the
     current `departments`/`categories`) → "This filter is no longer
     available" + `Reset filters`;
  5. request failed → `ErrorState` with retry;
  6. stale → offline badge (rendered for every ready state).
  - "Reset filters" button also appears above the grid whenever a filter
    is active.
  - The "Showing: …" line is built from the **same** state variables
    (`category`, `department`) that are passed into `fetchBoard` — the
    displayed filters can never drift from the query.
  - No publication date is shown (the board API exposes none — see §7);
    the client fabricates nothing.

### 4.5 Shared language (Part F) — home / registration / pass

- `REG_STATUS.active.meaning` → "Your registration is active and usable
  for entry." (both `home.tsx` and `registration.tsx`) — "active" no
  longer masquerades as "confirmed"; official-list membership stays its
  own row (`Official convocation list`, Phase 31) with its own wording.
- `pass.tsx`: event-details row retitled `Date` → `Ceremony date`;
  venue fallback "Not set" → "Not published" (consistent with the other
  screens).
- Kept separate everywhere (never merged): registration active /
  registration confirmed (no such concept is invented) / included in
  official list / profile complete / schedule published / ceremony
  confirmed / announcement published / medalist results published /
  entry pass issued / entry pass currently valid.

## 5. Files changed

Mobile:
- `mobile/src/ui/index.tsx` — `Screen` gained `stickyHeader` (opt-in
  `stickyHeaderIndices=[0]`); header background made opaque paper so a
  stuck header never shows content through it. Invisible to other screens.
- `mobile/app/(student)/event.tsx` — occasion cards, honest fallbacks,
  wrapping publication row, stale badge repositioned, sticky header.
- `mobile/app/(student)/history.tsx` — `ceremonyLine`, account-claim +
  registration-number lines, active-entry links, empty-state copy.
- `mobile/app/(student)/announcements.tsx` — six distinguishable states,
  last-load-time badge, audience/edit meta, event-schedule link.
- `mobile/app/(student)/medalists.tsx` — six empty/stale outcomes,
  active-filter display, reset affordance.
- `mobile/app/(student)/home.tsx` — REG_STATUS active meaning.
- `mobile/app/(student)/registration.tsx` — REG_STATUS active meaning.
- `mobile/app/(student)/pass.tsx` — `Ceremony date` row title, venue
  fallback wording.
- `mobile/src/api/eventApi.ts` — `Announcement.audience: string`.
- `mobile/scripts/phase33-event-history-announcements-medalists-test.mjs`
  — new: 47 source pins over the 14 required coverage areas.

Backend (one minimal, backward-compatible change):
- `app/web/student_routes.py` — `/api/student/announcements` now returns
  `audience` per row (the feed query already guaranteed
  `audience = 'students'`; the field lets the app state who a row was
  addressed to). No other backend file was modified.

## 6. Backend / API contract changes and compatibility

- **Change**: `/api/student/announcements` rows gain `audience`.
  - Compatibility: purely additive. The pinned exact-dict test covers the
    EMPTY payload (`{"convocation": None, "total": 0, "announcements":
    []}`), which is unaffected; populated-shape tests pin titles only.
    Older clients ignore the new field. All 42 backend tests pass.
- **Client-only changes**: everything in §4 is presentation logic over
  existing contracts; no existing field changed meaning or was removed.
  `Announcement.audience` is typed required because the server always
  sends it post-change.

## 7. Documented API limitations (no fabrication)

The following are NOT supported by the current API and therefore are
honestly absent from the client rather than faked:

- **Medalist board**: no list-level publication/updated timestamp (per
  card the API pins exactly `{id, department, student_name,
  award_category, position, has_photo}`). The board screen shows no
  publication date.
- **History**: no registration-confirmation timestamp exists — only
  `status` and `claimed_at`. History labels what exists (ceremony date,
  account-claim date) and invents no confirmation date.
- **Announcements**: no per-row event/occasion link and no
  replacement/update chain in the payload (server audit trail exists but
  is not exposed to students); no server-side `fetched_at` (the payload
  shape is pinned by an exact-dict test), so the app records the
  client-side load time for the offline badge.
- **Event**: no separate "reporting time" field (only ceremony start
  time); shown as such.

## 8. Tests — exact commands and actual results

Mobile (from `mobile/`):
- `npx tsc --noEmit` → **0 errors**
- `npx expo lint` → **0 problems**
- `node scripts/phase33-event-history-announcements-medalists-test.mjs` →
  **47/47 checks passed**
- Full regression, every script in `scripts/*.mjs` → **39/39 scripts
  exit 0** (38 pre-existing + the new Phase 33 script), including the
  contract-sensitive suites: `event-announcements-test.mjs` (25),
  `medalist-board-test.mjs` (22), `pass-history-source-test.mjs` (31),
  `phase28-authorization-source-test.mjs`,
  `phase29-annual-event-source-test.mjs`, `phase8-freshness-test.mjs`,
  `phase31-student-nav-test.mjs`, `phase32-student-profile-test.mjs`,
  `master-audit-regression.mjs`, `release-safety-test.mjs`.

Backend (from `app/`): all 42 `scripts/test_*.py` run with
`..\.venv\Scripts\python.exe` → **42/42 OK** (includes the exact-dict
feed pin, the medalist exact-key-set pins and the public-leak pins).

Note: three Phase-33 pins were corrected during bring-up (they were
written from memory before re-reading the sources): the date-literal scan
now strips comments (AdminScreen doc examples), the countdown pin accepts
the controlled live tick (`clearInterval` present), and the history
silent-guard pin matches the actual `prev.kind === "ready"` functional
updater. No existing assertion was weakened or deleted.

## 9. Regression status and unresolved items

- All 39 mobile scripts, tsc, lint and all 42 backend tests green.
- Unresolved / pending device acceptance (see §10): visual confirmation
  of the sticky header, occasion-card layout, wrap behaviour of the
  publication row, medalist reset affordance, and offline badges on a
  real Android device — no emulator/adb available in this environment.

## 10. Manual Android verification checklist (pending — no device)

1. Event Details: header stays pinned while scrolling; publication stamp
   wraps on a 320px screen; each occasion card shows only its own venue;
   unpublished state reads "No event information published".
2. History: ceremony-date lines labelled; `Account claim` line present;
   active entry shows pass/registration links; past entries do not.
3. Announcements: offline badge appears even when the feed is empty and
   names the load time; empty feed still offers "View event schedule".
4. Medalists: apply a department filter that matches nothing → "No
   medalists match these filters" + Reset works; after the board changes,
   a stale filter reads "This filter is no longer available".
5. Home/Registration: active meaning reads "active and usable for entry";
   pass shows "Ceremony date".

## 11. Production database integrity

- Hash before: `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F`
- Hash after:  `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F`
- Identical. All tests ran on disposable fixture DBs; `app/lgu.db` was
  never opened for writing. Nothing committed, pushed, deployed or
  branched.

## 12. Remaining prerequisites before release

- Device acceptance (§10) on a real Android device.
- A real publication must exist before the production event screen shows
  anything but the honest "No event information published" state (the
  current production event is unpublished — by design, not a defect).

## 13. Honest release status

**NO-GO for release solely on this phase's evidence** — everything
verifiable by automation is green (47/47 new pins, 39/39 mobile scripts,
tsc 0, lint 0, 42/42 backend, DB hash unchanged), but the spec requires
device acceptance to be reported separately, and no device was available.
The four screens now distinguish every state the API can evidence, keep
the published snapshot as the only schedule source, and fabricate nothing
where the API is silent (§7).
