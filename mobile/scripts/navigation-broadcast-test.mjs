#!/usr/bin/env node
/**
 * Phase 35G — navigation, broadcast safety and admin access source test.
 *
 * Static source-string assertions over the mobile + backend tree. Mirrors
 * the scanner-logic-test check() pattern: no network, no bundler; every
 * assertion pins a mandated string, prop or structural invariant so a
 * regression fails loudly before the visual pass.
 *
 *   node scripts/navigation-broadcast-test.mjs
 *
 * Exit code 0 means every assertion passed.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOBILE = dirname(dirname(fileURLToPath(import.meta.url)));
const ROOT = dirname(MOBILE);

let failures = 0;

function pass(name) {
  console.log(`  PASS  ${name}`);
}
function fail(name, detail) {
  failures += 1;
  console.log(`  FAIL  ${name}${detail ? " - " + detail : ""}`);
}
function check(name, condition, detail) {
  if (condition) pass(name);
  else fail(name, detail);
}

function read(rel) {
  return readFileSync(join(ROOT, rel), "utf8");
}

function has(src, needle) {
  return src.includes(needle);
}

console.log("Phase 35G navigation / broadcast / admin source test\n");

// ---- volunteer shell: five-tab allow-list ----
console.log("Volunteer tab bar");
const layout = read("mobile/app/(volunteer)/_layout.tsx");
check("VISIBLE_TABS allow-list is exactly the five destinations",
  has(layout, 'const VISIBLE_TABS = ["home", "scanner", "search", "guests", "more"];'));
check("tab bar filters state.routes by VISIBLE_TABS",
  has(layout, ".filter((route) => (VISIBLE_TABS as readonly string[]).includes(route.name))"));
check("tab bar maps hidden tabs to their parent via PARENT_OF (35H)",
  has(layout, "const PARENT_OF: Record<string, string> = {") &&
  has(layout, 'settings: "more"') &&
  has(layout, "const activeName = PARENT_OF[currentName] ?? currentName;") &&
  !has(layout, "const index = state.routes.indexOf(route);"));
check("Scanner tab is labelled Scan",
  has(layout, 'name="scanner"') && has(layout, 'tabBarLabel: "Scan"'));
check("More tab exists with ellipsis icon",
  has(layout, 'name="more"') && has(layout, 'tabBarIcon: tabIcon("ellipsis-horizontal")'));
check("settings/admin/broadcast are hidden (href null, headerShown false)",
  (layout.match(/options=\{\{ title: "(?:Settings|Admin|Announcement)", href: null, headerShown: false \}\}/g) || []).length === 3);
check("no dark navigator headers remain",
  !has(layout, "headerShown: true") && !has(layout, "headerStyle: { backgroundColor: colors.ink }"));
check("BackHeaderButton removed with its router import",
  !has(layout, "BackHeaderButton") && !has(layout, 'import { router } from "expo-router"'));
check("back styles removed from the stylesheet",
  !has(layout, "backPressed") && !has(layout, "backText"));

// ---- More destination ----
console.log("More destination");
const moreRoute = read("mobile/app/(volunteer)/more.tsx");
const moreScreen = read("mobile/src/screens/MoreScreen.tsx");
check("more route file exists and renders MoreScreen",
  has(moreRoute, "MoreScreen"));
check("More header copy is exact",
  has(moreScreen, 'title="More"') && has(moreScreen, 'subtitle="Settings and administrator tools"'));
check("More pushes Settings for everyone",
  has(moreScreen, 'router.push("/(volunteer)/settings")'));
check("unlocked More exposes Broadcast and Admin",
  has(moreScreen, 'router.push("/(volunteer)/broadcast")') && has(moreScreen, 'router.push("/(volunteer)/admin")'));
check("locked More shows Administrator access row with lock",
  has(moreScreen, "Administrator access") && has(moreScreen, "lock-closed-outline"));
check("More re-reads the PIN on focus",
  has(moreScreen, "getAdminPin") && has(moreScreen, "useFocusEffect"));

// ---- admin gate wiring ----
console.log("Admin gate");
const gate = read("mobile/src/components/AdminGate.tsx");
const broadcastRoute = read("mobile/app/(volunteer)/broadcast.tsx");
const adminRoute = read("mobile/app/(volunteer)/admin.tsx");
check("AdminGate verifies the PIN against the backend",
  has(gate, "verifyAdminPin") && has(gate, "getAdminPin") && has(gate, "setAdminPin"));
check("AdminGate keeps tools locked until access is granted",
  has(gate, "Administrator tools stay locked on this device until access is granted."));
check("broadcast route is wrapped in AdminGate",
  has(broadcastRoute, "<AdminGate>") && has(broadcastRoute, "<BroadcastScreen />"));
check("admin route is wrapped in AdminGate",
  has(adminRoute, "<AdminGate>") && has(adminRoute, "<AdminScreen />"));

// ---- broadcast screen copy and safety ----
console.log("Broadcast screen");
const broadcast = read("mobile/src/screens/BroadcastScreen.tsx");
check("header title is Announcements",
  has(broadcast, 'title="Announcements"'));
check("subtitle is exact (35M R2 item 10 mandate)",
  has(broadcast, 'subtitle="Log a message for students and volunteers"'));
check("stale copy is gone (old subtitle + pre-35G labels)",
  !has(broadcast, 'subtitle="Send a message to students and volunteers"') && !has(broadcast, "Send broadcast"));
check("light header with back action to More",
  has(broadcast, "onBack") && has(broadcast, 'router.replace("/(volunteer)/more")'));
check("server message limit (35K K) is enforced on the Field",
  has(broadcast, "const MESSAGE_LIMIT_FALLBACK = 160;") &&
  has(broadcast, "maxLength={messageLimit}"));
check("live character counter renders against server limit",
  has(broadcast, "{message.length} / {messageLimit}"));
check("body-font operational helper, not the Field hint prop",
  has(broadcast, "Gate, time, action") && !has(broadcast, "hint="));
check("By-gate selector loads the real gate list",
  has(broadcast, "fetchGates") && has(broadcast, "fetchAppConfig"));
check("confirmation sheet names the real log action (35J P0)",
  has(broadcast, "Save announcement to all students?") &&
  has(broadcast, "Send announcement to all students?") && has(broadcast, "Go back"));
check("confirm action carries the real audience count (35J P0 / 35K I)",
  has(broadcast, "Save for ") && has(broadcast, "actionCount.toLocaleString()"));
check("demo-mode honesty preserved (35J P0)",
  has(broadcast, "Demo mode: recorded in the broadcast log only") &&
  has(broadcast, "Demo mode — announcements are saved only"));
check("primary action is mode-aware (35K G), never claims delivery",
  has(broadcast, "const primaryLabel = isDemo ? \"Save announcement\" : \"Send announcement\";") &&
  has(broadcast, "label={primaryLabel}") &&
  !has(broadcast, "Message sent") && !has(broadcast, "Delivered"));
check("success note is the SERVER's note, not a client invention (35K G)",
  has(broadcast, "result.note ?? \"Announcement recorded.\""));
check("by-gate multi-select with explicit count (35J M)",
  has(broadcast, "selectedGateIds") && has(broadcast, "gateCountText") &&
  has(broadcast, 'flexBasis: "48%"'));
check("history rows are separated, readable, locally clocked (35H)",
  has(broadcast, "formatLocalClock(entry.sent_at)") &&
  !has(broadcast, "formatServerClock(entry.sent_at)") &&
  !has(broadcast, "numberOfLines={3}"));
check("send attaches the device PIN via sendBroadcast header",
  has(broadcast, "X-Admin-Pin"));

// ---- client + store ----
console.log("Client and store");
const client = read("mobile/src/api/client.ts");
const adminAccess = read("mobile/src/store/adminAccess.ts");
check("sendBroadcast attaches X-Admin-Pin when a PIN is stored",
  has(client, '"X-Admin-Pin": adminPin'));
check("verifyAdminPin posts to /api/admin/verify",
  has(client, "/api/admin/verify") && has(client, "verifyAdminPin"));
check("PIN persists under lgu.admin_pin",
  has(adminAccess, '"lgu.admin_pin"'));

// ---- backend ----
console.log("Backend");
const config = read("app/config.py");
const routes = read("app/web/routes.py");
const cleanup = read("app/scripts/cleanup_test_fixtures.py");
check("config.py defines ADMIN_PIN",
  has(config, "ADMIN_PIN"));
check("POST /api/broadcasts requires X-Admin-Pin",
  has(routes, "X-Admin-Pin") && has(routes, "Administrator access required to send announcements."));
check("POST /api/admin/verify exists with exact 401 copy",
  has(routes, "/api/admin/verify") && has(routes, "Incorrect PIN. Try again."));
check("GET /api/broadcasts stays open (read-only, no PIN on GET)",
  has(routes, '@bp.route("/api/broadcasts")') && !/@bp\.route\("\/api\/broadcasts", methods=\["GET"\]\)/.test(routes));
check("cleanup script targets only known test fixtures",
  has(cleanup, '"ApiTest"') && has(cleanup, '"PhaseTest"') && has(cleanup, "API test %%") && has(cleanup, "Phase34B smoke"));

// ---- direct-entry removal ----
console.log("Direct-entry removal");
const home = read("mobile/src/screens/HomeScreen.tsx");
const settings = read("mobile/src/screens/SettingsScreen.tsx");
check("Home no longer pushes admin/broadcast directly",
  !has(home, "(volunteer)/admin") && !has(home, "(volunteer)/broadcast") && !has(home, "shortcutRow"));
check("Settings no longer contains a broadcast section",
  !has(settings, "(volunteer)/broadcast") && !has(settings, "Broadcast message"));
check("Settings header gained a back action",
  has(settings, "onBack"));

// ---- kit + typography ----
console.log("Kit and typography");
const kit = read("mobile/src/ui/index.tsx");
const typography = read("mobile/src/theme/typography.ts");
check("AppHeader accepts onBack",
  has(kit, "onBack?: () => void"));
check("label/labelMedium letterSpacing is 0.2",
  /labelMedium:\s*\{[^}]*letterSpacing:\s*0\.2/.test(typography));

// ---- test harness self-consistency ----
console.log("Harness");
const apiTest = read("mobile/scripts/api-test.mjs");
check("api-test.mjs sends X-Admin-Pin and checks the verify endpoint",
  has(apiTest, "X-Admin-Pin") && has(apiTest, "/api/admin/verify") && has(apiTest, "ADMIN_PIN"));

console.log(`\nDone: ${failures} failure(s).`);
process.exit(failures > 0 ? 1 : 0);
