/**
 * Phase 35H — static source test for the targeted UI/UX corrections.
 * Pins the mandated behaviors at source level: foundations (muted token,
 * 13px helper tier), kit changes (crest exits, local clock, field labels),
 * and each corrected screen. Run: node scripts/ui-35h-source-test.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOBILE = join(dirname(fileURLToPath(import.meta.url)), "..");

function read(rel) {
  return readFileSync(join(MOBILE, rel), "utf8");
}
function has(src, needle) {
  return src.includes(needle);
}

let failures = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
}

console.log("Phase 35H UI/UX correction source test\n");

// ---- foundations -----------------------------------------------------------
console.log("Foundations (theme)");
const colors = read("src/theme/colors.ts");
check("muted token darkened to #5C5642", has(colors, 'muted: "#5C5642"'));
const typography = read("src/theme/typography.ts");
check("13px helper tier exists in the scale", has(typography, "helper: 13"));
check("text.helper preset exists", has(typography, "helper: {"));

// ---- design-system kit -----------------------------------------------------
console.log("Design-system kit (ui/index.tsx)");
const kit = read("src/ui/index.tsx");
check("crest hold delay is configurable", has(kit, "crestHoldMs = 3000"));
check("crest uses delayLongPress={crestHoldMs}", has(kit, "delayLongPress={crestHoldMs}"));
check(
  "crest a11y advertises tap-or-hold exit",
  has(kit, 'accessibilityLabel="Tap or hold to exit the live dashboard"'),
);
check("formatLocalClock exists", has(kit, "export function formatLocalClock"));
check(
  "all clock formatters render 12h",
  has(kit, 'toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })') &&
    has(kit, "export function formatServerClock"),
);
check(
  "formatLocalClock delegates to formatServerClock",
  has(kit, "return formatServerClock(ts)"),
);
check("field labels use the 13px sans style", has(kit, "fieldLabel: {") && has(kit, "fontSize: 13"));
check(
  "MetricBlock caption uses text.helper",
  has(kit, "[text.helper, dark && styles.textMutedOnDark, styles.metricCaption]"),
);

// ---- Home ------------------------------------------------------------------
console.log("Home screen");
const home = read("src/screens/HomeScreen.tsx");
check(
  // 35M R2 (item 1) replaced the old inline mode suffix: the hero label
  // shows the gate name only; Entry/Exit moved to the SegmentedControl
  // BELOW the label (pinned in full by ui-35m check 1).
  "assigned gate shows gate + Change; mode via toggle below (35M R2 item 1)",
  has(home, "heroGate") && has(home, ">Change</Text>") &&
    has(home, "SegmentedControl") &&
    !has(home, '{scanMode === "exit" ? "Exit" : "Entry"}'),
);
check("sentence-case 'Inside now' (cycle 4 rename)", has(home, "Inside now"));
check("no ALL-CAPS 'STUDENTS INSIDE'", !has(home, "STUDENTS INSIDE"));
check("old choose-gate button removed", !has(home, "chooseButton") && !has(home, '"Choose gate"'));

// ---- Broadcast -------------------------------------------------------------
console.log("Broadcast screen");
const broadcast = read("src/screens/BroadcastScreen.tsx");
check("history uses formatLocalClock", has(broadcast, "formatLocalClock(entry.sent_at)"));
check("no formatServerClock remains", !has(broadcast, "formatServerClock"));
check("sheet title names the real log action (35J P0)", has(broadcast, "Save announcement to all students?"));
check(
  "Send disabled while the message is empty",
  has(broadcast, "disabled={message.trim().length === 0}"),
);
check("operational helper copy kept", has(broadcast, "Gate, time, action"));

// ---- Live dashboard --------------------------------------------------------
console.log("Live dashboard");
const liveboard = read("src/screens/LiveBoardScreen.tsx");
check("header crest arms the exit on tap + hold", has(liveboard, "onCrestLongPress={armExit}"));
check("crest hold shortened to ~2s", has(liveboard, "crestHoldMs={2000}"));
// 33-QA (I13) supersedes the board-wide tap: the wrapping Pressable
// nested inside the crest's Pressable (web <button> errors) and armed
// the exit on any stray tap. Exit is now explicit — crest tap/hold or
// the footer Exit control — and the confirmation renders as an overlay.
check(
  "explicit exit: footer control + always-visible confirm overlay (33-QA I13)",
  has(liveboard, 'accessibilityLabel="Exit live dashboard"') &&
    has(liveboard, "styles.exitOverlay") &&
    !has(liveboard, 'accessibilityLabel="Live dashboard — tap to show exit options"'),
);
check(
  "crest exit wired through the kit (single a11y source)",
  has(liveboard, "onCrestLongPress={armExit}") && has(liveboard, "crestHoldMs={2000}"),
);
check("exit confirm copy unchanged", has(liveboard, "Leave the display?"));
check("double-tap guard removed", !has(liveboard, "handleCrestPress"));

// ---- Volunteer shell -------------------------------------------------------
console.log("Volunteer shell");
const layout = read("app/(volunteer)/_layout.tsx");
check("PARENT_OF map present", has(layout, "const PARENT_OF: Record<string, string> = {"));
check("focus derives from PARENT_OF", has(layout, "PARENT_OF[currentName] ?? currentName"));
check("indexOf route removed", !has(layout, "state.routes.indexOf(route)"));

// ---- Search ----------------------------------------------------------------
console.log("Search screen");
const search = read("src/screens/SearchScreen.tsx");
check("plain Search Field — no duplicate label (35J T)", !has(search, 'label="Search"') && has(search, "autoFocus"));
check("gate-operations eyebrow removed", !has(search, 'eyebrow="Gate operations"'));
check("search action button removed", !has(search, "searchButton"));

// ---- Scanner ---------------------------------------------------------------
console.log("Scanner screen");
const scanner = read("src/screens/ScannerScreen.tsx");
check("permission auto-requested on open", has(scanner, "requestedPermissionRef"));
check("header title is Scanner (no duplicate eyebrow)", has(scanner, '<AppHeader title="Scanner"') && !has(scanner, 'eyebrow="Scanner"'));
check("misleading EmptyState icon removed", !has(scanner, "EmptyState"));
check("denied state uses plain text + one action", has(scanner, "permissionTitle") && has(scanner, 'label="Grant camera permission"'));

// ---- Scanner sheet ---------------------------------------------------------
console.log("Scanner sheet");
const sheet = read("src/scanner/ScannerSheet.tsx");
check("gate tiles use short labels", has(sheet, "gate.label.replace(/ Gate$/, \"\")"));
check("selected tile shows a check icon", has(sheet, 'name="checkmark"'));
check("two-column chip grid", has(sheet, 'flexBasis: "48%"'));
check("Done disabled until a gate is chosen", has(sheet, "disabled={gateId === null}"));

// ---- Admin gate + lockout --------------------------------------------------
console.log("Admin gate + lockout");
const gate = read("src/components/AdminGate.tsx");
check("numeric PIN keyboard", has(gate, 'keyboardType="numeric"'));
check("lockout countdown copy", has(gate, "Too many attempts. Try again in "));
check("Unlock disabled while locked", has(gate, "disabled={locked}"));
check("wrong-PIN failures registered", has(gate, "registerFailure"));
check("success resets the counters", has(gate, "resetOnSuccess"));
const lockout = read("src/store/adminLockout.ts");
check("lockout helper pinned to 3 attempts / 30s", has(lockout, "MAX_ATTEMPTS = 3") && has(lockout, "LOCKOUT_MS = 30000"));

// ---- Admin screen ----------------------------------------------------------
console.log("Admin screen");
const admin = read("src/screens/AdminScreen.tsx");
check("structured date/time editors", has(admin, "formatFullLabel") && has(admin, "calendarGrid"));
check("Year field removed", !has(admin, 'label="Year"'));
check("year derived from the chosen date", has(admin, "convocation_year: String(parts.y)"));
// 33-QA (I24) supersedes the old 1,000,000 hint — the realistic cap is
// 25,000 (server-enforced); the plain-language shape of the hint is kept.
check("attendance hint is plain language", has(admin, 'hint="Enter a number up to 25,000"'));
check("Save disabled until dirty", has(admin, "disabled={!settingsDirty || savingSettings}"));
check("queue row is a non-pressable status", has(admin, '"All synced"') && !has(admin, "QUEUED"));

// ---- Guests ----------------------------------------------------------------
console.log("Guests screen");
const guests = read("src/screens/GuestsScreen.tsx");
check("guest eyebrow removed", !has(guests, 'eyebrow="Guests"'));
check("masked phone helper", has(guests, "maskPhone"));
check(
  "Used pill is neutral (nodata)",
  has(guests, 'guest.used\n                                ? "nodata"') ||
    (/guest\.used\s*\n?\s*\? "nodata"/.test(guests) && has(guests, '"nodata"')),
);
check(
  "Revoked pass takes pill precedence (duplicate) over Used/Ready",
  has(guests, 'guest.status === "revoked"') && has(guests, '"duplicate"') && has(guests, '"Revoked"'),
);
check(
  "Used shows entered time + gate (35I: date-aware usedStamp)",
  has(guests, "usedStamp(guest.used_at)") && has(guests, "used_gate"),
);
check("client search + filter + clear", has(guests, "Clear filters") && has(guests, "SegmentedControl"));
check("empty-filtered state copy", has(guests, "No guests match"));

// ---- Settings --------------------------------------------------------------
console.log("Settings screen");
const settings = read("src/screens/SettingsScreen.tsx");
check(
  "eyebrow removed (35I U.2: title names the screen)",
  !has(settings, "eyebrow={eventTitle()}") && !has(settings, "eventTitle"),
);
check(
  "Save name disabled unless changed (35I U.1)",
  has(settings, "disabled={!nameDirty}"),
);
check("helper rows are 13px sans", !has(settings, "fontSize: 11"));

// ---- backend + client ------------------------------------------------------
console.log("Backend + client");
const models = read("../app/models.py");
check("all_guests returns used_at + used_gate", has(models, "used_at") && has(models, "used_gate"));
check("latest guest scan via MAX(id)", has(models, "MAX(id) AS mid"));
const client = read("src/api/client.ts");
check("Guest type carries used_at / used_gate", has(client, "used_at?: string | null") && has(client, "used_gate?: string | null"));

// ---- splash ----------------------------------------------------------------
console.log("Splash asset config");
const appjson = read("app.json");
check("splash resizeMode contain", has(appjson, '"resizeMode": "contain"'));
check("splash backgroundColor paper", has(appjson, '"backgroundColor": "#F6F1E4"'));

console.log(`\nDone: ${failures} failure(s).`);
process.exit(failures > 0 ? 1 : 0);
