// Phase 10 (convocation readiness centre + personalized reminders) —
// source checks on the student app.
//
// Mandate verified here, at the source level:
//  - The readiness screen renders server-computed data only; it never keeps
//    an editable local copy of registration status, event dates or support
//    status (no local mutation of those facts).
//  - Freshness is the SHARED useFreshServerData rule (focus/resume/manual/
//    ≤30s cadence) — no bespoke setInterval, no extra timers, no duplicate
//    polling on the readiness screen.
//  - Completion reflects backend state, not a screen being opened (the
//    screen has no "mark complete by visiting" logic).
//  - Only informational reminders expose a dismiss control; required
//    reminders (registration issue / staff awaiting info) are not
//    dismissible in the UI.
//  - Home exposes the readiness entry point without replacing any existing
//    action.
//
// This suite ADDS coverage on top of the existing layout/ui/scanner suites —
// nothing here weakens them.

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
if (!cwd.endsWith("mobile")) cwd = root;

const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const has = (src, needle) => src.includes(needle);
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const screen = read("app/(student)/readiness.tsx");
const api = read("src/api/readinessApi.ts");
const home = read("app/(student)/home.tsx");
const more = read("app/(student)/more.tsx");
const layout = read("app/(student)/_layout.tsx");
const sScreen = stripComments(screen);
const sApi = stripComments(api);
const sHome = stripComments(home);
const sMore = stripComments(more);

let passed = 0;
let failed = 0;

function check(name, ok) {
  if (ok) {
    passed += 1;
    console.log(`ok  ${name}`);
  } else {
    failed += 1;
    console.error(`FAIL ${name}`);
  }
}

console.log("\nPhase 10 — readiness centre (source checks)");

// --- the screen is registered via the file-based (student) stack ---------
check(
  "1: readiness screen lives at app/(student)/readiness.tsx",
  existsSync(join(cwd, "app", "(student)", "readiness.tsx")),
);
check(
  // Phase 31 Part A contract change (documented, not weakened): the
  // (student) shell is no longer a headerless Stack — it is the mandated
  // five-destination Tabs shell. The readiness route stays registered
  // (hidden, href: null) and headerless, so the original intent — routes
  // auto-registered under a headerless shell — still holds.
  "2: the (student) shell is the headerless five-destination Tabs shell",
  has(stripComments(layout), "<Tabs") &&
    has(
      stripComments(layout),
      'const VISIBLE_TABS = ["home", "registration", "pass", "announcements", "more"]',
    ) &&
    has(stripComments(layout), 'name="readiness"') &&
    has(stripComments(layout), 'name="readiness" options={{ title: "Readiness", href: null, headerShown: false }}'),
);

// --- data is server-computed, never edited locally ------------------------
check(
  "3: the screen fetches from the typed readiness client",
  has(sScreen, "readinessApi.get(token)"),
);
check(
  "4: the client targets the authenticated /api/student/readiness endpoint",
  has(sApi, '"/api/student/readiness"'),
);
check(
  "5: readiness rides the shared Bearer auth (no cookies/CSRF surface)",
  has(sApi, "Bearer ${token}") && has(sApi, "Authorization"),
);
check(
  "6: the screen holds NO editable copies of registration/event/support facts",
  !has(sScreen, "useState<readinessApi.ChecklistItem") &&
    !has(sScreen, "setStatus") &&
    !has(sScreen, "setRegistration") &&
    !has(sScreen, "setEvent"),
);
check(
  "7: the client never mutates registration/event/support state — only reminders",
  !has(sApi, "/api/student/support") &&
    !has(sApi, "/api/student/event") &&
    has(sApi, '`${BASE}/reminders`'),
);

// --- freshness: the shared rule, no bespoke timers ------------------------
check(
  "8: readiness uses the shared useFreshServerData hook",
  has(sScreen, "useFreshServerData(() => load(true))"),
);
check(
  "9: the readiness screen adds NO independent timer or polling",
  !has(sScreen, "setInterval") &&
    !has(sScreen, "setTimeout") &&
    !has(sScreen, "addEventListener(\"change\""),
);
check(
  "10: it imports the hook from the single shared module",
  has(sScreen, 'from "../../src/hooks/useFreshServerData"'),
);

// --- completion reflects backend state, not a screen open -----------------
check(
  "11: rendering the screen issues no 'mark complete' write",
  !has(sScreen, "markComplete") &&
    !has(sScreen, "acknowledge(") &&
    !has(sScreen, "onPress={() => setDone"),
);
check(
  "12: done/attention status comes straight from the server item.status",
  has(sScreen, "item.status") && has(sScreen, "STATUS_PILL[item.status]"),
);

