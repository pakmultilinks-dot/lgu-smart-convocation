// Phase 35K source tests — data truth + dynamic configuration + identity
// integrity. Pure-node substring pins over mobile AND backend source
// (same pattern as ui-35h/35i/35j-source-test.mjs).
// Usage (from mobile/): node scripts/ui-35k-source-test.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const repo = join(root, "..");
let cwd = process.cwd();
// Run from repo root OR mobile/ — resolve to the mobile folder.
if (!cwd.endsWith("mobile")) cwd = root;

const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const readApp = (rel) => readFileSync(join(repo, "app", rel), "utf8");
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

console.log("Backend — shared configuration (Phase 35K F/J/K/G)");
const configPy = readApp("config.py");
check("config defines GATE_ACTIVITY_WINDOW_MINUTES from env (default 15)",
  has(configPy, "GATE_ACTIVITY_WINDOW_MINUTES") &&
    has(configPy, "LGU_GATE_WINDOW_MINUTES"));
check("config defines MESSAGE_CHAR_LIMIT from env (default 160)",
  has(configPy, "MESSAGE_CHAR_LIMIT") && has(configPy, "LGU_MESSAGE_LIMIT"));
check("config defines BROADCAST_MODE from env (default demo)",
  has(configPy, "BROADCAST_MODE") && has(configPy, "LGU_BROADCAST_MODE"));

const modelsPy = readApp("models.py");
check("models derives broadcast audience from roster / scan history",
  has(modelsPy, "_announcement_audience") && has(modelsPy, "broadcast_audience"));
check("models exposes app_config_payload for /api/config",
  has(modelsPy, "app_config_payload"));
check("models queued_scan_exists for sync idempotency (Part O)",
  has(modelsPy, "queued_scan_exists"));
check("dashboard summary uses shared window constant (Part J)",
  has(modelsPy, "GATE_ACTIVITY_WINDOW_MINUTES"));
check("dashboard summary no longer invents expected_male/expected_female/expected_guests",
  !has(modelsPy, "expected_male") && !has(modelsPy, "expected_female") &&
    !has(modelsPy, "expected_guests"));

const databasePy = readApp("database.py");
check("settings seed includes university_name (Part F)",
  has(databasePy, "university_name"));

const routesPy = readApp("web/routes.py");
check("routes serve GET /api/config",
  has(routesPy, "/api/config") && has(routesPy, "app_config_payload"));
check("routes serve GET /api/broadcast/audience",
  has(routesPy, "/api/broadcast/audience"));
check("settings PUT requires admin PIN (Part T)",
  has(routesPy, "_require_admin_pin") &&
    routesPy.indexOf("_require_admin_pin") < routesPy.indexOf("def api_put_settings"));
check("gate rename requires admin PIN (Part T)",
  has(routesPy, "def api_rename_gate") &&
    has(routesPy.slice(routesPy.indexOf("def api_rename_gate"), routesPy.indexOf("def api_rename_gate") + 2000), "_require_admin_pin"));
check("sync path guards duplicate queued scans (Part O)",
  has(routesPy, "queued_scan_exists") && has(routesPy, "ALREADY SYNCED"));
check("broadcast enforces server message limit (Part K)",
  has(routesPy, "MESSAGE_CHAR_LIMIT"));
check("broadcast demo/real notes are honest (Part G)",
  has(routesPy, "Delivery gateway is not configured") &&
    has(routesPy, "Demo mode: not sent by SMS"));

const dashboardHtml = readApp("web/templates/dashboard.html");
check("dashboard template reads the shared window (Part J)",
  has(dashboardHtml, "window_minutes"));

console.log("Mobile — server config consumed, fallbacks documented (Part F)");
const clientTs = read("src/api/client.ts");
check("client fetches /api/config with typed AppConfig",
  has(clientTs, "fetchAppConfig") && has(clientTs, "interface AppConfig"));
check("client fetches broadcast audience per gate",
  has(clientTs, "fetchBroadcastAudience"));
check("DashboardData carries attendance_set / roster counts (Part B)",
  has(clientTs, "attendance_set") && has(clientTs, "student_roster_count") &&
    has(clientTs, "announcement_audience_count"));
check("DashboardData no longer carries expected_total/expected_male/expected_female",
  !has(clientTs, "expected_total") && !has(clientTs, "expected_male") &&
    !has(clientTs, "expected_female"));

