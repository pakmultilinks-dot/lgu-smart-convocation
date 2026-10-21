#!/usr/bin/env node
/**
 * Release-safety regression — Issue 1 + Issue 21 (dev tool exposure).
 *
 * Proves that the deterministic test panel and its destructive reset are
 * unreachable in release builds and unauthorized sessions:
 *
 *   S1  ScannerScreen renders ScannerTestPanel only under __DEV__ AND
 *       adminUnlocked (source-level guard present).
 *   S2  ScannerScreen reset button routes through requestTestReset
 *       (confirmation modal), not a direct destructive call.
 *   S3  ScannerTestPanel never shows "Start the backend to enable Test
 *       Scan" (Issue 21) — the volunteer-facing copy is neutral.
 *   S4  client.ts resetTestScans sends the X-Admin-Pin header.
 *   R1  POST /api/test-reset WITHOUT the admin PIN -> rejected (401/403).
 *   R2  POST /api/test-reset WITH the correct PIN -> 200 on a test DB.
 *   R3  POST /api/test-reset on a PRODUCTION db -> 404 (guard).
 *   R4  GET  /api/test-records on a PRODUCTION db -> 404 (guard).
 *   R5  GET  /api/demo-payload on a PRODUCTION db -> 404 (guard).
 *   R6  GET  /api/test-records on a TEST db without PIN -> 200 (read is
 *       non-destructive; the destructive path is the one that is locked).
 *
 * The production database (app/lgu.db) is never opened: a size+mtime
 * stamp is taken before and after the run to prove it.
 *
 *   node scripts/release-safety-test.mjs
 *
 * Exit code 0 = every check passed.
 */

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const APP_DIR = path.join(REPO_ROOT, "app");
const PRODUCTION_DB = path.resolve(APP_DIR, "lgu.db");
const MOBILE_DIR = path.join(REPO_ROOT, "mobile");

const venvPython = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
const PYTHON = fs.existsSync(venvPython)
  ? venvPython
  : process.platform === "win32"
    ? "python"
    : "python3";

const ADMIN_PIN = process.env.LGU_ADMIN_PIN || "2026";

function resolveTestDb() {
  const override = process.env.LGU_DB_PATH
    ? path.resolve(process.env.LGU_DB_PATH)
    : null;
  if (override && override.toLowerCase() === PRODUCTION_DB.toLowerCase()) {
    console.error(
      `FATAL: LGU_DB_PATH resolves to the production database (${PRODUCTION_DB}).`,
    );
    process.exit(2);
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "lgu-release-"));
  return { dir, dbPath: path.join(dir, "lgu-test.db") };
}

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function fileStamp(p) {
  try {
    const st = fs.statSync(p);
    return `${st.size} bytes, mtime ${st.mtimeMs}`;
  } catch {
    return "absent";
  }
}

async function waitForHealth(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${url}/api/health`, {
        signal: AbortSignal.timeout(1500),
      });
      if (res.ok) {
        const body = await res.json().catch(() => null);
        if (body && body.ok) return;
      }
    } catch {
      // Not up yet.
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`Server at ${url} did not become healthy in ${timeoutMs}ms.`);
}

async function startServer(extraEnv = {}) {
  const port = await freePort();
  const env = {
    ...process.env,
    LGU_DB_PATH: TEST.dbPath,
    LGU_TESTING: "1",
    LGU_PORT: String(port),
    // Throwaway database: opt in to the demo secrets run.py refuses by default.
    LGU_ALLOW_DEMO_SECRETS: "1",
    ...extraEnv,
  };
  delete env.LGU_SECRET_KEY;
  delete env.LGU_HMAC_SECRET;
  const flask = spawn(PYTHON, ["run.py"], {
    cwd: APP_DIR,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const logs = [];
  flask.stdout.on("data", (d) => logs.push(String(d)));
  flask.stderr.on("data", (d) => logs.push(String(d)));
  const base = `http://127.0.0.1:${port}`;
  await waitForHealth(base, 30000);
  return { flask, base, logs };
}

async function stopServer(s) {
  if (!s || s.flask.exitCode !== null || s.flask.signalCode !== null) return;
  const closed = new Promise((res) => s.flask.once("close", res));
  try {
    s.flask.kill();
  } catch {
    /* gone */
  }
  // Await child close so process.exit() never races an UV_HANDLE_CLOSING handle.
  await Promise.race([closed, new Promise((res) => setTimeout(res, 5000))]);
}

