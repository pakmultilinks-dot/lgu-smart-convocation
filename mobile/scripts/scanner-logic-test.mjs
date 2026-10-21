// Phase 35B scanner logic tests — pure-node, compile-on-demand from the
// TypeScript source with the project tsc (no test framework in mobile).
// Usage: node scripts/scanner-logic-test.mjs
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const tsc = join(root, "node_modules", "typescript", "bin", "tsc");
const src = join(root, "src", "scanner", "scanResultLogic.ts");
const outDir = mkdtempSync(join(tmpdir(), "scanner-logic-"));

let passed = 0;
let failed = 0;
function check(name, condition, detail) {
  if (condition) {
    passed += 1;
    console.log(`  PASS  ${name}`);
  } else {
    failed += 1;
    console.error(`  FAIL  ${name}${detail ? ` :: ${detail}` : ""}`);
  }
}

try {
  execFileSync(
    process.execPath,
    [tsc, src, "--outDir", outDir, "--module", "commonjs", "--target", "es2020", "--skipLibCheck"],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  // Phase 35K (P): compile the mode+gate-aware cooldown helper too.
  execFileSync(
    process.execPath,
    [
      tsc,
      join(root, "src", "scanner", "scanCooldown.ts"),
      "--outDir",
      outDir,
      "--module",
      "commonjs",
      "--target",
      "es2020",
      "--skipLibCheck",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
} catch (e) {
  console.error("tsc compile failed:", e.stderr?.toString() ?? e.message);
  process.exit(1);
}

const require = createRequire(import.meta.url);
const logic = require(join(outDir, "scanResultLogic.js"));
const {
  classifyScanResult,
  createScanResultController,
  createVolunteerName,
  sanitizeInvalidDetail,
  scanGateBlocked,
  scanPayload,
  SCAN_RESULT_MS,
} = logic;

console.log("Result mapping (success → VALID, used → ALREADY USED, unknown → INVALID)");
const validEntry = classifyScanResult({ status: "ok", level: "green", title: "ENTRY RECORDED", name: "A", sub: "s", gate: "g", time: "t" });
check("ENTRY RECORDED → valid / Entry / success",
  validEntry.kind === "valid" && validEntry.action === "Entry" && validEntry.haptic === "success",
  JSON.stringify(validEntry));
const validExit = classifyScanResult({ status: "ok", level: "green", title: "EXIT RECORDED" });
check("EXIT RECORDED → valid / Exit", validExit.kind === "valid" && validExit.action === "Exit", JSON.stringify(validExit));
const validGuest = classifyScanResult({ status: "ok", level: "green", title: "GUEST ENTRY RECORDED" });
check("GUEST ENTRY RECORDED → valid", validGuest.kind === "valid", validGuest.kind);
const used = classifyScanResult({ status: "error", level: "red", title: "ALREADY USED", detail: "x" });
check("ALREADY USED → already-used / 'Already used' / error",
  used.kind === "already-used" && used.stateTitle === "Already used" && used.haptic === "error",
  JSON.stringify(used));
const inside = classifyScanResult({ status: "error", level: "red", title: "ALREADY INSIDE" });
check("ALREADY INSIDE → already-used", inside.kind === "already-used", inside.kind);
// Phase 35K (O): the sync path's ALREADY SYNCED is a different signal —
// the scan was already recorded by an earlier sync, not a double camera
// read. It maps to "other" so the sheet shows the amber sync detail.
const alreadySynced = classifyScanResult({ status: "error", level: "amber", title: "ALREADY SYNCED", detail: "This scan was already recorded by an earlier sync." });
check("ALREADY SYNCED → other (amber sync detail, not camera already-used)",
  alreadySynced.kind === "other", alreadySynced.kind);
const unknown = classifyScanResult({ status: "error", level: "red", title: "UNKNOWN CODE" });
check("UNKNOWN CODE → invalid / 'Invalid code' / error (35J H)",
  unknown.kind === "invalid" && unknown.stateTitle === "Invalid code" && unknown.haptic === "error",
  JSON.stringify(unknown));
const invalid = classifyScanResult({ status: "error", level: "red", title: "INVALID CODE" });
check("INVALID CODE → invalid / 'Invalid code'", invalid.kind === "invalid" && invalid.stateTitle === "Invalid code", invalid.stateTitle);

console.log("Gate-required rule + invalid-detail sanitization (35J G/H)");
check("scanGateBlocked(null) is blocked", scanGateBlocked(null) === true);
check("scanGateBlocked(0) is allowed structurally (id exists server-side)", scanGateBlocked(0) === false);
check("scanGateBlocked(7) is allowed", scanGateBlocked(7) === false);
check("signature detail sanitized away",
  sanitizeInvalidDetail("Signature check failed") === undefined, sanitizeInvalidDetail("Signature check failed"));
check("API/HTTP detail sanitized away",
  sanitizeInvalidDetail("http://api.internal/500") === undefined);
check("forged/tamper detail sanitized away",
  sanitizeInvalidDetail("Token tampered") === undefined);
check("empty detail → undefined", sanitizeInvalidDetail(undefined) === undefined && sanitizeInvalidDetail("") === undefined);
check("benign operational detail passes through",
  sanitizeInvalidDetail("Not on the list. Check the card and try again.") ===
    "Not on the list. Check the card and try again.");
const noGate = classifyScanResult({ status: "error", level: "red", title: "NO GATE SELECTED" });
check("NO GATE SELECTED → other (setup notice)", noGate.kind === "other", noGate.kind);
const notInside = classifyScanResult({ status: "error", level: "amber", title: "NOT INSIDE" });
check("NOT INSIDE (amber) → other / warning", notInside.kind === "other" && notInside.haptic === "warning", JSON.stringify(notInside));
const evil = classifyScanResult({ status: "error", level: "red", title: "http://evil.example/boom" });
check("URL title sanitized → 'Scan failed' (invalid kind)",
  evil.stateTitle === "Scan failed" && evil.kind === "other", evil.stateTitle);

console.log("Result lifecycle (auto-clear ~1.2s, no stale overwrite, cleanup)");
const fakeTimers = (() => {
  const pending = new Map();
  let nextId = 1;
  let now = 0;
  return {
    set(fn, ms) {
      const id = nextId++;
      pending.set(id, { at: now + ms, fn });
      return id;
    },
    clear(handle) {
      pending.delete(handle);
    },
    advance(ms) {
      now += ms;
      const due = [...pending.entries()].filter(([, t]) => t.at <= now).sort((a, b) => a[0] - b[0]);
      for (const [id, t] of due) {
        pending.delete(id);
        t.fn();
      }
    },
    count() {
      return pending.size;
    },
  };
})();

let visible = null;
let clears = 0;
const controller = createScanResultController(
  (r) => {
    visible = r;
  },
  () => {
    clears += 1;
    visible = null;
  },
  fakeTimers,
);
check("SCAN_RESULT_MS is 1200", SCAN_RESULT_MS === 1200, String(SCAN_RESULT_MS));
const rA = { status: "ok", level: "green", title: "A" };
const rB = { status: "ok", level: "green", title: "B" };
controller.show(rA, SCAN_RESULT_MS);
check("show() renders immediately", visible?.title === "A", visible?.title);
fakeTimers.advance(600);
check("still visible before timeout", visible?.title === "A" && clears === 0);
// Rapid second scan replaces the first; the first timer must not clear B.
controller.show(rB, SCAN_RESULT_MS);
fakeTimers.advance(600); // A's original deadline passes — must NOT clear B
check("stale timer does not clear newer result", visible?.title === "B" && clears === 0, `visible=${visible?.title} clears=${clears}`);
fakeTimers.advance(600); // B's own 1200ms elapse
check("auto-clear after ~1.2s on the newest result", visible === null && clears === 1, `visible=${visible?.title} clears=${clears}`);
check("no overlapping timers remain", fakeTimers.count() === 0, String(fakeTimers.count()));
controller.show(rA, SCAN_RESULT_MS);
controller.clear();
check("clear() dismisses immediately", visible === null && clears === 2);
controller.show(rA, SCAN_RESULT_MS);
controller.dispose();
fakeTimers.advance(2000);
check("dispose() prevents clears after unmount", clears === 2 && visible?.title === "A", `visible=${visible?.title} clears=${clears}`);
fakeTimers.advance(2000);
check("dispose() leaves no pending timers", fakeTimers.count() === 0, String(fakeTimers.count()));

console.log("Volunteer name (asked once, persisted, stamped on scans)");
const storeMap = new Map();
const fakeStore = {
  load: async () => storeMap.get("name") ?? "",
  save: async (v) => {
    storeMap.set("name", v);
  },
};
const vol = createVolunteerName(fakeStore);
check("empty store → needsSetup", vol.needsSetup === true);
const saved = await vol.ensure("  Bilal Ahmad  ");
check("ensure() trims + persists", saved === "Bilal Ahmad" && storeMap.get("name") === "Bilal Ahmad", JSON.stringify(saved));
check("current reflects stored name", vol.current === "Bilal Ahmad");
check("no longer needs setup", vol.needsSetup === false);
const reopened = createVolunteerName(fakeStore);
const loaded = await reopened.load();
check("reopening loads persisted name (no prompt)", loaded === "Bilal Ahmad" && reopened.needsSetup === false, loaded);
const unchanged = await reopened.ensure("   ");
check("ensure('') keeps previous name", unchanged === "Bilal Ahmad" && storeMap.get("name") === "Bilal Ahmad");
const payload = scanPayload({ volunteerName: reopened.current, gateId: 7, mode: "exit", payload: "QR-1", occasion: "ceremony" });
check("scan payload carries persisted volunteer name", payload.volunteer === "Bilal Ahmad" && payload.gate_id === 7 && payload.mode === "exit" && payload.payload === "QR-1", JSON.stringify(payload));
// Phase 29: every payload carries the confirmed occasion — the server
// refuses a scan without one, and the queue replay needs it.
check("scan payload stamps the occasion (Phase 29)", payload.occasion === "ceremony", JSON.stringify(payload.occasion));
const rehearsalScan = scanPayload({ volunteerName: reopened.current, gateId: 7, mode: "entry", payload: "QR-1", occasion: "rehearsal" });
check("scan payload can carry the rehearsal occasion", rehearsalScan.occasion === "rehearsal", JSON.stringify(rehearsalScan.occasion));
const fallback = scanPayload({ volunteerName: "", gateId: 1, mode: "entry", payload: "QR-2", occasion: "ceremony" });
check("scan payload with empty name falls back to 'Volunteer'", fallback.volunteer === "Volunteer", fallback.volunteer);

console.log("Cooldown (mode+gate+occasion-aware repeat suppression, Phase 35K P / Phase 29)");
const cooldown = require(join(outDir, "scanCooldown.js"));
const { shouldSuppressRepeat } = cooldown;
const now = 1_000_000;
const win = 4000;
check("no previous entry → never suppress", shouldSuppressRepeat(undefined, "p1", "entry", 1, "ceremony", now, win) === false);
const prev = { payload: "p1", mode: "entry", gateId: 1, occasion: "ceremony", at: now - 1000 };
check("same payload+mode+gate+occasion within window → suppress", shouldSuppressRepeat(prev, "p1", "entry", 1, "ceremony", now, win) === true);
check("different gate → never suppress (Entry→Exit never suppressed)", shouldSuppressRepeat(prev, "p1", "exit", 2, "ceremony", now, win) === false);
check("different mode same gate → never suppress", shouldSuppressRepeat(prev, "p1", "exit", 1, "ceremony", now, win) === false);
check("different payload → never suppress", shouldSuppressRepeat(prev, "p2", "entry", 1, "ceremony", now, win) === false);
check("outside window → no suppress", shouldSuppressRepeat(prev, "p1", "entry", 1, "ceremony", now + win + 1, win) === false);
// Phase 29: occasion is part of the cooldown key — the same pass admitted
// for the rehearsal is a legitimate, separate admission for the main
// convocation minutes later at the same gate, and must never be eaten by
// the in-frame cooldown.
check("different occasion same gate/pass → never suppress", shouldSuppressRepeat(prev, "p1", "entry", 1, "rehearsal", now, win) === false);
const rehearsalPrev = { payload: "p1", mode: "entry", gateId: 1, occasion: "rehearsal", at: now - 1000 };
check("rehearsal duplicate within window still suppresses", shouldSuppressRepeat(rehearsalPrev, "p1", "entry", 1, "rehearsal", now, win) === true);
// Phase 35L (F/D): name validator + guest success state — additive only,
// all pins above remain green under these checks.
console.log("Name validator + guest state (Phase 35L)");
const { isValidVolunteerName } = require(join(outDir, "scanResultLogic.js"));
check("isValidVolunteerName: 2+ letters → true", isValidVolunteerName("Bilal Ahmad") === true);
check("isValidVolunteerName: whitespace → false", isValidVolunteerName("   ") === false);
check("isValidVolunteerName: single letter → false", isValidVolunteerName("A") === false);
check("isValidVolunteerName: digits only → false", isValidVolunteerName("404") === false);
check("isValidVolunteerName: single letter + digits → false (strips to 1 letter)", isValidVolunteerName("B1") === false);
check("isValidVolunteerName: two letters + digits → true", isValidVolunteerName("AB1") === true);
const guestSuccess = classifyScanResult({ status: "ok", level: "green", title: "GUEST ENTRY RECORDED", name: "Tariq Mehmood", sub: "Guest of R46B4SDA (03001234567)" });
check("guest scan → guest success stateTitle, valid kind",
  guestSuccess.kind === "valid" && guestSuccess.stateTitle === "Guest entry" && guestSuccess.haptic === "success",
  JSON.stringify(guestSuccess));

// Scanner Fix Round 1 (35M): gate-chip label + seeded scan-result proof.
console.log("Gate chip label (Round 1) — 'Loading gates...' only while loading");
const { resolveGateLabel } = logic;
const round1Gates = [
  { id: 1, label: "Main Gate" },
  { id: 7, label: "Sports Complex Gate" },
];
check("selected gate → server-provided label",
  resolveGateLabel(round1Gates, 7, null, true) === "Sports Complex Gate",
  resolveGateLabel(round1Gates, 7, null, true));
check("loaded + no selection → 'Choose a gate' (never Loading gates...)",
  resolveGateLabel(round1Gates, null, null, true) === "Choose a gate",
  resolveGateLabel(round1Gates, null, null, true));
check("still loading → 'Loading gates...' (honest initial state)",
  resolveGateLabel([], null, null, false) === "Loading gates...");
check("load error → 'Gate unavailable'",
  resolveGateLabel([], null, "network down", true) === "Gate unavailable");
check("stale gate id after reload → 'Choose a gate' (loaded)",
  resolveGateLabel(round1Gates, 99, null, true) === "Choose a gate");

console.log("Seeded scan-result proof (real /api/scan response shapes)");
// Fixtures are the EXACT response shapes app/web/routes.py process_scan
// returns for the seeded roster/guests — no invented identities.
const proofStudent = classifyScanResult({
  status: "ok", level: "green", title: "ENTRY RECORDED",
  name: "Muhammad Ahmed", sub: "LGU-2024-102, BS Computer Science, Male",
  gate: "Main Gate", time: "2026-10-05 12:00:00",
});
check("valid student → valid / VALID / Entry / success + identity intact",
  proofStudent.kind === "valid" && proofStudent.stateTitle === "VALID" &&
    proofStudent.action === "Entry" && proofStudent.haptic === "success",
  JSON.stringify(proofStudent));
const proofGuest = classifyScanResult({
  status: "ok", level: "green", title: "GUEST ENTRY RECORDED",
  name: "Nasir Khan", sub: "Guest of LGU-2024-108 (0300-1112223)",
  gate: "Main Gate", time: "2026-10-05 12:05:00",
});
check("guest pass → guest-specific success (Guest entry) + host sub intact",
  proofGuest.kind === "valid" && proofGuest.stateTitle === "Guest entry" &&
    proofGuest.haptic === "success",
  JSON.stringify(proofGuest));
const proofUsedGuest = classifyScanResult({
  status: "error", level: "red", title: "ALREADY USED",
  detail: "Tariq Mehmood: this guest pass was already used. One entry per guest.",
  name: "Tariq Mehmood", gate: "Main Gate", time: "2026-10-04 00:08:59",
});
check("used guest pass → already-used / 'Already used' / error",
  proofUsedGuest.kind === "already-used" && proofUsedGuest.stateTitle === "Already used" &&
    proofUsedGuest.haptic === "error",
  JSON.stringify(proofUsedGuest));
const proofDupStudent = classifyScanResult({
  status: "error", level: "red", title: "ALREADY INSIDE",
  detail: "Muhammad Ahmed (LGU-2024-102) already entered at Main Gate, 2026-10-05 12:00:00.",
  name: "Muhammad Ahmed", gate: "Main Gate", time: "2026-10-05 12:00:00",
});
check("duplicate student scan → already-used (ALREADY INSIDE)",
  proofDupStudent.kind === "already-used" && proofDupStudent.stateTitle === "Already used",
  JSON.stringify(proofDupStudent));

// --- Phase 23 §2: transient SQLite contention (backend "busy") ------------
// The backend answers HTTP 503 with {status:"busy", level:"amber",
// title:"TEMPORARILY BUSY", detail, retryable:true}. These checks pin the
// volunteer-facing contract: contention is a notice to retry, never a gate
// outcome, and never an error haptic (which reads as "your scan broke").
const proofBusy = classifyScanResult({
  status: "busy", level: "amber", title: "TEMPORARILY BUSY",
  detail: "The system is busy right now. Please retry this scan.",
});
check("busy → notice card with the backend's own title",
  proofBusy.kind === "other" && proofBusy.stateTitle === "TEMPORARILY BUSY",
  JSON.stringify(proofBusy));
check("busy → warning haptic, never success or error",
  proofBusy.haptic === "warning", JSON.stringify(proofBusy));
check("busy is never classified valid / already-used / invalid",
  proofBusy.kind !== "valid" && proofBusy.kind !== "already-used" &&
    proofBusy.kind !== "invalid", JSON.stringify(proofBusy));
// Contention must stay a notice even if a title were hostile enough to
// collide with the ALREADY / INVALID branches.
const proofBusyAlias = classifyScanResult({
  status: "busy", level: "amber", title: "ALREADY INSIDE",
});
check("busy with an outcome-shaped title is STILL just a notice",
  proofBusyAlias.kind === "other" && proofBusyAlias.haptic === "warning" &&
    proofBusyAlias.stateTitle === "ALREADY INSIDE",
  JSON.stringify(proofBusyAlias));
// An empty busy title must say TEMPORARILY BUSY, not the classifier's own
// generic "Scan failed" fallback (that wording reads as a real failure).
const proofBusyEmpty = classifyScanResult({ status: "busy", level: "amber", title: "" });
check("busy with an empty title falls back to TEMPORARILY BUSY",
  proofBusyEmpty.stateTitle === "TEMPORARILY BUSY" && proofBusyEmpty.haptic === "warning",
  JSON.stringify(proofBusyEmpty));
// Developer/infra text can never reach the operator, busy path included.
const proofBusyLeak = classifyScanResult({
  status: "busy", level: "amber", title: "Traceback http://10.0.0.5/db",
});
check("busy title leaking technical text falls back to TEMPORARILY BUSY",
  proofBusyLeak.stateTitle === "TEMPORARILY BUSY", JSON.stringify(proofBusyLeak));

// --- Phase 24D: offline queue reconciliation (permanent rejections, mutex) ---
// The queue writes to AsyncStorage with no transactions, so reconcileSync's
// read→filter→overwrite and enqueueScan's read→append→overwrite must not
// interleave or a scan added mid-reconcile is silently dropped. We compile
// offlineQueue.ts, stub AsyncStorage, and prove (a) the two convocation-era
// permanent titles are dropped, (b) transient titles are kept, and (c) a scan
// enqueued while reconcile is in flight survives.
console.log("Offline queue reconcile (Phase 24D) — permanent drops, transient keeps, no lost scans");
{
  const Module = require("module");
  const fakeStorage = new Map();
  const fake = {
    getItem: async (k) => (fakeStorage.has(k) ? fakeStorage.get(k) : null),
    setItem: async (k, v) => { fakeStorage.set(k, v); },
    removeItem: async (k) => { fakeStorage.delete(k); },
  };
  fake.default = fake; // match either interop shape tsc emits
  const originalLoad = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === "@react-native-async-storage/async-storage") return fake;
    return originalLoad.apply(this, arguments);
  };
  try {
    execFileSync(
      process.execPath,
      [tsc, join(root, "src", "store", "offlineQueue.ts"), "--outDir", outDir,
        "--module", "commonjs", "--target", "es2020", "--skipLibCheck",
        "--esModuleInterop"],
      { stdio: ["ignore", "pipe", "pipe"] },
    );
  } catch (e) {
    check("offlineQueue.ts compiles", false, e.stderr?.toString() ?? e.message);
  }
  const q = require(join(outDir, "offlineQueue.js"));
  check("PERMANENT_REJECTIONS contains ALREADY ADMITTED (convocation replay)",
    q.PERMANENT_REJECTIONS.has("ALREADY ADMITTED"));
  check("PERMANENT_REJECTIONS contains GATE NOT AUTHORIZED (unauthorized gate)",
    q.PERMANENT_REJECTIONS.has("GATE NOT AUTHORIZED"));

  const mk = (payload, mode = "entry") => ({ payload, gate_id: 1, mode, volunteer: "V", scanned_at: `t-${payload}` });
  await q.clearQueue();
  await q.enqueueScan(mk("P1"));
  await q.enqueueScan(mk("P2"));
  // Reconcile: P1 accepted (ok), P2 permanently rejected (GATE NOT AUTHORIZED).
  const recP = q.reconcileSync([
    { payload: "P1", result: { status: "ok", level: "green", title: "ENTRY RECORDED" } },
    { payload: "P2", result: { status: "error", level: "red", title: "GATE NOT AUTHORIZED", detail: "no" } },
  ]);
  // While reconcile is in flight, a new offline scan lands (the real race).
  const enqP = q.enqueueScan(mk("P3", "exit"));
  const rec = await recP;
  await enqP;
  const after = await q.getQueue();
  check("reconcile counts P1 accepted, P2 rejected (positional)",
    rec.accepted === 1 && rec.rejected.length === 1 && rec.rejected[0].title === "GATE NOT AUTHORIZED",
    JSON.stringify(rec));
  check("scan enqueued during reconcile is NOT lost",
    after.some((s) => s.payload === "P3"), JSON.stringify(after));
  check("P1 (accepted) and P2 (permanent) dropped, only P3 remains",
    !after.some((s) => s.payload === "P1") && !after.some((s) => s.payload === "P2") && after.length === 1,
    JSON.stringify(after));

  // Transient failure (e.g. TEMPORARILY BUSY) must stay queued for retry.
  await q.clearQueue();
  await q.enqueueScan(mk("T1"));
  await q.enqueueScan(mk("T2"));
  const recT = await q.reconcileSync([
    { payload: "T1", result: { status: "ok", level: "green", title: "ENTRY RECORDED" } },
    { payload: "T2", result: { status: "busy", level: "amber", title: "TEMPORARILY BUSY", detail: "retry" } },
  ]);
  const kept = await q.getQueue();
  check("transient TEMPORARILY BUSY stays queued; accepted T1 dropped",
    recT.accepted === 1 && recT.rejected.length === 0 && kept.length === 1 && kept[0].payload === "T2",
    JSON.stringify({ kept }));
  await q.clearQueue();
}

console.log(`\nscanner-logic-test: ${passed} passed, ${failed} failed`);
rmSync(outDir, { recursive: true, force: true });
process.exit(failed > 0 ? 1 : 0);
