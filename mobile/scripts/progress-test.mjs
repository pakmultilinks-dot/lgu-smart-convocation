#!/usr/bin/env node
// Unit tests for src/utils/progress.ts (Phase 35A bugs 1, 2, 5).
// The helper is pure TypeScript; this script compiles it with the project's
// tsc into a temp dir, then asserts the required behaviors with plain Node —
// no new test framework, using the existing toolchain.

import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, ".."); // mobile/
const tsc = join(repo, "node_modules", "typescript", "bin", "tsc");
const src = join(repo, "src", "utils", "progress.ts");
const outDir = mkdtempSync(join(tmpdir(), "lgu-progress-test-"));

execFileSync(
  process.execPath,
  [tsc, src, "--outDir", outDir, "--module", "commonjs", "--target", "es2020", "--skipLibCheck"],
  { stdio: "inherit" },
);

const require2 = createRequire(import.meta.url);
const { safePercent, safePercentFromPct, progressDenominator } = require2(
  join(outDir, "progress.js"),
);

let failed = 0;
function check(name, actual, expected) {
  const ok = Object.is(actual, expected);
  if (!ok) failed += 1;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}  (expected ${expected}, got ${actual})`);
}

// --- Bug 1: progress bar math — 0 means empty, value/max proportional -----
check("value=0 → 0%", safePercent(0, 100), 0);
check("value=25,max=100 → 25%", safePercent(25, 100), 25);
check("value=100,max=100 → 100%", safePercent(100, 100), 100);
check("value=7,max=3 clamps to 100%", safePercent(7, 3), 100);
check("negative value clamps to 0%", safePercent(-5, 100), 0);

// --- Bug 2: gate bars — zero/invalid max never divides ---------------------
check("max=0 → 0% (empty, no NaN)", safePercent(0, 0), 0);
check("count>0,max=0 → 0%", safePercent(5, 0), 0);
check("negative max → 0%", safePercent(5, -10), 0);
check("NaN input → 0%", safePercent(NaN, 100), 0);
check("NaN max → 0%", safePercent(5, NaN), 0);
check("Infinity value → 0%", safePercent(Infinity, 100), 0);

// --- Gate bar proportional cases -------------------------------------------
check("gate count=max → 100%", safePercent(12, 12), 100);
check("gate count=3,max=12 → 25%", safePercent(3, 12), 25);

// --- Bug 5: expected=0 guard + 0..100 clamp --------------------------------
check("expected=0 → 0 (never NaN/Infinity)", safePercent(0, 0), 0);
check("pct clamp upper", safePercentFromPct(150), 100);
check("pct clamp lower", safePercentFromPct(-20), 0);
check("pct NaN → 0", safePercentFromPct(NaN), 0);

// --- Phase 35K: progress denominator is attendance-only ---------------------
// The roster is never a fallback target — a 0 or non-finite attendance
// means "expected attendance not set" and must resolve to 0 (the UI shows
// an explicit Not-set state instead of inventing a percentage).
check("attendance=2500 → 2500", progressDenominator(2500), 2500);
check("attendance=0 → 0 (no roster fallback)", progressDenominator(0), 0);
check("attendance=NaN → 0 (non-finite)", progressDenominator(NaN), 0);

if (failed > 0) {
  console.error(`\n${failed} test(s) FAILED`);
  process.exit(1);
}
console.log("\nAll progress-math tests passed.");
