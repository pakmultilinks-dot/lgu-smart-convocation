/**
 * Phase 35H — administrator PIN lockout unit test (item 23).
 * Compiles the pure helper src/store/adminLockout.ts on demand and
 * asserts the 3-strikes / 30-seconds behavior with an injected clock.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOBILE = join(dirname(fileURLToPath(import.meta.url)), "..");
const TSC = join(MOBILE, "node_modules", "typescript", "bin", "tsc");
const outDir = mkdtempSync(join(tmpdir(), "admin-lockout-"));

let failures = 0;
function check(name, ok) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures += 1;
}

console.log("Phase 35H admin lockout unit test\n");

execFileSync(
  process.execPath,
  [
    TSC,
    "src/store/adminLockout.ts",
    "--outDir",
    outDir,
    "--module",
    "commonjs",
    "--target",
    "es2020",
    "--skipLibCheck",
  ],
  { cwd: MOBILE, stdio: "inherit" },
);

const requireFromMobile = createRequire(join(MOBILE, "package.json"));
const lo = requireFromMobile(join(outDir, "adminLockout.js"));

const now = 1000000;

// initialLockState is exported as a frozen-shape const object (35H).
const initial = lo.initialLockState;
check(
  "initial state is clean",
  initial.attempts === 0 && initial.lockUntil === 0 && !lo.isLocked(initial, now),
);

const s1 = lo.registerFailure(initial, now);
check("1st wrong PIN: attempts 1, not locked", s1.attempts === 1 && !lo.isLocked(s1, now + 1));

const s2 = lo.registerFailure(s1, now + 1);
check("2nd wrong PIN: attempts 2, not locked", s2.attempts === 2 && !lo.isLocked(s2, now + 2));

const locked = lo.registerFailure(s2, now + 2);
check(
  "3rd wrong PIN engages the lockout window",
  locked.lockUntil === now + 2 + lo.LOCKOUT_MS && lo.isLocked(locked, now + 3),
);
check(
  "still locked inside the window",
  lo.isLocked(locked, now + 2 + lo.LOCKOUT_MS - 1),
);
check(
  "unlocked after LOCKOUT_MS has passed",
  !lo.isLocked(locked, now + 2 + lo.LOCKOUT_MS),
);
check(
  "countdown seconds round up",
  lo.lockSecondsRemaining(locked, now + 2 + 1000) ===
    Math.ceil((lo.LOCKOUT_MS - 1000) / 1000),
);

const clean = lo.resetOnSuccess();
check(
  "resetOnSuccess returns a clean state",
  clean.attempts === 0 && clean.lockUntil === 0 && !lo.isLocked(clean, now),
);

const fresh = lo.registerFailure(locked, now + 2 + lo.LOCKOUT_MS);
check(
  "registerFailure after expiry starts a fresh count",
  fresh.attempts === 1 && fresh.lockUntil === 0,
);

const held = lo.registerFailure(locked, now + 3);
check(
  "registerFailure while locked keeps the existing lock",
  held.lockUntil === locked.lockUntil,
);

check(
  "constants are 3 attempts / 30 seconds",
  lo.MAX_ATTEMPTS === 3 && lo.LOCKOUT_MS === 30000,
);

rmSync(outDir, { recursive: true, force: true });
console.log(`\nDone: ${failures} failure(s).`);
process.exit(failures > 0 ? 1 : 0);
