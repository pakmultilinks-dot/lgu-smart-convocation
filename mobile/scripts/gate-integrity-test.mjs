/**
 * Gate-integrity regression test — Issue 2 (gate+ENTRY/EXIT on every scan result)
 *                           + Issue 3 (distinct Entry/Exit colors + mode confirmation).
 *
 * Source-level checks (mobile app):
 *   G1  ScannerTopBar renders a large semantic mode label (ENTRY/EXIT text).
 *   G2  ScannerTopBar Entry button uses valid/green styling when active.
 *   G3  ScannerTopBar Exit button uses amber styling when active.
 *   G4  ScannerTopBar mode buttons call onModeChange (not SegmentedControl).
 *   G5  ScannerScreen routes mode changes through requestModeChange (confirmation).
 *   G6  ScannerScreen shows a mode-switch confirmation modal.
 *   G7  ScannerScreen blocks camera when gateId is null (gate-required state).
 *   G8  ScannerResult shows gate on valid results.
 *   G9  ScannerResult shows ENTRY/EXIT action pill on valid results.
 *   G10 ScannerResult shows "Gate unknown" fallback on invalid results without gate.
 *   G11 ScannerTopBar does NOT use SegmentedControl import.
 *   G12 ScannerTopBar does NOT render a gold underline on gate text.
 *   G13 HomeScreen consumes getSelectedGate + getScanMode (same ops store).
 *
 * Server-level checks (isolated backend):
 *   S1  POST /api/scan with unknown gate_id → rejected (400/404).
 *   S2  POST /api/scan with valid gate_id → accepted (gate stamped).
 *
 * Production DB is never touched — server runs on a disposable temp DB.
 */

import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { spawn, spawnSync } from "node:child_process";
import { createHmac } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const MOBILE = join(__dirname, "..");
const APP = join(MOBILE, "..", "app");
const REPO = join(MOBILE, "..");

let passed = 0;
let failed = 0;
function check(id, label, ok) {
  if (ok) {
    passed += 1;
    console.log(`  PASS  ${id} ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL  ${id} ${label}`);
  }
}

function read(rel) {
  return readFileSync(join(MOBILE, rel), "utf8");
}

// ─── Source-level checks ────────────────────────────────────────────────────
console.log("Source-level checks (mobile app):");

const topBar = read(join("src", "scanner", "ScannerTopBar.tsx"));
const screen = read(join("src", "screens", "ScannerScreen.tsx"));
const result = read(join("src", "scanner", "ScannerResult.tsx"));
const home = read(join("src", "screens", "HomeScreen.tsx"));

// G1–G4 + G11/G12 UPDATED (user-directed scanner UI visual revert): the
// Entry/Exit presentation returns to the previous compact neutral
// SegmentedControl (no large ENTRY/EXIT banner, no semantic mode colors,
// gold gate accent restored). The pinned SECURITY intent is unchanged:
// the mode control still routes through onModeChange → requestModeChange
// → confirmation modal (G5), and gate/result integrity (G7–G10) is
// untouched. Valid/invalid/amber tokens stay reserved for scan-result
// semantics in ScannerResult.
const topBarNoCommentsG = topBar.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
check("G1", "ScannerTopBar uses the compact Entry/Exit SegmentedControl (no large mode label)",
  /SegmentedControl/.test(topBarNoCommentsG) &&
    !/modeLabelText|modeButton/.test(topBarNoCommentsG) &&
    !/\bENTRY\b|\bEXIT\b/.test(topBarNoCommentsG));

// G2 UPDATED (QA fix cycle 4, Finding 2): the selected segment now
// carries a sanctioned semantic accent — Entry = valid/green, Exit =
// amber — on the shared SegmentedControl's activeColor only. What stays
// banned is the old full-width semantic mode fill above the camera.
check("G2", "mode colors appear only as the sanctioned activeColor accent (Finding 2)",
  /activeColor=\{mode === "exit" \? colors\.amber : colors\.valid\}/.test(topBarNoCommentsG) &&
    !/backgroundColor:\s*colors\.(valid|amber)/.test(topBarNoCommentsG));

check("G3", "gate-text gold underline GONE (QA fix cycle 2 — sanctioned gold is the active tab underline only)",
  !/borderBottomColor:\s*colors\.gold/.test(topBarNoCommentsG));

