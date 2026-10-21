// Phase 33 — event consistency, history, announcements & medalist board:
// source-level pins (no server needed) for the four event-facing screens
// plus the shared schedule source.
//
// Covers spec §9's 14 areas:
//   1  authoritative schedule source (published snapshot, no hardcoded dates)
//   2  rehearsal vs main ceremony as distinct cards/occasions
//   3  missing/unpublished schedules read honestly (never blank)
//   4  countdown never negative / never over a provisional date
//   5  history date labels state their meaning (no bare "Confirmed <date>")
//   6  history authz intact (account-scoped backend + 401 handling)
//   7  announcement states distinguish loading/empty/offline/error
//   8  failed request never masquerades as empty success
//   9  announcement audience + publication rules pinned server & client
//  10  medalist filters: displayed state === queried state
//  11  medalist empty: unpublished / no-match / unsupported-filter distinct
//  12  no publication metadata is fabricated on the medalist board
//  13  Part F language: "confirmed" never merges distinct concepts
//  14  Phase 31/32 nav + link integrity re-pinned
//
//   node scripts/phase33-event-history-announcements-medalists-test.mjs
//
// Exit code 0 = every check passed.

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
if (!cwd.endsWith("mobile")) cwd = root;
const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const readRepo = (rel) => readFileSync(join(cwd, "..", rel), "utf8");
const has = (src, needle) => src.includes(needle);
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

let failures = 0;
let total = 0;
const check = (label, ok, detail = "") => {
  total += 1;
  if (ok) {
    console.log(`ok   ${label}`);
  } else {
    failures += 1;
    console.log(`FAIL ${label}${detail ? ` :: ${detail}` : ""}`);
  }
};

const eventScreen = read("app/(student)/event.tsx");
const histScreen = read("app/(student)/history.tsx");
const annScreen = read("app/(student)/announcements.tsx");
const medalScreen = read("app/(student)/medalists.tsx");
const homeScreen = read("app/(student)/home.tsx");
const regScreen = read("app/(student)/registration.tsx");
const passScreen = read("app/(student)/pass.tsx");
const eventCode = stripComments(eventScreen);
const histCode = stripComments(histScreen);
const annCode = stripComments(annScreen);
const medCode = stripComments(medalScreen);
const passCode = stripComments(passScreen);
const eventApi = read("src/api/eventApi.ts");
const studentRoutes = readRepo("app/web/student_routes.py");
const convHistory = readRepo("app/convocation_history.py");
const announcementsPy = readRepo("app/announcements.py");

// 1 — authoritative schedule source -------------------------------
{
  const appSources = [];
  const walk = (dir) => {
    for (const e of readdirSync(join(cwd, dir), { withFileTypes: true })) {
      const rel = `${dir}/${e.name}`;
      if (e.isDirectory()) walk(rel);
      else if (e.name.endsWith(".ts") || e.name.endsWith(".tsx"))
        appSources.push(rel);
    }
  };
  walk("app");
  walk("src");
  // Comments may NAME example shapes (AdminScreen ISO-format docs) — only
  // live code counts as a schedule source of truth.
  const dateLiterals = appSources.filter((rel) =>
    /20(2[4-9]|[3-9]\d)-\d{2}-\d{2}/.test(stripComments(read(rel))),
  );
  check(
    "1.1 no hardcoded schedule date literal in mobile app/src sources",
    dateLiterals.length === 0,
    dateLiterals.join(", "),
  );
  check(
    "1.2 event screen renders only the server snapshot (fetchEvent)",
    has(eventCode, "eventApi.fetchEvent()"),
  );
  check(
    "1.3 publication stamp shown as data, not a hardcoded date",
    has(eventCode, 'Published ${event.published_at.slice(0, 10)}'),
  );
  check(
    "1.4 timezone comes from the server payload (portal_tz), never a client constant",
    has(eventCode, "event.portal_tz") && !has(eventApi, "Asia/Karachi"),
  );
}

