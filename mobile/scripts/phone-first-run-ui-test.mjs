// Regression checks for screenshot-reported Android onboarding and offline UX.
// Dependency-free and reproducible on CI; does not claim physical device QA.
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => readFileSync(resolve(root, p), "utf8").replace(/\r\n/g, "\n");
const picker = read("app/mode-picker.tsx");
const scanner = read("src/screens/ScannerScreen.tsx");
const home = read("src/screens/HomeScreen.tsx");
const client = read("src/api/client.ts");

function assertAll(name, ...conditions) {
  for (const cond of conditions) assert(cond, name);
  console.log("PASS: " + name);
}

assertAll("Mode picker is scrollable and confirmation no longer pushes cards",
  picker.includes("<Screen>"),
  picker.includes("<Modal"),
  picker.includes("styles.confirmBackdrop"),
  picker.includes("styles.confirmBar"),
  !picker.includes("<Screen scroll={false}>")
);
assertAll("Scanner loads only one login/name prompt at a time",
  scanner.includes("setNamePromptVisible(!!sess && volunteerRef.current.needsSetup)"),
  scanner.includes("visible={namePromptVisible && session !== null && !loginVisible}"),
  scanner.includes("setNamePromptVisible(false);\n          setLoginVisible(true);")
);
assertAll("Scanner checks connection before asking for credentials",
  scanner.includes("getApiBaseUrl()"),
  scanner.includes("connectionConfigured === false || online === false"),
  scanner.includes('label="Connect to server"'),
  scanner.includes('label="Back to home"'),
  scanner.includes('label="Retry connection"')
);
assertAll("Scanner re-reads server gates after setup",
  scanner.includes("void loadGates();"),
  scanner.includes("[refreshQueueCount, loadGates]")
);
assertAll("Authenticated volunteer display name suppresses redundant prompt",
  scanner.includes("volunteerRef.current.ensure(sess.displayName)")
);
assertAll("Home never reports zero attendance as actual while offline",
  home.includes("setSummary(null)"),
  home.includes('value={loaded ? inside.toLocaleString() : summaryError ? "—" : "..."}'),
  home.includes("{loaded ? <ProgressTrack"),
  home.includes("{loaded ? <View style={styles.demoRow}>")
);
assertAll("Home surfaces connection setup and reloads gate list",
  home.includes("backendConfigured === false"),
  home.includes('label="Connect to server"'),
  home.includes("void loadGates();")
);
assertAll("Offline queue count is not lost when offline",
  home.indexOf("queued > 0\n      ?") > -1,
  home.indexOf("queued > 0\n      ?") < home.indexOf("online === false\n        ?")
);
assertAll("API errors point to current connection flow instead of hidden Admin area",
  client.includes("Tap Connect to server"),
  !client.includes("Admin > Backend Connection")
);
