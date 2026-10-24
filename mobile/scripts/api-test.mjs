#!/usr/bin/env node
/**
 * Integration test for the LGU Smart Convocation Flask backend.
 *
 * Phase 35I — DATABASE ISOLATION: this suite no longer runs against
 * whatever server happens to be on :5000. It boots its OWN Flask instance
 * on a free port with LGU_DB_PATH pointing at a disposable SQLite database
 * in a fresh temp directory, runs the full suite against it, then tears
 * everything down. The production database (app/lgu.db) is never opened,
 * written, or even required — a stamp (size + mtime) is taken before and
 * after the run to prove it.
 *
 *   node scripts/api-test.mjs
 *
 * A safety guard refuses to start if LGU_DB_PATH is set to the production
 * database (fail loudly — never a silent fallback). The test database is
 * removed after the run.
 *
 * Exit code 0 means every test passed, non-zero means at least one failed.
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const APP_DIR = path.join(REPO_ROOT, "app");
const PRODUCTION_DB = path.resolve(APP_DIR, "lgu.db");

if (process.argv[2] || process.env.API_BASE) {
  console.log(
    "Note: Phase 35I api-test.mjs always boots its own isolated server " +
      "on a free port; an external baseUrl argument is ignored.",
  );
}

/** Select the disposable test database; refuse production loudly. */
function resolveTestDb() {
  const override = process.env.LGU_DB_PATH
    ? path.resolve(process.env.LGU_DB_PATH)
    : null;
  if (override && override.toLowerCase() === PRODUCTION_DB.toLowerCase()) {
    console.error(
      `FATAL: LGU_DB_PATH resolves to the production database (${PRODUCTION_DB}).`,
    );
    console.error(
      "Refusing to run API tests against production. " +
        "Unset LGU_DB_PATH or point it at a test database.",
    );
    process.exit(2);
  }
  if (override) {
    return { dir: path.dirname(override), dbPath: override, temp: false };
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "lgu35i-testdb-"));
  return { dir, dbPath: path.join(dir, "lgu-test.db"), temp: true };
}

/** A free TCP port on loopback for the isolated test server. */
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

/** Size + mtime stamp — proves production was untouched by the run. */
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
      // Not up yet — keep polling.
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(
    `Test server did not become healthy at ${url} within ${timeoutMs}ms.`,
  );
}

let BASE = "";
let TEST = null;
let flask = null;
const flaskLogs = [];

async function startTestServer() {
  const port = await freePort();
  const venvPython = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
  const python = fs.existsSync(venvPython)
    ? venvPython
    : process.platform === "win32"
      ? "python"
      : "python3";
  const env = {
    ...process.env,
    LGU_DB_PATH: TEST.dbPath,
    LGU_TESTING: "1",
    LGU_PORT: String(port),
    // run.py refuses to boot with the committed demo secrets. This harness
    // runs against a throwaway database, so it opts in explicitly.
    LGU_ALLOW_DEMO_SECRETS: "1",
  };
  flask = spawn(python, ["run.py"], { cwd: APP_DIR, env, stdio: ["ignore", "pipe", "pipe"] });
  flask.stdout.on("data", (d) => flaskLogs.push(String(d)));
  flask.stderr.on("data", (d) => flaskLogs.push(String(d)));
  flask.on("error", (e) => {
    console.error("FATAL: could not start the isolated test server:", e.message);
  });
  BASE = `http://127.0.0.1:${port}`;
  try {
    await waitForHealth(BASE, 30000);
  } catch (e) {
    console.error(e.message);
    if (flaskLogs.length) {
      console.error("--- test server output (tail) ---");
      console.error(flaskLogs.join("").slice(-2000));
    }
    throw e;
  }
}

async function stopTestServer() {
  const child = flask;
  flask = null;
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  // On Windows the Python process may still hold the SQLite file handle a
  // moment after kill(); wait for actual exit before the caller deletes the
  // temp dir, else rmSync throws EPERM/EBUSY and teardown is skipped.
  const exited = new Promise((resolve) => child.once("exit", resolve));
  try {
    child.kill();
  } catch {
    return; // Already gone.
  }
  await Promise.race([exited, new Promise((r) => setTimeout(r, 3000))]);
}

