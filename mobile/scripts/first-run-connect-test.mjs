// Preview setup contract: no accounts or credentials are embedded into APKs.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { strict as assert } from "node:assert";
const cwd = resolve(import.meta.dirname, "..");
const read = (p) => readFileSync(resolve(cwd, p), "utf8");
const appConfig = requireConfig();
function requireConfig() {
  const source = read("app.config.js");
  assert(source.includes('APP_VARIANT !== "preview"'));
  assert(source.includes('pk.edu.lgu.smartconvocation.preview'));
  assert(source.includes("usesCleartextTraffic: false"));
  return source;
}
const eas = JSON.parse(read("eas.json"));
assert.equal(eas.build.preview.android.buildType, "apk");
assert.equal(eas.build.preview.env.APP_VARIANT, "preview");
assert(read("app/_layout.tsx").includes('name="connect-server"'));
assert(read("app/mode-picker.tsx").includes('router.push("/connect-server")'));
assert(read("app/(student)/welcome.tsx").includes('router.push("/connect-server")'));
assert(read("src/components/AdminGate.tsx").includes('router.push("/connect-server")'));
assert(read("src/screens/SettingsScreen.tsx").includes('router.push("/connect-server")'));
assert(read("src/screens/ScannerScreen.tsx").includes('router.push("/connect-server")'));
const setup = read("app/connect-server.tsx");
assert(setup.includes("setApiBaseUrl(next)"));
assert(setup.includes("probeBackend(next)"));
assert(setup.includes('next.toLowerCase().startsWith("https://")'));
const storage = read("src/store/settings.ts");
assert(storage.includes('result.app === "LGU Smart Convocation"'));
assert(storage.includes("clearAdminPin()"));
assert(storage.includes("clearScannerSession()"));
assert(storage.includes("clearToken()"));
assert(storage.includes("await queueCount()"));
assert(storage.includes("await AsyncStorage.multiSet"));
console.log("PASS: EAS preview config and ungated HTTPS first-run setup");