check("G4", "SegmentedControl onChange routes to onModeChange (confirmation path intact)",
  /onChange=\{onModeChange\}/.test(topBarNoCommentsG) &&
    /\{\s*label:\s*"Entry",\s*value:\s*"entry"\s*\}/.test(topBar) &&
    /\{\s*label:\s*"Exit",\s*value:\s*"exit"\s*\}/.test(topBar));

// G5: ScannerScreen routes through requestModeChange
check("G5", "ScannerScreen routes mode changes through requestModeChange",
  /onModeChange=\{requestModeChange\}/.test(screen));

// G6: mode-switch confirmation modal
check("G6", "ScannerScreen shows mode-switch confirmation modal",
  /modeSwitchPending/.test(screen) && /Switch mode\?/.test(screen));

// G7: gate-required camera block
check("G7", "ScannerScreen blocks camera when gateId is null",
  /gateId === null/.test(screen) && /gateRequired/.test(screen) && /Choose a gate/.test(screen));

// G8: ScannerResult shows gate on valid results
check("G8", "ScannerResult shows gate on valid results",
  /result\.gate/.test(result) && /fullMeta/.test(result));

// G9: ScannerResult shows ENTRY/EXIT action pill
check("G9", "ScannerResult shows ENTRY/EXIT action pill on valid results",
  /actionPill/.test(result) && /action\.toUpperCase\(\)/.test(result));

// G10: "Gate unknown" fallback on invalid results
check("G10", "ScannerResult shows 'Gate unknown' fallback on invalid results",
  /Gate unknown/.test(result));

// G11: SegmentedControl restored (previous visual treatment)
check("G11", "ScannerTopBar imports SegmentedControl (previous visual treatment restored)",
  /import \{[^}]*SegmentedControl/.test(topBar));

// G12: gold underline on gate text stays REMOVED (QA fix cycle 2 reverts
//      the Issue 31 visual revert — the accent was retired so the only
//      sanctioned gold marker is the active tab underline).
check("G12", "ScannerTopBar renders NO gold underline accent on gate text",
  !/borderBottomColor:\s*colors\.gold/.test(topBarNoCommentsG));

// G13: HomeScreen consumes same ops store
check("G13", "HomeScreen consumes getSelectedGate + getScanMode",
  /getSelectedGate/.test(home) && /getScanMode/.test(home));

// G14: Home scan button is disabled until a gate is chosen (QA fix
//      cycle 2) — no gate, no scan attempt.
check("G14", "HomeScreen scan button disabled while no gate is selected",
  /disabled=\{gateId === null\}/.test(home));

// G15: the ops store is the SINGLE source of gate truth — selection
//      persists (readJson/writeJson) and both surfaces read the same key.
const ops = read(join("src", "store", "ops.ts"));
check("G15", "ops store single source (selected gate persisted via readJson/writeJson)",
  /KEY_SELECTED_GATE = "lgu\.ops_selected_gate"/.test(ops) &&
    /export async function getSelectedGate/.test(ops) &&
    /export async function setSelectedGate/.test(ops) &&
    /readJson<SelectedGate>\(KEY_SELECTED_GATE\)/.test(ops) &&
    /writeJson\(KEY_SELECTED_GATE, gate\)/.test(ops));

// G16: direct navigation / restart safety — ScannerScreen renders the
//      gate-required block when gateId is null (fresh start or direct
//      deep-nav without a stored selection).
check("G16", "ScannerScreen blocks the camera with gateRequired on null gate (restart/direct-nav)",
  /gateId === null/.test(screen) && /gateRequired/.test(screen));

// ─── Server-level checks (isolated backend) ─────────────────────────────────
console.log("\nServer-level checks (isolated backend):");

const testDb = join(mkdtempSync(join(tmpdir(), "lgu-gate-")), "lgu-test.db");
const pythonExe = join(REPO, ".venv", "Scripts", "python.exe");
const serverPort = 51199;