// 2 — rehearsal vs main ceremony ----------------------------------
check(
  "2.1 occasions render as SEPARATE cards keyed by occasion",
  has(eventCode, "event.occasions.map((o) => (") &&
    has(eventCode, "<SectionCard key={o.key}>"),
);
check(
  "2.2 each occasion card carries its own venue line (venue follows its occasion)",
  has(eventCode, 'o.venue || "Venue not published"'),
);
check(
  "2.3 rehearsal no longer rendered by a truthy-only venue branch",
  !has(eventCode, "{event.rehearsal.venue ? (") &&
    !has(eventCode, "{o.venue ? ("),
);
check(
  "2.4 ceremony card names expected and confirmed dates separately",
  has(eventCode, 'title="Expected date"') &&
    has(eventCode, 'title="Confirmed date"') &&
    has(eventCode, 'title="Start time"'),
);
check(
  "2.5 page context stays reachable while scrolling (sticky header)",
  has(eventScreen, "<Screen stickyHeader>"),
);

// 3 — honest missing/unpublished ----------------------------------
check(
  "3.1 empty event state reads 'No event information published'",
  has(eventCode, '"No event information published"'),
);
check(
  "3.2 unpublished occasion fields say 'not published', never blank",
  has(eventCode, '"Date and time not published"') &&
    has(eventCode, '"Venue not published"'),
);
check(
  "3.3 missing confirmation is explicit",
  has(eventCode, '"Not officially confirmed yet"'),
);
check(
  "3.4 stale badge renders in EVERY ready state (before the null check)",
  annCode.indexOf("stale ? (") !== -1 &&
    histCode.indexOf("Offline") !== -1 &&
    eventCode.indexOf("Offline — showing the last loaded event information") <
      eventCode.indexOf("{event === null ? ("),
);

// 4 — countdown honesty -------------------------------------------
{
  const countdown = read("src/components/EventCountdown.tsx");
  const cc = stripComments(countdown);
  check(
    "4.1 completed occasions show Completed — no negative countdown",
    has(cc, 'if (o.phase === "completed") return "Completed";') &&
      has(cc, "clearInterval"),
  );
  check(
    "4.2 countdown only runs over announced dates",
    has(cc, '"not_announced"') && has(cc, '"expected"'),
  );
}

// 5 — history date labels -----------------------------------------
check(
  "5.1 history names the ceremony date (bare 'Confirmed <date>' gone)",
  has(histCode, "ceremonyLine") &&
    !has(histCode, "return `Confirmed ${event.confirmed_date}`"),
);
check(
  "5.2 provisional ceremony dates stay labelled in history",
  has(histCode, "(provisional)"),
);
check(
  "5.3 account-claim date is its own labelled line",
  has(histCode, "Account claim · Claimed"),
);
check(
  "5.4 registration reference surfaced (identity, not decoration)",
  has(histCode, "registration_number"),
);
check(
  "5.5 empty history explains the claim condition, not 'confirmed registration'",
  has(histCode, "claims an active registration"),
);

// 6 — history authz ------------------------------------------------
check(
  "6.1 history loads with the account token and 401 → welcome",
  has(histCode, "getToken()") && has(histCode, "e.status === 401"),
);
check(
  "6.2 backend history is account-scoped",
  has(convHistory, "WHERE c.account_id = ?"),
);

// 7 — announcement states -----------------------------------------
check(
  "7.1 loading / empty / error each render distinctly",
  has(annCode, "<LoadingState") &&
    has(annCode, "<EmptyState") &&
    has(annCode, "<ErrorState"),
);
check(
  "7.2 no-active-convocation and nothing-published read differently",
  has(annCode, '"No active convocation"') &&
    has(annCode, '"No announcements yet"'),
);
check(
  "7.3 offline badge names the last successful load time",
  has(annCode, "loaded at ${lastOk") && has(annCode, "setLastOk("),
);
check(
  "7.4 event info reachable from an empty feed",
  has(annCode, '"View event schedule"') &&
    has(annCode, 'router.push("/(student)/event")'),
);

