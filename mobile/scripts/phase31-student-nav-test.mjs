// Phase 31 — student navigation shell + Home redesign (mobile source pins)
//
// Source-level checks for the ten required verifications in Part F. Like the
// other scripts in this folder these are honest source pins: they assert what
// the shipped code actually contains, not what a screenshot might suggest.
// Run: node scripts/phase31-student-nav-test.mjs
import { readFileSync } from "node:fs";
import { join } from "node:path";

const cwd = process.cwd();
const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const has = (src, needle) => src.includes(needle);
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const layout = stripComments(read("app/(student)/_layout.tsx"));
const home = stripComments(read("app/(student)/home.tsx"));
const reg = stripComments(read("app/(student)/registration.tsx"));
const more = stripComments(read("app/(student)/more.tsx"));
const ui = stripComments(read("src/ui/index.tsx"));

let passed = 0;
let failed = 0;
function check(name, ok) {
  if (ok) {
    passed += 1;
    console.log(`ok   ${name}`);
  } else {
    failed += 1;
    console.error(`FAIL ${name}`);
  }
}

// 1 — the shell exposes the intended destinations -------------------------
check(
  "1: the shell exposes the five intended destinations",
  has(layout, 'const VISIBLE_TABS = ["home", "registration", "pass", "announcements", "more"]') &&
    has(layout, 'name="home"') &&
    has(layout, 'name="registration"') &&
    has(layout, 'name="pass"') &&
    has(layout, 'name="announcements"') &&
    has(layout, 'name="more"'),
);

// 2 — active navigation and destination changes ---------------------------
check(
  "2: the tab bar marks the active destination and maps children to parents",
  has(layout, "PARENT_OF") &&
    has(layout, "accessibilityState") &&
    has(layout, "selected") &&
    has(layout, "tabUnderlineActive"),
);

// 3 — existing student routes still resolve -------------------------------
check(
  "3: hidden student routes stay registered with href null",
  has(layout, 'name="profile"') &&
    has(layout, 'name="event"') &&
    has(layout, 'name="readiness"') &&
    has(layout, "href: null") &&
    has(layout, 'name="welcome"') &&
    has(layout, 'name="index"'),
);

// 4 — no privileged staff actions in student navigation -------------------
check(
  "4: student navigation exposes no staff/volunteer destinations",
  !has(layout, '"/(volunteer)') &&
    !has(home, '"/(volunteer)') &&
    !has(more, '"/(volunteer)') &&
    !has(reg, '"/(volunteer)') &&
    !has(home, "staff") &&
    !has(more, "staff"),
);

// 5 — status / list / claim / profile stay separate concepts ---------------
check(
  "5: status, official list, claim date and profile completion are separate",
  has(home, 'title="Official convocation list"') &&
    has(home, 'title="Registration reference"') &&
    has(home, 'title="Account claimed"') &&
    has(home, "Profile: ${me.completion.done} of ${me.completion.total} complete") &&
    has(home, "Event readiness: ${summary.required_done} of ${summary.required_total} complete") &&
    has(home, "no separate last-status-check time"),
);

// 6 — event cards are authoritative and occasion-specific -----------------
check(
  "6: rehearsal and ceremony render as separate server-driven cards",
  has(home, "eventApi.fetchEvent()") &&
    has(home, 'o.key === "rehearsal"') &&
    has(home, 'o.key === "ceremony"') &&
    has(home, "<OccasionCard o={rehearsal}") &&
    has(home, "<OccasionCard o={ceremony}") &&
    has(home, "useCountdown("),
);

// 7 — missing schedules and unavailable data render honestly --------------
check(
  "7: missing schedule and unavailable data are stated, never faked",
  has(home, 'title="No schedule published"') &&
    has(home, 'title="Event schedule unavailable"') &&
    has(home, '"Event readiness unavailable"') &&
    has(home, "Not yet scheduled") &&
    has(home, '"Venue not published"'),
);

// 8 — a failed request never becomes a false approval ---------------------
check(
  "8: a failed request never renders an approval state",
  has(home, "e.status === 401") &&
    has(home, "stale: true") &&
    !has(home, "Approved") &&
    !has(home, "You are approved"),
);

// 9 — bottom navigation does not hide content -----------------------------
check(
  "9: the tab bar reserves space and the screen scrolls clear of it",
  has(layout, "insets.bottom") &&
    has(ui, "contentContainerStyle") &&
    has(ui, "automaticallyAdjustKeyboardInsets"),
);

// 10 — auth / readiness / pass / profile compatibility ---------------------
check(
  "10: auth, readiness, pass and profile flows still wire up",
  has(home, 'router.push("/(student)/pass")') &&
    has(home, 'router.push("/(student)/profile")') &&
    has(home, 'router.push("/(student)/readiness")') &&
    has(home, 'router.replace("/(student)/welcome")') &&
    has(home, "studentApi.logout(token)") &&
    has(reg, 'router.push("/(student)/profile")') &&
    has(more, '"/(student)/readiness"'),
);

console.log(`\n${passed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);