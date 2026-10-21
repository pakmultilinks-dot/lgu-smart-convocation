// Phase 35J source tests — final operational blocker pass.
// Pure-node substring pins over the mobile source (no test framework in
// mobile; the same pattern as ui-35h/35i-source-test.mjs).
// Usage (from mobile/): node scripts/ui-35j-source-test.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
// Run from repo root OR mobile/ — resolve to the mobile folder.
if (!cwd.endsWith("mobile")) cwd = root;

const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const has = (src, needle) => src.includes(needle);
// Strip comments before banned-wording scans — doc comments may explain
// what was removed (e.g. "Send to N" implied delivery). User-visible copy
// is what the mandate forbids.
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

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

// ---- PRIORITY 0: broadcast demo-mode honesty --------------------------------
console.log("P0 — Broadcast demo-mode honesty");
const broadcast = read("src/screens/BroadcastScreen.tsx");
check(
  "banner at the top: 'Demo mode — announcements are saved only'",
  has(broadcast, "Demo mode — announcements are saved only") &&
    broadcast.indexOf("Demo mode — announcements are saved only") <
      broadcast.indexOf("<Field"),
);
check("primary action is mode-aware (35K G)",
  has(broadcast, "const primaryLabel = isDemo ? \"Save announcement\" : \"Send announcement\";") &&
    has(broadcast, "label={primaryLabel}"));
check(
  "confirm action names logging with the real count ('Save for ' + toLocaleString)",
  has(broadcast, "Save for ${actionCount.toLocaleString()}") ||
    has(broadcast, "`Save for ${actionCount.toLocaleString()}`"),
);
const broadcastCode = broadcast;
const broadcastNoComments = stripComments(broadcastCode);
// Backend demo behavior preserved (routes.py records, never SMS).
const routes = read("../app/web/routes.py");
check("no banned delivery wording anywhere in the screen (user-visible copy)",
  !has(broadcastNoComments, "Send to ") &&
    !has(broadcastNoComments, "Sent to ") &&
    !has(broadcastNoComments, "Message sent") &&
    !has(broadcastNoComments, "Delivered") &&
    !has(broadcastNoComments, 'label="Send announcement"'));
check("success note is rendered from the SERVER note (35K G)",
  has(broadcast, "result.note ?? \"Announcement recorded.\"") &&
    has(routes, "Demo mode: not sent by SMS"));
check("confirm sheet repeats the demo-mode reality",
  has(broadcast, "Demo mode: recorded in the broadcast log only"));

check("backend demo message preserved (recorded, not SMS)",
  has(routes, "Demo mode: messages are recorded here, not sent by SMS."));
check("backend broadcast POST still requires X-Admin-Pin",
  has(routes, "X-Admin-Pin") && has(routes, "Administrator access required"));

// ---- A: dashboard gate-row geometry ----------------------------------------
console.log("A — Dashboard gate-row geometry");
const liveboard = read("src/screens/LiveBoardScreen.tsx");
check("count shares the gate-name line (inside gateHeadRow)",
  has(liveboard, "<Text style={styles.gateCount}>{g.count}</Text>") &&
    liveboard.indexOf("<Text style={styles.gateCount}>{g.count}</Text>") <
      liveboard.indexOf("gateBarRow") + 400 ||
    (!has(liveboard, "gateBarRow") &&
      has(liveboard, "gateHeadRow") &&
      has(liveboard, "gateCount")));
check("6px bar sits underneath, full width (no wrap+count row)",
  has(liveboard, "height={6}") &&
    has(liveboard, "trackColor={BOARD_TRACK}") &&
    !has(liveboard, "gateBarWrap"));
check("all 7 gates render (no slice/take) — backend sends every gate",
  !has(liveboard, ".slice(") && !has(liveboard, ".take("));
check("board does not scroll; footer pinned",
  has(liveboard, "<Screen scroll={false}>") &&
    has(liveboard, 'marginTop: "auto" as const'));

// ---- B/C/D/E: dashboard values + freshness ---------------------------------
console.log("B–E — Dashboard values, hero, labels, freshness");
check("progress denominator is attendance-only (35K B): no roster fallback, no expected_total",
  liveboard.includes("progressDenominator(expected)") &&
    liveboard.includes("data?.expected_attendance ?? 0") &&
    !liveboard.includes("expected_total"));
