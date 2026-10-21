/**
 * Phase 29 — annual convocation lifecycle + complete student dashboard
 * (mobile half). SOURCE-level pins (no device/emulator here); tsc + lint
 * gate the code, this suite gates the contract at source.
 *
 * Backend proof: app/scripts/test_phase29_annual_event_and_student.py
 *
 * Run from mobile/:  node scripts/phase29-annual-event-source-test.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOBILE = join(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = dirname(MOBILE);

const read = (rel) => readFileSync(join(ROOT, rel), "utf8");
const has = (src, needle) => src.includes(needle);

let failures = 0;
let passed = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
  else passed += 1;
}

console.log("Phase 29 - annual event + student dashboard (mobile source pins)\n");

const client = read("mobile/src/api/client.ts");
const scannerScreen = read("mobile/src/screens/ScannerScreen.tsx");
const topBar = read("mobile/src/scanner/ScannerTopBar.tsx");
const ops = read("mobile/src/store/ops.ts");
const queue = read("mobile/src/store/offlineQueue.ts");
const cooldown = read("mobile/src/scanner/scanCooldown.ts");
const scanLogic = read("mobile/src/scanner/scanResultLogic.ts");
const countdown = read("mobile/src/components/EventCountdown.tsx");
const eventApi = read("mobile/src/api/eventApi.ts");
const eventScreen = read("mobile/app/(student)/event.tsx");
const homeScreen = read("mobile/app/(student)/home.tsx");
const passScreen = read("mobile/app/(student)/pass.tsx");

// ---- 1. one Occasion type, stamped on every scan ---------------------------
console.log("1 - the scan payload records which occasion it admits");
check(
  "client.ts declares Occasion as the two literal occasions",
  has(client, 'export type Occasion = "rehearsal" | "ceremony";'),
);
check("postScan payload carries occasion", has(client, "occasion: Occasion;"));
check(
  "ScannerScreen stamps scanPayload with the confirmed occasion",
  has(scannerScreen, "occasion,") && has(scannerScreen, "scanPayload({"),
);
check(
  "scanPayload stamps the occasion onto the outgoing payload",
  has(scanLogic, 'occasion: "rehearsal" | "ceremony";') &&
    has(scanLogic, "occasion: input.occasion,"),
);
check(
  "a rehearsal success reads as its own state title",
  has(scanLogic, 'upper.includes("REHEARSAL")') &&
    has(scanLogic, '"Rehearsal entry"'),
);

// ---- 2. occasion switch is a confirmed action ------------------------------
console.log("\n2 - switching occasion needs explicit confirmation");
check(
  "TopBar offers both occasions with honest labels",
  has(topBar, '{ label: "Main convocation", value: "ceremony" }') &&
    has(topBar, '{ label: "Rehearsal", value: "rehearsal" }'),
);
check(
  "rehearsal selection is visually distinct (amber)",
  has(topBar, 'occasion === "rehearsal" ? colors.amber : colors.valid'),
);
check(
  "ScannerScreen keeps a pending occasion awaiting confirmation",
  has(scannerScreen, "const [occasionSwitchPending, setOccasionSwitchPending] ="),
);
check(
  "requestOccasionChange never flips directly",
  has(scannerScreen, "if (next === occasion) return;") &&
    has(scannerScreen, "setOccasionSwitchPending(next);"),
);
check(
  "confirmOccasionChange persists only after confirmation",
  has(scannerScreen, "void setScanOccasion(next);"),
);
check(
  "confirmation modal names the target occasion",
  has(scannerScreen, "`Switch to ${occasionSwitchPending === \"rehearsal\" ? \"Rehearsal\" : \"Main convocation\"}?`"),
);
check(
  "modal is visible exactly while a switch is pending",
  has(scannerScreen, "visible={occasionSwitchPending !== null}"),
);

// ---- 3. occasion persists across scanner restarts --------------------------
console.log("\n3 - the chosen occasion survives an app restart");
check(
  "ops.ts stores the occasion under its own key",
  has(ops, 'const KEY_SCAN_OCCASION = "lgu.ops_scan_occasion";'),
);
check(
  "getScanOccasion reads it (fail-closed default)",
  has(ops, "export async function getScanOccasion(): Promise<ScanOccasion>"),
);
check(
  "setScanOccasion writes it",
  has(ops, "export async function setScanOccasion(occasion: ScanOccasion)"),
);
check(
  "ScannerScreen loads the saved occasion on mount",
  has(scannerScreen, "getScanOccasion(),") &&
    has(scannerScreen, "setOccasion(savedOccasion);"),
);

// ---- 4. offline queue: occasion is part of the record ----------------------
console.log("\n4 - offline queue keeps occasion honest");
check(
  "queued rows carry an occasion (legacy rows default to ceremony)",
  has(queue, 'export type QueuedOccasion = "rehearsal" | "ceremony";') &&
    has(queue, "occasion: QueuedOccasion;"),
);
check(
  "dedup key includes occasion — same pass twice on one occasion is a dup",
  has(queue, '(q.occasion ?? "ceremony") === item.occasion'),
);
check(
  "REHEARSAL NOT SCHEDULED is a permanent rejection (never retried)",
  has(queue, '"REHEARSAL NOT SCHEDULED"'),
);
check(
  "UNKNOWN OCCASION is a permanent rejection (never retried)",
  has(queue, '"UNKNOWN OCCASION"'),
);
check(
  "permanent rejections are consumed by the drain path",
  has(queue, "PERMANENT_REJECTIONS.has(r.title)"),
);
check(
  "offlineQueue does not import client.ts (standalone-compilable)",
  !has(queue, 'from "../api/client"'),
);

// ---- 5. cooldown key includes occasion -------------------------------------
console.log("\n5 - the repeat-scan cooldown is occasion-aware");
check(
  "shouldSuppressRepeat takes occasion as an argument",
  has(cooldown, "export function shouldSuppressRepeat(") &&
    has(cooldown, "occasion: string,"),
);
check(
  "same pass on a different occasion is NOT suppressed",
  has(cooldown, "last.occasion === occasion &&"),
);

// ---- 6. countdown honesty ---------------------------------------------------
console.log("\n6 - the countdown never fabricates a schedule");
check(
  "pickNextOccasion only picks announced/confirmed occasions",
  has(countdown, 'o.state === "confirmed" || o.state === "announced"'),
);
check(
  "unannounced/provisional occasions never count down",
  has(countdown, 'if (o.state === "not_announced" || o.state === "expected") return null;'),
);
check(
  "a passed occasion reads Completed — never a negative count",
  has(countdown, 'if (o.phase === "completed") return "Completed";'),
);
check(
  "no published start time → days only, no fake clock",
  has(countdown, "No published start time: days only") &&
    has(countdown, 'o.days_until === 1 ? "" : "s"'),
);
check(
  "a started instant reads Happening now, not a negative timer",
  has(countdown, '"Happening now"'),
);
check(
  "the clock ticks only when there is something to show",
  has(countdown, "if (!live) return;") &&
    has(countdown, "setInterval(() => setNow(Date.now()), 1000)"),
);
check(
  "EventCountdown renders nothing without an occasion or text",
  has(countdown, "if (!next || !text) return null;"),
);

// ---- 7. student dashboard surfaces -----------------------------------------
console.log("\n7 - the student dashboard exposes both occasions");
check(
  "eventApi carries OccasionInfo + occasions + portal_tz",
  has(eventApi, "export interface OccasionInfo {") &&
    has(eventApi, "occasions?: OccasionInfo[];") &&
    has(eventApi, "portal_tz?: string;"),
);
check(
  "event screen shows the server-computed countdown",
  has(eventScreen, "<EventCountdown") &&
    has(eventScreen, "occasions={event.occasions}"),
);
check(
  "event screen lists the annual cycle with per-occasion state",
  has(eventScreen, "<SectionEyebrow>Annual cycle</SectionEyebrow>") &&
    has(eventScreen, "event.occasions.map((o) => ("),
);
check(
  "each occasion pill is honest (Not announced / Provisional / Completed)",
  has(eventScreen, '"Not announced"') &&
    has(eventScreen, '"Provisional"') &&
    has(eventScreen, '"Completed"'),
);
check(
  "home loads profile and event together",
  has(homeScreen, "await Promise.all([") &&
    has(homeScreen, "eventApi.fetchEvent().catch(() => null)"),
);
check(
  // Phase 31 Part B: Home renders two separate occasion cards (rehearsal +
  // ceremony) instead of one <EventCountdown> list; the countdown still comes
  // from the fetched event via the shared useCountdown hook.
  "home renders the countdown from the fetched event",
  has(homeScreen, "useCountdown(") &&
    has(homeScreen, "<OccasionCard o={rehearsal}") &&
    has(homeScreen, "<OccasionCard o={ceremony}"),
);
check(
  "pass note states which occasions the pass applies to",
  has(passScreen, 'Applies to{" "}') &&
    has(passScreen, '"both the rehearsal and the main convocation"') &&
    has(passScreen, '"the main convocation"'),
);
check(
  "both-occasions wording only when rehearsal is actually announced",
  has(passScreen, 'o.key === "rehearsal" && o.state !== "not_announced"'),
);

console.log(`\n${passed} checks, ${failures} failures`);
process.exit(failures ? 1 : 0);