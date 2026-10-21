#!/usr/bin/env node
/**
 * Master release audit — regression suite for the confirmed findings.
 *
 * Boots its OWN isolated Flask instance (free port, disposable SQLite DB,
 * LGU_TESTING=1) and verifies every fix applied for the master audit:
 *
 *   B1-B8   production test/dev endpoints hidden behind is_production_db
 *   V-AUTH-03/04  browser admin surfaces PIN-gated (session unlock)
 *   V-AUTH-01/02  per-IP PIN rate limiting (429 after N wrong attempts)
 *   V-INP-01..04  length caps on settings / broadcast / guest / volunteer
 *   E6      sync items with malformed types no longer 500
 *   F-INP-05 guest-pass ids bounded (no sqlite overflow 500)
 *   V-RACE-01/02/03  concurrent duplicate scans collapse to ONE row
 *   V-CORS-01  wildcard ACAO replaced by an explicit allowlist
 *   V-HEAD-01  nosniff / X-Frame-Options / Referrer-Policy headers
 *
 * The production database (app/lgu.db) is never opened: a size+mtime stamp
 * is taken before and after the run to prove it.
 *
 *   node scripts/master-audit-regression.mjs
 *
 * Exit code 0 = every check passed.
 */

import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const APP_DIR = path.join(REPO_ROOT, "app");
const PRODUCTION_DB = path.resolve(APP_DIR, "lgu.db");

const venvPython = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
const PYTHON = fs.existsSync(venvPython)
  ? venvPython
  : process.platform === "win32"
    ? "python"
    : "python3";

// The isolated backend runs with the documented demo default HMAC secret
// (same as every other battery script); payloads are forged with it.
const HMAC_SECRET = "lgu-convocation-hmac-secret-change-in-production";
const ADMIN_PIN = process.env.LGU_ADMIN_PIN || "2026";

function forge(qrId) {
  const mac = crypto
    .createHmac("sha256", HMAC_SECRET)
    .update(qrId)
    .digest("hex")
    .slice(0, 10);
  return `LGU1:${qrId}:${mac}`;
}

/** Test records carry {key,kind,label,payload}; roll no lives in the
 *  label as "Name (ROLL)", e.g. "Muhammad Ahmed (LGU-2024-102)". */
function rollOf(rec) {
  const m = /\(([^)]+)\)/.exec(rec?.label || "");
  return m ? m[1] : (rec?.roll_no || "");
}

/** scans are keyed by qr_id; signed payloads embed it: LGU1:<qr_id>:<mac>. */
function qrOf(payload) {
  return String(payload || "").split(":")[1] || "";
}

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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "lgu-regress-"));
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

function stopServer(s) {
  if (s && !s.flask.killed) {
    try {
      s.flask.kill();
    } catch {
      /* gone */
    }
  }
}

/** Read-only sqlite query against the disposable DB (via python). */
function queryDb(dbPath, sql) {
  const code = [
    "import sqlite3, json, sys",
    "con = sqlite3.connect('file:' + sys.argv[1].replace('\\\\\\\\', '/') + '?mode=ro', uri=True)",
    "con.row_factory = sqlite3.Row",
    "rows = con.execute(sys.argv[2]).fetchall()",
    "print(json.dumps([dict(r) for r in rows]))",
  ].join("; ");
  const r = spawnSync(PYTHON, ["-c", code, dbPath, sql], {
    encoding: "utf8",
  });
  if (r.status !== 0) {
    throw new Error(`queryDb failed: ${r.stderr}`);
  }
  return JSON.parse(r.stdout.trim());
}