// run.py handles init_db() + seed() + create_app() automatically.
// LGU_TESTING=1 activates the test-db safety guard (require_test_db).
// Demo secrets are used (env vars deleted) — same pattern as release-safety-test.
const serverEnv = {
  ...process.env,
  LGU_DB_PATH: testDb,
  LGU_PORT: String(serverPort),
  LGU_TESTING: "1",
  LGU_ADMIN_PIN: "9999",
  // Demo secrets are deliberate here, so run.py needs the explicit opt-in.
  LGU_ALLOW_DEMO_SECRETS: "1",
};
delete serverEnv.LGU_SECRET_KEY;
delete serverEnv.LGU_HMAC_SECRET;

const server = spawn(pythonExe, ["run.py"], {
  cwd: APP,
  env: serverEnv,
  stdio: ["ignore", "pipe", "pipe"],
});
let serverErr = "";
server.stderr.on("data", (d) => { serverErr += d.toString(); });

// Wait for health
let healthy = false;
for (let i = 0; i < 30; i += 1) {
  try {
    const res = await fetch(`http://127.0.0.1:${serverPort}/api/health`);
    if (res.ok) { healthy = true; break; }
  } catch {}
  await new Promise((r) => setTimeout(r, 1000));
}
check("S0", "isolated backend healthy", healthy);
if (!healthy && serverErr) {
  console.log(`  server stderr: ${serverErr.slice(0, 800)}`);
}

