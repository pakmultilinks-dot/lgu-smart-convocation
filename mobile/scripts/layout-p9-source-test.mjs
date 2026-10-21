// 33-QA P9 source tests — release blocker fix cycle, small findings
// (typography scale, PKT time labels, guest-count labelling convention).
// Pure-node substring pins — same harness family as layout-p8-source-test.
// Usage (from mobile/): node scripts/layout-p9-source-test.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
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

// ---- P9a: typography scale -----------------------------------------------
console.log("P9a — typography scale");
const topbar = read("src/scanner/ScannerTopBar.tsx");
// User-directed scanner UI visual revert: the large mode label is gone —
// Entry/Exit is the compact SegmentedControl again (previous cleaner
// design). The scale law itself (below) is unchanged.
check(
  "scanner mode control is compact — no large standalone ENTRY/EXIT label",
  /SegmentedControl/.test(topbar) &&
    !/modeLabelText/.test(topbar) &&
    !/\bENTRY\b|\bEXIT\b/.test(
      topbar.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, ""),
    ),
);
const typo = read("src/theme/typography.ts");
check(
  "type-system header documents the full scale incl. the 13 helper tier",
  has(typo, "Type scale ONLY: 11 / 13 / 15 / 24 / 46 / 64–88"),
);
check(
  "sanctioned exceptions documented (32 heroGate, 72 hero, 21 passTitle)",
  has(typo, "heroGate") && has(typo, "32") && has(typo, "72") && has(typo, "21"),
);
const agents = read("AGENTS.md");
check(
  "AGENTS.md restates the scale + exceptions (repo law matches code)",
  has(agents, "11 / 13 / 15 / 24 / 46 / 64–88") && has(agents, "snapped to 24"),
);

// ---- P9b: PKT time labels on stakeholder surfaces ------------------------
console.log("P9b — PKT time labels");
const liveboard = read("src/screens/LiveBoardScreen.tsx");
check(
  "mobile LiveBoard Updated footer names PKT",
  has(liveboard, "PKT") && has(liveboard, "formatServerClock(data?.generated_at)"),
);
const dash = read("../app/web/templates/dashboard.html");
check(
  "web dashboard generated line carries PKT",
  has(dash, '"generated " + d.generated_at + " PKT"'),
);
check(
  "web dashboard scan-feed rows carry PKT",
  has(dash, "${escapeHtml(f.scanned_at.slice(11))} PKT"),
);
const bcast = read("../app/web/templates/broadcast.html");
check(
  "web announcement log carries PKT",
  has(bcast, "{{ b.sent_at[11:] }} PKT"),
);
const webScanner = read("../app/web/templates/scanner.html");
check(
  "volunteer ops surfaces stay unlabeled by convention (web scanner queue)",
  !has(webScanner, " PKT"),
);

// ---- P9c: guest-count labelling convention (no-defect pin) --------------
console.log("P9c — guest-count labelling");
const home = read("src/screens/HomeScreen.tsx");
check(
  "mobile Home counts guests inside (never bare 'Guests')",
  has(home, "Guests inside") && !has(home, ">Guests <"),
);
check(
  "mobile Guests screen counts registrations explicitly",
  has(read("src/screens/GuestsScreen.tsx"), "registered"),
);
check(
  "web dashboard KPI says Guests inside",
  has(dash, '<div class="lbl">Guests inside</div>'),
);
check(
  "web guests page says Registered guests",
  has(read("../app/web/templates/guests.html"), "Registered guests"),
);

// ---- P9d: queued badge contrast -----------------------------------------
// The dashboard redesign unified amber under the --amber token, mirroring
// mobile/src/theme/colors.ts (amber: "#7C5A15", darkened from #9A6B1A/#9A6A00
// which failed WCAG AA at ~4.0:1). The queued badge now colors its text with
// var(--amber) rather than a hardcoded #6b4c00. These checks therefore verify
// the real contract — token alignment + computed AA contrast — instead of
// pinning a hex that the approved redesign deliberately retired.
console.log("P9d — queued badge contrast (token-aligned, AA-verified)");
const css = read("../app/web/static/css/style.css");