// 33-QA (I8/I10) supersedes 35M item 3: at 360×800 the 96px hero
// pushed gates 6–7 + the Entries tail + the Updated footer below the
// fold with no visible affordance. QA fix cycle 2 dropped it further
// to 64px so 320×568 fits too — the mandated scale exception stands;
// the pixel size is QA-adjusted.
check("hero value 64px (33-QA I8/I10 board fit at 360×800 + 320×568)",
  has(liveboard, "fontSize: 64") && has(liveboard, "lineHeight: 58"));
check("offline wording uses '·' separator with last-success time",
  has(liveboard, "Offline · showing data from ${formatClock(lastOkAt)}"));
check("footer carries 12h server clock + Synced/Delayed/Offline/Connecting",
  has(liveboard, "formatServerClock(data?.generated_at)") &&
    has(liveboard, '"Synced"') &&
    has(liveboard, '"Delayed"') &&
    has(liveboard, '"Offline"') &&
    has(liveboard, '"Connecting"'));
check("offline threshold stays 30s; values retained",
  // Phase 38: the band scales with the server-suggested cadence but keeps
  // the 35I (L) 30s floor at the default 5s poll.
  has(liveboard, "Math.max(30000, pollMs * 6)"));
check("demo labels are sans 13, never mono",
  has(liveboard, "fontFamily: fonts.displayMedium") &&
    !has(liveboard, "fontFamily: fonts.mono"));

// ---- F: Home fonts ----------------------------------------------------------
console.log("F — Home readable labels");
const home = read("src/screens/HomeScreen.tsx");
check("heroEyebrow is sans displayMedium 13 (was mono 11)",
  /heroEyebrow:\s*\{[^}]*displayMedium/s.test(home) &&
    !/heroEyebrow:\s*\{[^}]*fonts\.mono/s.test(home));
check("demoItem labels are sans displayMedium 13 (was mono 11)",
  /demoItem:\s*\{[^}]*displayMedium/s.test(home) &&
    !/demoItem:\s*\{[^}]*fonts\.mono/s.test(home));
check("Home operational copy kept",
  has(home, "Inside now") &&
    has(home, "All scans synced") &&
    has(home, 'label="Scan QR Code"'));
check("Home never claims 'QR code not working?' as a label",
  !has(home, 'label="QR code not working"'));
check("no 'Send/Sent/Delivered' copy on Home",
  !has(home, "Message sent") && !has(home, "Delivered"));

// ---- G/H/I/J/K: scanner gate-required + results -----------------------------
console.log("G–K — Scanner gate-required + result states");
const scanner = read("src/screens/ScannerScreen.tsx");
const logic = read("src/scanner/scanResultLogic.ts");
const result = read("src/scanner/ScannerResult.tsx");
const sheet = read("src/scanner/ScannerSheet.tsx");
const overlay = read("src/scanner/ScannerOverlay.tsx");
const topbar = read("src/scanner/ScannerTopBar.tsx");
const bottombar = read("src/scanner/ScannerBottomBar.tsx");
check("scanGateBlocked rule exists and is a type predicate",
  has(logic, "export function scanGateBlocked(gateId: number | null): gateId is null"));
check("scanner blocks scans via scanGateBlocked (never posts/queues without gate)",
  has(scanner, "scanGateBlocked(gateId)") && has(scanner, "setSheetVisible(true)"));
check("scanner never auto-selects the first gate",
  !has(scanner, "list[0].id") && !has(scanner, "savedGateRef.current = { id: list[0]"));
check("gate sheet auto-opens when no gate is chosen",
  has(scanner, "setSheetVisible(true)"));
check("gate sheet is gate-only — no SegmentedControl inside",
  !has(sheet, "SegmentedControl"));
check("gate sheet: 2-column tiles + Done disabled until chosen",
  has(sheet, 'flexBasis: "48%"') && has(sheet, "disabled={gateId === null}"));
check("camera area ~2/3 above controls, window-driven (no fixed pixel height)",
  has(scanner, "windowH * 0.62") || has(scanner, "windowH -"));
check("scanner top bar carries gate + Entry/Exit + connection (one control area)",
  has(topbar, "gateLabel") && has(topbar, "onModeChange") && has(topbar, "online"));
