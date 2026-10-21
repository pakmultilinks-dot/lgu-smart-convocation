// Phase 35M Round 2 — audit cleanup source tests.
// One focused check per mandated audit item (16 items; item 3 is
// data-layer cleanup verified at runtime in the production pass, so its
// static half is "nothing in code re-seeds the deleted records").
// Pure-node substring/regex pins over the mobile + backend source — the
// same pattern as ui-35h/35i/35j-source-test.mjs. No test framework.
// Usage (from mobile/ OR repo root): node scripts/ui-35m-source-test.mjs
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
// Strip comments before banned-string scans — doc comments may explain
// what was removed; user-visible code is what the mandate pins.
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

console.log("Phase 35M Round 2 — audit cleanup source test\n");

const home = read("src/screens/HomeScreen.tsx");
const liveboard = read("src/screens/LiveBoardScreen.tsx");
const guestPass = read("src/screens/GuestPassScreen.tsx");
const phoneUtil = read("src/utils/phone.ts");
const appLayout = read("app/_layout.tsx");
const broadcast = read("src/screens/BroadcastScreen.tsx");
const kit = read("src/ui/index.tsx");
const typography = read("src/theme/typography.ts");
const indexTs = read("app/index.tsx");
const modePicker = read("app/mode-picker.tsx");
const appJson = read("app.json");
const pkg = read("package.json");
const sheet = read("src/scanner/ScannerSheet.tsx");
const models = read("../app/models.py");
const routes = read("../app/web/routes.py");
const client = read("src/api/client.ts");
const admin = read("src/screens/AdminScreen.tsx");
const scannerScreen = read("src/screens/ScannerScreen.tsx");
const topbar = read("src/scanner/ScannerTopBar.tsx");
const bottombarT = read("src/scanner/ScannerBottomBar.tsx");
const agents = read("AGENTS.md");

// ---- 1. Home selected-gate compact label ----------------------------------
console.log("Items 1–2 — Home hero + LiveBoard footer");
check("1: Home hero gate label is compact (~32px), clipped, toggle below",
  has(home, "heroGateRow") &&
    /heroGate:\s*\{[^}]*fontSize: 32/.test(home) &&
    has(home, 'numberOfLines={1}') &&
    has(home, 'ellipsizeMode="clip"') &&
    // QA fix cycle 2: the toggle is a DIRECT child of the hero (no
    // wrapping heroControl style) — anchor on the JSX usage, not the
    // import, so ordering still means "below the label".
    home.indexOf("heroGateRow") < home.indexOf("<SegmentedControl") &&
    !has(home, "heroControl") &&
    !has(home, "· {scanMode"));
check("2: LiveBoard footer clears the Android nav bar via safe-area insets",
  has(liveboard, "useSafeAreaInsets") &&
    has(liveboard, "Math.max(insets.bottom, 6)") &&
    has(liveboard, 'marginTop: "auto"'));

// ---- 3. Production broadcast cleanup (runtime in §21; static half) -------
console.log("Items 3–5 — Guest pass privacy + cleanup half");
check("3: deleted broadcast texts (ids 17/16) are referenced nowhere in code",
  !has(stripComments(routes), "Main event start") &&
    !has(stripComments(models), "Main event start") &&
    !has(stripComments(broadcast), "Main event start") &&
    !has(stripComments(broadcast), "\u{1F64F}"));
check("4: guest pass masks the phone with the shared guest-list convention",
  has(guestPass, "maskPhone") &&
    has(phoneUtil, "\u2022\u2022\u2022") &&
    // 33-QA (I23) supersedes the old roll-only pin — the pass names the
    // host; QA fix cycle 3 (Issue 3) renders it as a stacked passMeta row.
    has(guestPass, "passMetaText") &&
    has(guestPass, "{`Host: ${pass.host_name}`}"));
check("5: no visible Pass ID in guest-facing UI; backend QR id kept",
  !has(stripComments(guestPass), "Pass ID") &&
    has(guestPass, "pass.payload") &&
    has(client, "/api/guest-pass/"));

