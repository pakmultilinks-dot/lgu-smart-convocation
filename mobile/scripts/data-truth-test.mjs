#!/usr/bin/env node
/**
 * Phase 35K — Data truth + dynamic configuration + identity integrity.
 *
 * Server-level proof on an ISOLATED temp database (Phase 35I pattern: the
 * production app/lgu.db stamp is captured before and after every server
 * boot and must be byte-identical). Two Flask instances are booted:
 *
 *   Server 1 (default env → broadcast_mode "demo"):
 *     1. /api/config structure + population truth (roster vs target)
 *     2. REQUIRED PROOF: attendance 2500→2800 via PUT + PIN
 *     3. REQUIRED PROOF: event metadata change (name/venue/university)
 *     4. REQUIRED PROOF: gate rename via POST + PIN
 *     5. Broadcast audience stays roster-based through settings changes
 *     6. Sync idempotency (ALREADY SYNCED) + original timestamp preserved
 *     7. Guest reuse rules (single-use → ALREADY USED)
 *     8. Message character limit enforced server-side
 *     9. Admin PIN required on settings PUT and gate rename
 *    10. PIN-less and wrong-PIN requests rejected (401)
 *
 *   Server 2 (LGU_BROADCAST_MODE=real):
 *    11. REQUIRED PROOF: broadcast mode change — /api/config + honest note
 *
 * Usage (from mobile/): node scripts/data-truth-test.mjs
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

let passed = 0;
let failures = 0;

function pass(name) {
  passed += 1;
  console.log(`  PASS  ${name}`);
}
function fail(name, detail) {
  failures += 1;
  console.log(`  FAIL  ${name}${detail ? " - " + detail : ""}`);
}
function check(name, condition, detail) {
  if (condition) pass(name);
  else fail(name, detail);
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
    return `${st.size}:${st.mtimeMs}`;
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
  throw new Error(`Test server not healthy at ${url} within ${timeoutMs}ms.`);
}

const venvPython = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
const python = fs.existsSync(venvPython)
  ? venvPython
  : process.platform === "win32"
    ? "python"
    : "python3";

const ADMIN_PIN = process.env.LGU_ADMIN_PIN || "2026";
const productionStampBefore = fileStamp(PRODUCTION_DB);

/** Boot an isolated Flask on a free port with a fresh temp DB. */
async function startServer(extraEnv = {}) {
  const port = await freePort();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "lgu35k-truth-"));
  const dbPath = path.join(dir, "lgu-truth.db");
  if (dbPath.toLowerCase() === PRODUCTION_DB.toLowerCase()) {
    throw new Error("FATAL: test DB path resolves to the production database.");
  }
  const env = {
    ...process.env,
    LGU_DB_PATH: dbPath,
    LGU_TESTING: "1",
    LGU_PORT: String(port),
    // Throwaway database: opt in to the demo secrets run.py refuses by default.
    LGU_ALLOW_DEMO_SECRETS: "1",
    ...extraEnv,
  };
  const flask = spawn(python, ["run.py"], {
    cwd: APP_DIR,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const logs = [];
  flask.stdout.on("data", (d) => logs.push(String(d)));
  flask.stderr.on("data", (d) => logs.push(String(d)));
  const base = `http://127.0.0.1:${port}`;
  try {
    await waitForHealth(base, 30000);
  } catch (e) {
    console.error(e.message);
    if (logs.length) console.error(logs.join("").slice(-2000));
    flask.kill();
    throw e;
  }
  return { base, flask, logs, dir, dbPath };
}

function stopServer(s) {
  if (s && !s.flask.killed) {
    try {
      s.flask.kill();
    } catch {
      /* gone */
    }
  }
  if (s && s.dir) {
    // Windows: flask.kill() returns before the child fully releases the
    // SQLite handle, so the immediate rmSync can hit a transient EPERM.
    // Retrying (Node retries only EPERM/EBUSY/ENOTEMPTY) lets the dying
    // process finish; this is cleanup-only and cannot mask an assertion.
    try {
      fs.rmSync(s.dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    } catch {
      /* best-effort temp cleanup */
    }
  }
}

async function api(base, method, pth, { pin, body, scanner } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (pin !== undefined) headers["X-Admin-Pin"] = pin;
  if (scanner) headers["X-Scanner-Token"] = await scannerToken(base);
  const res = await fetch(base + pth, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(8000),
  });
  const json = await res.json().catch(() => null);
  return { status: res.status, json };
}

let server1 = null;
let server2 = null;

// Phase 14: /api/scan and /api/sync require an authenticated scanner. Mint a
// random synthetic token per server base (guarded test helper, never prod).
const _scannerTokens = new Map();
async function scannerToken(base) {
  if (_scannerTokens.has(base)) return _scannerTokens.get(base);
  const res = await fetch(base + "/api/test-scanner-session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ gate_ids: [1, 2, 3, 4, 5, 6, 7] }),
    signal: AbortSignal.timeout(8000),
  });
  const body = await res.json().catch(() => null);
  if (!res.ok || !body || !body.ok) throw new Error("scanner session failed.");
  _scannerTokens.set(base, body.token);
  return body.token;
}

