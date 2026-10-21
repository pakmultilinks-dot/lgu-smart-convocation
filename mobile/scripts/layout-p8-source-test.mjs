// 33-QA P8 source tests — release blocker fix cycle, Issues 26–33
// (contrast, server-address field, offline toggle, launch cards, status
// pill readability, yellow underline, seal mark, stray dot).
// Pure-node substring pins over mobile source + brand assets — the same
// harness family as ui-35h/35i/35j/… and layout-p5/p6/p7.
// Usage (from mobile/): node scripts/layout-p8-source-test.mjs
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
// Run from repo root OR mobile/ — resolve to the mobile folder.
if (!cwd.endsWith("mobile")) cwd = root;

const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const has = (src, needle) => src.includes(needle);

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

// WCAG contrast math (same implementation as ui-35j-source-test.mjs).
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

// ---- P8-26: semantic tokens pass 4.5:1 as text AND as grounds ----------
console.log("P8-26 — button / text contrast tokens");
const colors = read("src/theme/colors.ts");
check("valid token darkened to #177245 (web --green)", has(colors, 'valid: "#177245"'));
check("invalid token darkened to #B3261E (web --red)", has(colors, 'invalid: "#B3261E"'));
check("amber token darkened to #7C5A15", has(colors, 'amber: "#7C5A15"'));
check(
  "old failing values gone from the palette assignments",
  !/valid:\s*"#1E8A4C"/.test(colors) &&
    !/invalid:\s*"#C93A2E"/.test(colors) &&
    !/amber:\s*"#9A6B1A"/.test(colors),
);
const paper = "#F6F1E4";
for (const [name, hex, floor] of [
  ["valid", "#177245", 4.5],
  ["invalid", "#B3261E", 4.5],
  ["amber", "#7C5A15", 4.5],
]) {
  const r = contrast(paper, hex);
  check(
    `contrast paper↔${name} ≥ ${floor}:1 (both directions — token text on paper AND paper text on token bg)`,
    r >= floor,
    `${name}=${r.toFixed(2)}`,
  );
}
// QA fix cycle 4 (Finding 2): the Entry/Exit SegmentedControl now
// carries a semantic ACCENT on the active segment — green for entry,
// amber for exit. This is the mode PRESENTATION only; the valid/invalid
// tokens above still carry SCAN-RESULT semantics in ScannerResult and
// must not be reused as mode chrome elsewhere.
const topbar = read("src/scanner/ScannerTopBar.tsx");
check(
  "scanner mode control accents the active mode (green entry / amber exit)",
  has(topbar, "SegmentedControl") &&
    has(topbar, 'activeColor={mode === "exit" ? colors.amber : colors.valid}'),
);
check(
  "gate-label body tier stays 15px (4.5:1 rule applies)",
  has(topbar, "fontSize: 15"),
);
// Danger buttons / error text keep their semantic reference — the token
// behind them is what changed.
const ui = read("src/ui/index.tsx");
check(
  "AppButton danger still maps to the invalid token",
  has(ui, 'danger: { bg: "transparent", fg: colors.invalid, border: colors.invalid }'),
);

// ---- P8-27: server address field shows the effective server -------------
console.log("P8-27 — server address field");
const admin = read("src/screens/AdminScreen.tsx");
check(
  "effectiveUrl state exists",
  has(admin, "const [effectiveUrl, setEffectiveUrl] = useState(\"\")"),
);
check(
  "effective server recorded on load and after Automatic reset",
  (admin.match(/setEffectiveUrl\(effective\)/g) ?? []).length >= 2,
);
check(
  "auto mode placeholder shows the effective address",
  has(admin, "mode === \"custom\" || !effectiveUrl") && has(admin, ": effectiveUrl"),
);
check(
  "operator label stays 'Server address' (35I W.2 — never 'backend')",
  has(admin, 'label="Server address"'),
);

// ---- P8-28: offline toggle carries an accessible name -------------------
console.log("P8-28 — offline toggle");
const bottombar = read("src/scanner/ScannerBottomBar.tsx");
check(
  "Switch has accessibilityLabel 'Offline mode'",
  has(bottombar, "accessibilityLabel=\"Offline mode\""),
);
check(
  "Switch has accessibilityHint describing queue-later behavior",
  has(bottombar, "accessibilityHint=\"Queue scans on this device and sync later\""),
);
// QA fix cycle 3 (Issue 1): network truth is separate from the offline
// preference; the explanation is full; on/off are distinct states.
const scannerscreen = read("src/screens/ScannerScreen.tsx");
check(
  "bottom bar receives the real network status (online prop)",
  has(bottombar, "online: boolean | null") &&
    has(scannerscreen, "online={online}"),
);
check(
  "connection label shows real state — syncing / offline / online / connecting",
  /syncing\s*\?\s*"Syncing"\s*:\s*online === false\s*\?\s*"Offline"\s*:\s*online\s*\?\s*"Online"\s*:\s*"Connecting"/.test(bottombar),
);
check(
  "offline preference states the full explanation on/off (distinct states)",
  has(bottombar, "On. Scans are saved on this phone and sent later.") &&
    has(bottombar, "Off. Scans send right away."),
);
check(
  "scanner offline banner reads 'Offline' + 'N scans waiting'",
  has(scannerscreen, '${online === false ? "Offline" : "Waiting to sync"}. ${queued} scan${queued === 1 ? "" : "s"} waiting.') &&
    has(scannerscreen, ': "Waiting to sync"'),
);
check(
  "Switch keeps palette track/thumb colors",
  has(bottombar, "trackColor={{ false: colors.track, true: colors.ink }}") &&
    has(bottombar, "thumbColor={colors.paper}"),
);

