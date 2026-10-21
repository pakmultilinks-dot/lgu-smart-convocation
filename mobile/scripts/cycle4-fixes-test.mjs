// QA fix cycle 4 source tests — targeted remediation of the 19 findings.
// Highest-value pins: Finding 6 (server-verify on mount — CRITICAL),
// Finding 1 (standardized wrong-PIN copy), Finding 2 (semantic mode
// accent), Finding 4 (honest offline/connection copy), Findings 10/14
// (search + dashboard/announcement naming).
// Pure-node substring pins over mobile source — same harness family as
// layout-p8 / ui-35h. Usage (from mobile/): node scripts/cycle4-fixes-test.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
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

const adminAccess = read("src/store/adminAccess.ts");
const adminGate = read("src/components/AdminGate.tsx");
const liveboard = read("src/screens/LiveBoardScreen.tsx");
const home = read("src/screens/HomeScreen.tsx");
const topbar = read("src/scanner/ScannerTopBar.tsx");
const bottombar = read("src/scanner/ScannerBottomBar.tsx");
const scanner = read("src/screens/ScannerScreen.tsx");
const broadcast = read("src/screens/BroadcastScreen.tsx");
const admin = read("src/screens/AdminScreen.tsx");
const search = read("src/screens/SearchScreen.tsx");

// ---- Finding 6 (CRITICAL): a stored PIN is never self-authorization ------
console.log("Finding 6 — AdminGate re-verifies the stored PIN with the server");
check(
  "mount effect re-verifies saved PIN against the server",
  has(adminGate, "verifyAdminPin(saved)"),
);
check(
  "gate opens only on a server `verified.ok`",
  has(adminGate, "verified.ok) setUnlocked(true)"),
);
check(
  "old trusting pattern (setUnlocked(saved !== null)) is gone",
  !has(adminGate, "setUnlocked(saved !== null)"),
);
check(
  "unreachable/rejected server keeps the gate locked (safe default)",
  has(adminGate, "NEVER treated as") && has(adminGate, "catch"),
);

// ---- Finding 1: standardized wrong-PIN copy ------------------------------
console.log("Finding 1 — one clear wrong-PIN message");
check(
  "WRONG_PIN constant is the mandated copy",
  has(adminAccess, 'export const WRONG_PIN = "Wrong PIN. Try again."'),
);
check(
  "AdminGate surfaces WRONG_PIN on a 401/400",
  has(adminGate, "setError(WRONG_PIN)"),
);
check(
  "LiveBoard exit flow surfaces the same WRONG_PIN",
  has(liveboard, "setExitPinError(WRONG_PIN)") &&
    has(liveboard, 'import { WRONG_PIN }'),
);

// ---- Finding 2: Entry green / Exit amber mode accent ---------------------
console.log("Finding 2 — Entry/Exit semantic mode accent");
check(
  "scanner top bar accents the active mode",
  has(topbar, 'activeColor={mode === "exit" ? colors.amber : colors.valid}'),
);
check(
  "home mode control accents the active mode",
  has(home, 'activeColor={scanMode === "exit" ? colors.amber : colors.valid}'),
);

// ---- Finding 4: honest connection + offline copy -------------------------
console.log("Finding 4 — connection/offline copy");
check(
  "connection label distinguishes Syncing / Offline / Online / Connecting",
  /syncing\s*\?\s*"Syncing"\s*:\s*online === false\s*\?\s*"Offline"\s*:\s*online\s*\?\s*"Online"\s*:\s*"Connecting"/s.test(
    bottombar,
  ),
);
check(
  "offline preference explains what it does (on)",
  has(bottombar, "On. Scans are saved on this phone and sent later."),
);
check(
  "offline preference explains what it does (off)",
  has(bottombar, "Off. Scans send right away."),
);
check(
  "scanner banner names the state + queue depth",
  has(scanner, "Waiting to sync\") :") || has(scanner, "scan${queued === 1"),
);

// ---- Finding 10: search placeholder --------------------------------------
console.log("Finding 10 — search field hint");
check(
  "search placeholder is 'Name, roll number or phone'",
  has(search, 'placeholder="Name, roll number or phone"'),
);

// ---- Finding 14: dashboard + announcement naming -------------------------
console.log("Finding 14 — naming");
check("home hero reads 'Inside now'", has(home, "Inside now"));
check("live board hero reads 'Inside now'", has(liveboard, "Inside now"));
check(
  "broadcast header is 'Announcements'",
  has(broadcast, 'title="Announcements"'),
);
check(
  "admin action is 'Open announcements'",
  has(admin, 'label="Open announcements"'),
);

console.log(`\ncycle4-fixes-test: ${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
