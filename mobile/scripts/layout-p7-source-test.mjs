/**
 * 33-QA release-blocker fix cycle — P7 cluster regression test.
 * Pins Issues 19–25 at source level:
 *   I19 Home "Find attendee" removed — Search tab owns attendee lookup;
 *       scanner instruction copy untouched
 *   I20 guest search placeholder reads "Name or phone" (what volunteers
 *       search by); server-side roll/host matching retained
 *   I21 mode switch confirmation — picking a DIFFERENT surface shows
 *       Confirm/Cancel first; picking the current mode stays one tap
 *   I22 duplicate guest identity rejected at intake — one live pass per
 *       host roll + no name+phone twin under another host
 *   I23 host NAME + roll everywhere a host is shown (backend JOIN →
 *       host_name → client types → guest list/pass/search UI)
 *   I24 realistic expected_attendance cap (25,000) server + client
 * Run: node scripts/layout-p7-source-test.mjs
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

console.log("33-QA P7 regression test (Issues 19-25)\n");

const modelsPy = read("app/models.py");
const routesPy = read("app/web/routes.py");
const client = read("mobile/src/api/client.ts");
const home = read("mobile/src/screens/HomeScreen.tsx");
const guests = read("mobile/src/screens/GuestsScreen.tsx");
const search = read("mobile/src/screens/SearchScreen.tsx");
const guestPass = read("mobile/src/screens/GuestPassScreen.tsx");
const admin = read("mobile/src/screens/AdminScreen.tsx");
const modePicker = read("mobile/app/mode-picker.tsx");
const volunteerLayout = read("mobile/app/(volunteer)/_layout.tsx");
const scannerResult = read("mobile/src/scanner/ScannerResult.tsx");
const guestPassHtml = read("app/web/templates/guest_pass.html");
const guestsHtml = read("app/web/templates/guests.html");

// ---- I19: Home "Find attendee" removed -------------------------------------
console.log("I19 - Home no longer duplicates attendee lookup");
check("Home has no Find attendee button", !has(home, 'label="Find attendee"'));
check("Home still routes to the scanner", has(home, 'router.push("/(volunteer)/scanner")'));
check("Search tab still exists in the volunteer shell", has(volunteerLayout, '"search"'));
check("scanner instruction copy preserved (Do not admit. Use Find attendee.)",
  has(scannerResult, "Do not admit. Use Find attendee."));

// ---- I20: guest search placeholder -----------------------------------------
console.log("I20 - guest search placeholder matches real search fields");
check("placeholder reads 'Name or phone'", has(guests, 'placeholder="Name or phone"'));
check("old roll-in-placeholder wording gone", !has(guests, 'placeholder="Name, roll no. or phone"'));
check("host roll matching retained in the filter", has(guests, "guest.host_roll_no.toLowerCase().includes(q)"));
check("host name matching added to the filter", has(guests, '(guest.host_name ?? "").toLowerCase().includes(q)'));

// ---- I21: mode switch confirmation -----------------------------------------
console.log("I21 - mode switch asks before changing the device role");
check("current mode loaded via getAppMode", has(modePicker, "getAppMode"));
check("pending state gates a cross-mode pick", has(modePicker, "const [pending, setPending]"));
// Phase 27 (E3): this used to pin the fail-open guard
// `if (current && mode !== current)`, which asked for confirmation only
// when a current mode had loaded — so an entry point that cleared the mode
// first (Settings) silently skipped the confirm step. The gate is now the
// shared, fail-closed needsModeConfirmation() rule.
check("different mode → pending instead of instant switch (fails closed)",
  has(modePicker, "needsModeConfirmation(current, mode)"));
check("same mode still switches directly", has(modePicker, "void commit(mode)"));
check("Confirm button present", has(modePicker, "Confirm mode switch"));
check("Cancel button present", has(modePicker, "Cancel mode switch"));
check("confirm copy names the target surface", has(modePicker, "Switch this device to"));
check("ui-35m mode-picker pins untouched",
  has(modePicker, "displayMedium") && !has(modePicker, '"Your selection is saved"') &&
    has(modePicker, "cfg?.event.name || eventTitle()") && has(modePicker, "cfg?.university || UNIVERSITY_NAME"));

// ---- I22: duplicate guest identity -----------------------------------------
console.log("I22 - duplicate guest identity rejected at intake");
check("host duplicate query before insert", has(modelsPy, "SELECT id FROM guests WHERE host_roll_no = ? LIMIT 1"));
check("host duplicate message", has(modelsPy, "This student already has a guest registered."));
check("name+phone twin query (spaced-format tolerant)",
  has(modelsPy, "SELECT id FROM guests WHERE name = ?") &&
    has(modelsPy, "REPLACE(phone, ' ', '') = REPLACE(?, ' ', '')"));
check("twin message", has(modelsPy, "A guest with this name and phone is already registered."));
check("route surfaces the model error as 400", has(routesPy, "return jsonify({\"ok\": False, \"error\": err}), 400"));

// ---- I23: host name + roll --------------------------------------------------
console.log("I23 - host name travels with the roll");
check("guest_by_id joins the roster name", has(modelsPy, "SELECT g.*, st.name AS host_name FROM guests g"));
check("all_guests joins the roster name", has(modelsPy, "LEFT JOIN students st ON st.roll_no = g.host_roll_no"));
check("guest pass payload carries host_name", has(routesPy, '"host_name": g.get("host_name")'));
check("search endpoint joins host_name", has(routesPy, "SELECT g.*, st.name AS host_name FROM guests g"));
check("client Guest type carries host_name", has(client, "host_name?: string | null"));
check("guest list row shows name + roll", has(guests, "Host{\" \"}") && has(guests, "guest.host_name"));
// QA fix cycle 3 (Issue 2): the duplicate host sentence in the header
// subtitle is gone — the host lives once, in the stacked passMeta rows.
check("guest pass header no longer repeats the host sentence",
  !has(guestPass, "`Guest of ${hostDisplay}`"));
check("guest pass meta rows are stacked sans (Host/ID/Phone/Valid) (QA fix cycle 3)",
  has(guestPass, "passMetaText") &&
    has(guestPass, "{`Host: ${pass.host_name}`}") &&
    has(guestPass, "{`ID: ${pass.host_roll_no}`}") &&
    has(guestPass, "maskPhone(pass.phone)"));
check("search result row uses host name", has(search, "hit.host_name"));
check("web guest pass shows host name", has(guestPassHtml, "guest.host_name"));
check("web guest list shows host name", has(guestsHtml, "g.host_name"));

// ---- I24: realistic attendance cap -----------------------------------------
console.log("I24 - expected_attendance capped at 25,000");
check("server bound is 25_000", has(routesPy, "expected > 25_000"));
check("server error states 25000", has(routesPy, "expected_attendance must be between 0 and 25000."));
check("old million attendance bound gone",
  !has(routesPy, "expected > 1_000_000") && !has(routesPy, "between 0 and 1000000"));
check("client validation bound 25000", has(admin, "attendance > 25000"));
check("client error message 25,000", has(admin, "between 0 and 25,000."));
check("client hint 25,000", has(admin, 'hint="Enter a number up to 25,000"'));
check("old million copy gone from Admin", !has(admin, "1,000,000"));

console.log(`\nlayout-p7-source-test: ${passed} passed, ${failures} failed`);
process.exit(failures > 0 ? 1 : 0);