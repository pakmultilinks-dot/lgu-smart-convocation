// Phase 38 source tests — event reliability and shared analytics (mobile side).
// Pure-node substring pins over the mobile source (no test framework in
// mobile; same pattern as the ui-35*-source-test.mjs family).
// Covers: MOB-001 (secure credential storage), MOB-002 (automatic offline
// scan queueing), MOB-003 (network error classification), configurable
// polling with overlap guards, and the dashboard/attendance integrations.
// Usage (from mobile/): node scripts/phase38-reliability-test.mjs
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
const count = (src, needle) => src.split(needle).length - 1;

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

// ---- MOB-001: credentials in the platform keystore -------------------------
console.log("MOB-001 — Secure scanner + admin credential storage");
const secure = read("src/store/secureStorage.ts");
check("secureStorage wraps expo-secure-store with WHEN_UNLOCKED",
  has(secure, "expo-secure-store") && has(secure, "WHEN_UNLOCKED"));
check("secureStorage migrates a legacy AsyncStorage row and removes it",
  has(secure, "AsyncStorage.getItem(key)") &&
    has(secure, "AsyncStorage.removeItem(key)") &&
    secure.indexOf("SecureStore.setItemAsync(key, legacy") <
      secure.indexOf("AsyncStorage.removeItem(key)"));
check("secureStorage keeps an in-memory web fallback",
  has(secure, 'Platform.OS === "web"') && has(secure, "memory.get(key)"));

const scannerSession = read("src/store/scannerSession.ts");
check("scannerSession no longer imports AsyncStorage",
  !has(scannerSession, "@react-native-async-storage/async-storage"));
check("scannerSession reads/writes/erases through secureStorage",
  has(scannerSession, "readSecret(KEY_SESSION") &&
    has(scannerSession, "writeSecret(KEY_SESSION") &&
    has(scannerSession, "eraseSecret(KEY_SESSION"));
check("scannerSession keeps its local expiry check",
  has(scannerSession, "Date.parse(s.expiresAt) <= Date.now()"));

const adminAccess = read("src/store/adminAccess.ts");
check("adminAccess no longer imports AsyncStorage",
  !has(adminAccess, "@react-native-async-storage/async-storage"));
check("adminAccess stores the PIN through secureStorage",
  has(adminAccess, "readSecret(KEY_ADMIN_PIN") &&
    has(adminAccess, "writeSecret(KEY_ADMIN_PIN"));
check("adminAccess keeps the shared WRONG_PIN export",
  has(adminAccess, 'export const WRONG_PIN = "Wrong PIN. Try again.";'));

// ---- MOB-002 / MOB-003: queue path + network classification ----------------
console.log("MOB-002/003 — Automatic queueing and network classification");
const scanner = read("src/screens/ScannerScreen.tsx");
check("one shared queueScan helper exists",
  has(scanner, "const queueScan = useCallback(") &&
    has(scanner, "async (stamped: ReturnType<typeof scanPayload>)"));
check("offline mode and the network-failure path share it",
  count(scanner, "await queueScan(stamped);") === 2);
check("only status 0 (networkError) sets the device offline",
  count(scanner, "e.status === 0") >= 3 &&
    count(scanner, "if (e instanceof ApiError && e.status === 0) setOnline(false);") >= 2);
check("the old blanket !retryable offline flip is gone",
  !has(scanner, "if (!retryable) {\n      setOnline(false)"));
check("a failed sync still re-locks a revoked session (Phase 14)",
  count(scanner, "handleAuthFailure(e);") >= 2);
check("the queued scan carries the same stamped payload + local timestamp",
  has(scanner, "enqueueScan({\n        ...stamped,\n        scanned_at: localTimestamp(),") ||
    has(scanner, "scanned_at: localTimestamp()"));
check("busy stays a retryable notice, never an offline transition",
  has(scanner, "const retryable = e instanceof ApiError && e.retryable === true;") &&
    has(scanner, 'await haptic(retryable ? "warning" : "error");'));

