/**
 * Display/admin authorization regression test — Issue 4 (display exit requires
 * server-verified PIN) + Issue 5 (admin surfaces/API gated, keep-awake intact).
 *
 * Source-level checks (mobile app):
 *   A1  LiveBoardScreen imports verifyAdminPin (server-verified exit).
 *   A2  "Exit dashboard" routes through requestExitPin (PIN step), not finishExit.
 *   A3  PIN step UI exists (Field, secureTextEntry, exitStep === "pin").
 *   A4  confirmExitWithPin verifies the PIN before finishExit.
 *   A5  Exit PIN gate reuses the shared adminLockout rules.
 *   A6  Display keep-awake still active while the board is focused.
 *   A7  Admin route wrapped by AdminGate (client PIN gate + server verify).
 *   A8  Broadcast route wrapped by AdminGate.
 *
 * Server-level checks (isolated backend, disposable temp DB):
 *   V1  POST /api/admin/verify correct PIN → 200 ok:true.
 *   V2  POST /api/admin/verify wrong PIN → 401 ok:false (counts a failure).
 *   S1  PUT /api/settings without X-Admin-Pin → 401 (failure #2).
 *   S2  POST /api/broadcasts without X-Admin-Pin → 401 (failure #3).
 *   S3  POST /api/test-reset without X-Admin-Pin → 401 (failure #4).
 *   S4  POST /api/gates/1/rename without X-Admin-Pin → 401 (failure #5).
 *   S5  Next unauthenticated admin mutation → 429 (rate limit enforced).
 *
 * Production DB is never touched — server runs on a disposable temp DB.
 */

import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

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

// ─── Source-level checks (mobile app) ───────────────────────────────────────
console.log("Source-level checks (mobile app):");

const board = read(join("src", "screens", "LiveBoardScreen.tsx"));
const adminRoute = read(join("app", "(volunteer)", "admin.tsx"));
const broadcastRoute = read(join("app", "(volunteer)", "broadcast.tsx"));

// A1: LiveBoardScreen imports verifyAdminPin.
check("A1", "LiveBoardScreen imports verifyAdminPin",
  /import\s*\{[^}]*verifyAdminPin[^}]*\}\s*from\s*"\.\.\/api\/client"/.test(board));

// A2: "Leave display" in the confirm step routes through requestExitPin —
//     the destructive step is never wired straight to finishExit.
check("A2", "'Leave display' routes through requestExitPin (not finishExit)",
  /label="Leave display"[\s\S]{0,200}?onPress=\{requestExitPin\}/.test(board));

// A3: PIN step UI — Field with secureTextEntry behind exitStep === "pin".
check("A3", "PIN step UI exists (exitStep pin + secure Field)",
  /exitStep === "pin"/.test(board) && /secureTextEntry/.test(board)
  && /<Field/.test(board));

// A4: confirmExitWithPin verifies via verifyAdminPin, exits only after ok.
const confirmFn = board.match(/const confirmExitWithPin[\s\S]{0,1600}?\}, \[/);
check("A4", "confirmExitWithPin calls verifyAdminPin before finishExit",
  !!confirmFn
  && /await verifyAdminPin\(candidate\)/.test(confirmFn[0])
  && /finishExit\(\)/.test(confirmFn[0])
  && /verified\.ok/.test(confirmFn[0]));

// A5: shared adminLockout rules (registerFailure + resetOnSuccess) reused.
check("A5", "Exit PIN gate reuses adminLockout store rules",
  /registerFailure\(prev, Date\.now\(\)\)/.test(board)
  && /resetOnSuccess\(\)/.test(board)
  && /from "\.\.\/store\/adminLockout"/.test(board));

// A6: keep-awake intact — the board must stay awake on the projector.
check("A6", "Display keep-awake still active (activateKeepAwakeAsync)",
  /activateKeepAwakeAsync\(KEEP_AWAKE_TAG\)/.test(board)
  && /deactivateKeepAwake\(KEEP_AWAKE_TAG\)/.test(board));

// A7/A8: admin + broadcast routes wrapped by AdminGate.
check("A7", "Admin route wrapped by AdminGate",
  /import\s*\{\s*AdminGate\s*\}/.test(adminRoute) && /<AdminGate>/.test(adminRoute));
check("A8", "Broadcast route wrapped by AdminGate",
  /import\s*\{\s*AdminGate\s*\}/.test(broadcastRoute) && /<AdminGate>/.test(broadcastRoute));

// ─── Server-level checks (isolated backend) ─────────────────────────────────
console.log("\nServer-level checks (isolated backend):");

const testDb = join(mkdtempSync(join(tmpdir(), "lgu-auth-")), "lgu-test.db");
const pythonExe = join(REPO, ".venv", "Scripts", "python.exe");
const serverPort = 51207;