// 8 — failure ≠ empty success -------------------------------------
check(
  "8.1 silent failure keeps the last feed (stale badge), never an empty swap",
  has(annCode, "if (silent && hasDataRef.current)") &&
    has(annCode, "setStale(true)"),
);
check(
  "8.2 non-silent failure is an error state, not an empty page",
  has(annCode, '"Announcements unavailable"'),
);
check(
  "8.3 same guard on history, medalists and event screens",
  has(histCode, 'prev.kind === "ready"') &&
    has(medCode, "silent && hasDataRef.current") &&
    has(eventCode, "silent && hasDataRef.current"),
);

// 9 — audience + publication rules ---------------------------------
check(
  "9.1 backend feed is published + students-only",
  has(announcementsPy, "status = 'published'") &&
    has(announcementsPy, "audience = 'students'"),
);
check(
  "9.2 route returns the audience per row",
  has(studentRoutes, '"audience": r["audience"]'),
);
check(
  "9.3 client displays audience + published date per announcement",
  has(annCode, "cap(a.audience)") && has(annCode, "Published ${day("),
);
check(
  "9.4 edited announcements show their update date",
  has(annCode, "Updated ${day(a.updated_at)}"),
);

// 10 — medalist filters are truthful -------------------------------
check(
  "10.1 'Showing' line built from the same state as the query",
  has(medCode, "medalistApi.fetchBoard") &&
    has(medCode, "Showing: ${[category && cap(category), department]"),
);
check(
  "10.2 reset-filter affordance exists (button + empty-state action)",
  has(medCode, '"Reset filters"') && has(medCode, "resetFilters"),
);

// 11 — medalist empty outcomes -------------------------------------
check(
  "11.1 unpublished / no-match / unsupported-filter read differently",
  has(medCode, '"No medalists published yet"') &&
    has(medCode, '"No medalists match these filters"') &&
    has(medCode, '"This filter is no longer available"'),
);
check(
  "11.2 no convocation still reads 'No convocation configured'",
  has(medCode, '"No convocation configured"'),
);
check(
  "11.3 the generic 'No medalists to show' title is gone",
  !has(medCode, '"No medalists to show"'),
);
check(
  "11.4 failed board is an error state with retry",
  has(medCode, "<ErrorState") && has(medCode, "onRetry"),
);

// 12 — no fabricated publication metadata --------------------------
check(
  "12.1 medalist screen shows no list publication date (API has none)",
  !has(medCode, "published_at") && !has(medCode, "updated_at"),
);

// 13 — Part F language ---------------------------------------------
check(
  "13.1 registration 'active' no longer merges into 'confirmed'",
  !has(homeScreen, "registration is confirmed") &&
    !has(regScreen, "registration is confirmed"),
);
check(
  "13.2 pass names the ceremony date (not an ambiguous Date row)",
  has(passCode, 'title="Ceremony date"'),
);
check(
  "13.3 history and event share the 'Published <date>' convention",
  has(eventCode, "Published ${") &&
    has(annCode, "Published ${") &&
    has(histCode, "Claimed "),
);
check(
  "13.4 no screen collapses distinct concepts into one 'Confirmed' badge",
  !has(homeScreen, 'label="Confirmed"') && !has(regScreen, 'label="Confirmed"'),
);

// 14 — nav + link integrity (Phase 31/32 re-pins) -------------------
check(
  "14.1 history links pass + registration from the active entry",
  has(histCode, 'router.push("/(student)/pass")') &&
    has(histCode, 'router.push("/(student)/registration")'),
);
check(
  "14.2 stale badges + manual refresh retained on all four screens",
  ["eventCode|event", "histCode|history", "annCode|announcements", "medCode|medalists"]
    .map((s) => s.split("|"))
    .every(([k]) =>
      has({ eventCode, histCode, annCode, medCode }[k], "void refresh()"),
    ),
);
check(
  "14.3 home keeps its Phase 31 title rows",
  has(homeScreen, 'title="Official convocation list"') &&
    has(homeScreen, 'title="Registration reference"') &&
    has(homeScreen, 'title="Account claimed"'),
);

console.log(`\n${total - failures}/${total} checks passed`);
process.exit(failures === 0 ? 0 : 1);