const ADMIN_PIN = process.env.LGU_ADMIN_PIN || "2026";

let failures = 0;
let skipped = 0;

function pass(name) {
  console.log(`  PASS  ${name}`);
}
function fail(name, detail) {
  failures += 1;
  console.log(`  FAIL  ${name}${detail ? " - " + detail : ""}`);
}
function skip(name, reason) {
  skipped += 1;
  console.log(`  SKIP  ${name} (${reason})`);
}
function check(name, condition, detail) {
  if (condition) pass(name);
  else fail(name, detail);
}

// ---- client logic (mirrors src/api/client.ts) ----

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, init) {
  const url = `${BASE}${path}`;
  let response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { "Content-Type": "application/json", ...((init && init.headers) || {}) },
    });
  } catch {
    throw new ApiError(`Could not reach the server at ${BASE}.`, 0);
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const message =
      body && typeof body === "object" && typeof body.error === "string"
        ? body.error
        : `Server returned status ${response.status}.`;
    throw new ApiError(message, response.status);
  }
  return body;
}

// Phase 14: /api/scan and /api/sync now require an authenticated scanner.
// Fixtures mint one synthetic scanner (random, non-production) via the
// guarded test helper and reuse the token for the whole run.
let _scannerHeaders = null;
async function scannerHeaders() {
  if (_scannerHeaders) return _scannerHeaders;
  const res = await fetch(`${BASE}/api/test-scanner-session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ gate_ids: [1, 2, 3, 4, 5, 6, 7] }),
  });
  const body = await res.json().catch(() => null);
  if (!res.ok || !body || !body.ok) {
    throw new ApiError((body && body.error) || "scanner session failed.", res.status);
  }
  _scannerHeaders = { "X-Scanner-Token": body.token };
  return _scannerHeaders;
}

const api = {
  gates: () => request("/api/gates").then((d) => d.gates),
  dashboard: () => request("/api/dashboard"),
  scan: async (input) =>
    request("/api/scan", { method: "POST", body: JSON.stringify(input), headers: await scannerHeaders() }),
  sync: async (items) =>
    request("/api/sync", { method: "POST", body: JSON.stringify({ items }), headers: await scannerHeaders() }),
  demoPayload: () => request("/api/demo-payload"),
  guests: async () =>
    request("/api/guests", { headers: await scannerHeaders() }).then((d) => d.guests),
  registerGuest: async (input) => {
    const res = await fetch(`${BASE}/api/guests`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    const body = await res.json();
    if (!res.ok || !body.ok) throw new ApiError(body.error || "Guest registration failed.", res.status);
    return body;
  },
  // Phase 27 C3: the pass payload is a bearer credential, so reading one
  // rides the scanner session (as the mobile app does) — an anonymous GET
  // from an enumerable gid is refused.
  guestPass: async (gid) =>
    request(`/api/guest-pass/${gid}`, { headers: await scannerHeaders() }),
  testRecords: () => request("/api/test-records").then((d) => d.records),
  broadcasts: () => request("/api/broadcasts").then((d) => d.log),
  sendBroadcast: async (input) => {
    const res = await fetch(`${BASE}/api/broadcasts`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Admin-Pin": ADMIN_PIN },
      body: JSON.stringify(input),
    });
    const body = await res.json();
    if (!res.ok || !body.ok) throw new ApiError(body.error || "Broadcast failed.", res.status);
    return body;
  },
};

function nowStamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function rollFromHint(hint) {
  const m = /\(([^)]+)\)\s*$/.exec(hint || "");
  return m ? m[1] : null;
}

// ---- tests ----

async function main() {
  TEST = resolveTestDb();
  const prodBefore = fileStamp(PRODUCTION_DB);
  console.log("LGU Smart Convocation API test (Phase 35I isolated mode)");
  console.log(`Test database: ${TEST.dbPath}`);
  console.log(`Production database: ${PRODUCTION_DB}`);
  console.log(`Production before: ${prodBefore}\n`);

  try {
    await startTestServer();
    console.log(`Base URL: ${BASE}\n`);

  console.log("Gates");
  let gates;
  try {
    gates = await api.gates();
    check("GET /api/gates returns a non-empty list", Array.isArray(gates) && gates.length > 0, JSON.stringify(gates));
  } catch (e) {
    fail("GET /api/gates", e.message);
    return;
  }
  const gateId = gates[0].id;

  console.log("Demo payload");
  let demo;
  let demoDisabled = false;
  try {
    demo = await api.demoPayload();
  } catch (e) {
    if (e && e.status === 404) {
      // Production correctly hides signed student passes; keep testing safe routes.
      demoDisabled = true;
      demo = { payload: null, hint: "Demo helper disabled." };
      pass("GET /api/demo-payload is disabled");
    } else {
      fail("GET /api/demo-payload", e.message);
      return;
    }
  }
  const studentPayload = demo.payload || null;
  const hostRoll = rollFromHint(demo.hint);
  if (studentPayload) {
    pass(`GET /api/demo-payload returned a payload (${demo.hint})`);
    check("demo hint carries a host roll number", !!hostRoll, demo.hint);
  } else {
    skip("student scan tests", demoDisabled ? "demo QR helper disabled by design" : "every student is already inside");
  }

  console.log("Guest registration");
  const tag = String(Date.now()).slice(-6);
  const guestName = `Test Guest ${tag}`;
  // 33-QA (I22): seeded guests already occupy hosts 101/106/112 — the
  // one-guest-per-host rule now REJECTS those rolls, so the registration
  // proof picks a host the seed leaves free (102 = Muhammad Ahmed).
  const seededHostRolls = ["LGU-2024-101", "LGU-2024-106", "LGU-2024-112"];
  const guestHostRoll = hostRoll && !seededHostRolls.includes(hostRoll)
    ? hostRoll
    : "LGU-2024-102";
  let guest;
  try {
    guest = await api.registerGuest({
      name: guestName,
      phone: `0300${tag}1`.slice(0, 11),
      host_roll_no: guestHostRoll,
    });
    check("POST /api/guests registers a guest", guest.ok === true && !!guest.gid && !!guest.payload, JSON.stringify(guest));
  } catch (e) {
    fail("POST /api/guests", e.message);
  }

  // 33-QA (I22): duplicate identity is rejected at intake — the "one
  // free guest" rule is enforced server-side, not just advertised.
  if (guest) {
    const phone = `0300${tag}1`.slice(0, 11);
    const dupHostRes = await fetch(`${BASE}/api/guests`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: guestName, phone, host_roll_no: guestHostRoll }),
    });
    const dupHostBody = await dupHostRes.json().catch(() => null);
    check("duplicate host registration → 400 (one guest per student)",
      dupHostRes.status === 400 && /already has a guest/.test((dupHostBody || {}).error || ""),
      JSON.stringify(dupHostBody));
    const twinRes = await fetch(`${BASE}/api/guests`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: guestName, phone, host_roll_no: "LGU-2024-103" }),
    });
    const twinBody = await twinRes.json().catch(() => null);
    check("twin identity (same name + phone, other host) → 400",
      twinRes.status === 400 && /name and phone is already registered/.test((twinBody || {}).error || ""),
      JSON.stringify(twinBody));
  } else {
    skip("duplicate identity checks", "guest registration failed");
  }

  console.log("Offline sync");
  if (guest) {
    const items = [
      { payload: guest.payload, gate_id: gateId, mode: "entry", volunteer: "ApiTest", scanned_at: nowStamp() },
    ];
    if (studentPayload) items.push({ payload: studentPayload, gate_id: gateId, mode: "entry", volunteer: "ApiTest", scanned_at: nowStamp() });
    const syncRes = await api.sync(items);
    check("POST /api/sync uploads queued scans", syncRes.synced === items.length, JSON.stringify(syncRes.synced));
    const titles = syncRes.results.map((r) => r.result.title);
    check("sync records the guest entry", titles.includes("GUEST ENTRY RECORDED"), titles.join(", "));
    if (studentPayload) check("sync records the student entry", titles.includes("ENTRY RECORDED"), titles.join(", "));
  } else {
    skip("offline sync", "needs a registered guest");
  }

  console.log("Scan rules");
  if (studentPayload) {
    const dup = await api.scan({ payload: studentPayload, gate_id: gateId, mode: "entry", volunteer: "ApiTest" });
    check("duplicate entry is rejected", dup.level === "red" && dup.title === "ALREADY INSIDE", dup.title);
    check("ALREADY INSIDE carries structured name/gate/time",
      typeof dup.name === "string" && typeof dup.gate === "string" && typeof dup.time === "string",
      JSON.stringify(dup));
    const exit = await api.scan({ payload: studentPayload, gate_id: gateId, mode: "exit", volunteer: "ApiTest" });
    check("exit is recorded", exit.status === "ok" && exit.title === "EXIT RECORDED", exit.title);
    check("valid scan returns name/gate/time/sub",
      !!exit.name && !!exit.gate && typeof exit.time === "string" && typeof exit.sub === "string",
      JSON.stringify(exit));
    const exitAgain = await api.scan({ payload: studentPayload, gate_id: gateId, mode: "exit", volunteer: "ApiTest" });
    check("exit with no active entry is amber", exitAgain.level === "amber" && exitAgain.title === "NOT INSIDE", exitAgain.title);
  } else {
    skip("student scan rules", "no outside student available");
  }

  if (guest) {
    const reuse = await api.scan({ payload: guest.payload, gate_id: gateId, mode: "entry", volunteer: "ApiTest" });
    check("guest pass is single-use", reuse.level === "red" && reuse.title === "ALREADY USED", reuse.title);
    check("ALREADY USED carries structured name/gate/time",
      typeof reuse.name === "string" && typeof reuse.gate === "string" && typeof reuse.time === "string",
      JSON.stringify(reuse));
    const passInfo = await api.guestPass(guest.gid);
    check("GET /api/guest-pass reports the pass as used", passInfo.used === true, JSON.stringify(passInfo.used));
    // 33-QA (I23): the pass payload carries the HOST'S NAME (UI falls
    // back to roll-only when null).
    check("guest pass payload carries the host name",
      typeof passInfo.host_name === "string" && passInfo.host_name.length > 0,
      JSON.stringify(passInfo.host_name));
  } else {
    skip("guest single-use", !hostRoll ? "requires an explicitly enabled demo QR" : "guest registration failed");
  }

  // Scanner Fix Round 1 — deterministic proof through the REAL /api/scan
  // with the seeded records the mobile Test Scan panel uses (same signed
  // payloads, no invented identities). Runs on the isolated test DB.
  console.log("Seeded record proof (Round 1 — valid student / already-used / guest)");
  try {
    const records = await api.testRecords();
    const maleRec = records.find((r) => r.key === "male");
    const guestRec = records.find((r) => r.key === "guest");
    check("test records expose student + guest signed payloads",
      !!maleRec?.payload && !!guestRec?.payload,
      JSON.stringify(records.map((r) => r.key)));
    if (maleRec?.payload) {
      // Pre-flight exit closes any stray entry so the valid-entry proof
      // is deterministic (NOT INSIDE amber when already outside — no write).
      await api.scan({ payload: maleRec.payload, gate_id: gateId, mode: "exit", volunteer: "Round1Proof" });
      const ok = await api.scan({ payload: maleRec.payload, gate_id: gateId, mode: "entry", volunteer: "Round1Proof" });
      check("valid student → ENTRY RECORDED green + seeded identity (LGU-2024-102)",
        ok.status === "ok" && ok.level === "green" && ok.title === "ENTRY RECORDED" &&
          ok.name === "Muhammad Ahmed" && typeof ok.sub === "string" && ok.sub.includes("LGU-2024-102"),
        JSON.stringify(ok));
      const second = await api.scan({ payload: maleRec.payload, gate_id: gateId, mode: "entry", volunteer: "Round1Proof" });
      check("duplicate student → ALREADY INSIDE red + structured name/gate/time",
        second.status === "error" && second.level === "red" && second.title === "ALREADY INSIDE" &&
          second.name === "Muhammad Ahmed" && typeof second.gate === "string" && typeof second.time === "string",
        JSON.stringify(second));
    } else {
      skip("seeded student proof", "male test record unavailable");
    }
    if (guestRec?.payload) {
      const g = await api.scan({ payload: guestRec.payload, gate_id: gateId, mode: "entry", volunteer: "Round1Proof" });
      check("guest pass → GUEST ENTRY RECORDED green + host sub",
        g.status === "ok" && g.level === "green" && g.title === "GUEST ENTRY RECORDED" &&
          !!g.name && typeof g.sub === "string" && g.sub.startsWith("Guest of "),
        JSON.stringify(g));
    } else {
      skip("seeded guest proof", "guest test record unavailable");
    }
  } catch (e) {
    fail("seeded record proof", e.message);
  }

  const forged = await api.scan({ payload: "LGU1-FORGED00", gate_id: gateId, mode: "entry", volunteer: "ApiTest" });
  check("forged payload is rejected", forged.level === "red" && forged.title === "INVALID CODE", forged.title);

  console.log("Dashboard");
  const dash = await api.dashboard();
  check("inside_total is a number", typeof dash.inside_total === "number", String(dash.inside_total));
  if (guest) {
    check("guests_inside counts the synced guest", dash.guests_inside >= 1, String(dash.guests_inside));
  } else {
    check("guests_inside is a nonnegative number", typeof dash.guests_inside === "number" && dash.guests_inside >= 0, String(dash.guests_inside));
  }
  check("throughput covers every gate", Array.isArray(dash.throughput) && dash.throughput.length === gates.length, String(dash.throughput.length));
  check("feed is a list", Array.isArray(dash.feed), typeof dash.feed);
  check("busiest_gate is present", typeof dash.busiest_gate === "string" && dash.busiest_gate.length > 0, String(dash.busiest_gate));

  console.log("Guests list");
  const guestList = await api.guests();
  check("GET /api/guests lists the new guest", guestList.some((g) => g.name === guestName), `count=${guestList.length}`);
  // 33-QA (I23): guest rows carry the host's roster NAME alongside the roll.
  const newRow = guestList.find((g) => g.name === guestName);
  check("guest row carries the host name (not roll alone)",
    !!newRow && typeof newRow.host_name === "string" && newRow.host_name.length > 0,
    JSON.stringify(newRow && newRow.host_name));

  // 33-QA P7 regression pin: /api/search must answer a guest query with
  // 200 + results carrying the host name. The P7 JOIN fix initially used
  // sqlite3.Row.get() (no such method) and crashed search with a 500 —
  // this end-to-end check pins the endpoint against that class of bug.
  // Phase 34 Part D: the lookup is scanner-gated, so it rides the session.
  const anonSearchRes = await fetch(`${BASE}/api/search?q=${encodeURIComponent(guestName)}`);
  check("GET /api/search without a scanner session is refused 401",
    anonSearchRes.status === 401, `status=${anonSearchRes.status}`);
  const searchRes = await fetch(`${BASE}/api/search?q=${encodeURIComponent(guestName)}`, {
    headers: await scannerHeaders(),
  });
  const searchBody = await searchRes.json().catch(() => null);
  const guestHit = searchBody?.results?.find((r) => r.type === "guest" && r.name === guestName);
  check("GET /api/search answers a guest query with 200 + results",
    searchRes.status === 200 && !!searchBody && searchBody.ok === true && Array.isArray(searchBody.results),
    `status=${searchRes.status}`);
  check("search guest hit carries the host name",
    !!guestHit && typeof guestHit.host_name === "string" && guestHit.host_name.length > 0,
    JSON.stringify(guestHit && guestHit.host_name));
  check("search results never return the qr_id bearer credential",
    !JSON.stringify(searchBody?.results ?? []).includes("qr_id"));

  console.log("Broadcasts");
  const marker = `API test ${nowStamp()}`;

  // Phase 35G: POST /api/broadcasts now requires X-Admin-Pin; verify the
  // gate and the /api/admin/verify endpoint before the happy path.
  const noPinRes = await fetch(`${BASE}/api/broadcasts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audience: "All students", message: marker, sent_by: "ApiTest" }),
  });
  const noPinBody = await noPinRes.json().catch(() => null);
  check("POST /api/broadcasts without PIN is rejected 401",
    noPinRes.status === 401 && !!noPinBody && noPinBody.ok === false, `status=${noPinRes.status}`);

  const badPinRes = await fetch(`${BASE}/api/admin/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin: "0000" }),
  });
  check("POST /api/admin/verify rejects a wrong PIN", badPinRes.status === 401, `status=${badPinRes.status}`);

  const goodPinRes = await fetch(`${BASE}/api/admin/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin: ADMIN_PIN }),
  });
  const goodPinBody = await goodPinRes.json().catch(() => null);
  check("POST /api/admin/verify accepts the correct PIN",
    goodPinRes.status === 200 && !!goodPinBody && goodPinBody.ok === true, `status=${goodPinRes.status}`);

  const sent = await api.sendBroadcast({ audience: "All students", message: marker, sent_by: "ApiTest" });
  check("POST /api/broadcasts is accepted with the PIN header", sent.ok === true, JSON.stringify(sent));
  check("response carries the demo-mode note", typeof sent.note === "string" && /demo mode/i.test(sent.note), sent.note);
  const log = await api.broadcasts();
  check("GET /api/broadcasts log contains the message", log.some((b) => b.message === marker), `log=${log.length}`);

  // ---- Phase 35K: dynamic config + PIN gates + audience --------------------
  console.log("35K — /api/config, PIN gates, broadcast audience");
  const cfgRes = await fetch(`${BASE}/api/config`);
  const cfgBody = await cfgRes.json().catch(() => null);
  check("GET /api/config responds with event + population + limits",
    cfgRes.status === 200 && !!cfgBody && !!cfgBody.event &&
    typeof cfgBody.student_roster_count === "number" &&
    typeof cfgBody.announcement_audience_count === "number" &&
    typeof cfgBody.expected_attendance === "number" &&
    typeof cfgBody.broadcast_mode === "string" &&
    Array.isArray(cfgBody.gates),
    JSON.stringify(cfgBody && Object.keys(cfgBody)));
  check("config audience (all) equals roster count by rule",
    !!cfgBody && cfgBody.announcement_audience_count === cfgBody.student_roster_count,
    `audience=${cfgBody && cfgBody.announcement_audience_count}`);

  const settingsNoPin = await fetch(`${BASE}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ venue: "Should Not Save" }),
  });
  check("PUT /api/settings without PIN is rejected 401", settingsNoPin.status === 401,
    `status=${settingsNoPin.status}`);

  const firstGate = (cfgBody && cfgBody.gates && cfgBody.gates[0]) || null;
  if (firstGate) {
    const renameNoPin = await fetch(`${BASE}/api/gates/${firstGate.id}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: "Should Not Rename" }),
    });
    check("POST /api/gates/<id>/rename without PIN is rejected 401",
      renameNoPin.status === 401, `status=${renameNoPin.status}`);
  }

  const audRes = await fetch(`${BASE}/api/broadcast/audience`);
  const audBody = await audRes.json().catch(() => null);
  check("GET /api/broadcast/audience returns count + basis",
    audRes.status === 200 && !!audBody && audBody.ok === true &&
    typeof audBody.count === "number" && /roster/.test(audBody.basis || ""),
    JSON.stringify(audBody));
  // 33-QA (I15): no gates → an honest EMPTY per_gate list — never a
  // fabricated breakdown for an audience that has no gate story.
  check("audience without gates carries an empty per_gate list",
    Array.isArray(audBody.per_gate) && audBody.per_gate.length === 0,
    JSON.stringify(audBody && audBody.per_gate));

  console.log(`\nDone: ${failures} failure(s), ${skipped} skipped.`);
    process.exitCode = failures > 0 ? 1 : 0;
  } finally {
    await stopTestServer();
    const prodAfter = fileStamp(PRODUCTION_DB);
    console.log(`\nProduction database after: ${prodAfter}`);
    console.log(
      prodBefore === prodAfter
        ? "Production DB unchanged by tests."
        : "WARNING: production DB changed during the test run!",
    );
    if (TEST.temp) {
      // Windows may briefly hold the SQLite file after the server exits;
      // retry a few times so teardown is reliable, not racy.
      let removed = false;
      for (let i = 0; i < 5 && !removed; i++) {
        try {
          fs.rmSync(TEST.dir, { recursive: true, force: true });
          removed = true;
        } catch {
          Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 200);
        }
      }
      if (removed) console.log("Test database removed.");
      else console.log(`WARNING: could not remove test dir ${TEST.dir}`);
    }
  }
}

main()
  .then(() => process.exit(process.exitCode ?? 0))
  .catch((e) => {
    console.error("Fatal:", e && e.message ? e.message : e);
    process.exit(2);
  });
