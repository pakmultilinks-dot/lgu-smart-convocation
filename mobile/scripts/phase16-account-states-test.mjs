// Phase 16 — student email verification + account lifecycle (mobile side).
//
// Proves (source-level, no server needed):
//   S  The nine account states the brief requires are each rendered from
//      an authoritative backend response, never from request submission.
//   H  No screen claims success before the server confirmed it, and the
//      password hint matches the server's real 12-character rule.
//   L  Deep-link finding: the verification/recovery mail carries only a
//      6-digit code (no URL), so there is no link route to handle — the
//      app's scheme-only Expo config is documented, not faked.
//
//   node scripts/phase16-account-states-test.mjs
//
// Exit code 0 = every check passed.

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
if (!cwd.endsWith("mobile")) cwd = root;
const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const readRepo = (rel) => readFileSync(join(cwd, "..", rel), "utf8");
const has = (src, needle) => src.includes(needle);
/** Order-sensitive: `a` must appear before `b` in `src`. */
const before = (src, a, b) => {
  const i = src.indexOf(a);
  const j = src.indexOf(b);
  return i !== -1 && j !== -1 && i < j;
};

const login = read("app/(student)/login.tsx");
const verify = read("app/(student)/verify.tsx");
const code = read("app/(student)/code.tsx");
const recovery = read("app/(student)/recovery.tsx");
const studentApi = read("src/api/studentApi.ts");
const appJson = read("app.json");
const studentRoutes = readRepo("app/web/student_routes.py");
const studentAuth = readRepo("app/student_auth.py");
const examAuth = readRepo("app/exam_auth.py");
const emailer = readRepo("app/emailer.py");

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

console.log("\nPhase 16 — account-state accuracy on the student screens");

// S — the nine states -----------------------------------------------------
check(
  "S1: account creation in progress is its own state",
  has(code, "Account creation in progress") &&
    has(code, "Confirming your code..."),
);
check(
  "S2: email verification required is stated before the code is typed",
  has(code, "Email verification required"),
);
check(
  "S3: verification success is shown only after /complete answered 200",
  has(code, "Verification successful") &&
    before(code, "await studentApi.complete(", "setOk(true)"),
);
check(
  "S4: expired/used token state comes from the server's own 410 text",
  has(studentAuth, "That verification code has expired") &&
    has(studentAuth, "That verification code has already been used") &&
    has(studentRoutes, "This recovery step no longer exists") &&
    has(code, "e.message"),
);
check(
  "S5: resending verification has a visible in-flight state",
  has(code, "Resending verification...") && has(code, 'loading={busy === "resend"}'),
);
check(
  "S6: invalid credentials use the server's uniform 401 text",
  has(studentAuth, "Email or password is incorrect") &&
    has(login, "e instanceof ApiError") &&
    has(login, "e.message"),
);
check(
  "S7: recovery request is reported as a submission, not a success",
  has(recovery, "setNote(r.message)") &&
    has(studentRoutes, "If that email has an account") &&
    !has(recovery, "Password reset"),
);
check(
  "S8: password reset completion is confirmed on the sign-in screen",
  has(recovery, 'pathname: "/(student)/login", params: { reset: "1" }') &&
    has(recovery, "await clearToken()") &&
    has(login, "Password changed. Sign in with your new password."),
);
check(
  "S9: network and provider unavailability are distinguished in the UI",
  has(verify, "e.status === 0") &&
    has(recovery, "e.status === 0") &&
    has(code, "e.status === 0") &&
    has(verify, 'e.code === "email_unavailable"') &&
    has(recovery, 'e.code === "email_unavailable"'),
);

// H — honesty + password rule --------------------------------------------
check(
  "H1: no screen navigates on an unconfirmed request",
  !before(verify, "router.push", "await studentApi.verify(") &&
    !before(login, "router.replace", "await studentApi.login(") &&
    !before(recovery, "router.replace", "await studentApi.completeRecovery("),
);
check(
  "H2: provider failure tells the student nothing was created",
  has(verify, "no code was sent and no account was created") &&
    has(studentRoutes, "email_unavailable"),
);
check(
  "H3: password hints state the server's real 12-character minimum",
  has(code, "At least 12 characters") &&
    has(recovery, "At least 12 characters") &&
    !has(code, "At least 8 characters") &&
    !has(recovery, "At least 8 characters"),
);
check(
  "H4: MIN_PASSWORD_LENGTH is the single source of truth (12)",
  has(examAuth, "MIN_PASSWORD_LENGTH = 12"),
);

// L — deep links / verification links -------------------------------------
check(
  "L1: the verification mail carries only a code — no URL to open",
  !has(emailer, "http") && !has(emailer, "href") && !has(emailer, "url"),
);
check(
  "L2: no link route is registered, so none is invented for the app",
  !has(studentRoutes, "token=") && !has(studentRoutes, "/verify-link"),
);
check(
  "L3: Expo config stays scheme-only; nothing claims link handling",
  has(appJson, '"scheme": "lgu-smart-convocation"') &&
    !has(appJson, "intentFilters") &&
    !has(studentApi, "Linking"),
);
check(
  "L4: recovery completion still supports the email-addressed contract",
  has(studentApi, "email: string") && has(studentApi, "completeRecovery"),
);

console.log(`\n${passed} checks, ${failed} failures`);
process.exit(failed === 0 ? 0 : 1);
