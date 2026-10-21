/**
 * Phase 28 — remaining authorization closure (mobile half).
 *
 * Closes the four mobile concerns carried out of the Phase 27 report:
 *
 *   1. GET /api/settings was ungated server-side (fixed in
 *      app/web/routes.py — backend proof in
 *      app/scripts/test_phase28_authorization_closure.py). This suite pins
 *      the CLIENT half: the settings read now carries the same X-Admin-Pin
 *      as the write, both halves share one request path, and the public
 *      surfaces keep using the anonymous /api/config instead — so gating
 *      the settings read breaks no kiosk, landing page or connectivity
 *      discovery flow, and no IP is hard-coded anywhere.
 *
 *   2. HomeScreen's Entry/Exit toggle committed every tap straight to
 *      storage. It is now gated by needsScanModeConfirmation — the same
 *      fail-closed shape as Phase 27 E3's needsModeConfirmation — and
 *      nothing is persisted until the operator confirms.
 *
 *   3. event.tsx dropped the Venue section entirely when no venue was
 *      published. It now always renders and states "Not announced".
 *
 *   4. scanResultLogic's `.action` field was reported as "never read".
 *      Review: it is a typed field of the classification contract, asserted
 *      by scanner-logic-test.mjs, while the RENDER deliberately shows the
 *      DEVICE mode (ScannerResult derives `action` from `mode`). That is a
 *      display-accuracy nuance with zero authorization impact — NO CODE
 *      CHANGE. This suite pins the reviewed state so the decision is
 *      reproducible, and the Phase 27 report carries the correction.
 *
 * These are SOURCE-level checks (no device/emulator here); tsc + lint gate
 * the code, this suite gates the contract at source.
 *
 * Run from mobile/:  node scripts/phase28-authorization-source-test.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOBILE = join(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = dirname(MOBILE);

const read = (rel) => readFileSync(join(ROOT, rel), "utf8");
const has = (src, needle) => src.includes(needle);
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");

let failures = 0;
let passed = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
  else passed += 1;
}

console.log("Phase 28 - remaining authorization closure (mobile source pins)\n");

const settingsApi = read("mobile/src/api/settingsApi.ts");
const client = read("mobile/src/api/client.ts");
const adminGate = read("mobile/src/components/AdminGate.tsx");
const adminScreen = read("mobile/src/screens/AdminScreen.tsx");
const liveboard = read("mobile/src/screens/LiveBoardScreen.tsx");
const home = read("mobile/src/screens/HomeScreen.tsx");
const appMode = read("mobile/src/store/appMode.ts");
const eventScreen = read("mobile/app/(student)/event.tsx");
const scanLogic = read("mobile/src/scanner/scanResultLogic.ts");
const scannerResult = read("mobile/src/scanner/ScannerResult.tsx");
const scannerLogicTest = read("mobile/scripts/scanner-logic-test.mjs");

// ---- 1. the settings read carries the administrator PIN -------------------
console.log("1 - GET /api/settings is an administrator action on the client too");
const getSettings = settingsApi.match(
  /export async function getSettings[\s\S]*?\n\}/,
);
const putSettings = settingsApi.match(
  /export async function updateSettings[\s\S]*?\n\}/,
);
check("getSettings exists and is pinned as a whole function", !!getSettings);
check("updateSettings exists and is pinned as a whole function", !!putSettings);
check(
  "the settings READ attaches X-Admin-Pin (same gate as the write)",
  !!getSettings && has(getSettings[0], "X-Admin-Pin"),
);
check(
  "the settings WRITE still attaches X-Admin-Pin",
  !!putSettings && has(putSettings[0], "X-Admin-Pin"),
);
check(
  "both halves read the PIN from the on-device admin gate",
  !!getSettings && !!putSettings &&
    has(getSettings[0], "getAdminPin()") &&
    has(putSettings[0], "getAdminPin()"),
);
check(
  "both halves go through the ONE shared request path (no side door)",
  !!getSettings && !!putSettings &&
    has(getSettings[0], "request<ConvocationSettings>") &&
    has(putSettings[0], "request<ConvocationSettings>"),
);
const IP_RE = /\d{1,3}(?:\.\d{1,3}){3}/;
check(
  "the settings module hard-codes no IP address or host",
  !IP_RE.test(stripComments(settingsApi)),
);
check(
  "the IP guard is real (detects a hard-coded address)",
  IP_RE.test('const url = "http://192.168.1.50:5000";'),
);
check(
  "the settings module never embeds a PIN literal (it reads the stored one)",
  !/"\d{4,8}"/.test(stripComments(settingsApi)),
);

// ---- 2. the Admin screen can only reach that read behind the gate ----------
console.log("\n2 - the PIN is verified before the read can happen");
check(
  "AdminGate renders its children only once unlocked",
  has(adminGate, "if (unlocked) {") && has(adminGate, "<>{children}</>"),
);
check(
  "AdminGate re-verifies the stored PIN against the server before mounting",
  has(adminGate, "verifyAdminPin(saved)") &&
    has(adminGate, "if (alive && verified.ok) setUnlocked(true)"),
);
check(
  "a locally stored PIN alone never opens the gate (server ok required)",
  has(adminGate, "a locally stored PIN is NEVER treated as") &&
    has(adminGate, "verified.ok"),
);
check(
  "unlock() persists the PIN only after the server accepts it",
  /const unlock[\s\S]*?await verifyAdminPin\(candidate\)[\s\S]*?await setAdminPin\(candidate\)/.test(adminGate),
);
check(
  "the Admin screen reads settings through getSettings (not a raw fetch)",
  has(adminScreen, "getSettings()") &&
    !adminScreen.includes('"/api/settings"'),
);

// ---- 3. public surfaces keep the public config endpoint --------------------
console.log("\n3 - legitimate public workflows are untouched");
check(
  "client.ts still exports fetchAppConfig for the public /api/config",
  has(client, "export async function fetchAppConfig") &&
    has(client, "/api/config"),
);
check(
  "the Live Board reads public config, not the gated settings read",
  has(liveboard, "fetchAppConfig") && !has(liveboard, "getSettings"),
);
check(
  "Home reads public config for event identity + gate window",
  has(home, "fetchAppConfig") && !has(home, "getSettings"),
);
check(
  "the settings module documents /api/config as the public path",
  has(settingsApi, "/api/config"),
);

// ---- 4. HomeScreen Entry/Exit is confirmed before it is applied ------------
console.log("\n4 - HomeScreen Entry/Exit cannot be flipped by one stray tap");
const scanRule = appMode.match(
  /export function needsScanModeConfirmation[\s\S]{0,260}?\n\}/,
);
check("the scan-mode rule is exported from the shared store", !!scanRule);
check(
  "the scan-mode rule fails CLOSED (unknown current mode asks too)",
  !!scanRule && has(scanRule[0], "return current !== next;"),
);
check(
  "HomeScreen imports the shared rule (no inline copy)",
  has(home, "needsScanModeConfirmation"),
);
const modeChange = home.match(
  /const handleModeChange[\s\S]*?\n  \}, \[scanMode\]\);/,
);
check("handleModeChange is pinned as a whole function", !!modeChange);
check(
  "the tap only ARMS a pending change — nothing is persisted there",
  !!modeChange &&
    has(modeChange[0], "setPendingMode(mode)") &&
    !has(modeChange[0], "persistScanMode"),
);
check(
  "persistScanMode is called only from the confirm handler",
  has(home, "const confirmModeChange") &&
    /const confirmModeChange[\s\S]*?persistScanMode\(mode\)/.test(home) &&
    (home.match(/persistScanMode\(/g) || []).length === 1, // the confirm call only
);
check(
  "the SegmentedControl routes through the gated handler",
  has(home, "onChange={handleModeChange}"),
);
check(
  "a confirmation prompt is rendered with an explicit Cancel",
  has(home, "pendingMode !== null") &&
    has(home, "onPress={cancelModeChange}"),
);
check(
  "cancelling leaves the current direction untouched",
  has(home, "const cancelModeChange = useCallback(() => setPendingMode(null)"),
);

// ---- 5. the student event page states a missing venue ----------------------
console.log("\n5 - an unpublished venue is stated, never silently dropped");
check(
  "the Venue section always renders (no truthy-only branch)",
  !has(eventScreen, "{event.venue ? ("),
);
check(
  "an empty venue reads 'Not announced'",
  has(eventScreen, 'subtitle={event.venue || "Not announced"}'),
);
check(
  "the venue eyebrow still labels the section",
  has(eventScreen, "<SectionEyebrow>Venue</SectionEyebrow>"),
);

// ---- 6. scanResultLogic .action — reviewed, documented, unchanged ---------
console.log("\n6 - scanResultLogic .action: reviewed as a contract field (NO CHANGE)");
check(
  "the classifier still types .action on its result",
  has(scanLogic, 'action?: "Entry" | "Exit"'),
);
check(
  "the classifier still populates .action from the scanned text",
  /action:\s*upper\.includes\("EXIT"\)/.test(scanLogic),
);
check(
  "the contract test still asserts .action (it is not dead surface)",
  has(scannerLogicTest, ".action") &&
    (scannerLogicTest.match(/\.action\b/g) || []).length >= 2,
);
check(
  "the RENDER derives its label from the DEVICE mode, not the payload",
  has(scannerResult, 'const action = mode === "exit" ? "Exit" : "Entry"'),
);
check(
  "the render never reads the classifier's .action (documented decision)",
  !has(scannerResult, "c.action") && !has(scannerResult, "result.action"),
);

// ---- summary ---------------------------------------------------------------
console.log(`\n${passed + failures} checks, ${failures} failures`);
process.exit(failures ? 1 : 0);