// Phase 14: /api/scan and /api/sync require an authenticated scanner. Mint a
// random synthetic token per server base (guarded test helper, never prod).
const _scannerTokens = new Map();
async function scannerToken(base) {
  if (!_scannerTokens.has(base)) {
    const res = await fetch(`${base}/api/test-scanner-session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ gate_ids: [1, 2, 3, 4, 5, 6, 7] }),
    });
    const body = await res.json().catch(() => null);
    if (!res.ok || !body || !body.ok) throw new Error("scanner session failed.");
    _scannerTokens.set(base, body.token);
  }
  return _scannerTokens.get(base);
}

async function req(base, p, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  // Phase 14: scan/sync are scanner-gated; Phase 26C: so is /api/guests.
  if (p === "/api/scan" || p === "/api/sync" || p === "/api/guests") {
    headers["X-Scanner-Token"] = await scannerToken(base);
  }
  const res = await fetch(`${base}${p}`, {
    method: opts.method || "GET",
    headers,
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

const TEST = resolveTestDb();
const prodStampBefore = fileStamp(PRODUCTION_DB);
let A = null;
let B = null;

async function main() {
  console.log("Master audit regression — isolated backend, disposable DB");
  console.log(`test db: ${TEST.dbPath}`);
  console.log(`production stamp before: ${prodStampBefore}\n`);

  A = await startServer({ LGU_PIN_MAX_FAILS: "50" });
  const base = A.base;
  console.log(`server A (functional): ${base} (PIN limit raised to 50)\n`);

  // ---------------------------------------------------------------- smoke
  const health = await req(base, "/api/health");
  check("health ok", health.json && health.json.ok === true);

  // ------------------------------------------- B1-B3 test endpoint guards
  const tr = await req(base, "/api/test-records");
  check(
    "B1 GET /api/test-records works on isolated backend (200)",
    tr.status === 200 && Array.isArray(tr.json?.records) && tr.json.records.length > 0,
    `status=${tr.status}`,
  );
  const dp = await req(base, "/api/demo-payload");
  check(
    "B3 GET /api/demo-payload works on isolated backend (200)",
    dp.status === 200 && !!dp.json?.payload,
    `status=${dp.status}`,
  );
  // Production-path unit proof: the guard condition itself.
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
    "guard: is_production_db(prod)=True, is_production_db(test temp)=False",
    prodIs === "True" && testIs === "False",
    guardUnit.stdout.trim(),
  );

  // ------------------------------------ V-AUTH-03/04 web admin PIN gate --
  const adminNoPin = await req(base, "/admin", { redirect: "manual" });
  check(
    "V-AUTH-03 GET /admin without session -> 401 unlock page",
    adminNoPin.status === 401 && adminNoPin.text.includes("Admin unlock"),
    `status=${adminNoPin.status}`,
  );
  const vendorNoPin = await req(base, "/admin/vendor.csv", { redirect: "manual" });
  check(
    "V-AUTH-04 GET /admin/vendor.csv without session -> 401 (no CSV)",
    vendorNoPin.status === 401 && !vendorNoPin.text.startsWith("roll_no"),
    `status=${vendorNoPin.status}`,
  );
  const cardsNoPin = await req(base, "/admin/cards", { redirect: "manual" });
  check("GET /admin/cards without session -> 401", cardsNoPin.status === 401, `status=${cardsNoPin.status}`);
  const bcNoPin = await req(base, "/broadcast", { redirect: "manual" });
  check("GET /broadcast without session -> 401", bcNoPin.status === 401, `status=${bcNoPin.status}`);

  const gatesBefore = await req(base, "/api/gates");
  const gate1Label = gatesBefore.json.gates.find((g) => g.id === 1)?.label;
  const renameNoSession = await req(base, "/admin", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "action=rename_gate&gate_id=1&label=Hacked+Gate",
    redirect: "manual",
  });
  const gatesAfterHack = await req(base, "/api/gates");
  const gate1AfterHack = gatesAfterHack.json.gates.find((g) => g.id === 1)?.label;
  check(
    "V-AUTH-03 POST /admin rename without session -> rejected, gate unchanged",
    renameNoSession.status === 401 && gate1AfterHack === gate1Label,
    `status=${renameNoSession.status}, label=${gate1AfterHack}`,
  );

  // Unlock with correct PIN -> session cookie.
  const unlock = await req(base, "/admin", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `admin_pin=${ADMIN_PIN}`,
    redirect: "manual",
  });
  const setCookie = unlock.headers.get("set-cookie") || "";
  const sessionCookie = setCookie.split(";")[0];
  check(
    "unlock with correct PIN -> 200 + session cookie",
    unlock.status === 200 && sessionCookie.startsWith("session="),
    `status=${unlock.status}, cookie=${sessionCookie.slice(0, 20)}...`,
  );
  const authed = { Cookie: sessionCookie };
  const adminWithSession = await req(base, "/admin", { headers: authed, redirect: "manual" });
  check("GET /admin with session -> 200", adminWithSession.status === 200, `status=${adminWithSession.status}`);
  const vendorWithSession = await req(base, "/admin/vendor.csv", { headers: authed });
  check(
    "GET /admin/vendor.csv with session -> 200 CSV",
    vendorWithSession.status === 200 && vendorWithSession.text.startsWith("roll_no"),
    `status=${vendorWithSession.status}`,
  );
  const renameWithSession = await req(base, "/admin", {
    method: "POST",
    headers: { ...authed, "Content-Type": "application/x-www-form-urlencoded" },
    body: "action=rename_gate&gate_id=1&label=Regression+Gate",
    redirect: "manual",
  });
  const gatesRenamed = await req(base, "/api/gates");
  const gate1Renamed = gatesRenamed.json.gates.find((g) => g.id === 1)?.label;
  check(
    "POST /admin rename WITH session -> applied (label verified via API)",
    (renameWithSession.status === 200 || renameWithSession.status === 302) &&
      gate1Renamed === "Regression Gate",
    `status=${renameWithSession.status}, label=${gate1Renamed}`,
  );
  // Restore via API (PIN header) — also proves the API gate still works.
  const restore = await req(base, "/api/gates/1/rename", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Pin": ADMIN_PIN },
    body: JSON.stringify({ label: gate1Label }),
  });
  const gatesRestored = await req(base, "/api/gates");
  check(
    "gate label restored via API with PIN",
    restore.status === 200 &&
      gatesRestored.json.gates.find((g) => g.id === 1)?.label === gate1Label,
  );

  // Web broadcast: GET gated; POST length-capped; short message stored.
  const bcWeb = await req(base, "/broadcast", { headers: authed });
  check("GET /broadcast with session -> 200", bcWeb.status === 200, `status=${bcWeb.status}`);
  const marker = `REGRESSION-BC-${Date.now()}`;
  await req(base, "/broadcast", {
    method: "POST",
    headers: { ...authed, "Content-Type": "application/x-www-form-urlencoded" },
    body: `audience=All+students&sent_by=QA&message=${encodeURIComponent(marker)}`,
  });
  const log1 = await req(base, "/api/broadcasts");
  check(
    "web broadcast (session, <=160 chars) stored",
    (log1.json.log || []).some((b) => b.message === marker),
  );
  const longMsg = "X".repeat(500);
  await req(base, "/broadcast", {
    method: "POST",
    headers: { ...authed, "Content-Type": "application/x-www-form-urlencoded" },
    body: `audience=All+students&sent_by=QA&message=${longMsg}`,
  });
  const log2 = await req(base, "/api/broadcasts");
  check(
    "V-INP-02 web broadcast 500-char message rejected (not stored)",
    !(log2.json.log || []).some((b) => b.message === longMsg),
  );

  // --------------------------------------------- V-INP-01..04 length caps
  const cfgBefore = await req(base, "/api/config");
  const longSetting = "Z".repeat(10000);
  const putLong = await req(base, "/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-Admin-Pin": ADMIN_PIN },
    body: JSON.stringify({ university_name: longSetting }),
  });
  const cfgAfter = await req(base, "/api/config");
  check(
    "V-INP-01 settings PUT 10KB university_name -> 400, value unchanged",
    putLong.status === 400 &&
      cfgAfter.json.university === cfgBefore.json.university &&
      cfgAfter.json.university.length < 200,
    `status=${putLong.status}, value=${cfgAfter.json.university?.slice(0, 40)}`,
  );
  const bcLong = await req(base, "/api/broadcasts", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Pin": ADMIN_PIN },
    body: JSON.stringify({ message: "B".repeat(5000) }),
  });
  check(
    "V-INP-02 API broadcast 5000-char message -> 400",
    bcLong.status === 400,
    `status=${bcLong.status}`,
  );
  const bcAudLong = await req(base, "/api/broadcasts", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Pin": ADMIN_PIN },
    body: JSON.stringify({ message: "ok-aud", audience: "A".repeat(5000) }),
  });
  const log3 = await req(base, "/api/broadcasts");
  const audStored = (log3.json.log || []).find((b) => b.message === "ok-aud");
  check(
    "V-INP-02 API broadcast 5000-char audience -> bounded to <=64 chars",
    bcAudLong.status === 200 &&
      !!audStored &&
      (audStored.audience || "").length <= 64,
    `status=${bcAudLong.status}, stored_len=${(audStored?.audience || "").length}`,
  );
  const guestLong = await req(base, "/api/guests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: "N".repeat(5000),
      phone: "03000000000",
      host_roll_no: "LGU-2024-102",
    }),
  });
  check(
    "V-INP-03 guest name 5000 chars -> 400",
    guestLong.status === 400,
    `status=${guestLong.status}`,
  );

  // ------------------------------------------------------------- E6 sync
  const records = tr.json.records;
  const male = records.find((r) => r.key === "male") || records[0];
  const female = records.find((r) => r.key === "female") || records[1];
  const guestRec = records.find((r) => r.key === "guest") || records[2];
  const maleRoll = rollOf(male);
  const payloadOf = (rec) => rec.payload || forge(rec.qr_id);
  const volCapScan = await req(base, "/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      // Seeded test guest — keeps male/female fresh for the race tests.
      payload: payloadOf(guestRec),
      gate_id: 1,
      mode: "entry",
      volunteer: "V".repeat(5000),
    }),
  });
  const volRows = queryDb(
    TEST.dbPath,
    `SELECT volunteer FROM scans WHERE qr_id = '${qrOf(payloadOf(guestRec))}'`,
  );
  check(
    "V-INP-04 scan volunteer 5000 chars -> 200, stored value truncated <=64",
    volCapScan.status === 200 &&
      volRows.length > 0 &&
      (volRows[0].volunteer || "").length <= 64,
    `status=${volCapScan.status}, len=${(volRows[0]?.volunteer || "").length}`,
  );
  const e6 = await req(base, "/api/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items: [{
      payload: payloadOf(female),
      gate_id: { evil: true },
      mode: "entry",
      volunteer: "E6",
      scanned_at: "2026-10-07 02:10:00",
    }] }),
  });
  check(
    "E6 sync with dict gate_id -> 200 (per-item error, no 500)",
    e6.status === 200 && Array.isArray(e6.json?.results) && e6.json.results.length === 1,
    `status=${e6.status}`,
  );
  const e6b = await req(base, "/api/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items: [{ payload: payloadOf(female), gate_id: "not-a-number", mode: "entry", volunteer: "E6b", scanned_at: "2026-10-07 02:11:00" }] }),
  });
  check(
    "E6 sync with non-numeric gate_id -> 200 (no 500)",
    e6b.status === 200,
    `status=${e6b.status}`,
  );
  const e6c = await req(base, "/api/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify([{ payload: payloadOf(female), gate_id: 9, mode: "entry" }]),
  });
  check(
    "E6 sync bare-list body -> JSON 400 before writes (no 500)",
    e6c.status === 400 && e6c.json?.ok === false && typeof e6c.json?.error === "string",
    `status=${e6c.status}, body=${e6c.text.slice(0, 120)}`,
  );
  const healthAfterE6 = await req(base, "/api/health");
  check("server healthy after malformed sync items", healthAfterE6.json?.ok === true);

  // ------------------------------------------------ F-INP-05 guest bounds
  const hugeId = "99999999999999999999";
  const webPass = await req(base, `/guests/${hugeId}/pass`, { redirect: "manual" });
  check(
    "F-INP-05 /guests/<20-digit>/pass -> 404 (no 500)",
    webPass.status === 404,
    `status=${webPass.status}`,
  );
  const apiPass = await req(base, `/api/guest-pass/${hugeId}`);
  check(
    "F-INP-05 /api/guest-pass/<20-digit> -> 404 JSON (no 500)",
    apiPass.status === 404 && apiPass.json?.ok === false,
    `status=${apiPass.status}`,
  );

  // ------------------------------------------------------------ V-CORS-01
  const evil = await req(base, "/api/config", { headers: { Origin: "https://evil.example" } });
  check(
    "V-CORS-01 foreign origin gets NO Access-Control-Allow-Origin",
    evil.headers.get("access-control-allow-origin") === null,
    `acao=${evil.headers.get("access-control-allow-origin")}`,
  );
  const loop = await req(base, "/api/config", { headers: { Origin: "http://127.0.0.1:5000" } });
  check(
    "V-CORS-01 loopback origin echoed",
    loop.headers.get("access-control-allow-origin") === "http://127.0.0.1:5000",
    `acao=${loop.headers.get("access-control-allow-origin")}`,
  );
  const lan = await req(base, "/api/config", { headers: { Origin: "http://192.168.99.99:8082" } });
  check(
    "V-CORS-01 foreign LAN origin NOT allowed for loopback-host server",
    lan.headers.get("access-control-allow-origin") === null,
    `acao=${lan.headers.get("access-control-allow-origin")}`,
  );

  // ------------------------------------------------------------ V-HEAD-01
  const cfg = await req(base, "/api/config");
  check(
    "V-HEAD-01 nosniff / SAMEORIGIN / no-referrer present",
    cfg.headers.get("x-content-type-options") === "nosniff" &&
      cfg.headers.get("x-frame-options") === "SAMEORIGIN" &&
      cfg.headers.get("referrer-policy") === "no-referrer",
  );

  // -------------------------------------------------- V-RACE-01 student
  const stuPayload = payloadOf(male);
  const raceStu = await Promise.all(
    Array.from({ length: 12 }, () =>
      req(base, "/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: stuPayload, gate_id: 2, mode: "entry", volunteer: "Race" }),
      }),
    ),
  );
  const stuRows = queryDb(
    TEST.dbPath,
    `SELECT COUNT(*) AS n FROM scans WHERE qr_id = '${qrOf(stuPayload)}' AND mode = 'entry'`,
  );
  const stuRecorded = raceStu.filter((r) => r.json?.title === "ENTRY RECORDED").length;
  check(
    "V-RACE-01 12 concurrent student entries -> exactly 1 row",
    stuRows[0].n === 1 && stuRecorded === 1,
    `rows=${stuRows[0].n}, recorded=${stuRecorded}`,
  );

  // ------------------------------------------------------ V-RACE-02 guest
  const guestReg = await req(base, "/api/guests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "Race Guest", phone: "03111111111", host_roll_no: maleRoll }),
  });
  const guestPayload = guestReg.json?.payload;
  // Registration returns {ok, gid, payload} — look the roll up in /api/guests.
  const guestList = await req(base, "/api/guests");
  const guestRow = (guestList.json?.guests || []).find(
    (g) => g.id === guestReg.json?.gid,
  );
  // Phase 26C: the roster no longer exposes qr_id (it is a credential);
  // the signed payload embeds it: LGU1:<qr_id>:<mac>.
  const guestRoll = qrOf(guestPayload);
  check(
    "fresh guest registered for race test",
    guestReg.status === 200 && !!guestPayload && !!guestRow && !!guestRoll,
    `status=${guestReg.status}, qr=${guestRoll}`,
  );
  const raceGuest = await Promise.all(
    Array.from({ length: 10 }, () =>
      req(base, "/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: guestPayload, gate_id: 3, mode: "entry", volunteer: "RaceG" }),
      }),
    ),
  );
  const guestRows = queryDb(
    TEST.dbPath,
    `SELECT COUNT(*) AS n FROM scans WHERE qr_id = '${qrOf(guestPayload)}'`,
  );
  const guestRecorded = raceGuest.filter((r) => r.json?.title === "GUEST ENTRY RECORDED").length;
  check(
    "V-RACE-02 10 concurrent guest entries -> exactly 1 row",
    guestRows[0].n === 1 && guestRecorded === 1,
    `rows=${guestRows[0].n}, recorded=${guestRecorded}`,
  );

  // ------------------------------------------------------ V-RACE-03 sync
  const syncItem = {
    payload: payloadOf(female),
    gate_id: 4,
    mode: "entry",
    volunteer: "SyncRace",
    scanned_at: "2026-10-07 02:30:00",
  };
  const raceSync = await Promise.all(
    Array.from({ length: 6 }, () =>
      req(base, "/api/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: [syncItem] }),
      }),
    ),
  );
  const syncRows = queryDb(
    TEST.dbPath,
    `SELECT COUNT(*) AS n FROM scans WHERE qr_id = '${qrOf(payloadOf(female))}' AND mode = 'entry' AND source = 'queued'`,
  );
  const syncRecorded = raceSync.filter(
    (r) => r.json?.results?.[0]?.result?.title === "ENTRY RECORDED",
  ).length;
  check(
    "V-RACE-03 6 concurrent duplicate sync batches -> exactly 1 row",
    syncRows[0].n === 1 && syncRecorded === 1,
    `rows=${syncRows[0].n}, recorded=${syncRecorded}`,
  );
  // Sequential idempotency still intact after the lock change.
  const seqSync = await req(base, "/api/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items: [syncItem] }),
  });
  const seqTitle = seqSync.json?.results?.[0]?.result?.title;
  check(
    "sequential duplicate sync -> ALREADY SYNCED (idempotency kept)",
    seqSync.status === 200 && seqTitle === "ALREADY SYNCED",
    `title=${seqTitle}`,
  );

  stopServer(A);
  A = null;

  // ------------------------------------- V-AUTH-01/02 rate limiting (B)
  B = await startServer(); // default limit: 5 fails / 60 s
  const baseB = B.base;
  console.log(`\nserver B (rate limit, default 5/60s): ${baseB}`);
  let statuses = [];
  for (let i = 0; i < 5; i += 1) {
    const r = await req(baseB, "/api/admin/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: "0000" }),
    });
    statuses.push(r.status);
  }
  const sixth = await req(baseB, "/api/admin/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin: "0000" }),
  });
  const correctDuringLock = await req(baseB, "/api/admin/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin: ADMIN_PIN }),
  });
  const readDuringLock = await req(baseB, "/api/config");
  check(
    "V-AUTH-01 5 wrong PINs -> 401 each",
    statuses.every((s) => s === 401),
    `statuses=${statuses.join(",")}`,
  );
  check(
    "V-AUTH-02 6th wrong PIN -> 429 rate limited",
    sixth.status === 429,
    `status=${sixth.status}`,
  );
  check(
    "V-AUTH-02 correct PIN during lockout also 429 (brief lockout by design)",
    correctDuringLock.status === 429,
    `status=${correctDuringLock.status}`,
  );
  check(
    "read endpoints unaffected by PIN lockout",
    readDuringLock.status === 200,
    `status=${readDuringLock.status}`,
  );
  stopServer(B);
  B = null;

  // ------------------------------------------------------------- summary
  const prodStampAfter = fileStamp(PRODUCTION_DB);
  console.log(`\nproduction stamp after:  ${prodStampAfter}`);
  check(
    "production DB untouched by the whole run (size+mtime identical)",
    prodStampAfter === prodStampBefore,
  );
  console.log(
    `\n${failures === 0 ? "ALL CHECKS PASSED" : failures + " CHECK(S) FAILED"}`,
  );
  process.exitCode = failures === 0 ? 0 : 1;
}

main()
  .catch((e) => {
    console.error("FATAL:", e.message);
    if (A?.logs?.length) console.error(A.logs.join("").slice(-1500));
    if (B?.logs?.length) console.error(B.logs.join("").slice(-1500));
    process.exitCode = 1;
  })
  .finally(() => {
    stopServer(A);
    stopServer(B);
    try {
      fs.rmSync(TEST.dir, { recursive: true, force: true });
    } catch {
      /* best effort */
    }
  });
