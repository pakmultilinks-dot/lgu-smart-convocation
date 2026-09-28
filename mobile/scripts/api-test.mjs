#!/usr/bin/env node
/**
 * Integration test for the LGU Smart Convocation Flask backend.
 *
 * This script is the logic equivalent of mobile/src/api/client.ts: the same
 * typed request helpers, the same endpoints, the same expectations. It runs
 * against the real backend:
 *
 *   cd ~/workspace/lgu-smart-entry/app && python3 run.py
 *   node scripts/api-test.mjs [baseUrl]
 *
 * Exit code 0 means every test passed, non-zero means at least one failed.
 */

const BASE = (process.argv[2] || process.env.API_BASE || "http://localhost:5000").replace(/\/+$/, "");

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

const api = {
  gates: () => request("/api/gates").then((d) => d.gates),
  dashboard: () => request("/api/dashboard"),
  scan: (input) => request("/api/scan", { method: "POST", body: JSON.stringify(input) }),
  sync: (items) => request("/api/sync", { method: "POST", body: JSON.stringify({ items }) }),
  demoPayload: () => request("/api/demo-payload"),
  guests: () => request("/api/guests").then((d) => d.guests),
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
  guestPass: (gid) => request(`/api/guest-pass/${gid}`),
  broadcasts: () => request("/api/broadcasts").then((d) => d.log),
  sendBroadcast: async (input) => {
    const res = await fetch(`${BASE}/api/broadcasts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
  console.log(`LGU Smart Convocation API test\nBase URL: ${BASE}\n`);

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
  const demo = await api.demoPayload();
  const studentPayload = demo.payload || null;
  const hostRoll = rollFromHint(demo.hint);
  if (studentPayload) {
    pass(`GET /api/demo-payload returned a payload (${demo.hint})`);
    check("demo hint carries a host roll number", !!hostRoll, demo.hint);
  } else {
    skip("student scan tests", "every student is already inside");
  }

  console.log("Guest registration");
  const tag = String(Date.now()).slice(-6);
  const guestName = `Test Guest ${tag}`;
  let guest;
  try {
    guest = await api.registerGuest({
      name: guestName,
      phone: `0300${tag}1`.slice(0, 11),
      host_roll_no: hostRoll || "UNKNOWN",
    });
    check("POST /api/guests registers a guest", guest.ok === true && !!guest.gid && !!guest.payload, JSON.stringify(guest));
  } catch (e) {
    fail("POST /api/guests", e.message);
  }

  console.log("Offline sync");
  if (studentPayload && guest) {
    const syncRes = await api.sync([
      { payload: guest.payload, gate_id: gateId, mode: "entry", volunteer: "ApiTest", scanned_at: nowStamp() },
      { payload: studentPayload, gate_id: gateId, mode: "entry", volunteer: "ApiTest", scanned_at: nowStamp() },
    ]);
    check("POST /api/sync uploads 2 queued scans", syncRes.synced === 2, JSON.stringify(syncRes.synced));
    const titles = syncRes.results.map((r) => r.result.title);
    check("sync records the guest entry", titles.includes("GUEST ENTRY RECORDED"), titles.join(", "));
    check("sync records the student entry", titles.includes("ENTRY RECORDED"), titles.join(", "));
  } else {
    skip("offline sync", "needs a student payload and a registered guest");
  }

  console.log("Scan rules");
  if (studentPayload) {
    const dup = await api.scan({ payload: studentPayload, gate_id: gateId, mode: "entry", volunteer: "ApiTest" });
    check("duplicate entry is rejected", dup.level === "red" && dup.title === "ALREADY INSIDE", dup.title);
    const exit = await api.scan({ payload: studentPayload, gate_id: gateId, mode: "exit", volunteer: "ApiTest" });
    check("exit is recorded", exit.status === "ok" && exit.title === "EXIT RECORDED", exit.title);
    const exitAgain = await api.scan({ payload: studentPayload, gate_id: gateId, mode: "exit", volunteer: "ApiTest" });
    check("exit with no active entry is amber", exitAgain.level === "amber" && exitAgain.title === "NOT INSIDE", exitAgain.title);
  } else {
    skip("student scan rules", "no outside student available");
  }

  if (guest) {
    const reuse = await api.scan({ payload: guest.payload, gate_id: gateId, mode: "entry", volunteer: "ApiTest" });
    check("guest pass is single-use", reuse.level === "red" && reuse.title === "ALREADY USED", reuse.title);
    const passInfo = await api.guestPass(guest.gid);
    check("GET /api/guest-pass reports the pass as used", passInfo.used === true, JSON.stringify(passInfo.used));
  } else {
    skip("guest single-use", "guest registration failed");
  }

  const forged = await api.scan({ payload: "LGU1-FORGED00", gate_id: gateId, mode: "entry", volunteer: "ApiTest" });
  check("forged payload is rejected", forged.level === "red" && forged.title === "INVALID CODE", forged.title);

  console.log("Dashboard");
  const dash = await api.dashboard();
  check("inside_total is a number", typeof dash.inside_total === "number", String(dash.inside_total));
  check("guests_inside counts the synced guest", dash.guests_inside >= 1, String(dash.guests_inside));
  check("throughput covers every gate", Array.isArray(dash.throughput) && dash.throughput.length === gates.length, String(dash.throughput.length));
  check("feed is a list", Array.isArray(dash.feed), typeof dash.feed);
  check("busiest_gate is present", typeof dash.busiest_gate === "string" && dash.busiest_gate.length > 0, String(dash.busiest_gate));

  console.log("Guests list");
  const guestList = await api.guests();
  check("GET /api/guests lists the new guest", guestList.some((g) => g.name === guestName), `count=${guestList.length}`);

  console.log("Broadcasts");
  const marker = `API test ${nowStamp()}`;
  const sent = await api.sendBroadcast({ audience: "All students", message: marker, sent_by: "ApiTest" });
  check("POST /api/broadcasts is accepted", sent.ok === true, JSON.stringify(sent));
  check("response carries the demo-mode note", typeof sent.note === "string" && /demo mode/i.test(sent.note), sent.note);
  const log = await api.broadcasts();
  check("GET /api/broadcasts log contains the message", log.some((b) => b.message === marker), `log=${log.length}`);

  console.log(`\nDone: ${failures} failure(s), ${skipped} skipped.`);
  process.exit(failures > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error("Fatal:", e && e.message ? e.message : e);
  process.exit(2);
});