// ---- 6–7. Guest Pass header + exact info text ----------------------------
console.log("Items 6–7 — Guest Pass header + info text");
check("6: single Guest Pass title, native header hidden, back to mode-picker",
  /name="guest-pass"[\s\S]{0,160}headerShown: false/.test(appLayout) &&
    has(guestPass, 'title="Guest Pass"') &&
    !has(guestPass, "eyebrow=") &&
    !has(guestPass, 'statusBar="light"') &&
    has(guestPass, 'router.replace("/mode-picker")'));
check("7: single-use info text is exactly the mandated sentence",
  has(guestPass, "Single-use. Shows as used after the first scan.") &&
    !has(guestPass, "The gate scanner records it once"));

// ---- 8–10. Broadcast loading line + flat banner + subtitle ---------------
console.log("Items 8–10 — Broadcast audit fixes");
check("8: history loading is a text line; gates-loading LoadingState kept",
  has(broadcast, "Loading history...") &&
    !has(broadcast, '<LoadingState label="Loading history..." />') &&
    has(broadcast, '<LoadingState label="Loading gates..." />'));
check("9: demo banner is a flat tinted strip (no border/radius)",
  /demoBanner:\s*\{[^}]*backgroundColor: colors\.tint/.test(broadcast) &&
    !/demoBanner:\s*\{[^}]*border(Width|Color)/.test(broadcast) &&
    !/demoBanner:\s*\{[^}]*borderRadius/.test(broadcast) &&
    has(broadcast, "Demo mode \u2014 announcements are saved only"));
check("10: announcement subtitle is the mandated log-first copy",
  has(broadcast, 'subtitle="Log a message for students and volunteers"') &&
    !has(broadcast, 'subtitle="Send a message to students and volunteers"'));

// ---- 11–12. Home gate rows + sans eyebrow --------------------------------
console.log("Items 11–12 — Home gate list + eyebrow family");
check("11: gate rows compact (sm gap), fully dynamic — no hard-coded count",
  /gateRow:\s*\{[^}]*gap: spacing\.sm/.test(home) &&
    has(home, "gates.map") &&
    !has(stripComments(home), "7 gates"));
check("12: Home eyebrow is sans via AppHeader eyebrowSans; hero stays displayMedium",
  has(kit, "eyebrowSans") &&
    has(home, "eyebrowSans") &&
    /eyebrowSans:\s*\{[^}]*fontFamily: fonts\.displayMedium/.test(kit) &&
    /heroEyebrow:\s*\{[^}]*fontFamily: fonts\.displayMedium/.test(home));

// ---- 13. Splash typography + footer hint removal -------------------------
console.log("Item 13 — Splash entry screens");
check("13: university name is sans on both entry screens; footer hint gone",
  /university:\s*\{[^}]*fontFamily: fonts\.displayMedium/.test(indexTs) &&
    !/university:\s*\{[^}]*fonts\.mono/.test(indexTs) &&
    !has(indexTs, "letterSpacing: 0.6") &&
    /university:\s*\{[^}]*fontFamily: fonts\.displayMedium/.test(modePicker) &&
    !/university:\s*\{[^}]*fonts\.mono/.test(modePicker) &&
    !has(modePicker, "Your selection is saved") &&
    !has(modePicker, "hint: {"));

// ---- 14. Font loading architecture ----------------------------------------
console.log("Item 14 — Font loading architecture");
check("14: no RN fontWeight synthesis in the kit; families encode weights",
  !has(kit, "fontWeight: fontWeight.") &&
    has(typography, 'display: "BricolageGrotesque_800ExtraBold"') &&
    has(typography, 'displayMedium: "BricolageGrotesque_500Medium"') &&
    has(typography, 'mono: "DMMono_400Regular"') &&
    has(typography, 'monoMedium: "DMMono_500Medium"') &&
    has(typography, "fontFamily: fonts.display,") &&
    /segmentLabelActive:\s*\{[^}]*color: colors\.paper[^}]*fontFamily: fonts\.display/.test(kit));

