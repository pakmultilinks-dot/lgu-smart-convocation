#!/usr/bin/env node
/**
 * Phase 35I — Database isolation test (PART AE focused suite).
 *
 * Verifies that the automated test path can NEVER touch the production
 * database (app/lgu.db):
 *
 *   1. Source pins — config/run/api-test/cleanup wiring is in place and the
 *      startup path performs no destructive resets.
 *   2. Runtime guard — Python with LGU_TESTING=1 refuses to boot against the
 *      production DB (SystemExit, non-zero exit) and selects a temp DB when
 *      LGU_DB_PATH points elsewhere.
 *   3. End-to-end proof — a full api-test.mjs run boots its own Flask on a
 *      free port with a temp DB and the production file's stamp (size +
 *      mtime) is byte-identical before/after; the temp DB is removed.
 *
 *   node scripts/db-isolation-test.mjs        # full proof (default)
 *   node scripts/db-isolation-test.mjs --fast # source pins + runtime guard only
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const APP_DIR = path.join(REPO_ROOT, "app");
const SCRIPTS = path.join(APP_DIR, "scripts");
const MOBILE_SCRIPTS = __dirname;
const PRODUCTION_DB = path.resolve(APP_DIR, "lgu.db");
const CONFIG_PY = path.join(APP_DIR, "config.py");
const RUN_PY = path.join(APP_DIR, "run.py");
const API_TEST = path.join(MOBILE_SCRIPTS, "api-test.mjs");
const CLEANUP_PY = path.join(SCRIPTS, "cleanup_test_fixtures.py");
const FAST = process.argv.includes("--fast");

let passed = 0;
let failures = 0;

function ok(label) {
  passed += 1;
  console.log(`ok  ${label}`);
}

function fail(label, detail) {
  failures += 1;
  console.log(`FAIL ${label}${detail ? ` — ${detail}` : ""}`);
}

function pythonBin() {
  const venvPython = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvPython)) return venvPython;
  return process.platform === "win32" ? "python" : "python3";
}

function runPython(code, envExtra) {
  return spawnSync(pythonBin(), ["-c", code], {
    cwd: APP_DIR,
    env: { ...process.env, ...envExtra },
    encoding: "utf8",
    timeout: 30000,
  });
}

function fileStamp(p) {
  try {
    const st = fs.statSync(p);
    return `${st.size}:${st.mtimeMs}`;
  } catch {
    return "absent";
  }
}

console.log("Phase 35I database isolation test");
console.log(`Production database: ${PRODUCTION_DB}\n`);

// ---------------------------------------------------------------- 1. source pins
{
  const configSrc = fs.readFileSync(CONFIG_PY, "utf8");
  const runSrc = fs.readFileSync(RUN_PY, "utf8");
  const apiSrc = fs.readFileSync(API_TEST, "utf8");
  const cleanupSrc = fs.readFileSync(CLEANUP_PY, "utf8");

  const pins = [
    ["config.py defines PRODUCTION_DB_PATH", /PRODUCTION_DB_PATH\s*=\s*os\.path\.join\(BASE_DIR/.test(configSrc)],
    ["config.py selects DB_PATH from LGU_DB_PATH", /DB_PATH\s*=\s*os\.environ\.get\("LGU_DB_PATH"\)/.test(configSrc)],
    ["config.py defines is_production_db", /def is_production_db\(/.test(configSrc)],
    ["config.py defines require_test_db (SystemExit guard)", /def require_test_db\(/.test(configSrc) && /SystemExit/.test(configSrc)],
    ["run.py guards LGU_TESTING before init_db", /LGU_TESTING/.test(runSrc) && /require_test_db\(\)/.test(runSrc) && /init_db\(\)/.test(runSrc)],
    ["run.py guard precedes init_db in source order", runSrc.indexOf("require_test_db()") !== -1 && runSrc.indexOf("require_test_db()") < runSrc.indexOf("init_db()")],
    ["run.py supports LGU_PORT override", /LGU_PORT/.test(runSrc)],
    ["api-test.mjs refuses production via exit 2", /process\.exit\(2\)/.test(apiSrc) && /production database/i.test(apiSrc)],
    ["api-test.mjs builds a temp test DB", /mkdtempSync/.test(apiSrc) && /lgu35i-testdb-/.test(apiSrc)],
    ["api-test.mjs spawns its own Flask with LGU_DB_PATH + LGU_TESTING", /spawn\(/.test(apiSrc) && /LGU_TESTING:\s*"1"/.test(apiSrc) && /LGU_DB_PATH:\s*TEST\.dbPath/.test(apiSrc)],
    ["api-test.mjs tears the test DB down", /rmSync/.test(apiSrc)],
    ["api-test.mjs stamps production before/after", /fileStamp\(PRODUCTION_DB\)/.test(apiSrc)],
    ["cleanup utility knows test scan volunteers", /TEST_SCAN_VOLUNTEERS/.test(cleanupSrc)],
    ["cleanup utility deletes scans by volunteer", /DELETE FROM scans WHERE volunteer IN/.test(cleanupSrc)],
    ["startup never imports the cleanup utility", !/cleanup_test_fixtures/.test(runSrc)],
    ["run.py startup performs no DROP/DELETE", !/DROP\s+TABLE|DELETE\s+FROM/i.test(runSrc)],
    ["database.py startup performs no DROP/DELETE", !/DROP\s+TABLE|DELETE\s+FROM/i.test(fs.readFileSync(path.join(APP_DIR, "database.py"), "utf8"))],
  ];
  for (const [label, condition] of pins) {
    if (condition) ok(label);
    else fail(label);
  }
}

// ------------------------------------------------- 2. python runtime selection + guard
{
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "lgu35i-iso-"));
  const testDb = path.join(tmp, "runtime-test.db");
  const sel = runPython(
    "import config; print(config.DB_PATH); print(config.is_production_db()); print(config.require_test_db())",
    { LGU_DB_PATH: testDb },
  );
  const lines = (sel.stdout || "").trim().split(/\r?\n/);
  if (lines[0] === testDb) ok("runtime: DB_PATH follows LGU_DB_PATH");
  else fail("runtime: DB_PATH follows LGU_DB_PATH", `got ${lines[0]}`);
  if (lines[1] === "False") ok("runtime: temp DB is not production");
  else fail("runtime: temp DB is not production", `got ${lines[1]}`);
  if (lines[2] === testDb) ok("runtime: require_test_db accepts a test DB");
  else fail("runtime: require_test_db accepts a test DB", `got ${lines[2]}`);

  const guard = runPython("import config; config.require_test_db()", {
    LGU_DB_PATH: PRODUCTION_DB,
  });
  if (guard.status !== 0) ok("runtime: require_test_db refuses production (non-zero exit)");
  else fail("runtime: require_test_db refuses production (non-zero exit)", "exit 0");
  if (/FATAL/.test(guard.stderr || "")) ok("runtime: guard message mentions FATAL");
  else fail("runtime: guard message mentions FATAL", (guard.stderr || "").slice(0, 120));

  const prodStampBefore = fileStamp(PRODUCTION_DB);
  const boot = runPython("import run", { LGU_DB_PATH: PRODUCTION_DB, LGU_TESTING: "1" });
  if (boot.status !== 0) ok("runtime: run.py with LGU_TESTING=1 against production fails loudly");
  else fail("runtime: run.py with LGU_TESTING=1 against production fails loudly", "server booted!");
  if (/FATAL/.test(boot.stderr || "")) ok("runtime: run.py guard prints FATAL before any write");
  else fail("runtime: run.py guard prints FATAL before any write", (boot.stderr || "").slice(0, 120));
  const bootStamp = fileStamp(PRODUCTION_DB);
  if (bootStamp === prodStampBefore) ok("runtime: refused boot left production untouched");
  else fail("runtime: refused boot left production untouched", `${prodStampBefore} -> ${bootStamp}`);

  try {
    fs.rmSync(tmp, { recursive: true, force: true });
  } catch {
    // Best-effort temp cleanup.
  }
}

// ------------------------------------- 3. full api-test run (production untouched)
if (!FAST) {
  const prodStampBefore = fileStamp(PRODUCTION_DB);
  console.log("\nRunning isolated api-test.mjs (full proof)...");
  const res = spawnSync(process.execPath, [API_TEST], {
    cwd: MOBILE_SCRIPTS,
    encoding: "utf8",
    timeout: 180000,
  });
  const out = `${res.stdout || ""}${res.stderr || ""}`;
  if (res.status === 0) ok("api-test exits 0 in isolated mode");
  else fail("api-test exits 0 in isolated mode", `exit ${res.status}`);
  if (/Production DB unchanged by tests\./.test(out)) ok("api-test proves production unchanged");
  else fail("api-test proves production unchanged", out.slice(-300));
  if (/Test database removed\./.test(out)) ok("api-test removes its test database");
  else fail("api-test removes its test database", "missing teardown message");
  const prodStampAfter = fileStamp(PRODUCTION_DB);
  if (prodStampAfter === prodStampBefore) ok("production stamp identical after full api-test");
  else fail("production stamp identical after full api-test", `${prodStampBefore} -> ${prodStampAfter}`);
} else {
  console.log("\n--fast: skipping full api-test run.");
}

console.log(`\nDone: ${passed} passed, ${failures} failed.`);
process.exit(failures > 0 ? 1 : 0);
