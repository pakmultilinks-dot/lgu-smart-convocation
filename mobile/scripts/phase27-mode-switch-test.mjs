/**
 * Phase 27 — E3: the device role can never be switched without confirmation.
 *
 * Finding: `SettingsScreen` called `clearAppMode()` BEFORE routing to the
 * mode picker. The picker loaded the device's current mode from storage and
 * its guard (`if (current && mode !== current)`) therefore found nothing and
 * committed straight through — the 33-QA I21 Confirm/Cancel step was skipped
 * and one stray tap silently changed the device role. The bug is structural:
 * the confirmation depended on state an unrelated entry point could destroy.
 *
 * Fixes pinned here:
 *   1. `needsModeConfirmation(current, next)` — ONE shared rule, failing
 *      CLOSED: confirm unless the device is provably already on `next`.
 *   2. Settings navigates only; the stored mode stays intact until the user
 *      confirms, so Cancel genuinely preserves the mode.
 *   3. Every other entry point (launch redirect, student home, student
 *      welcome) reaches the picker without clearing anything, so none of
 *      them can bypass another.
 *   4. The one remaining `clearAppMode()` (Live Board exit) sits behind an
 *      armed confirm AND an admin PIN, and even then the picker asks again.
 *
 * Role selection is navigation, not authorization: it grants no session.
 *
 * These are SOURCE-level checks. No device/emulator is available in this
 * environment, so the tap-through itself is not physically verified here —
 * tsc + lint gate the code, and this suite gates the contract at source.
 *
 * Run from mobile/:  node scripts/phase27-mode-switch-test.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOBILE = join(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = dirname(MOBILE);

function read(rel) {
  return readFileSync(join(ROOT, rel), "utf8");
}
function has(src, needle) {
  return src.includes(needle);
}

let failures = 0;
let passed = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
  else passed += 1;
}

console.log("Phase 27 E3 - a device role change is always confirmed\n");

const appMode = read("mobile/src/store/appMode.ts");
const picker = read("mobile/app/mode-picker.tsx");
const settings = read("mobile/src/screens/SettingsScreen.tsx");
const liveboard = read("mobile/src/screens/LiveBoardScreen.tsx");
const launch = read("mobile/app/index.tsx");
const studentHome = read("mobile/app/(student)/home.tsx");
const welcome = read("mobile/app/(student)/welcome.tsx");

// ---- 1. one shared, fail-closed rule ---------------------------------------
console.log("1 - a single shared confirmation rule, failing closed");
const rule = appMode.match(/export function needsModeConfirmation[\s\S]{0,220}?\n\}/);
check("the rule is exported from the mode store", !!rule);
check("an UNKNOWN current mode requires confirmation too",
  !!rule && has(rule[0], "return current !== next;"));
check("the picker is gated by that rule, not by its own inline copy",
  has(picker, "needsModeConfirmation(current, mode)") &&
    !has(picker, "current && mode !== current"));

// ---- 2. the picker is the only writer, and it writes before it navigates --
console.log("2 - the picker commits the mode and then navigates");
const commit = picker.match(/const commit = async[\s\S]{0,320}?\n  \};/);
check("commit persists the mode", !!commit && has(commit[0], "await setAppMode(mode)"));
check("commit navigates only AFTER the write", !!commit &&
  commit[0].indexOf("await setAppMode(mode)") < commit[0].indexOf("router.replace("));
check("the picker is the only place a surface is persisted",
  (picker.match(/setAppMode\(/g) ?? []).length === 1);

// ---- 3. Confirm and Cancel are distinct ------------------------------------
console.log("3 - Confirm changes the device, Cancel changes nothing");
const bar = picker.match(/\{pending \? \([\s\S]*?\) : null\}/);
check("the pending bar renders Confirm and Cancel", !!bar &&
  has(bar[0], "Confirm mode switch") && has(bar[0], "Cancel mode switch"));
const cancel = picker.match(
  /accessibilityLabel="Cancel mode switch"[\s\S]{0,160}?onPress=\{\(\) => setPending\(null\)\}/,
);
check("Cancel only clears the pending choice — no write, no route",
  !!cancel && !has(cancel[0], "setAppMode") && !has(cancel[0], "router."));
const confirm = picker.match(
  /accessibilityLabel="Confirm mode switch"[\s\S]{0,280}?commit\(next\)/,
);
check("Confirm is the only path that commits", !!confirm);

// ---- 4. no entry point clears the mode before the picker can see it -------
console.log("4 - no entry point destroys the current mode first");
check("Settings no longer clears the mode on its way to the picker",
  !has(settings, "clearAppMode") && has(settings, 'router.replace("/mode-picker")'));
check("launch redirect routes to the picker without clearing",
  has(launch, '<Redirect href="/mode-picker"') && !has(launch, "clearAppMode"));
check("student home reaches the picker without clearing",
  has(studentHome, 'router.replace("/mode-picker")') && !has(studentHome, "clearAppMode"));
check("student welcome reaches the picker without clearing",
  has(welcome, 'router.replace("/mode-picker")') && !has(welcome, "clearAppMode"));

// ---- 5. the one remaining clear is an authenticated, confirmed exit -------
console.log("5 - the Live Board exit stays explicit, and still cannot bypass");
const finish = liveboard.match(/const finishExit = useCallback[\s\S]{0,420}?\}, \[\]\);/);
const pin = liveboard.match(/const confirmExitWithPin[\s\S]{0,1600}?\}, \[/);
check("its only clearAppMode lives in finishExit", !!finish &&
  has(finish[0], "clearAppMode()") &&
  (liveboard.match(/clearAppMode\(/g) ?? []).length === 1);
check("finishExit is reached only after the admin PIN verifies", !!pin &&
  has(pin[0], "verifyAdminPin(") && has(pin[0], "finishExit()"));
check("even that cleared state cannot pass silently — the picker asks again",
  !!rule && has(rule[0], "return current !== next;"));

// ---- 6. picking a surface is navigation, not authorization ----------------
console.log("6 - role selection grants no session");
check("the picker imports no auth or session store",
  !/from "[^"]*(auth|session)[^"]*"/.test(picker));
check("the picker never writes a scanner or student credential",
  !has(picker, "scannerAuth") && !has(picker, "studentAuth"));

console.log(`\n${passed} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