if (healthy) {
  // Phase 14: /api/scan requires an authenticated scanner. Mint a random
  // synthetic session (guarded test helper, never production) authorized
  // for every seeded gate so S1–S5 exercise gate logic, not auth.
  const sessRes = await fetch(`http://127.0.0.1:${serverPort}/api/test-scanner-session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ gate_ids: [1, 2, 3, 4, 5, 6, 7] }),
  });
  const sessBody = await sessRes.json().catch(() => null);
  const scannerHdr = { "X-Scanner-Token": sessBody?.token || "" };
  check("S0b", "scanner session minted for scan calls", sessRes.ok && !!sessBody?.token);

  // Query the temp DB for gate/student IDs (run.py already seeded them).
  const queryPy = `
import sqlite3
db = sqlite3.connect(${JSON.stringify(testDb)})
db.row_factory = sqlite3.Row
g = db.execute("SELECT id FROM gates WHERE code='G1'").fetchone()
s = db.execute("SELECT id, qr_id FROM students WHERE roll_no='LGU-2024-101'").fetchone()
print(f"GATE_ID={g['id']}")
print(f"QR_ID={s['qr_id']}")
db.close()
`;
  writeFileSync(join(tmpdir(), "gate-query.py"), queryPy);
  const queryProc = spawnSync(pythonExe, [join(tmpdir(), "gate-query.py")], { encoding: "utf8" });
  const gateMatch = queryProc.stdout.match(/GATE_ID=(\d+)/);
  const qrMatch = queryProc.stdout.match(/QR_ID=(\S+)/);
  const gateId = gateMatch ? parseInt(gateMatch[1], 10) : 0;
  const studentQrId = qrMatch ? qrMatch[1] : "";

  // Sign a payload exactly like app/ids.py: HMAC-SHA256(secret, qr_id)[:10].
  // The test server uses the demo default secret (env vars deleted above).
  function signPayload(qrId) {
    const sig = createHmac("sha256", "lgu-convocation-hmac-secret-change-in-production")
      .update(qrId, "ascii")
      .digest("hex")
      .slice(0, 10);
    return `LGU1:${qrId}:${sig}`;
  }

  // S1: validly-signed payload + unknown gate_id → "UNKNOWN GATE".
  // Signature verification passes, gate lookup fails → body says UNKNOWN GATE.
  const signedPayload = signPayload(studentQrId);
  const badScan = await fetch(`http://127.0.0.1:${serverPort}/api/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...scannerHdr },
    body: JSON.stringify({
      payload: signedPayload,
      mode: "entry",
      gate_id: 99999,
      volunteer_name: "Tester",
    }),
  });
  const badBody = await badScan.json().catch(() => null);
  const s1ok = badBody
    && /UNKNOWN GATE/i.test(badBody.title || "");
  check("S1", `validly-signed scan + unknown gate_id → UNKNOWN GATE (${badBody?.title || "no body"})`,
    !!s1ok);

  // S2: validly-signed payload + valid gate_id → NOT "UNKNOWN GATE".
  // Gate check passes; the scan may succeed (ENTRY RECORDED) or hit a
  // state error (ALREADY INSIDE, etc.) — but never UNKNOWN GATE.
  const goodScan = await fetch(`http://127.0.0.1:${serverPort}/api/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...scannerHdr },
    body: JSON.stringify({
      payload: signedPayload,
      mode: "entry",
      gate_id: gateId,
      volunteer_name: "Tester",
    }),
  });
  const goodBody = await goodScan.json().catch(() => null);
  const s2ok = goodBody && !/UNKNOWN GATE/i.test(goodBody.title || "");
  check("S2", `validly-signed scan + valid gate_id → not UNKNOWN GATE (${goodBody?.title || "no body"})`,
    !!s2ok);

  // S3: gate_id null → server rejects (client can never "forget" a gate
  // into an unguarded scan — the server is the source of truth).
  const nullGateScan = await fetch(`http://127.0.0.1:${serverPort}/api/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...scannerHdr },
    body: JSON.stringify({
      payload: signPayload(studentQrId),
      mode: "entry",
      gate_id: null,
      volunteer_name: "Tester",
    }),
  });
  const nullGateBody = await nullGateScan.json().catch(() => null);
  // The API answers 200 with a semantic envelope — rejection = the title
  // names the gate problem and no scan was recorded ("…RECORDED").
  const s3ok = nullGateBody &&
    /NO GATE SELECTED|UNKNOWN GATE/i.test(nullGateBody.title || "") &&
    !/RECORDED|INSIDE/i.test(nullGateBody.title || "");
  check("S3", `gate_id null → rejected (${nullGateBody?.title || "no body"})`,
    !!s3ok);

  // S4: malformed/forged payload (bad signature) → rejected outright.
  const forgedScan = await fetch(`http://127.0.0.1:${serverPort}/api/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...scannerHdr },
    body: JSON.stringify({
      payload: `LGU1:${studentQrId}:0000000000`,
      mode: "entry",
      gate_id: gateId,
      volunteer_name: "Tester",
    }),
  });
  const forgedBody = await forgedScan.json().catch(() => null);
  // Semantic rejection: the forged signature names INVALID CODE (or a
  // signature failure) and nothing is recorded.
  const s4ok = forgedBody &&
    /INVALID|FORGERY|SIGNATURE/i.test(forgedBody.title || "") &&
    !/RECORDED|INSIDE/i.test(forgedBody.title || "");
  check("S4", `forged signature → rejected (${forgedBody?.title || "no body"})`,
    !!s4ok);

  // S5: stale gate — the gate row is DELETED after the client picked it;
  // a scan still naming it must fail (server re-checks every scan, so a
  // cached/renamed gate from a previous session can never slip through).
  const staleDelete = spawnSync(pythonExe, ["-c", `
import sqlite3
db = sqlite3.connect(${JSON.stringify(testDb)})
db.execute("DELETE FROM gates WHERE id=?", (${JSON.stringify(gateId)},))
db.commit()
db.close()
`], { encoding: "utf8" });
  const staleScan = await fetch(`http://127.0.0.1:${serverPort}/api/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...scannerHdr },
    body: JSON.stringify({
      payload: signPayload(studentQrId),
      mode: "entry",
      gate_id: gateId,
      volunteer_name: "Tester",
    }),
  });
  const staleBody = await staleScan.json().catch(() => null);
  const s5ok = staleDelete.status === 0 && staleBody &&
    /UNKNOWN GATE/i.test(staleBody.title || "");
  check("S5", `stale (deleted) gate_id → UNKNOWN GATE (${staleBody?.title || "no body"})`,
    !!s5ok);

  server.unref();
  try { server.kill(); } catch {}
} else {
  check("S1", "validly-signed scan + unknown gate_id → UNKNOWN GATE", false);
  check("S2", "validly-signed scan + valid gate_id → not UNKNOWN GATE", false);
  check("S3", "gate_id null → rejected", false);
  check("S4", "forged signature → rejected", false);
  check("S5", "stale (deleted) gate_id → UNKNOWN GATE", false);
  server.unref();
  try { server.kill(); } catch {}
}

// ─── Summary ────────────────────────────────────────────────────────────────
console.log(`\ngate-integrity-test: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