const settingsApi = read("src/api/settingsApi.ts");
check("settingsApi types university_name (Part F)",
  has(settingsApi, "university_name"));
check("settings PUT attaches X-Admin-Pin (Part T)",
  has(settingsApi, "X-Admin-Pin"));

const configTs = read("src/config.ts");
check("config.ts documents constants as startup fallbacks only",
  has(configTs, "Startup fallbacks ONLY") || has(configTs, "startup fallback"));

const offlineQueue = read("src/store/offlineQueue.ts");
check("offline queue treats ALREADY SYNCED as permanent rejection (Part O)",
  has(offlineQueue, "ALREADY SYNCED"));

const progress = read("src/utils/progress.ts");
check("progressDenominator is attendance-only (Part B)",
  has(progress, "progressDenominator") &&
    !/roster fallback|fallback.*roster/i.test(progress));

const dedup = read("src/scanner/useScanDedup.ts");
const cooldown = read("src/scanner/scanCooldown.ts");
check("camera dedup is mode+gate-aware (Part P)",
  has(dedup, "shouldSuppressRepeat") && has(cooldown, "shouldSuppressRepeat") &&
    has(cooldown, "mode") && has(cooldown, "gateId"));

const scannerScreen = read("src/screens/ScannerScreen.tsx");
check("scanner claims scan with mode+gate+occasion (Part P)",
  has(scannerScreen, "claim(scan.data, mode, gateId, occasion)"));

const scanLogic = read("src/scanner/scanResultLogic.ts");
check("ALREADY SYNCED maps to other, not camera already-used (Part O)",
  has(scanLogic, "ALREADY SYNCED"));

const home = read("src/screens/HomeScreen.tsx");
check("Home reads event year/university/window from /api/config (Part F/J)",
  has(home, "fetchAppConfig") && has(home, "gate_activity_window_minutes"));
check("Home sync copy is honest when offline (Part D)",
  has(home, "No scans waiting to sync"));

const liveboard = read("src/screens/LiveBoardScreen.tsx");
check("LiveBoard reads event name + window from /api/config (Part F/J)",
  has(liveboard, "fetchAppConfig") && has(liveboard, "cfg?.event.name") &&
    has(liveboard, "windowLabel"));
check("LiveBoard no longer hardcodes 'Gate activity · 15 min'",
  !has(liveboard, "Gate activity · 15 min"));

const broadcast = read("src/screens/BroadcastScreen.tsx");
check("Broadcast consumes server audience/mode/limit (Part G/I/K)",
  has(broadcast, "fetchAppConfig") && has(broadcast, "fetchBroadcastAudience") &&
    has(broadcast, "broadcastMode") && has(broadcast, "messageLimit"));
check("Broadcast shows demo banner + honest counter",
  has(broadcast, "Demo mode — announcements are saved only") &&
    has(broadcast, "{message.length} / {messageLimit}"));

const admin = read("src/screens/AdminScreen.tsx");
check("Admin form edits university_name (Part F)",
  has(admin, "university_name"));

const guestPass = read("src/screens/GuestPassScreen.tsx");
check("Guest pass artwork reads university from server config (Part F)",
  has(guestPass, "cfg?.university"));

console.log("Security scans (Part E/Q — no secret leakage, honest limits)");
const secretScan = read("src/config.ts") + clientTs + settingsApi +
  read("src/store/settings.ts") + read("src/screens/AdminScreen.tsx");
check("HMAC secret never appears in mobile source",
  !has(secretScan, "lgu-convocation-hmac-secret") &&
    !has(secretScan, "HMAC_SECRET") && !has(secretScan, "hmac_secret"));
const allMobileScreens = ["src/screens/HomeScreen.tsx", "src/screens/LiveBoardScreen.tsx",
  "src/screens/BroadcastScreen.tsx", "src/screens/AdminScreen.tsx",
  "src/screens/ScannerScreen.tsx", "src/screens/SettingsScreen.tsx",
].map(read).join("\n");
check("no hard-coded population numbers on operational screens",
  !/(?:^|[^0-9])24 students|roster of 24|(?:^|[^0-9])3 guests? inside(?:[^0-9]|$)/m.test(allMobileScreens));

console.log(`\nui-35k-source-test: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