// ---- 15. Android nav-bar honest documentation ----------------------------
console.log("Item 15 — Android nav-bar honesty");
check("15: no navigation-bar dependency claimed; limitation documented in-sheet",
  !has(appJson, "androidNavigationBar") &&
    !has(pkg, "expo-navigation-bar") &&
    has(sheet, "expo-navigation-bar") &&
    has(sheet, "35M R2 (item 15)"));

// ---- 16. Dynamic expected attendance --------------------------------------
console.log("Item 16 — Dynamic expected attendance");
check("16: expected attendance flows from settings (number) on every surface",
  has(home, "summary?.expected_attendance ?? 0") &&
    has(liveboard, "data?.expected_attendance ?? 0") &&
    has(models, "_expected_attendance") &&
    has(models, "student_roster_count") &&
    has(models, "announcement_audience_count"));

// ---- 17+. Targeted fix cycle (35M follow-up items) -------------------------
console.log("Targeted cycle — layout, config truth, typography");
check("17: Home Change action keeps a >=48px hit area",
  /changeAction:\s*\{[^}]*minHeight: 48/.test(home) &&
    has(home, 'accessibilityLabel="Change gate or direction"'));
check("18: gate board rows are symmetric (row padding + absolute marker)",
  /gateRow:\s*\{[^}]*paddingHorizontal: spacing\.md/.test(home) &&
    /gateMarker:\s*\{[^}]*position: "absolute"/.test(home));
check("19: Guest Pass actions pinned bottom; duplicate name removed from header",
  has(guestPass, "bottomActions") &&
    has(guestPass, "bodyScroll") &&
    has(guestPass, 'label="Share pass"') &&
    has(guestPass, '"Save as image"') &&
    !has(guestPass, "· Guest of") &&
    // QA fix cycle 3 (Issue 2): the header no longer repeats the host
    // sentence — the host lives once in the stacked passMeta rows.
    !has(guestPass, "`Guest of ${hostDisplay}`"));
check("20: Admin eyebrow sans; connection + convocation sections + sans queue count",
  has(admin, 'eyebrow="Admin"') &&
    has(admin, "eyebrowSans") &&
    has(admin, "<SectionEyebrow>Server connection</SectionEyebrow>") &&
    has(admin, "<SectionEyebrow>Convocation details</SectionEyebrow>") &&
    /connTitle:\s*\{[^}]*fontFamily: fonts\.display/.test(admin));
check("21: mono only for status chips + identifiers; rule documented in AGENTS.md",
  /gateCaption:\s*\{[^}]*fontFamily: fonts\.displayMedium/.test(topbar) &&
    /promptError:\s*\{[^}]*fontFamily: fonts\.displayMedium/.test(scannerScreen) &&
    /offlineHint:\s*\{[^}]*fontFamily: fonts\.displayMedium/.test(bottombarT) &&
    has(agents, "Typography (35M item 18)") &&
    has(agents, "status chips"));
check("22: entry screens consume server config for the event title",
  has(indexTs, "cfg?.event.name || eventTitle()") &&
    has(modePicker, "cfg?.event.name || eventTitle()") &&
    /title:\s*\{[^}]*fontSize: 20/.test(indexTs) &&
    /title:\s*\{[^}]*fontSize: 20/.test(modePicker));
// 35M item 20 trace+fix: the splash university line consumed the local
// UNIVERSITY_NAME constant even when the server value differed — it now
// reads cfg.university like Home (L188) and Guest Pass (L201).
check("23: splash university line consumes server cfg.university (35M item 20 fix)",
  has(indexTs, "cfg?.university || UNIVERSITY_NAME") &&
    has(modePicker, "cfg?.university || UNIVERSITY_NAME"));

console.log(`\nDone: ${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