check("scanner bottom bar keeps labeled Flash + Find manually → search",
  has(bottombar, "Find manually") && has(bottombar, "onFindManual"));
check("invalid main message is 'Invalid code' (both backend variants)",
  has(logic, 'stateTitle: "Invalid code"'));
check(
  "invalid detail sanitized — technical phrases never render",
  has(logic, "sanitizeInvalidDetail") &&
    has(logic, "signature|tamper|forged?|api|backend") &&
    has(result, "sanitizeInvalidDetail(result.detail)"),
);
check("operator instruction rendered: 'Do not admit. Use Find attendee.'",
  has(result, "Do not admit. Use Find attendee."));
check("invalid shows actual gate · 12h time (stamped by the device)",
  has(result, "formatServerClock(result.time)") &&
    has(scanner, "response.time = localTimestamp();"));
check("large 'Scan next' button on scan outcomes",
  has(result, '"Scan next"') && has(result, "minHeight: 56"));
check("already-used is full-surface red with name + previous gate/time",
  has(result, "fullSurface") &&
    has(result, "already-used") &&
    has(result, "colors.invalid"));
check("valid is full-surface green with name/roll + Entry/Exit + gate + time",
  has(result, "colors.valid") && has(result, "actionPill") && has(result, "fullName"));
check("no actionPillExit pale variant",
  !has(result, "actionPillExit"));
check("haptics per outcome (success/warning/error cues)",
  has(scanner, "classifyScanResult(response).haptic") &&
    has(scanner, "NotificationFeedbackType.Success") &&
    has(scanner, "NotificationFeedbackType.Warning") &&
    has(scanner, "NotificationFeedbackType.Error"));
check("invalid/already-used hold the 4s read window; valid keeps ~1.2s",
  has(scanner, 'kind === "invalid" || kind === "already-used"') &&
    has(scanner, "RESULT_DISMISS_MS") &&
    has(scanner, "SCAN_RESULT_MS"));
check("in-frame status strip stays removed",
  !has(overlay, "statusStrip") && !has(overlay, "statusDot"));
check("camera hint is sans 13",
  has(overlay, "fontSize: 13"));

// ---- Scanner Fix Round 1 (35M) — render paths + lifecycle + contrast -------
console.log("Round 1 — Flash/Find manually paths, gate label, pause/resume, contrast");
const cameraView = read("src/scanner/CameraScannerView.tsx");
const uiKit = read("src/ui/index.tsx");
check("1: Flash rendered from the active scanner permission path",
  has(scanner, "<ScannerBottomBar") && has(scanner, "torch={torch}") &&
    has(scanner, "torchSupported={torchSupported}") &&
    has(bottombar, '"Flash" : "Flash unavailable"'));
check("2: Find manually rendered from active + denied + unavailable paths",
  has(scanner, 'label="Find manually"') &&
    has(scanner, 'onFindManual={() => router.push("/(volunteer)/search")}') &&
    has(cameraView, '"Find manually"') && has(cameraView, "onFindManual") &&
    has(bottombar, "Find manually"));
check("3: gate label via pure helper — 'Loading gates...' only before load",
  has(scanner, "resolveGateLabel(gates, gateId, gatesError, gatesLoaded)") &&
    has(scanner, "setGatesLoaded(true)") &&
    // Code only — doc comments may quote the retired label.
    !has(stripComments(scanner), '"Loading gates..."') &&
    has(logic, 'return gatesLoaded ? "Choose a gate" : "Loading gates..."'));
check("4: 'Choose a gate' is the no-selection label (same words as the sheet)",
  has(logic, '"Choose a gate"') && has(sheet, "Choose a gate"));
check("5: camera pause state from sheet; listener stable across open/close",
  has(scanner, "paused={sheetVisible}") &&
    has(cameraView, "pausedRef.current = paused") &&
    has(cameraView, "onScanRef.current = onBarcodeScanned") &&
    has(cameraView, "onBarcodeScanned={handleBarcodeScanned}") &&
    !has(cameraView, "paused ? undefined"));
