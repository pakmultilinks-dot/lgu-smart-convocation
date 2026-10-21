/**
 * 33-QA release-blocker fix cycle — P6 cluster regression test.
 * Pins Issues 15–18 at source level:
 *   I15 by-gate audience ordering — per_gate breakdown (count DESC, ties
 *       label ASC) from models → routes → client → composer UI
 *   I16 truthful connection state — freshnessState never reads live on a
 *       failed refresh; Admin/Settings probe verdicts are timestamped;
 *       the Settings pill reports a real probe (LIVE/OFFLINE/CHECKING),
 *       never "READY" from queue state; offline queue copy is honest
 *   I17 dashboard metric naming — windowed "Entries … in the last N min"
 *       caption; Home "Guests inside" (guests_inside, not roster guests)
 *   I18 announcement naming — More row, history eyebrow/error, web nav +
 *       web page + PERSISTENT web demo banner (not post-POST only)
 * Run: node scripts/layout-p6-source-test.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOBILE = join(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = dirname(MOBILE);

function read(rel) {
  return readFileSync(join(ROOT, rel), "utf8");
}
function has(src, needle) {
  return src.includes(needle);
}

let failures = 0;
let passed = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
  else passed += 1;
}

console.log("33-QA P6 truth/naming regression test (Issues 15-18)\n");

const modelsPy = read("app/models.py");
const routesPy = read("app/web/routes.py");
const client = read("mobile/src/api/client.ts");
const broadcast = read("mobile/src/screens/BroadcastScreen.tsx");
const kit = read("mobile/src/ui/index.tsx");
const admin = read("mobile/src/screens/AdminScreen.tsx");
const settingsScreen = read("mobile/src/screens/SettingsScreen.tsx");
const settingsStore = read("mobile/src/store/settings.ts");
const liveboard = read("mobile/src/screens/LiveBoardScreen.tsx");
const home = read("mobile/src/screens/HomeScreen.tsx");
const more = read("mobile/src/screens/MoreScreen.tsx");
const baseHtml = read("app/web/templates/base.html");
const broadcastHtml = read("app/web/templates/broadcast.html");

// ---- I15: per-gate audience ordering ---------------------------------------
console.log("I15 - by-gate audience ordering");
check(
  "models.broadcast_audience builds a per_gate list",
  has(modelsPy, "per_gate = []") &&
    has(modelsPy, "_announcement_audience(db, [gid])") &&
    has(modelsPy, 'return {"count": count, "basis": basis, "per_gate": per_gate}'),
);
check(
  "per_gate is ordered count DESC, ties label ASC (stable across refreshes)",
  has(modelsPy, 'per_gate.sort(key=lambda g: (-g["count"], g["label"]))'),
);
check(
  "routes return per_gate alongside count + basis",
  has(routesPy, '"per_gate": audience["per_gate"]'),
);
check(
  "audience route keeps its path + unknown-gate 400 guard",
  has(routesPy, '@bp.route("/api/broadcast/audience")') &&
    has(routesPy, '"Unknown gate id(s): %s."'),
);
check(
  "client declares BroadcastGateAudience + optional per_gate",
  has(client, "export interface BroadcastGateAudience {") &&
    has(client, "per_gate?: BroadcastGateAudience[];"),
);
check(
  "composer carries the breakdown through to render + styles it",
  has(broadcast, "type BroadcastGateAudience,") &&
    has(broadcast, "per_gate: res.per_gate") &&
    has(broadcast, "gateAudience?.per_gate") &&
    has(broadcast, "styles.gateAudienceBreakdown") &&
    has(broadcast, "styles.gateAudienceLine") &&
    // QA fix cycle 2: per-gate line names the live count plainly.
    has(broadcast, "{g.label} · {g.count.toLocaleString()} inside now"),
);

// ---- I16: truthful connection state ----------------------------------------
console.log("I16 - truthful connection state");
check(
  "freshnessState downgrades a failed refresh immediately (never live)",
  has(kit, "if (online === false && lastOkAt > 0) {") &&
    has(kit, 'return offlineMs > 0 && age < offlineMs ? "stale" : "offline";'),
);
check(
  "freshnessState keeps the 35I L delayed-offline contract (ui-35i needles)",
  has(kit, "offlineMs = 0") && has(kit, "const age = now - lastOkAt"),
);
check(
  "AdminScreen stamps every probe verdict with the probe time",
  has(admin, "function probeNoteFor(reachable: boolean): string {") &&
    (admin.match(/setProbeNote\(probeNoteFor\(/g) || []).length >= 4 &&
    has(admin, "formatClock"),
);
check(
  "SettingsScreen probes the effective server on focus",
  has(settingsScreen, "probeBackend") &&
    has(settingsScreen, 'setProbe("checking")') &&
    has(settingsScreen, "setTestedAt(Date.now());"),
);
check(
  "Settings pill is the probe verdict — sentence case (QA fix cycle 2), no READY",
  has(settingsScreen, 'probe === "ok" ? "Live" : probe === "down" ? "Offline" : "Checking"') &&
    // The old queue-derived pill literal is gone (the word READY may
    // still appear in explanatory comments).
    !has(settingsScreen, '"READY"}'),
);
check(
  "Settings row carries the Tested timestamp + honest offline queue copy",
  has(settingsScreen, "Tested {formatClock(testedAt)}") &&
    has(settingsScreen, '"No scans waiting to sync · server unreachable"') &&
    has(settingsScreen, "cloud-offline-outline"),
);
check(
  "probeBackend is exported for the settings surface",
  has(settingsStore, "export async function probeBackend"),
);

// ---- I17: dashboard metric naming ------------------------------------------
console.log("I17 - dashboard metric naming");
check(
  "LiveBoard Entries tail is window-qualified from the server window",
  has(liveboard, "` in the last ${windowMinutes} min`") &&
    has(liveboard, ': " across all gates"'),
);
check(
  "LiveBoard keeps the server-driven windowLabel + 64px hero (QA fix cycle 2)",
  has(liveboard, "windowLabel") && /fontSize: 64,/.test(liveboard),
);
check(
  "Home guests metric says Guests inside (guests_inside, not roster)",
  has(home, "Guests inside <Text") && !has(home, ">Guests <Text"),
);
check(
  "Home keeps the pinned Inside now hero label",
  has(home, "heroEyebrow}>Inside now<"),
);

// ---- I18: announcement naming + persistent web demo banner -----------------
console.log("I18 - announcement naming");
check(
  "More row is Announcements (subtitle unchanged)",
  has(more, 'title="Announcements"') &&
    has(more, 'subtitle="Send an announcement"') &&
    has(more, 'router.push("/(volunteer)/broadcast")'),
);
check(
  "BroadcastScreen history naming is announcement-first",
  has(broadcast, "<SectionEyebrow>Recent announcements</SectionEyebrow>") &&
    has(broadcast, "Announcement history could not be loaded.") &&
    !has(broadcast, "Recent broadcasts") &&
    !has(broadcast, "Broadcast history could not be loaded."),
);
check(
  "BroadcastScreen pinned demo honesty strings survive (ui-35j/navigation)",
  has(broadcast, "Demo mode — announcements are saved only") &&
    broadcast.indexOf("Demo mode — announcements are saved only") <
      broadcast.indexOf("<Field") &&
    has(broadcast, 'const primaryLabel = isDemo ? "Save announcement" : "Send announcement";') &&
    has(broadcast, 'result.note ?? "Announcement recorded."') &&
    has(broadcast, "Demo mode: recorded in the broadcast log only"),
);
check(
  "web nav + web page are Announcement-first",
  has(baseHtml, ">Announcement</a>") && !has(baseHtml, ">Broadcast</a>") &&
    has(broadcastHtml, "Announcement | {{ APP_NAME }}") &&
    has(broadcastHtml, '<h1 class="page-title">Announcement</h1>') &&
    has(broadcastHtml, "Send announcement") &&
    !has(broadcastHtml, "Send broadcast"),
);
check(
  "web demo banner is persistent (rendered from broadcast_mode, not msg)",
  has(broadcastHtml, '{% if broadcast_mode == "demo" %}') &&
    has(broadcastHtml, "<strong>Demo mode</strong> — messages are only logged here") &&
    broadcastHtml.indexOf('broadcast_mode == "demo"') <
      broadcastHtml.indexOf("<form method=\"post\">"),
);
check(
  "routes pass broadcast_mode to the template; log copy is announcements",
  has(routesPy, "broadcast_mode=config.BROADCAST_MODE") &&
    has(broadcastHtml, "No announcements sent yet."),
);

console.log(`\nDone: ${passed} passed, ${failures} failure(s).`);
process.exit(failures > 0 ? 1 : 0);