// ---- P8-29: launch choices read as cards --------------------------------
console.log("P8-29 — launch cards");
const picker = read("app/mode-picker.tsx");
check(
  "choice rows carry a card treatment (track border + radius + padding)",
  has(picker, "borderColor: colors.track") &&
    has(picker, "borderRadius: radius.sm") &&
    has(picker, "paddingHorizontal: spacing.md") &&
    has(picker, "backgroundColor: colors.paper"),
);
check(
  "dashed divider style removed — cards separate themselves",
  !has(picker, "choiceDivider"),
);
check(
  "screen title stays fontSize 20 display (ui-35m pin preserved)",
  /title:\s*\{[^}]*fontSize: 20/.test(picker),
);
check(
  "university line stays displayMedium sans (ui-35m pin preserved)",
  /university:\s*\{[^}]*fontFamily: fonts\.displayMedium/.test(picker),
);

// ---- P8-30: status pill readability -------------------------------------
console.log("P8-30 — status pill readability");
check(
  "pill container sits on the track fill (visible chip on paper)",
  /pill:\s*\{[\s\S]*?backgroundColor: colors\.track/.test(ui),
);
check(
  "pill label carries an explicit ink color",
  has(ui, "pillLabel: {") && has(ui, "color: colors.ink"),
);
check(
  "StatusPill text applies styles.pillLabel",
  has(ui, "styles.pillLabel"),
);
check(
  "semantic dot map preserved (all 10 states)",
  has(ui, "live: colors.valid") && has(ui, "invalid: colors.invalid") &&
    has(ui, "connecting: colors.muted"),
);

// ---- P8-31: yellow underline removed from the tab bar -------------------
console.log("P8-31 — tab bar indicator");
const layout = read("app/(volunteer)/_layout.tsx");
check(
  "active tab underline is ink — no gold underline on every screen",
  /tabUnderlineActive:\s*\{[\s\S]*?backgroundColor: colors\.ink/.test(layout) &&
    !/tabUnderlineActive:\s*\{[\s\S]*?backgroundColor: colors\.gold/.test(layout),
);
check(
  "underline geometry unchanged (22×2, transparent when inactive)",
  has(layout, "width: 22") && has(layout, "height: 2") &&
    has(layout, "backgroundColor: \"transparent\""),
);
check(
  "gold rule kept on the mode-picker (one thin marker, launch screen)",
  has(picker, "backgroundColor: colors.gold"),
);

// ---- P8-32: seal mark — one source, paper surfaces ----------------------
console.log("P8-32 — seal mark simplification");
const brand = read("scripts/make-brand-assets.py");
check(
  "brand assets build from the authoritative transparent seal",
  has(brand, "SEAL = ASSETS / \"lgu-logo.png\""),
);
check(
  "splash is composited on paper — no dark ground baked in",
  has(brand, "PAPER = (246, 241, 228, 255)") &&
    has(brand, "im = Image.new(\"RGBA\", (w, h), PAPER)"),
);
const appjson = read("app.json");
check(
  "app.json still pins splash resizeMode contain + paper background",
  has(appjson, '"resizeMode": "contain"') &&
    has(appjson, '"backgroundColor": "#F6F1E4"'),
);
check(
  "LguMark still renders assets/lgu-logo.png (single seal source)",
  has(ui, "require(\"../../assets/lgu-logo.png\")"),
);
for (const f of ["lgu-logo.png", "splash.png", "icon.png", "adaptive-icon.png", "favicon.png"]) {
  check(`asset exists: ${f}`, existsSync(join(cwd, "assets", f)));
}

// ---- P8-33: stray dot — pill + toggle read as labeled controls ----------
console.log("P8-33 — stray dot");
check(
  "pill dot now sits inside a visible track chip (P8-30 wiring)",
  /pill:\s*\{[\s\S]*?backgroundColor: colors\.track/.test(ui) &&
    has(ui, "pillDot: {"),
);
check(
  "scanner offline switch is named (dot/toggle never anonymous)",
  has(bottombar, "accessibilityLabel=\"Offline mode\""),
);
check(
  "web favicon source configured (assets/favicon.png)",
  has(appjson, '"favicon": "./assets/favicon.png"'),
);

// ---- summary -------------------------------------------------------------
console.log("");
console.log(`LAYOUT-P8 RESULT: ${passed}/${failed}`);
if (failed > 0) process.exit(1);