// Parse a hex color out of a `--name: #hex;` custom property.
const cssVar = (name) => {
  const m = css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  return m ? m[1] : null;
};
// WCAG 2.x relative luminance + contrast ratio.
const lum = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
};
const contrast = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const amber = cssVar("amber");
const amberBg = cssVar("amber-bg");
// Web amber mirrors the committed mobile token (colors.ts is source of truth).
check(
  "web --amber mirrors mobile colors.ts amber (#7c5a15)",
  amber !== null && amber.toLowerCase() === "#7c5a15",
  `--amber=${amber}`,
);
// The badge is themed via the shared token, not a one-off literal.
check(
  "queued badge text is themed with var(--amber)",
  /\.badge\.queued[^}]*color:\s*var\(--amber\)/.test(css),
);

// Phase 18: audit EVERY status badge, not just queued. Each rule is parsed
// for its real background/color custom properties, resolved against the
// token block, and measured — so a token change that breaks any variant is
// caught here rather than shipping an unreadable status label.
// Resolve a `var(--name)` reference to its hex token.
const resolveVar = (name) => cssVar(name.replace(/^--/, "").trim());
const badgeRule = (variant) => {
  const m = css.match(new RegExp(`\\.badge\\.${variant}\\s*\\{([^}]*)\\}`));
  return m ? m[1] : null;
};
const BADGE_VARIANTS = [
  ["entry", "valid-bg", "valid"],
  ["exit", "neutral-bg", "muted"],
  ["bad", "invalid-bg", "invalid"],
  ["queued", "amber-bg", "amber"],
];
for (const [variant, wantBg, wantFg] of BADGE_VARIANTS) {
  const body = badgeRule(variant);
  const bgRef = body?.match(/background:\s*var\((--[\w-]+)\)/)?.[1];
  const fgRef = body?.match(/color:\s*var\((--[\w-]+)\)/)?.[1];
  const bg = bgRef ? resolveVar(bgRef) : null;
  const fg = fgRef ? resolveVar(fgRef) : null;
  check(
    `badge .badge.${variant} is token-themed (${wantBg}/${wantFg})`,
    bgRef === `--${wantBg}` && fgRef === `--${wantFg}`,
    `bg=${bgRef} fg=${fgRef}`,
  );
  const ratio = bg && fg ? contrast(fg, bg) : 0;
  check(
    `badge .badge.${variant} meets WCAG AA (>=4.5:1)`,
    ratio >= 4.5,
    `${ratio.toFixed(2)}:1 (${fg} on ${bg})`,
  );
}

// The StatusPill label (mobile) is ink on track — constant across every
// PillState, since the dot alone varies. Prove that one pairing too.
const pillSource = read("src/ui/index.tsx");
const pillLabelHex = pillSource.match(
  /pillLabel:\s*\{[^}]*color:\s*colors\.(\w+)/,
)?.[1];
const pillBgHex = pillSource.match(
  /pill:\s*\{[^}]*backgroundColor:\s*colors\.(\w+)/,
)?.[1];
const pillTheme = read("src/theme/colors.ts");
const toHex = (name) =>
  pillTheme.match(new RegExp(`${name}:\\s*"(#[0-9A-Fa-f]{6})"`))?.[1];
const pillFg = pillLabelHex ? toHex(pillLabelHex) : null;
const pillBg = pillBgHex ? toHex(pillBgHex) : null;
const pillRatio = pillFg && pillBg ? contrast(pillFg, pillBg) : 0;
check(
  "mobile StatusPill label meets WCAG AA (>=4.5:1)",
  pillRatio >= 4.5,
  `${pillRatio.toFixed(2)}:1 (${pillFg} on ${pillBg})`,
);

// ---- summary -------------------------------------------------------------
console.log("");
console.log(`LAYOUT-P9 RESULT: ${passed}/${failed}`);
if (failed > 0) process.exit(1);