try {
  console.log("Phase 35K data-truth test (isolated temp DB, production untouched)");
  console.log(`Production DB: ${PRODUCTION_DB}\n`);

  // ================================================================ server 1
  console.log("Server 1 — default env (broadcast_mode demo)");
  server1 = await startServer();
  const B1 = server1.base;

  // ---- 1. /api/config structure + population truth ------------------------
  const cfg0 = await api(B1, "GET", "/api/config");
  check("GET /api/config responds 200", cfg0.status === 200 && !!cfg0.json);
  const cfg = cfg0.json || {};
  check("config exposes event identity block",
    !!cfg.event && typeof cfg.event.name === "string" &&
    typeof cfg.event.year === "string" && typeof cfg.event.venue === "string");
  check("config exposes distinct population concepts",
    typeof cfg.student_roster_count === "number" &&
    typeof cfg.announcement_audience_count === "number" &&
    typeof cfg.expected_attendance === "number" &&
    typeof cfg.attendance_set === "boolean" &&
    typeof cfg.guest_registrations === "number");
  check("roster count > 0 on the seeded test DB", cfg.student_roster_count > 0,
    `roster=${cfg.student_roster_count}`);
  check("announcement audience (all) equals roster count by rule",
    cfg.announcement_audience_count === cfg.student_roster_count,
    `audience=${cfg.announcement_audience_count} roster=${cfg.student_roster_count}`);
  check("config exposes gates, broadcast_mode and shared limits",
    Array.isArray(cfg.gates) && cfg.gates.length > 0 &&
    (cfg.broadcast_mode === "demo" || cfg.broadcast_mode === "real") &&
    cfg.gate_activity_window_minutes > 0 && cfg.message_char_limit > 0);
  const seedExpected = cfg.expected_attendance;
  const rosterBefore = cfg.student_roster_count;
  const audienceBefore = cfg.announcement_audience_count;
  // The seed default for expected_attendance is 0 (unset); production's
  // 2500 was set by the administrator. Mirror that: establish 2500 first.
  check("seeded test DB starts at the seed default (0 = unset, honest)",
    seedExpected === 0, `seed=${seedExpected}`);

  // ---- 9/10. PIN gates on settings PUT ------------------------------------
  const noPin = await api(B1, "PUT", "/api/settings", {
    body: { expected_attendance: "2800" },
  });
  check("settings PUT without PIN → 401", noPin.status === 401,
    `status=${noPin.status}`);
  const badPin = await api(B1, "PUT", "/api/settings", {
    pin: "0000", body: { expected_attendance: "2800" },
  });
  check("settings PUT with wrong PIN → 401", badPin.status === 401,
    `status=${badPin.status}`);
  // 33-QA (I24): values beyond convocation scale are rejected, not stored.
  const overCap = await api(B1, "PUT", "/api/settings", {
    pin: ADMIN_PIN, body: { expected_attendance: "30000" },
  });
  check("settings PUT over the 25,000 cap → 400",
    overCap.status === 400, `status=${overCap.status} ${JSON.stringify(overCap.json)}`);

  // ---- 2. REQUIRED PROOF: attendance 2500→2800 ---------------------------
  console.log("\nREQUIRED PROOF — attendance target 2500 → 2800");
  // Establish the production-equivalent baseline (2500) via the same
  // admin path an operator would use, then prove the change to 2800.
  const putBase = await api(B1, "PUT", "/api/settings", {
    pin: ADMIN_PIN, body: { expected_attendance: "2500" },
  });
  check("baseline PUT establishes expected_attendance 2500 (production state)",
    putBase.status === 200 &&
    String((putBase.json || {}).expected_attendance) === "2500",
    JSON.stringify(putBase.json));
  const cfgBase = (await api(B1, "GET", "/api/config")).json;
  check("/api/config reports the 2500 baseline before the proof change",
    cfgBase && cfgBase.expected_attendance === 2500 &&
    cfgBase.attendance_set === true,
    `got=${cfgBase && cfgBase.expected_attendance}`);
  const put = await api(B1, "PUT", "/api/settings", {
    pin: ADMIN_PIN, body: { expected_attendance: "2800" },
  });
  check("settings PUT with PIN succeeds", put.status === 200,
    `status=${put.status} ${JSON.stringify(put.json)}`);
  check("settings response carries expected_attendance=2800",
    put.json && String(put.json.expected_attendance) === "2800",
    JSON.stringify(put.json && put.json.expected_attendance));
  const cfg1 = (await api(B1, "GET", "/api/config")).json;
  check("/api/config now reports expected_attendance 2800",
    cfg1 && cfg1.expected_attendance === 2800,
    `got=${cfg1 && cfg1.expected_attendance}`);
  check("attendance_set stays true after change",
    cfg1 && cfg1.attendance_set === true);
  check("roster count UNCHANGED by target change (2500→2800 is not a roster claim)",
    cfg1 && cfg1.student_roster_count === rosterBefore,
    `roster before=${rosterBefore} after=${cfg1 && cfg1.student_roster_count}`);
  const summary1 = (await api(B1, "GET", "/api/dashboard/summary")).json;
  check("dashboard summary mirrors the new target",
    summary1 && summary1.expected_attendance === 2800,
    `got=${summary1 && summary1.expected_attendance}`);
  check("dashboard summary carries attendance_set + roster count",
    summary1 && summary1.attendance_set === true &&
    summary1.student_roster_count === rosterBefore);
  const aud1 = (await api(B1, "GET", "/api/broadcast/audience")).json;
  check("broadcast audience (all) still roster-based after target change",
    aud1 && aud1.count === rosterBefore && aud1.count === audienceBefore &&
    /roster/.test(aud1.basis || ""),
    JSON.stringify(aud1));

  // ---- 3. REQUIRED PROOF: event metadata change ---------------------------
  console.log("\nREQUIRED PROOF — event metadata change");
  const meta = await api(B1, "PUT", "/api/settings", {
    pin: ADMIN_PIN,
    body: {
      convocation_name: "Test Convocation Renamed",
      venue: "Test Venue Hall",
      university_name: "Test University",
    },
  });
  check("event metadata PUT succeeds", meta.status === 200,
    `status=${meta.status}`);
  const cfg2 = (await api(B1, "GET", "/api/config")).json;
  check("/api/config reflects renamed event",
    cfg2 && cfg2.event.name === "Test Convocation Renamed",
    `got=${cfg2 && cfg2.event.name}`);
  check("/api/config reflects renamed venue",
    cfg2 && cfg2.event.venue === "Test Venue Hall");
  check("/api/config reflects renamed university",
    cfg2 && cfg2.university === "Test University",
    `got=${cfg2 && cfg2.university}`);

  // ---- 4. REQUIRED PROOF: gate rename -------------------------------------
  console.log("\nREQUIRED PROOF — gate rename");
  const firstGate = cfg.gates[0];
  const renameNoPin = await api(B1, "POST", `/api/gates/${firstGate.id}/rename`, {
    body: { label: "Should Fail" },
  });
  check("gate rename without PIN → 401", renameNoPin.status === 401,
    `status=${renameNoPin.status}`);
  const rename = await api(B1, "POST", `/api/gates/${firstGate.id}/rename`, {
    pin: ADMIN_PIN, body: { label: "RENAMED GATE PROOF" },
  });
  check("gate rename with PIN succeeds", rename.status === 200 &&
    rename.json && rename.json.ok === true, JSON.stringify(rename.json));
  const cfg3 = (await api(B1, "GET", "/api/config")).json;
  const renamedGate = (cfg3.gates || []).find((g) => g.id === firstGate.id);
  check("/api/config serves the renamed gate label",
    renamedGate && renamedGate.label === "RENAMED GATE PROOF",
    JSON.stringify(renamedGate));
  const audGate = await api(B1, "GET", `/api/broadcast/audience?gates=${firstGate.id}`);
  check("per-gate audience derives from scan history with honest basis",
    audGate.status === 200 && audGate.json && audGate.json.ok === true &&
    /inside at the selected gates/.test(audGate.json.basis || "") &&
    typeof audGate.json.count === "number" && audGate.json.count >= 0,
    JSON.stringify(audGate.json));
  // 33-QA (I15): one selected gate → one per_gate row mirroring the
  // total, carrying the REAL (renamed) gate label — never fabricated.
  const pg1 = Array.isArray(audGate.json && audGate.json.per_gate)
    ? audGate.json.per_gate : null;
  check("per_gate: single row mirrors the total with the real gate label",
    pg1 !== null && pg1.length === 1 && pg1[0].id === firstGate.id &&
    pg1[0].label === renamedGate.label && pg1[0].count === audGate.json.count,
    JSON.stringify(pg1));
  // 33-QA (I15): multi-gate query → ordered breakdown (count DESC, ties
  // label ASC) covering every selected gate exactly once.
  const twoIds = (cfg3.gates || []).slice(0, 2).map((g) => g.id);
  if (twoIds.length === 2) {
    const audTwo = await api(B1, "GET", `/api/broadcast/audience?gates=${twoIds.join(",")}`);
    const pg2 = Array.isArray(audTwo.json && audTwo.json.per_gate)
      ? audTwo.json.per_gate : null;
    const ordered = pg2 ? pg2.every((g, i) =>
      i === 0 || pg2[i - 1].count > g.count ||
      (pg2[i - 1].count === g.count && pg2[i - 1].label <= g.label)) : false;
    check("per_gate: two gates → ordered count DESC (ties label ASC), full coverage",
      audTwo.status === 200 && pg2 && pg2.length === 2 && ordered &&
      pg2.every((g) => twoIds.includes(g.id)),
      JSON.stringify(pg2));
  }
  const audBad = await api(B1, "GET", "/api/broadcast/audience?gates=99999");
  check("unknown gate id in audience query → 400", audBad.status === 400,
    `status=${audBad.status}`);

  // ---- 5/6. Sync idempotency + timestamp preservation ---------------------
  console.log("\nSync idempotency + original timestamp preserved");
  const records = (await api(B1, "GET", "/api/test-records")).json;
  const male = (records.records || []).find((r) => r.key === "male");
  const female = (records.records || []).find((r) => r.key === "female");
  const guestRec = (records.records || []).find((r) => r.key === "guest");
  check("test records available (male + female + guest)",
    !!male && !!female && !!guestRec,
    JSON.stringify((records.records || []).map((r) => r.key)));
  const originalStamp = "2026-01-01T10:00:00";
  const queuedItem = {
    payload: male.payload, gate_id: firstGate.id, mode: "entry",
    volunteer: "DataTruth", scanned_at: originalStamp,
  };
  const sync1 = await api(B1, "POST", "/api/sync", { scanner: true, body: { items: [queuedItem] } });
  check("first sync records the queued entry",
    sync1.status === 200 && sync1.json &&
    (sync1.json.results || [])[0]?.result?.title === "ENTRY RECORDED",
    JSON.stringify(sync1.json));
  const sync2 = await api(B1, "POST", "/api/sync", { scanner: true, body: { items: [queuedItem] } });
  check("identical re-sync → ALREADY SYNCED (no double count)",
    sync2.status === 200 && sync2.json &&
    (sync2.json.results || [])[0]?.result?.title === "ALREADY SYNCED",
    JSON.stringify(sync2.json));
  check("duplicate sync reports zero new rows",
    sync2.json && sync2.json.synced === 0, `synced=${sync2.json && sync2.json.synced}`);
  const dash = (await api(B1, "GET", "/api/dashboard")).json;
  const feed = (dash && dash.feed) || [];
  // Feed rows are scan-table records (qr_id, volunteer, scanned_at) —
  // the queued entry is the only scan at this point; match on timestamp.
  const queuedFeed = feed.find((f) =>
    String(f.scanned_at || "").startsWith(originalStamp));
  check("dashboard feed preserves the ORIGINAL client timestamp",
    queuedFeed ? String(queuedFeed.scanned_at).startsWith(originalStamp) : false,
    JSON.stringify(queuedFeed));

  // ---- 7. Guest reuse rules -----------------------------------------------
  console.log("\nGuest reuse rules (single-use pass)");
  // Host roll number comes from a STUDENT record label — "Name (LGU-2024-102)"
  // — the guest record's label is "Name (guest pass)" and carries no roll.
  const hostRoll = String((male && male.label) || "").match(/\(([^)]+)\)/)?.[1] || "";
  check("guest host roll number parsed from student test record",
    /^LGU-\d{4}-\d{3}$/.test(hostRoll), hostRoll);
  const reg = await api(B1, "POST", "/api/guests", {
    body: { name: "Truth Test Guest", phone: "03000000000", host_roll_no: hostRoll },
  });
  check("guest registration succeeds on isolated DB", reg.status === 200 &&
    reg.json && reg.json.ok === true, JSON.stringify(reg.json));
  // 33-QA (I22): a second pass for the SAME host is rejected at intake.
  const dupReg = await api(B1, "POST", "/api/guests", {
    body: { name: "Truth Test Guest Twin", phone: "03000000000", host_roll_no: hostRoll },
  });
  check("duplicate host registration rejected (one guest per student)",
    dupReg.status === 400 && /already has a guest/.test((dupReg.json || {}).error || ""),
    JSON.stringify(dupReg.json));
  // 33-QA (I23): guest rows carry the host's roster name (not roll alone).
  // Phase 26C: the roster is scanner-gated (phone PII); send the session.
  const gRows = ((await api(B1, "GET", "/api/guests", { scanner: true })).json || {}).guests || [];
  const row1 = gRows.find((g) => g.name === "Truth Test Guest");
  check("guest row carries the host roster name",
    !!row1 && typeof row1.host_name === "string" && row1.host_name.length > 0,
    JSON.stringify(row1 && row1.host_name));
  const guestPayload = reg.json && reg.json.payload;
  const gScan1 = await api(B1, "POST", "/api/scan", {
    scanner: true, body: { payload: guestPayload, gate_id: firstGate.id, mode: "entry", volunteer: "DataTruth" },
  });
  check("guest entry scan records once", gScan1.status === 200 && gScan1.json &&
    /GUEST ENTRY RECORDED/.test(gScan1.json.title || ""), JSON.stringify(gScan1.json));
  const gScan2 = await api(B1, "POST", "/api/scan", {
    scanner: true, body: { payload: guestPayload, gate_id: firstGate.id, mode: "entry", volunteer: "DataTruth" },
  });
  check("reused guest pass → ALREADY USED", gScan2.status === 200 && gScan2.json &&
    gScan2.json.title === "ALREADY USED", JSON.stringify(gScan2.json));

  // Online student flow sanity (entry → duplicate → exit), female payload.
  const sScan1 = await api(B1, "POST", "/api/scan", {
    scanner: true, body: { payload: female.payload, gate_id: firstGate.id, mode: "entry", volunteer: "DataTruth" },
  });
  check("student online entry records", sScan1.json && /ENTRY RECORDED/.test(sScan1.json.title || ""),
    JSON.stringify(sScan1.json));
  const sScan2 = await api(B1, "POST", "/api/scan", {
    scanner: true, body: { payload: female.payload, gate_id: firstGate.id, mode: "entry", volunteer: "DataTruth" },
  });
  check("duplicate student entry rejected server-side", sScan2.json &&
    /ALREADY/.test(sScan2.json.title || ""), JSON.stringify(sScan2.json));
  const sScan3 = await api(B1, "POST", "/api/scan", {
    scanner: true, body: { payload: female.payload, gate_id: firstGate.id, mode: "exit", volunteer: "DataTruth" },
  });
  check("student exit after entry records", sScan3.json &&
    /EXIT RECORDED/.test(sScan3.json.title || ""), JSON.stringify(sScan3.json));

  // ---- 8. Message character limit -----------------------------------------
  console.log("\nMessage character limit (server-enforced)");
  const longMsg = "x".repeat((cfg.message_char_limit || 160) + 1);
  const limit = await api(B1, "POST", "/api/broadcasts", {
    pin: ADMIN_PIN, body: { audience: "All students", message: longMsg, sent_by: "DataTruth" },
  });
  check("over-limit broadcast → 400 with limit stated",
    limit.status === 400 && /limited to 160/.test((limit.json && limit.json.error) || ""),
    JSON.stringify(limit.json));
  const shortMsg = "Phase 35K truth proof broadcast.";
  const bc = await api(B1, "POST", "/api/broadcasts", {
    pin: ADMIN_PIN, body: { audience: "All students", message: shortMsg, sent_by: "DataTruth" },
  });
  check("in-limit demo broadcast succeeds with honest note",
    bc.status === 200 && bc.json && bc.json.ok === true &&
    /Demo mode: not sent by SMS/.test(bc.json.note || ""),
    JSON.stringify(bc.json));
  const bcNoPin = await api(B1, "POST", "/api/broadcasts", {
    body: { audience: "All students", message: "no pin", sent_by: "X" },
  });
  check("broadcast without PIN → 401", bcNoPin.status === 401,
    `status=${bcNoPin.status}`);

  // Settings sanity: GET round-trips what PUT stored (Phase 28: the read
  // carries the administrator PIN, same as the write).
  const settingsNow = (await api(B1, "GET", "/api/settings", { pin: ADMIN_PIN })).json;
  check("GET /api/settings round-trips stored values",
    settingsNow && String(settingsNow.expected_attendance) === "2800" &&
    settingsNow.university_name === "Test University",
    JSON.stringify(settingsNow));

  // ================================================================ server 2
  console.log("\nServer 2 — LGU_BROADCAST_MODE=real");
  server2 = await startServer({ LGU_BROADCAST_MODE: "real" });
  const B2 = server2.base;
  const cfgReal = (await api(B2, "GET", "/api/config")).json;
  check("REQUIRED PROOF — /api/config reports broadcast_mode=real",
    cfgReal && cfgReal.broadcast_mode === "real",
    `got=${cfgReal && cfgReal.broadcast_mode}`);
  const bcReal = await api(B2, "POST", "/api/broadcasts", {
    pin: ADMIN_PIN, body: { audience: "All students", message: "Real mode proof.", sent_by: "DataTruth" },
  });
  check("real-mode broadcast note is honest (gateway not configured)",
    bcReal.status === 200 && bcReal.json && bcReal.json.ok === true &&
    /Delivery gateway is not configured/.test(bcReal.json.note || ""),
    JSON.stringify(bcReal.json));
  check("real-mode note never claims SMS delivery",
    bcReal.json && !/sent by SMS|delivered/i.test(bcReal.json.note || ""));
} catch (e) {
  failures += 1;
  console.error("FATAL:", e.message);
} finally {
  stopServer(server1);
  stopServer(server2);
}

// ---- production isolation proof -------------------------------------------
const productionStampAfter = fileStamp(PRODUCTION_DB);
check("production database stamp unchanged (temp DBs only)",
  productionStampBefore === productionStampAfter,
  `before=${productionStampBefore} after=${productionStampAfter}`);

console.log(`\ndata-truth-test: ${passed} passed, ${failures} failed`);
process.exit(failures > 0 ? 1 : 0);