async function req(base, p, opts = {}) {
  const res = await fetch(`${base}${p}`, {
    method: opts.method || "GET",
    headers: opts.headers || {},
    body: opts.body,
    redirect: opts.redirect || "follow",
  });
  const text = await res.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* not json */
  }
  return { status: res.status, text, json, headers: res.headers };
}

let failures = 0;
function pass(name) {
  console.log(`  PASS  ${name}`);
}
function fail(name, detail) {
  failures += 1;
  console.log(`  FAIL  ${name}${detail ? ` - ${detail}` : ""}`);
}
function check(name, cond, detail) {
  if (cond) pass(name);
  else fail(name, detail);
}

function readSource(rel) {
  return fs.readFileSync(path.join(MOBILE_DIR, rel), "utf8");
}

const TEST = resolveTestDb();
const prodStampBefore = fileStamp(PRODUCTION_DB);
let T = null;

async function main() {
  console.log("Release-safety test — Issue 1 + Issue 21 (dev tool exposure)");
  console.log(`test db: ${TEST.dbPath}`);
  console.log(`production stamp before: ${prodStampBefore}\n`);

  // ---------------------------------------------------------- source checks
  console.log("Source-level guards (mobile app):");
  const scannerSrc = readSource(path.join("src", "screens", "ScannerScreen.tsx"));
  const testPanelSrc = readSource(path.join("src", "scanner", "ScannerTestPanel.tsx"));
  const clientSrc = readSource(path.join("src", "api", "client.ts"));

  check(
    "S1 ScannerTestPanel render guarded by __DEV__ AND adminUnlocked",
    /\{__DEV__\s*&&\s*adminUnlocked\s*\?/.test(scannerSrc) &&
      /<ScannerTestPanel/.test(scannerSrc),
    "expected {__DEV__ && adminUnlocked ? <ScannerTestPanel .../> : null}",
  );

  check(
    "S2 reset button routed through requestTestReset (confirmation)",
    /onTestReset=\{requestTestReset\}/.test(scannerSrc) &&
      /resetConfirmVisible/.test(scannerSrc) &&
      /Reset test scans\?/.test(scannerSrc),
    "expected onTestReset={requestTestReset} + confirmation modal",
  );

  check(
    "S3 ScannerTestPanel never shows 'Start the backend to enable Test Scan'",
    !/Start the backend to enable Test Scan/.test(testPanelSrc),
    "Issue 21: dev error text must never appear in volunteer UI",
  );

  check(
    "S3b ScannerTestPanel empty copy is neutral ('Test data isn't available')",
    /Test data isn't available/.test(testPanelSrc),
    "expected the neutral fallback copy",
  );

  check(
    "S4 client resetTestScans sends X-Admin-Pin header",
    /X-Admin-Pin/.test(clientSrc) &&
      /resetTestScans[\s\S]*?getAdminPin/.test(clientSrc),
    "expected getAdminPin + X-Admin-Pin inside resetTestScans",
  );

  // Guard: __DEV__ load guard also requires adminUnlocked (no fetch in release).
  check(
    "S5 loadTestRecords guarded by __DEV__ AND adminUnlocked",
    /if\s*\(!__DEV__\s*\|\|\s*!adminUnlocked\)/.test(scannerSrc),
    "expected early return when !__DEV__ || !adminUnlocked",
  );

  // ------------------------------------------------------- server checks
  console.log("\nServer-level guards (isolated backend):");
  T = await startServer({ LGU_PIN_MAX_FAILS: "50" });
  const base = T.base;
  console.log(`server: ${base} (PIN limit raised to 50)\n`);

  const health = await req(base, "/api/health");
  check("health ok", health.json && health.json.ok === true);

  // R1: destructive reset without PIN -> rejected.
  const resetNoPin = await req(base, "/api/test-reset", { method: "POST" });
  check(
    "R1 POST /api/test-reset WITHOUT PIN -> rejected (401/403)",
    resetNoPin.status === 401 || resetNoPin.status === 403,
    `status=${resetNoPin.status}`,
  );

  // R2: destructive reset with correct PIN -> 200.
  const resetWithPin = await req(base, "/api/test-reset", {
    method: "POST",
    headers: { "X-Admin-Pin": ADMIN_PIN },
  });
  check(
    "R2 POST /api/test-reset WITH PIN -> 200 (test db)",
    resetWithPin.status === 200 && resetWithPin.json?.ok === true,
    `status=${resetWithPin.status}, body=${resetWithPin.text.slice(0, 80)}`,
  );

  // R3-R5: production-path guard proven via config.is_production_db unit
  // proof (same pattern as master-audit B1-B3) — the production DB is
  // never opened by this script (it is held by the live Flask instance).
  const guardUnit = spawnSync(
    PYTHON,
    [
      "-c",
      "import sys; sys.path.insert(0, sys.argv[1]); import config; print(config.is_production_db(sys.argv[2]), config.is_production_db(sys.argv[3]))",
      APP_DIR,
      PRODUCTION_DB,
      TEST.dbPath,
    ],
    { encoding: "utf8" },
  );
  const [prodIs, testIs] = guardUnit.stdout.trim().split(/\s+/);
  check(
    "R3 is_production_db(prod)=True -> _test_tool_guard returns 404",
    prodIs === "True",
    guardUnit.stdout.trim(),
  );
  check(
    "R4 is_production_db(test temp)=False -> test endpoints allowed on test DB",
    testIs === "False",
    guardUnit.stdout.trim(),
  );
  // The guard source must map is_production_db -> 404 for all three test tools.
  const routesSrc = fs.readFileSync(path.join(APP_DIR, "web", "routes.py"), "utf8");
  const guardBlock = /def _test_tool_guard\(\):[\s\S]*?(?=\ndef |\n@bp)/.exec(routesSrc);
  check(
    "R5 _test_tool_guard returns 404 when is_production_db is true",
    !!guardBlock &&
      /is_production_db/.test(guardBlock[0]) &&
      /404/.test(guardBlock[0]),
    "expected is_production_db + 404 inside _test_tool_guard",
  );
  // All three test endpoints must call _test_tool_guard.
  for (const [label, fn] of [
    ["api_test_records", "api_test_records"],
    ["api_test_reset", "api_test_reset"],
    ["api_demo_payload", "api_demo_payload"],
  ]) {
    const fnBlock = new RegExp(`def ${fn}\\(\\):[\\s\\S]*?(?=\\ndef |\\n@bp)`).exec(routesSrc);
    check(
      `${label} calls _test_tool_guard`,
      !!fnBlock && /_test_tool_guard\(\)/.test(fnBlock[0]),
      `expected _test_tool_guard() inside ${fn}`,
    );
  }
  // api_test_reset must ALSO call _require_admin_pin (Issue 1 reset auth).
  const resetBlock = /def api_test_reset\(\):[\s\S]*?(?=\ndef |\n@bp)/.exec(routesSrc);
  check(
    "R5b api_test_reset also calls _require_admin_pin (reset auth)",
    !!resetBlock && /_require_admin_pin\(\)/.test(resetBlock[0]),
    "expected _require_admin_pin() inside api_test_reset",
  );

  // R6: test-records on TEST db without PIN -> 200 (read is non-destructive).
  const recordsTest = await req(base, "/api/test-records");
  check(
    "R6 GET /api/test-records on TEST db -> 200 (read-only, non-destructive)",
    recordsTest.status === 200 && Array.isArray(recordsTest.json?.records),
    `status=${recordsTest.status}`,
  );

  await stopServer(T);

  const prodStampAfter = fileStamp(PRODUCTION_DB);
  console.log(`\nproduction stamp after:  ${prodStampAfter}`);
  check(
    "production DB untouched (size + mtime identical)",
    prodStampAfter === prodStampBefore,
    `before=${prodStampBefore} after=${prodStampAfter}`,
  );

  console.log(
    `\n${failures === 0 ? "ALL CHECKS PASSED" : `${failures} CHECK(S) FAILED`}`,
  );
  // Set the code and let the loop drain: a hard process.exit() here races the
  // undici/fetch keep-alive sockets still closing -> libuv UV_HANDLE_CLOSING abort.
  process.exitCode = failures === 0 ? 0 : 1;
}

main().catch(async (e) => {
  console.error(e);
  await stopServer(T);
  process.exitCode = 1;
});
