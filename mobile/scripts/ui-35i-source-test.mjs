/**
 * Phase 35I — static source test for database isolation + the critical
 * operational UX corrections (PART AE). Pins the mandated behaviors at
 * source level. Run: node scripts/ui-35i-source-test.mjs
 * Database isolation itself is proven end-to-end by
 * scripts/db-isolation-test.mjs — the pins here are a fast regression net.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOBILE = join(dirname(fileURLToPath(import.meta.url)), "..");
const APP = join(MOBILE, "..", "app");

function read(rel) {
  return readFileSync(join(MOBILE, rel), "utf8");
}
function readApp(rel) {
  return readFileSync(join(APP, rel), "utf8");
}
function has(src, needle) {
  return src.includes(needle);
}

let failures = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
}

console.log("Phase 35I database isolation + operational UX source test\n");

// ---- database isolation (P0) ----------------------------------------------
console.log("Database isolation (P0)");
const config = readApp("config.py");
check("production DB path pinned", has(config, 'PRODUCTION_DB_PATH = os.path.join(BASE_DIR, "lgu.db")'));
check("LGU_DB_PATH override exists", has(config, 'DB_PATH = os.environ.get("LGU_DB_PATH") or PRODUCTION_DB_PATH'));
check("is_production_db() helper", has(config, "def is_production_db("));
check("require_test_db() fatal guard", has(config, "def require_test_db(") && has(config, "FATAL: test database path resolves to the production database"));
const run = readApp("run.py");
check("LGU_TESTING guard before init", has(run, 'if os.environ.get("LGU_TESTING") == "1":') && has(run, "require_test_db()"));
const guardIdx = run.indexOf("require_test_db()");
const initIdx = run.indexOf("init_db()");
check("guard precedes init_db in source order", guardIdx > 0 && initIdx > guardIdx);
check("port configurable via LGU_PORT", has(run, 'os.environ.get("LGU_PORT", "5000")'));
const apiTest = read("scripts/api-test.mjs");
check("api-test spawns isolated server", has(apiTest, 'LGU_TESTING: "1"') && has(apiTest, "LGU_DB_PATH"));
check("api-test exits 2 on prod-path override", has(apiTest, "process.exit(2)"));
check("api-test removes its temp DB", has(apiTest, "rmSync"));
const cleanup = readApp("scripts/cleanup_test_fixtures.py");
check("cleanup also removes test scans by volunteer", has(cleanup, "TEST_SCAN_VOLUNTEERS") && has(cleanup, "DELETE FROM scans WHERE volunteer IN"));

// ---- kit: global time + helpers (global fixes) -----------------------------
console.log("Kit (ui/index.tsx) — time + controls");
const kit = read("src/ui/index.tsx");
check(
  "formatClock renders 12h",
  has(kit, 'toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })'),
);
check("formatLocalClock aliases formatServerClock", has(kit, "return formatServerClock(ts)"));
check("AppHeader back is its own row", has(kit, "backPressable") && has(kit, ">Back</Text>"));
check("SectionEyebrow has no rule (single text)", !has(kit, "eyebrowRule"));
check("Field label is optional", has(kit, "label?: string"));
check("ProgressTrack accepts trackColor", has(kit, "trackColor ?? colors.track"));
check("segment labels are control-sized (15px body)", has(kit, "segmentLabel: {") && has(kit, "fontSize: fontSize.body"));
check("btnDisabled pale style removed", !has(kit, "btnDisabled"));
check(
  "freshnessState supports delayed offline (35I L)",
  has(kit, "offlineMs = 0") && has(kit, "const age = now - lastOkAt"),
);

// ---- scanner layer ---------------------------------------------------------
console.log("Scanner layer");
const sheet = read("src/scanner/ScannerSheet.tsx");
check("gate sheet has no Direction control (35I Q)", !has(sheet, "SegmentedControl") && !has(sheet, "Direction SectionEyebrow"));
check("sheet doc states GATE ONLY", has(sheet, "GATE ONLY"));
const overlay = read("src/scanner/ScannerOverlay.tsx");
check("in-frame status strip removed (35I M)", !has(overlay, "statusStrip") && !has(overlay, "statusDot"));
check("camera hint is sans 13 (35I O)", has(overlay, "fontSize: 13"));
const result = read("src/scanner/ScannerResult.tsx");
check("already-used tone is red (35I C)", has(result, "ALREADY USED   — solid red") && has(result, 'c.kind === "already-used"'));
check("result times render 12h", has(result, "formatServerClock(result.time)"));
check(
  "invalid state: instruction + gate/time + sanitized detail (35J H)",
  has(result, "Do not admit. Use Find attendee.") &&
    has(result, "sanitizeInvalidDetail") &&
    has(result, "formatServerClock(result.time)"),
);
check("full-surface scan outcomes with Scan next (35J H/I/J)",
  has(result, "fullSurface") && has(result, '"Scan next"'));
check("Exit pill has no pale variant (35I P)", !has(result, "actionPillExit"));
const scanner = read("src/screens/ScannerScreen.tsx");
// 35M targeted fix (item 7): the window-driven camera share is kept
// (0.58) and a chrome budget reserves room for the top bar + bottom bar
// + banners, so Flash + Find manually stay above the fold on device.
check("camera window-driven share + chrome budget (35I N, 35M item 7)",
  has(scanner, "Math.min(260, windowH - 600)") &&
    has(scanner, "windowH - 600") &&
    has(scanner, "Math.max("));
// ---- end of scanner layer pins (camera pin lives at the read above) ----
check(
  "invalid results stamped with actual gate + time (35I C)",
  has(scanner, 'response.title === "INVALID CODE"') && has(scanner, "response.time = localTimestamp();"),
);
check(
  "sheet call carries no mode props (35I Q)",
  has(scanner, "gate selection only (35I Q") &&
    has(scanner, "onSelectGate={handleSelectGate}"),
);
check("camera view carries no status props (35I M)", !has(scanner, "volunteer={volunteer}"));

// ---- Home -----------------------------------------------------------------
console.log("Home screen");
const home = read("src/screens/HomeScreen.tsx");
check("hero label 'Inside now' (cycle 4)", has(home, "Inside now"));
check("sync copy 'All scans synced' (35I F)", has(home, "All scans synced"));
check("Scan QR Code sits after the gate row (35I B)", has(home, 'label="Scan QR Code"'));
check("invalid last-scan uses red 'invalid' pill (35I B)", has(home, 'invalidScan') && has(home, '"invalid"'));
check(
  "recovery row removed (35I E)",
  !has(home, "recoveryRow") && !has(home, "recoveryTitle"),
);

// ---- Live dashboard --------------------------------------------------------
console.log("Live dashboard");
const liveboard = read("src/screens/LiveBoardScreen.tsx");
// 33-QA (I8/I10) supersedes 35M item 3: 96px still pushed gates 6–7 +
// the Entries tail + the Updated footer past the fold at 360×800. 72px
// fixed 360×800 but the QA fix cycle 2 board-fit pass dropped it to
// 64px so the whole board also fits the 320×568 legacy screen; the
// scale exception (35I I) stands — only the pixel size is QA-adjusted.
check("hero value is 64px (35I I scale exception + 33-QA I8/I10 board fit)",
  has(liveboard, "fontSize: 64") && has(liveboard, "lineHeight: 58"));
check("gate bars use darker track (35I J)", has(liveboard, "BOARD_TRACK"));
check("count shares the gate-name line, 6px bar underneath (35J A)",
  has(liveboard, "gateCount") && !has(liveboard, "gateBarWrap") && has(liveboard, "height={6}"));
check("footer carries 12h + sync verdict (35I H)", has(liveboard, "Synced") && has(liveboard, "Connecting"));
check("board chrome fixed; content scrolls when viewport exceeded (35M R3)", has(liveboard, "<Screen scroll={false}>") && has(liveboard, 'marginTop: "auto" as const') && has(liveboard, "boardScrollContent"));
check("offline after 30s, values retained (35I L)", has(liveboard, "Math.max(30000, pollMs * 6)") && has(liveboard, "Offline · showing data from"));

// ---- Guests ---------------------------------------------------------------
console.log("Guests screen");
const guests = read("src/screens/GuestsScreen.tsx");
check("subtitle exact (35I T.5)", has(guests, "Single-use passes, tied to a host."));
check("Add guest is primary, no icon (35I T.3)", has(guests, 'formOpen ? "Cancel guest registration" : "+ Add guest"') && has(guests, 'variant="primary"'));
check("phone single-line, never ellipsised (35I T.2)", has(guests, 'style={styles.guestMeta} numberOfLines={1}'));
check("used line is date-aware (35I T.4)", has(guests, "function usedStamp(") && has(guests, "usedStamp(guest.used_at)"));
check("search field unlabeled (35I T.6)", !has(guests, 'label="Search"'));

// ---- Settings -------------------------------------------------------------
console.log("Settings screen");
const settings = read("src/screens/SettingsScreen.tsx");
check("Save name disabled unless changed (35I U.1)", has(settings, "disabled={!nameDirty}") && has(settings, "nameBaseline"));
check("baseline from stored name, no new key (35I U.1)", has(settings, "setNameBaseline(storedName)"));
check(
  "eyebrow removed (35I U.2)",
  !has(settings, "eyebrow={") && !has(settings, "eventTitle"),
);

// ---- Admin ----------------------------------------------------------------
console.log("Admin screen");
const admin = read("src/screens/AdminScreen.tsx");
check("section renamed Server connection (35I W.1)", has(admin, "<SectionEyebrow>Server connection</SectionEyebrow>"));
check("subtitle Server + Convocation details (35I W.1)", has(admin, "Dashboard availability, server connection and convocation details"));
check("operator copy says Server (35I W.2)", has(admin, "Server is reachable.") && has(admin, 'label="Server address"'));
check("no Backend operator copy (35I W.2)", !has(admin, "Backend connection") && !has(admin, "Backend address") && !has(admin, "Backend is reachable"));
check("pill labels Connected / Can't reach server / Checking (35I W.3)", has(admin, '"Connected"') && has(admin, '"Can\'t reach server"') && has(admin, '"Checking"'));
check("auto-probe on load (35I W.3)", has(admin, "probe the EFFECTIVE server address on load"));

// ---- Search recents (AA) --------------------------------------------------
console.log("Search + recent searches (AA)");
const search = read("src/screens/SearchScreen.tsx");
check("recents section shown without a query (AA)", has(search, "Recent searches") && has(search, "getRecentSearches"));
check("successful queries recorded (AA)", has(search, "addRecentSearch(debouncedQuery)"));
const settingsStore = read("src/store/settings.ts");
check("recent-search storage key + cap", has(settingsStore, 'KEY_RECENT_SEARCHES = "lgu.recent_searches"') && has(settingsStore, "RECENT_SEARCHES_MAX = 5"));
check("recents dedupe case-insensitively", has(settingsStore, "toLowerCase() !== q.toLowerCase()"));

console.log(`\nDone: ${failures} failure(s).`);
process.exit(failures > 0 ? 1 : 0);