// run.py handles init_db() + seed() + create_app() automatically.
// LGU_TESTING=1 activates the test-db safety guard (require_test_db).
// Test PIN 9999 — rate window/max from config defaults (60s / 5 fails).
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
delete serverEnv.LGU_PIN_WINDOW;
delete serverEnv.LGU_PIN_MAX_FAILS;

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
check("V0", "isolated backend healthy", healthy);
if (!healthy && serverErr) {
  console.log(`  server stderr: ${serverErr.slice(0, 800)}`);
}

const base = `http://127.0.0.1:${serverPort}`;

if (healthy) {
  const post = (path, body, headers = {}) => fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });
  const put = (path, body, headers = {}) => fetch(`${base}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });
  const statusOf = async (p) => { try { return await p; } catch { return null; } };

  // V1: correct PIN verifies — 200 ok:true. (Success records no failure.)
  const v1 = await statusOf(post("/api/admin/verify", { pin: "9999" }));
  const v1Body = v1 ? await v1.json().catch(() => null) : null;
  check("V1", `verify correct PIN → 200 ok:true (${v1?.status ?? "no response"})`,
    v1?.status === 200 && v1Body?.ok === true);

  // V2: wrong PIN → 401 ok:false. Failure #1 of the window.
  const v2 = await statusOf(post("/api/admin/verify", { pin: "0000" }));
  const v2Body = v2 ? await v2.json().catch(() => null) : null;
  check("V2", `verify wrong PIN → 401 ok:false (${v2?.status ?? "no response"})`,
    v2?.status === 401 && v2Body?.ok === false);

  // S1: PUT /api/settings without header → 401. Failure #2.
  const s1 = await statusOf(put("/api/settings", { expected_attendance: 1 }));
  check("S1", `PUT /api/settings without PIN → 401 (${s1?.status ?? "no response"})`,
    s1?.status === 401);

  // S2: POST /api/broadcasts without header → 401. Failure #3.
  const s2 = await statusOf(post("/api/broadcasts", {
    audience: "all", message: "auth probe", sent_by: "test",
  }));
  check("S2", `POST /api/broadcasts without PIN → 401 (${s2?.status ?? "no response"})`,
    s2?.status === 401);

  // S3: POST /api/test-reset without header → 401. Failure #4.
  const s3 = await statusOf(post("/api/test-reset", {}));
  check("S3", `POST /api/test-reset without PIN → 401 (${s3?.status ?? "no response"})`,
    s3?.status === 401);

  // S4: POST /api/gates/1/rename without header → 401. Failure #5 (max).
  const s4 = await statusOf(post("/api/gates/1/rename", { label: "Main Gate" }));
  check("S4", `POST /api/gates/1/rename without PIN → 401 (${s4?.status ?? "no response"})`,
    s4?.status === 401);

  // S5: the next unauthenticated admin mutation hits the rate limiter → 429.
  //     Proves repeated unauthorized attempts are blocked server-side.
  const s5 = await statusOf(put("/api/settings", { expected_attendance: 2 }));
  const s5Body = s5 ? await s5.json().catch(() => null) : null;
  check("S5", `rate limit enforced after 5 failures → 429 (${s5?.status ?? "no response"})`,
    s5?.status === 429 && /too many attempts/i.test(s5Body?.error || ""));

  server.unref();
  try { server.kill(); } catch {}
} else {
  for (const id of ["V1", "V2", "S1", "S2", "S3", "S4", "S5"]) {
    check(id, "server unavailable", false);
  }
  server.unref();
  try { server.kill(); } catch {}
}
// Teardown: wait for the child to actually exit before the summary —
// process.exit() while the spawn stdio handles are still closing trips a
// Windows libuv assertion (async.c) AFTER all checks have printed.
await new Promise((resolve) => {
  if (server.exitCode !== null || server.signalCode !== null) {
    resolve();
    return;
  }
  const onExit = () => resolve();
  server.once("exit", onExit);
  const t = setTimeout(() => {
    server.removeListener("exit", onExit);
    resolve();
  }, 3000);
  if (typeof t.unref === "function") t.unref();
});
// ─── Summary ────────────────────────────────────────────────────────────────
// NO forced process.exit(): on Windows, exiting while handles are mid-close
// trips a libuv assertion (async.c line 76) AFTER the results print. The
// child is already killed/unref'd above; drop its stdio refs and let node
// exit naturally with process.exitCode (undici keep-alive sockets drain
// within seconds).
console.log(`\ndisplay-admin-auth-test: ${passed} passed, ${failed} failed`);
try { server.stdout?.destroy(); } catch {}
try { server.stderr?.destroy(); } catch {}
process.exitCode = failed > 0 ? 1 : 0;
