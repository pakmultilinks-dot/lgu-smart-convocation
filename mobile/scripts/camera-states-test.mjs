// Issue 6 (Release blocker) — camera distinct states + recovery actions.
// Pure-node source pins over mobile/src (same pattern as ui-35l-source-test.mjs).
// Five distinct camera states, each with a recovery action — never a dead end:
//   REQUIRED (canAskAgain) / DENIED (!canAskAgain) — distinct copy in ScannerScreen
//   STARTING — spinner + "Starting camera…" + Find manually until onCameraReady
//   READY — live viewfinder
//   ERROR — "Camera unavailable" + Try Again / Back / Find manually
// Usage (from mobile/): node scripts/camera-states-test.mjs
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

const scannerScreen = read("src/screens/ScannerScreen.tsx");
const cameraView = read("src/scanner/CameraScannerView.tsx");

console.log("Part A — REQUIRED vs DENIED are distinct permission states");
check("A1: REQUIRED title exists ('Camera access needed')",
  has(scannerScreen, '"Camera access needed"'));
check("A2: DENIED title is distinct ('Camera permission is off')",
  has(scannerScreen, '"Camera permission is off"'));
check("A3: REQUIRED body asks to grant (distinct copy)",
  has(scannerScreen, "Grant camera access to scan QR codes at your gate."));
check("A4: DENIED body points to system settings (distinct copy)",
  has(scannerScreen, "Enable the camera for this app in system settings"));
check("A5: REQUIRED recovery = requestPermission()",
  has(scannerScreen, "canAsk ?") &&
    scannerScreen.includes("onPress={() => void requestPermission()}"));
check("A6: DENIED recovery = Linking.openSettings()",
  has(scannerScreen, "void Linking.openSettings().catch(() => {});"));
check("A7: both permission states keep 'Find manually' (never a dead end)",
  has(scannerScreen, '"Find manually"'));

console.log("Part B — STARTING state (distinct, self-clearing, recoverable)");
check("B1: starting overlay exists with 'Starting camera…' label",
  has(cameraView, "styles.startingText}>Starting camera…"));
check("B2: starting overlay has an ActivityIndicator spinner",
  has(cameraView, "<ActivityIndicator size=\"large\" color={colors.paper} />"));
check("B3: starting overlay offers 'Find manually' recovery",
  cameraView.split("Find manually").length - 1 >= 2); // error state + starting overlay
check("B4: CameraView receives onCameraReady (clears STARTING)",
  has(cameraView, "onCameraReady={onCameraReady}"));
check("B5: ScannerScreen tracks cameraReady and passes it as ready=",
  has(scannerScreen, "const [cameraReady, setCameraReady] = useState(false);") &&
    has(scannerScreen, "ready={cameraReady}") &&
    has(scannerScreen, "onCameraReady={handleCameraReady}"));
check("B6: retry remounts the camera AND restarts the starting state",
  has(scannerScreen, "setCameraReady(false);") &&
    has(scannerScreen, "setCameraKey((k) => k + 1);"));
check("B7: web placeholder reports ready on mount (no phantom spinner)",
  has(cameraView, "if (Platform.OS === \"web\") onCameraReady();"));

console.log("Part C — ERROR state recovery preserved (regression pin)");
check("C1: mount-error card title 'Camera unavailable' intact",
  has(cameraView, "Camera unavailable"));
check("C2: Try Again + Back recovery intact",
  has(cameraView, 'label="Try Again"') && has(cameraView, 'label="Back"'));
check("C3: mount-error handler still wired (onMountError)",
  has(cameraView, "onMountError={onMountError}") &&
    has(scannerScreen, "setCameraFailed(true);"));
check("C4: starting overlay sits above a still-mounted CameraView (onCameraReady can fire)",
  cameraView.indexOf("onCameraReady={onCameraReady}") <
    cameraView.indexOf("styles.startingText}>Starting camera…") &&
    cameraView.indexOf("styles.startingText}>Starting camera…") <
    cameraView.indexOf('text="Point the camera at a student QR card"'));

console.log(`\ncamera-states-test: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