// ---- Configurable polling with overlap guards ------------------------------
console.log("Polling — configurable cadence, clamped, no overlap");
const liveboard = read("src/screens/LiveBoardScreen.tsx");
check("LiveBoard clamps the server cadence into [2000, 30000]",
  has(liveboard, "Math.min(30000, Math.max(2000,") &&
    has(liveboard, "setPollMs(clampPollMs(result.poll_interval_ms))"));
check("LiveBoard interval restarts on the clamped cadence",
  has(liveboard, "setInterval(tick, pollMs)") &&
    !has(liveboard, "setInterval(tick, REFRESH_MS)"));
check("LiveBoard freshness bands scale with the cadence (floors = 15s/30s)",
  has(liveboard, "staleMsFor(pollMs)") && has(liveboard, "offlineMsFor(pollMs)"));
check("LiveBoard keeps the one-request-at-a-time guard",
  has(liveboard, "if (inflight.current) return;"));

const home = read("src/screens/HomeScreen.tsx");
check("Home summary refresh has an inflight guard",
  has(home, "const inflight = useRef(false);") &&
    has(home, "if (inflight.current) return;"));
check("Home refetches the summary whenever it gains focus",
  has(home, "void refresh();") && has(home, "}, [refresh]),"));

// ---- Dashboard + attendance integration ------------------------------------
console.log("Integration — DashboardData keys and student attendance");
const client = read("src/api/client.ts");
for (const key of [
  "remaining_attendance: number | null;",
  "rejected_count: number;",
  "duplicate_count: number;",
  "trends: {",
  "poll_interval_ms: number;",
  "admissions_by_occasion:",
  "occasion_filter?: Occasion;",
]) {
  check(`DashboardData carries additive key: ${key.slice(0, 40)}`, has(client, key));
}

const studentApi = read("src/api/studentApi.ts");
check("student API exposes the attendance endpoint",
  has(studentApi, "export async function fetchAttendance") &&
    has(studentApi, "`${BASE}/attendance`"));
// The privacy test scopes to the interface itself — the file's own doc
// comment may mention operational fields while explaining what is EXCLUDED.
const attBlock = studentApi.slice(
  studentApi.indexOf("interface StudentAttendance"),
  studentApi.indexOf("export async function fetchAttendance"),
);
check("StudentAttendance is the privacy-safe count shape",
  has(studentApi, "interface StudentAttendance") &&
    !has(attBlock, "feed") && !has(attBlock, "rejected_count") &&
    !has(attBlock, "gate"));

const studentHome = read("app/(student)/home.tsx");
check("student home fetches attendance as supplementary data",
  has(studentHome, "studentApi.fetchAttendance(token).catch(() => null)"));
check("attendance card renders honest set/unset states",
  has(studentHome, "att.attendance_set") &&
    has(studentHome, "Not set by the administration"));
check("student home never renders operational fields",
  !has(studentHome, "rejected_count") && !has(studentHome, "busiest_gate"));

// ---- Admin dashboard template ----------------------------------------------
console.log("Integration — admin dashboard.html");
const dash = readFileSync(
  join(cwd.replace(/mobile$/, ""), "app", "web", "templates", "dashboard.html"),
  "utf8",
).replace(/\r\n/g, "\n"); // the template is CRLF on Windows
check("analytics tiles present (remaining / rejected / duplicate)",
  has(dash, 'id="k-remaining"') && has(dash, 'id="k-rejected"') && has(dash, 'id="k-duplicate"'));
check("polling reads the server cadence, clamped, one-shot rescheduled",
  has(dash, "d.poll_interval_ms") &&
    has(dash, "Math.min(30000, Math.max(2000,") &&
    has(dash, "setTimeout(refresh, ms)") &&
    !has(dash, "setInterval(refresh, 5000)"));
check("unset target renders an em dash, never a fabricated 0",
  has(dash, "d.remaining_attendance") && has(dash, "\\u2014"));
check("the page still schedules its next fetch after every attempt",
  has(dash, "  } catch (e) { /* keep last good state on transient errors */ }\n  schedule();"));

console.log(`\nphase38-reliability-test: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
