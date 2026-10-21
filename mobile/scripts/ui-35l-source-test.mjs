// Phase 35L source tests — operational gaps + gate UX completion.
// Pure-node substring pins over mobile source (same pattern as
// ui-35k-source-test.mjs). 14 focused checks, one per spec part.
// Usage (from mobile/): node scripts/ui-35l-source-test.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
// Run from repo root OR mobile/ — resolve to the mobile folder.
if (!cwd.endsWith("mobile")) cwd = root;

const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const has = (src, needle) => src.includes(needle);

let passed = 0;
let failed = 0;
function check(name, condition, detail) {
  if (condition) {
    passed += 1;
    console.log(`  PASS  ${name}`);
  } else {
    failed += 1;
    console.error(`  FAIL  ${name}${detail ? ` :: ${detail}` : ""}`);
  }
}

const guestPass = read("src/screens/GuestPassScreen.tsx");
const scannerScreen = read("src/screens/ScannerScreen.tsx");
const scannerSheet = read("src/scanner/ScannerSheet.tsx");
const scannerView = read("src/scanner/CameraScannerView.tsx");
const scannerBar = read("src/scanner/ScannerBottomBar.tsx");
const scannerResult = read("src/scanner/ScannerResult.tsx");
const scanLogic = read("src/scanner/scanResultLogic.ts");
const searchScreen = read("src/screens/SearchScreen.tsx");
const settingsScreen = read("src/screens/SettingsScreen.tsx");
const scannerTopBar = read("src/scanner/ScannerTopBar.tsx");

console.log("Part A — Guest Pass sharing (Share sheet + Save as image)");
check("A1: Share action exists (OS share sheet, not custom WhatsApp UI)",
  has(guestPass, "Share.share") && has(guestPass, "sharePass"));
check("A2: Save as image exists (ViewShot capture + media library save)",
  has(guestPass, "ViewShot") && has(guestPass, "saveToLibraryAsync") &&
    has(guestPass, "requestPermissionsAsync") && has(guestPass, "Save as image"));

console.log("Part B — QR rendering quality (pure white + quiet zone)");
check("B1: QR plate is PURE white (#FFFFFF) with wide quiet zone, ink modules",
  has(guestPass, 'backgroundColor: "#FFFFFF"') &&
    has(guestPass, 'backgroundColor="#FFFFFF"') &&
    has(guestPass, "color={colors.ink}") &&
    has(guestPass, "padding: spacing.lg"));

console.log("Part C — Scanner flash + permission recovery");
check("C1: Flash control exists, gated by torch capability (never fake)",
  has(scannerBar, "torchSupported") && has(scannerView, "enableTorch={torch && torchSupported}") &&
    has(scannerBar, "Flash unavailable"));
check("C2: Denied permission is never a dead screen (settings + manual path)",
  has(scannerScreen, "Linking.openSettings") && has(scannerScreen, "canAskAgain") &&
    has(scannerScreen, "Open settings") && has(scannerScreen, "Find manually"));

console.log("Part D — Full-screen scan result states");
check("D: valid/guest/already-used/invalid all exist; sync notice stays 'other'",
  has(scanLogic, '"Guest entry"') &&
    has(scannerResult, "This pass has already been processed.") &&
    has(scannerResult, '"Do not admit. Use Find attendee."') &&
    has(scannerScreen, "fullResultLayer") && has(scannerResult, "fullSurface") &&
    has(scanLogic, "ALREADY SYNCED") &&
    has(scannerScreen, "SCAN_RESULT_MS") && has(scannerScreen, "RESULT_DISMISS_MS"));

console.log("Part E — Haptic feedback (real, distinct, graceful)");
check("E: haptic wrapper wired — success/warning/error distinct, no-op safe",
  has(scannerScreen, "NotificationFeedbackType.Success") &&
    has(scannerScreen, "NotificationFeedbackType.Warning") &&
    has(scannerScreen, "NotificationFeedbackType.Error") &&
    has(scannerScreen, "classifyScanResult(response).haptic") &&
    has(scannerScreen, "Platform.OS === \"web\"") &&
    has(scannerScreen, "haptic(\"success\")"));

console.log("Part F — Volunteer identity (usable name before scanning)");
check("F: ≥2-letter name validator wired in logic + scanner + settings",
  has(scanLogic, "isValidVolunteerName") &&
    has(scannerScreen, "isValidVolunteerName") &&
    has(scannerScreen, "needsSetup") &&
    has(scannerScreen, "setNamePromptVisible(true)") &&
    has(settingsScreen, "isValidVolunteerName"));

console.log("Part G — Gate sheet + camera pause");
check("G: sheet titled 'Choose a gate'; camera paused while sheet open",
  has(scannerSheet, "Choose a gate") &&
    has(scannerScreen, "paused={sheetVisible}") &&
    has(scannerView, "pausedRef.current = paused") &&
    has(scannerView, "onBarcodeScanned={handleBarcodeScanned}"));

console.log("Part H — Search helper text");
check("H: helper reads the minimum in plain words (QA fix cycle 2)",
  has(searchScreen, "Type at least 2 characters to search") &&
    has(searchScreen, "Results appear while you type"));

console.log("Part I — QR is an identifier, not identity proof");
check("I: guest identity + host relationship shown on the guest success state",
  has(scanLogic, 'upper.includes("GUEST")') &&
    has(scannerResult, "Guest of") === false && // sub flows through result, not the component
    // 33-QA (I23) supersedes the old roll-only pin — the pass names the
    // host; QA fix cycle 3 (Issue 3) renders it as a stacked passMeta row.
    has(guestPass, "passMetaText") &&
    has(guestPass, "{`Host: ${pass.host_name}`}"));

console.log("Part J — regression safety pins (timing/labels preserved)");
// Updated again (user-directed scanner UI visual revert): Entry/Exit is
// exposed as the compact SegmentedControl in the topbar (wired to
// onModeChange → confirmation modal in ScannerScreen) AND echoed in the
// result action pill — not a specific control widget, and never a large
// semantic banner.
check("J: Entry/Exit consistent — topbar SegmentedControl + result action pill",
  has(scannerTopBar, "SegmentedControl") &&
    has(scannerTopBar, "onChange={onModeChange}") &&
    has(scannerTopBar, 'label: "Entry"') &&
    has(scannerTopBar, 'label: "Exit"') &&
    has(scannerResult, 'const action = mode === "exit" ? "Exit" : "Entry"'));
check("J: no hard-coded gate list — scanner/sheet gates come from fetchGates/props",
  !has(scannerScreen, "Main Gate") && !has(scannerSheet, "Main Gate") &&
    has(scannerScreen, "fetchGates") && has(scannerSheet, "gates:") &&
    has(scannerScreen, "gates={gates}"));

console.log(`\nui-35l-source-test: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