check("6: Entry/Exit selected state readable (ink fill + paper label via 800 family)",
  // 35M R2 (item 14 architecture update): the active label now carries
  // the 800 display family directly — RN fontWeight synthesis on the 500
  // family is banned in the kit, so pin its absence too. The inactive
  // label stays ink-on-track, and both contrast proofs below are
  // unchanged (they run on the same #F6F1E4 / #1B1A16 / #E3DCC6 values).
  has(uiKit, "segmentItemActive") && has(uiKit, "segmentLabelActive") &&
    has(uiKit, "fontFamily: fonts.display,") &&
    has(uiKit, "color: colors.paper") &&
    !has(uiKit, "fontWeight: fontWeight.") &&
    /segmentLabel: \{[^}]*color: colors\.ink/.test(uiKit));
// WCAG contrast proof for both selected and unselected states.
const lum = (h) => {
  const c = [1, 3, 5].map((i) => {
    const v = parseInt(h.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const contrast = (a, b) => {
  const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
};
check("6: contrast ratios — paper-on-ink ≥ 7:1, ink-on-track ≥ 4.5:1",
  contrast("#F6F1E4", "#1B1A16") >= 7 && contrast("#1B1A16", "#E3DCC6") >= 4.5,
  `paper/ink=${contrast("#F6F1E4", "#1B1A16").toFixed(2)} ink/track=${contrast("#1B1A16", "#E3DCC6").toFixed(2)}`);
// 35M targeted fix (item 7): the camera reserves a chrome budget so the
// Flash + Find manually controls stay visible below the camera area
// without blind scrolling on device.
check("7: camera chrome budget keeps Flash + Find manually above the fold",
  /windowH\s*-\s*330/.test(stripComments(scanner)) &&
    /Math\.max\(\s*260/.test(stripComments(scanner)) &&
    /cameraArea[\s\S]*?<ScannerBottomBar/.test(stripComments(scanner)) &&
    has(bottombar, "Find manually") && has(bottombar, '"Flash" : "Flash unavailable"'));

// ---- L/M/N/O/P: announcement behavior ---------------------------------------
console.log("L–P — Announcement by-gate + copy");
check("by-gate is multi-select (array state, toggle on press)",
  has(broadcast, "selectedGateIds") &&
    has(broadcast, "prev.filter((id) => id !== g.id)") &&
    has(broadcast, "[...prev, g.id]"));
check("by-gate tiles match the scanner sheet model (2-col ink fill + checkmark)",
  has(broadcast, 'flexBasis: "48%"') &&
    has(broadcast, "gateTileSelected") &&
    has(broadcast, 'name="checkmark"') &&
    has(broadcast, "colors.paper"));
check("selected count is explicit ('1 gate selected' / '2 gates selected')",
  has(broadcast, "gateCountText") &&
    has(broadcast, 'selectedGateIds.length === 1 ? "" : "s"'));
check("review requires at least one gate for By gate",
  has(broadcast, "selectedGateIds.length === 0") &&
    has(broadcast, "Choose at least one gate"));
check("empty state is exactly one line: 'No announcements yet.'",
  has(broadcast, "No announcements yet.") &&
    !has(broadcast, "No broadcasts yet") &&
    !has(broadcast, "EmptyState"));
check("history times use local 12h clock",
  has(broadcast, "formatLocalClock(entry.sent_at)") &&
    !has(broadcast, "formatServerClock(entry.sent_at)"));

// ---- Q/R: guests -------------------------------------------------------------
console.log("Q–R — Guests");
const guests = read("src/screens/GuestsScreen.tsx");
check("Pass action has a 48px touch target (minHeight + minWidth)",
  /passLink:\s*\{[^}]*minHeight: 48[^}]*minWidth: 48/s.test(guests) ||
    (/passLink:\s*\{[^}]*minWidth: 48[^}]*minHeight: 48/s.test(guests)));
check("Pass aligned with the guest-name row (flex-start)",
  /passLink:\s*\{[^}]*alignSelf: "flex-start"/s.test(guests));
check("Used guests still show no Pass action",
  has(guests, "{guest.used ? null : ("));
check("used-stamp is date-aware (today → time; other days → date + time)",
  has(guests, "function usedStamp(") && has(guests, "MONTHS_SHORT"));
check("Entered line composes usedStamp + gate",
  has(guests, "Entered {usedStamp(guest.used_at)}"));
check("phone masked + single-line",
  has(guests, "maskPhone") && has(guests, "numberOfLines={1}"));

// ---- T: search ----------------------------------------------------------------
console.log("T — Search");
const search = read("src/screens/SearchScreen.tsx");
check("no duplicate label above the search field",
  !has(search, 'label="Search"'));
check("native-only autofocus on entry (web never forced)",
  has(search, 'autoFocus={Platform.OS !== "web"}') &&
    has(search, "setFocusTick"));

// ---- U/V: settings + admin (35I pins — verify wording holds) -----------------
console.log("U–V — Settings + Admin");
const settings = read("src/screens/SettingsScreen.tsx");
const admin = read("src/screens/AdminScreen.tsx");
check("settings: Save enabled only when the name actually changed",
  has(settings, "nameDirty") && has(settings, "disabled={!nameDirty}"));
check("settings: no duplicate eyebrow",
  !has(settings, 'eyebrow='));
check("admin: Server connection section + resolved outcome",
  has(admin, "Server connection") &&
    (has(admin, "Using a manually saved server address") ||
      has(admin, "Server found automatically")));
check("admin: two separated sections (connection + convocation details)",
  has(admin, "Server connection") && has(admin, "Convocation details"));
check("admin: health probe runs on load (resolve the server, not a saved IP only)",
  has(admin, "/api/health"));

// ---- W/X/Y/Z: kit + fonts + config -------------------------------------------
console.log("W–Z — Kit, fonts, config");
const kit = read("src/ui/index.tsx");
const typography = read("src/theme/typography.ts");
const layout = read("app/_layout.tsx");
const appJson = read("app.json");
const pkg = read("package.json");
check("kit: Screen is safe-area aware (SafeAreaView edges)",
  has(kit, "SafeAreaView") && has(kit, 'edges'));
check("kit: SectionEyebrow has no rule/markup",
  !has(kit, "eyebrowRule"));
check("fonts: four explicit families loaded in _layout",
  has(layout, "BricolageGrotesque_500Medium") &&
    has(layout, "BricolageGrotesque_800ExtraBold") &&
    has(layout, "DMMono_400Regular") &&
    has(layout, "DMMono_500Medium"));
check("fonts: distinct family constants in the theme",
  has(typography, 'display: "BricolageGrotesque_800ExtraBold"') &&
    has(typography, 'displayMedium: "BricolageGrotesque_500Medium"') &&
    has(typography, 'mono: "DMMono_400Regular"') &&
    has(typography, 'monoMedium: "DMMono_500Medium"'));
check("fonts: announcement sheet title uses Bricolage sectionTitle preset",
  has(broadcast, "sheetTitle: [text.sectionTitle") &&
    has(typography, "sectionTitle:") &&
    has(typography, "fontFamily: fonts.display,"));
check("config: no androidNavigationBar control claimed (documented honestly)",
  !has(appJson, "androidNavigationBar") && !has(pkg, "expo-navigation-bar"));
check("config: splash keeps cream backgroundColor + contain",
  has(appJson, '"backgroundColor": "#F6F1E4"') && has(appJson, '"resizeMode": "contain"'));

// ---- AA/AB/AC: isolation + cleanup -------------------------------------------
console.log("AA–AC — Isolation + cleanup pins");
const client = read("src/api/client.ts");
const settingsStore = read("src/store/settings.ts");
const cleanup = read("../app/scripts/cleanup_test_fixtures.py");
const apitest = read("scripts/api-test.mjs");
check("single volunteer-name storage key",
  has(settingsStore, 'KEY_VOLUNTEER_NAME = "lgu.volunteer_name"'));
check("broadcast sent_by uses the stored volunteer name",
  has(broadcast, "getVolunteerName") && has(broadcast, "sent_by"));
check("cleanup script never targets 'Bulsl' (user value, not a test fixture)",
  !has(cleanup, "Bulsl") &&
    has(cleanup, '"ApiTest"') &&
    has(cleanup, '"Test Guest %"'));
check("api-test harness uses an isolated temp DB + production stamp",
  has(apitest, "mkdtemp") &&
    has(apitest, "LGU_TESTING") &&
    has(apitest, "LGU_DB_PATH"));
check("client attaches X-Admin-Pin for broadcast POST",
  has(client, "X-Admin-Pin"));

// ---- Summary ------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
