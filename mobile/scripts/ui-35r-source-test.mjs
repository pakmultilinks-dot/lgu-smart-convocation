// Phase 35M Round 3 (navigation launch + scrolling) — source checks.
// Mandate: normal app launch must resolve to Volunteer Home (never Live
// Dashboard via stale persisted mode); Live Dashboard stays an explicit
// in-session mode; Home and Live Dashboard must be genuinely vertically
// scrollable (no fixed/hidden parents), with safe-area bottom spacing and
// all dynamic gates + footer reachable.
//
// 35M device fix (acceptance P3): the Live Dashboard's ScrollView must be
// the OUTERMOST board gesture participant — a Pressable parent used to
// compete for the Android touch responder and intermittently blocked
// scrolling on the physical device (check 11).
//
// This suite ADDS coverage on top of ui-35h/i/j/k/l/m + navigation-broadcast
// (those suites keep every pin green — nothing here weakens them).

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
if (!cwd.endsWith("mobile")) cwd = root;

const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const has = (src, needle) => src.includes(needle);
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const indexTs = read("app/index.tsx");
const rootLayout = read("app/_layout.tsx");
const modePicker = read("app/mode-picker.tsx");
const kit = read("src/ui/index.tsx");
const home = read("src/screens/HomeScreen.tsx");
const liveboard = read("src/screens/LiveBoardScreen.tsx");
const volLayout = read("app/(volunteer)/_layout.tsx");
const liveboardIndexPath = join(cwd, "app", "(liveboard)", "index.tsx");

let passed = 0;
let failed = 0;

function check(name, ok) {
  if (ok) {
    passed += 1;
    console.log(`ok  ${name}`);
  } else {
    failed += 1;
    console.error(`FAIL ${name}`);
  }
}

console.log("\n35M R3 — launch state + scrolling (navigation-launch)");

check(
  "1: default launch resolves to Volunteer Home, never Live Dashboard",
  !has(indexTs, 'Redirect href="/(liveboard)"') &&
    has(indexTs, 'Redirect href="/(volunteer)/home"') &&
    has(indexTs, 'Redirect href="/mode-picker"') &&
    // Phase 5: the student branch was inserted into the SAME chain —
    // volunteer stays the default and unknown/stale modes still fall
    // back to the picker (never Live Dashboard).
    has(indexTs, 'mode === "volunteer" ? "volunteer" : mode === "student" ? "student" : "picker"')
);

check(
  "2: stale stored liveboard cannot hijack launch (normalized to volunteer)",
  has(indexTs, 'mode === "liveboard"') &&
    has(indexTs, 'setAppMode("volunteer")') &&
    has(indexTs, 'setTarget("volunteer")')
);

check(
  "3: explicit Live Dashboard entry preserved (mode picker + route)",
  has(modePicker, 'mode: "liveboard"') &&
    has(modePicker, "router.replace(targetFor(mode))") &&
    has(modePicker, '"/(liveboard)"') &&
    existsSync(liveboardIndexPath)
);

check(
  "4: Home renders inside the kit's vertical ScrollView",
  has(home, "<Screen>") &&
    !has(home, "scroll={false}") &&
    has(kit, "<ScrollView") &&
    // Cross-line needle — tolerant of LF/CRLF in the checked file.
    /style=\{styles\.flex1\}\s+contentContainerStyle=\{styles\.screenScroll\}/.test(
      kit
    )
);

check(
  "5: Live Dashboard has an internal vertical ScrollView",
  has(liveboard, "<ScrollView") &&
    has(liveboard, "boardScrollContent") &&
    has(liveboard, "contentContainerStyle={styles.boardScrollContent}")
);

check(
  "6: no fixed/hidden parent blocks the scroll containers",
  !/screenScroll:\s*\{[^}]*overflow/.test(kit) &&
    !has(liveboard, 'overflow: "hidden"') &&
    !has(volLayout, "overflow")
);

check(
  "7: safe-area bottom spacing preserved on both boards",
  has(liveboard, "Math.max(insets.bottom, 6)") &&
    has(volLayout, "paddingBottom: insets.bottom") &&
    has(kit, 'edges={["top", "left", "right", "bottom"]}')
);

check(
  "8: all gates rendered dynamically — no hard-coded count",
  has(home, "gates.map(") &&
    has(liveboard, "gateRows.map(") &&
    !stripComments(home).includes("7 gates") &&
    !stripComments(liveboard).includes("7 gates")
);

check(
  "9: footer remains reachable inside the scroll content",
  liveboard.indexOf("boardScrollContent") <
    liveboard.indexOf("styles.footerRow") &&
    has(liveboard, 'marginTop: "auto"') &&
    has(liveboard, "Math.max(insets.bottom, 6)")
);

check(
  "10: router anchor — '/' resolves to the launch gate",
  has(rootLayout, 'initialRouteName: "index"') &&
    has(rootLayout, 'name="index"') &&
    !has(rootLayout, 'initialRouteName: "(volunteer)"')
);

// 35M device fix (acceptance P3) kept ScrollView outermost; 33-QA
// (I13) removed the remaining tap Pressable entirely — it nested
// inside the crest's Pressable (web <button> errors) and armed the
// protected exit on any stray tap. Exit is now explicit (crest
// tap/hold + footer Exit) with the confirm card as an always-visible
// absolute overlay.
check(
  "11: ScrollView outermost, no board tap wrapper; exit is explicit + overlaid (33-QA I13)",
  /<Screen scroll=\{false\}>[\s\S]*?<ScrollView[\s\S]*<\/ScrollView>/.test(
    stripComments(liveboard)
  ) &&
    !has(liveboard, 'accessibilityLabel="Live dashboard — tap to show exit options"') &&
    has(liveboard, 'accessibilityLabel="Exit live dashboard"') &&
    has(liveboard, "styles.exitOverlay") &&
    has(liveboard, "onCrestPress={armExit}") &&
    has(liveboard, "onCrestLongPress={armExit}")
);

console.log(`\nDone: ${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
