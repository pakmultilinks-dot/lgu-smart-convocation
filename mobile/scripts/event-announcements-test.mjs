// Phase 7 — convocation event + smart announcements: mobile wiring +
// cross-layer contract pins (source-level, no server needed).
//
// Proves:
//   R  The event + announcements routes exist, are wired into the student
//      root stack and reachable from home (both buttons).
//   A  eventApi hits exactly the Flask student routes (/api/student/event,
//      /api/student/announcements) via the shared authenticated request().
//   S  Both screens render loading / empty / server-error states and an
//      in-app Refresh, never claim push notifications, and refetch through
//      the ONE shared Phase 8 freshness hook (focus + resume + manual +
//      controlled ≤30s foreground cadence — no uncontrolled polling).
//   D  Expected vs confirmed dates stay explicitly distinct: an expected
//      date is always labelled provisional and a missing confirmed date
//      reads "Not officially confirmed yet" (never presented as confirmed).
//   T  Dashboard keeps the 15 KPI tiles (11 base + 4 Phase 7 event tiles).
//
//   node scripts/event-announcements-test.mjs
//
// Exit code 0 = every check passed.

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
if (!cwd.endsWith("mobile")) cwd = root;
const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const readRepo = (rel) => readFileSync(join(cwd, "..", rel), "utf8");
const has = (src, needle) => src.includes(needle);
// Doc comments NAME forbidden APIs ("no push") — checks run on stripped code.
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
const annScreen = read("app/(student)/announcements.tsx");
const homeScreen = read("app/(student)/home.tsx");
const eventApi = read("src/api/eventApi.ts");
const eventCode = stripComments(eventScreen);
const annCode = stripComments(annScreen);
const apiCode = stripComments(eventApi);
const hookCode = stripComments(read("src/hooks/useFreshServerData.ts"));

// R — routes + navigation -----------------------------------------------
check(
  "R1: event + announcements screens exist",
  existsSync(join(cwd, "app/(student)/event.tsx")) &&
    existsSync(join(cwd, "app/(student)/announcements.tsx")),
);
check(
  // Phase 31 Part B: Home's entry points are now the "Event details" and
  // "Updates" rows (the medalist board moved to the More tab, so it is pinned
  // there instead of being ordered against Home).
  "R2: home offers both entry points; medalist lives on More",
  has(homeScreen, 'title="Event details"') &&
    has(homeScreen, 'title="Updates"') &&
    has(read("app/(student)/more.tsx"), '"/(student)/medalists"'),
);
check(
  "R3: home pushes the announcements route",
  has(homeScreen, 'router.push("/(student)/announcements")'),
);

// A — API contract mirrors the Flask student routes ----------------------
check(
  "A1: eventApi calls /api/student/event",
  has(eventApi, "/api/student/event"),
);
check(
  "A2: eventApi calls /api/student/announcements",
  has(eventApi, "/api/student/announcements"),
);
check(
  "A3: fetches go through the shared authenticated request()",
  has(eventApi, 'from "./client"') && has(eventApi, "request<"),
);

// S — loading / empty / error / refresh states, no push claims -----------
for (const [name, code] of [
  ["event", eventCode],
  ["announcements", annCode],
]) {
  check(`${name} screen renders a loading state`, has(code, "<LoadingState"));
  check(`${name} screen renders an empty state`, has(code, "<EmptyState"));
  check(`${name} screen renders a server-error state`, has(code, "<ErrorState"));
  check(
    `${name} screen offers an in-app Refresh action`,
    has(code, 'actionLabel="Refresh"') && has(code, 'icon="refresh"'),
  );
  check(
    `${name} screen claims no push notifications`,
    !has(code.toLowerCase(), "notification") &&
      !has(code.toLowerCase(), "pushnotification"),
  );
}
// Phase 8 freshness contract (replaces the old "no polling" pin, which
// encoded a static screen): both screens now refetch through the ONE
// shared controlled hook — focus, resume-from-background, manual refresh
// and a ≤30s foreground cadence — with no uncontrolled polling left in
// the screens themselves and no new transport (no WebSocket/push).
check(
  "event screen refreshes through the shared freshness hook",
  has(eventCode, "useFreshServerData") && has(eventCode, "load(true)"),
);
check(
  "announcements screen refreshes through the shared freshness hook",
  has(annCode, "useFreshServerData") && has(annCode, "load(true)"),
);
check(
  "no uncontrolled polling remains in the screens (the hook owns timing)",
  !has(eventCode, "setInterval") && !has(annCode, "setInterval"),
);
check(
  "hook fetches on focus + resume (AppState) and stops when hidden",
  has(hookCode, "useFocusEffect") &&
    has(hookCode, 'AppState.addEventListener("change"') &&
    has(hookCode, "stopPolling"),
);
check(
  "hook cadence is controlled and ≤30s, cleared on blur/background",
  has(hookCode, "STUDENT_REFRESH_MS = 20000") &&
    has(hookCode, "clearInterval") &&
    !has(hookCode, "WebSocket"),
);

// D — expected never presented as confirmed ------------------------------
check(
  "D1: an expected date is explicitly labelled provisional",
  has(eventCode, "(provisional)"),
);
check(
  "D2: a missing confirmed date reads as not officially confirmed",
  has(eventCode, "Not officially confirmed yet"),
);
check(
  "D3: confirmed date is rendered from its own field only",
  has(eventCode, "event.confirmed_date"),
);

// T — dashboard tile preservation ----------------------------------------
const dashboardTpl = readRepo("app/web/templates/exam_dashboard.html");
check(
  "T1: dashboard keeps the 24 KPI tiles (22 + 2 Phase 29 occasion tiles)",
  (dashboardTpl.match(/kpi-tile/g) || []).length === 24,
  (dashboardTpl.match(/kpi-tile/g) || []).length,
);

console.log("");
console.log(`${total} checks, ${failures} failures`);
process.exit(failures === 0 ? 0 : 1);
