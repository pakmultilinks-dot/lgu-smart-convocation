/**
 * 33-QA release-blocker fix cycle — P5 layout cluster regression test.
 * Pins Issues 7–14 at source level:
 *   I7  minWidth: 0 on flex1 text containers beside StatusPills
 *   I8  live-board hero 72px (96px pushed gates 6–7 + footer below the
 *       fold at 360×800)
 *   I9  board scroll indicator stays discoverable
 *   I11 guest pass: Back pinned below a side-by-side Share/Save row
 *   I12 gate sheet: a lone 7th chip stays grid-aligned (maxWidth 48%)
 *   I13 explicit exit (crest tap/hold + footer Exit) + always-visible
 *       absolute confirm overlay — no board-wide tap wrapper
 *   I14 bounded scanner camera frame (flex: 1 + chrome-budget minHeight)
 * Run: node scripts/layout-p5-source-test.mjs
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
let passed = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
  else passed += 1;
}

console.log("33-QA P5 layout regression test (Issues 7-14)\n");

const settings = read("src/screens/SettingsScreen.tsx");
const admin = read("src/screens/AdminScreen.tsx");
const home = read("src/screens/HomeScreen.tsx");
const liveboard = read("src/screens/LiveBoardScreen.tsx");
const guestPass = read("src/screens/GuestPassScreen.tsx");
const sheet = read("src/scanner/ScannerSheet.tsx");
const scanner = read("src/screens/ScannerScreen.tsx");

// ---- I7: minWidth 0 on flex1 text containers -------------------------------
console.log("I7 - flex1 text containers (minWidth: 0)");
check(
  "SettingsScreen flex1 carries minWidth: 0",
  has(settings, "flex1: { flex: 1, minWidth: 0 }"),
);
check(
  "AdminScreen flex1 carries minWidth: 0",
  has(admin, "flex1: { flex: 1, minWidth: 0 }"),
);
check(
  "HomeScreen flex1 carries minWidth: 0",
  has(home, "flex1: { flex: 1, minWidth: 0 }"),
);
check(
  "LiveBoard gateName carries minWidth: 0",
  /gateName: \{[^}]*minWidth: 0/s.test(liveboard),
);
check(
  "LiveBoard demoCell carries minWidth: 0",
  /demoCell: \{[^}]*minWidth: 0/s.test(liveboard),
);
check(
  "GuestPass rulesText carries minWidth: 0",
  /rulesText: \{[^}]*minWidth: 0/s.test(guestPass),
);

// ---- I8/I10: hero fits the whole board at 360x800 --------------------------
console.log("I8/I10 - live board hero scale");
check(
  "heroValue is 64/58 (all 7 gates + tail + footer fit at 360x800 and 320x568)",
  /heroValue: \{[\s\S]*?fontSize: 64,[\s\S]*?lineHeight: 58,/s.test(liveboard),
);
check("the 96px hero is gone", !has(liveboard, "fontSize: 96"));

// ---- I9: scroll affordance kept ---------------------------------------------
console.log("I9 - scroll affordance kept");
check(
  "board ScrollView keeps the visible indicator",
  has(liveboard, "showsVerticalScrollIndicator={true}"),
);

// ---- I11: guest pass pinned actions ------------------------------------------
console.log("I11 - guest pass pinned actions");
check(
  "bottomActions + bodyScroll style names kept (35M pins)",
  has(guestPass, "bottomActions") && has(guestPass, "bodyScroll"),
);
check(
  "Share + Save share one row (actionRow / actionBtn)",
  has(guestPass, "actionRow") && has(guestPass, "actionBtn"),
);
check(
  "Share pass + Save as image labels kept",
  has(guestPass, 'label="Share pass"') && has(guestPass, '"Save as image"'),
);
const backIdx = guestPass.indexOf('label="Back to guests"');
const scrollCloseIdx = guestPass.indexOf("</ScrollView>");
const actionsIdx = guestPass.indexOf("<View style={styles.bottomActions}>");
check(
  "Back-to-guests button removed — header back arrow is the way back " +
    "(QA fix cycle 2)",
  backIdx === -1 && scrollCloseIdx > 0 && actionsIdx > 0,
);

// ---- I12: gate sheet grid ------------------------------------------------------
console.log("I12 - scanner gate sheet grid");
check(
  "gateChip keeps the two-column basis; a lone final chip spans the " +
    "full row (QA fix cycle 2)",
  has(sheet, 'flexBasis: "48%"') && has(sheet, 'maxWidth: "48%"') &&
    has(sheet, "flexGrow: 1") &&
    has(sheet, "gateChipFull") &&
    has(sheet, "loneTail") &&
    has(sheet, 'flexBasis: "100%"'),
);

// ---- I13: explicit exit + overlay ----------------------------------------------
console.log("I13 - live dashboard exit");
check(
  "board-wide tap label is gone",
  !has(liveboard, 'accessibilityLabel="Live dashboard — tap to show exit options"'),
);
check(
  "footer Exit control present",
  has(liveboard, 'accessibilityLabel="Exit live dashboard"'),
);
check(
  "crest tap + hold still arm the exit",
  has(liveboard, "onCrestPress={armExit}") && has(liveboard, "onCrestLongPress={armExit}"),
);
check(
  "confirm card renders as an absolute overlay",
  has(liveboard, "styles.exitOverlay") &&
    /exitOverlay: \{[^}]*position: "absolute" as const/s.test(liveboard),
);
check(
  "ScrollView outermost inside Screen scroll={false}",
  /<Screen scroll=\{false\}>[\s\S]*?<ScrollView/.test(liveboard),
);
check(
  "board scroll content + pinned footer kept (35M R3)",
  has(liveboard, "boardScrollContent") &&
    has(liveboard, 'marginTop: "auto" as const') &&
    has(liveboard, "Math.max(insets.bottom, 6)"),
);
check(
  "PIN-gated exit flow untouched (Issue 4)",
  has(liveboard, "verifyAdminPin") &&
    has(liveboard, 'label="Leave display"') &&
    has(liveboard, "confirmExitWithPin"),
);

// ---- I14: bounded scanner camera frame ------------------------------------------
console.log("I14 - scanner camera frame");
check(
  "main scanner column is bounded (scannerBody wrapper)",
  has(scanner, "scannerBody: {"),
);
check(
  "cameraArea style carries flex: 1",
  /cameraArea: \{[^}]*flex: 1/s.test(scanner),
);
check(
  "camera fills its slot with the chrome-budget floor as minHeight",
  has(scanner, "minHeight: cameraHeight") && !has(scanner, "{ height: cameraHeight }"),
);
check(
  "35M camera formula pins kept (0.58 share + 330 chrome budget)",
  has(scanner, "windowH * 0.58") && has(scanner, "windowH - 330"),
);
check(
  "cameraArea before ScannerBottomBar (35M layout order)",
  scanner.indexOf("cameraArea") < scanner.indexOf("<ScannerBottomBar"),
);

// ---- superseded pins stay in sync ------------------------------------------------
console.log("Test pins synced with the QA-superseded expectations");
check(
  "ui-35j pin updated to the 64px hero (QA fix cycle 2)",
  has(read("scripts/ui-35j-source-test.mjs"), "fontSize: 64"),
);
check(
  "ui-35h + ui-35r pins updated to the explicit exit",
  has(read("scripts/ui-35h-source-test.mjs"), 'accessibilityLabel="Exit live dashboard"') &&
    has(read("scripts/ui-35r-source-test.mjs"), 'accessibilityLabel="Exit live dashboard"'),
);

console.log(`\nDone: ${passed} passed, ${failures} failed.`);
process.exit(failures > 0 ? 1 : 0);