// --- reminders: only informational ones are dismissible in the UI ---------
check(
  "13: the dismiss control is gated on the server's dismissible flag",
  has(sScreen, "r.dismissible") && has(sScreen, 'act(r.key, "dismiss")'),
);
check(
  "14: read + dismiss both round-trip through the server",
  has(sScreen, 'act(r.key, "read")') &&
    has(sApi, 'action: "read" | "dismiss"'),
);
check(
  // Phase 18: was `} catch {` — a bare catch that swallowed the failure, so
  // the list looked untouched with no explanation. The failure is now
  // reported and the list stays usable (server state re-read on success).
  "15: a failed reminder mark never blocks the list (reported, retried)",
  has(sScreen, "const act = async") && has(sScreen, "setActError(") &&
    !/catch\s*\{\s*\}/.test(sScreen),
);

// --- helpful states -------------------------------------------------------
check(
  "16: loading, error and stale-data states are all present",
  has(sScreen, "LoadingState") &&
    has(sScreen, "ErrorState") &&
    has(sScreen, "stale"),
);
check(
  "17: a network failure is never rendered as 'no registration'",
  has(sScreen, "never rendered as \"you have no registration\"") ||
    has(sScreen, "stale: true"),
);
check(
  "18: an empty reminder list shows a friendly empty state",
  has(sScreen, "EmptyState") && has(sScreen, "No reminders"),
);
check(
  "19: a 401 clears back to the welcome screen",
  has(sScreen, "e.status === 401") && has(sScreen, 'router.replace("/(student)/welcome")'),
);

// --- confirmed vs provisional is preserved end-to-end ---------------------
check(
  "20: confirmed vs provisional is decided server-side (client carries no date)",
  !has(sApi, "confirmed_date") && !has(sApi, "expected_date"),
);

// --- home integration (added, not replaced) -------------------------------
check(
  "21: home links the readiness screen",
  has(sHome, 'router.push("/(student)/readiness")'),
);
check(
  // Phase 31 Part B: Home keeps profile/event/announcements/support as its own
  // actions; the medalist board moved to the More tab (secondary destination),
  // so it is pinned on more.tsx instead of home.tsx.
  "22: home keeps its actions; medalist lives on the More tab",
  has(sHome, 'router.push("/(student)/profile")') &&
    has(sHome, 'router.push("/(student)/event")') &&
    has(sHome, 'router.push("/(student)/announcements")') &&
    has(sHome, 'router.push("/(student)/support")') &&
    has(sMore, '"/(student)/medalists"'),
);
check(
  "23: home still keeps its own shared freshness rule",
  has(sHome, "useFreshServerData(() => load(true))"),
);

// --- no push/email claims -------------------------------------------------
check(
  "24: the readiness flow claims no external notification delivery",
  !has(sScreen, "sendPush") && !has(sScreen, "Notifications.schedule") &&
    !has(sApi, "mailto") && !has(sScreen, "email"),
);

// --- Phase 18: a failed dismissal is never silent -------------------------
// act() previously swallowed the whole mark-read call in a bare catch, so a
// dropped connection looked identical to a success. These pin the failure
// path end to end: error captured, error rendered, controls locked while the
// request is in flight, and the in-flight flag always released.
check(
  "25: act() keeps an explicit error state instead of a bare catch",
  has(sScreen, "const [actError, setActError] = useState<string | null>(null)") &&
    !/catch\s*\{\s*\}/.test(sScreen) &&
    has(sScreen, "setActError("),
);
check(
  "26: a failed reminder dismissal is rendered to the student",
  has(sScreen, "actError ?") &&
    /<Text[^>]*style=\{\[?styles\.actError\]?\}[^>]*>\{\s*actError\s*\}<\/Text>/.test(
      sScreen,
    ),
);
check(
  "27: the reminder controls lock while the request is in flight",
  has(sScreen, "loading={acting === r.key}") &&
    has(sScreen, "disabled={acting !== null}") &&
    has(sScreen, "if (acting) return;"),
);
check(
  "28: the in-flight flag is always released, so the screen never wedges",
  /finally\s*\{\s*setActing\(null\)/.test(sScreen),
);
check(
  "29: a failed dismissal keeps the previously loaded server state",
  has(sScreen, "setActError(null)") && has(sScreen, "await load(true)"),
);

console.log(`\nDone: ${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
