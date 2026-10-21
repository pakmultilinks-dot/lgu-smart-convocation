// Phase 5 — student accounts, profile completion + intelligent admin
// dashboard: mobile wiring + cross-layer contract pins.
//
// Proves (source-level, no server needed):
//   W  The student route group exists and mode wiring is complete
//      (mode picker 3rd choice, launch gate, root stack entry).
//   S  The student bearer token is SecureStore-only — never AsyncStorage —
//      and no password is ever persisted; the launch gate only trusts a
//      confirmed /me (401 → welcome, any other failure → retryable error).
//   A  studentApi endpoints exactly mirror the Flask blueprint routes,
//      including the email-addressed recovery completion contract.
//   E  Email delivery fails closed (503 + email_unavailable), the fake
//      provider stays gated behind LGU_TESTING, and the server never
//      hands out challenge ids from /recovery/request.
//   D  dashboard_metrics runs real COUNT queries with url_for issue hrefs;
//      the dashboard template keeps 11 KPI tiles (7 registration + 4
//      Phase 6 medalist) + import/issues cards.
//   V  Volunteer pins intact — VISIBLE_TABS unchanged, no student tab.
//
//   node scripts/student-screens-test.mjs
//
// Exit code 0 = every check passed.

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
if (!cwd.endsWith("mobile")) cwd = root;
const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const readRepo = (rel) => readFileSync(join(cwd, "..", rel), "utf8");
const has = (src, needle) => src.includes(needle);
const count = (src, needle) => src.split(needle).length - 1;
// Doc comments deliberately NAME the forbidden APIs ("never AsyncStorage")
// — executable-code checks run on comment-stripped source.
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const STUDENT_FILES = [
  "_layout.tsx",
  "index.tsx",
  "welcome.tsx",
  "login.tsx",
  "verify.tsx",
  "code.tsx",
  "recovery.tsx",
  "profile.tsx",
  "home.tsx",
];
const CLIENT_ENDPOINTS = [
  "/verify",
  "/resend",
  "/complete",
  "/login",
  "/logout",
  "/me",
  "/profile",
  "/profile/photo",
  "/recovery/request",
  "/recovery/complete",
];

const gate = read("app/(student)/index.tsx");
const welcome = read("app/(student)/welcome.tsx");
const login = read("app/(student)/login.tsx");
const verify = read("app/(student)/verify.tsx");
const codeScreen = read("app/(student)/code.tsx");
const recovery = read("app/(student)/recovery.tsx");
const profile = read("app/(student)/profile.tsx");
const home = read("app/(student)/home.tsx");
const studentSession = read("src/store/studentSession.ts");
const studentApi = read("src/api/studentApi.ts");
const client = read("src/api/client.ts");
const appMode = read("src/store/appMode.ts");
const launch = read("app/index.tsx");
const modePicker = read("app/mode-picker.tsx");
const rootLayout = read("app/_layout.tsx");
const volLayout = read("app/(volunteer)/_layout.tsx");
const emailer = readRepo("app/emailer.py");
const studentRoutes = readRepo("app/web/student_routes.py");
const examRoutes = readRepo("app/web/exam_routes.py");
const dashboardTpl = readRepo("app/web/templates/exam_dashboard.html");

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

console.log("\nPhase 5 — student portal + dashboard (mobile source pins)");

// W — route group + wiring ------------------------------------------------
check(
  "W1: all nine (student) screens exist",
  STUDENT_FILES.every((f) => existsSync(join(cwd, "app", "(student)", f))),
);
check(
  "W2: root stack registers the (student) group without a header",
  has(rootLayout, '<Stack.Screen name="(student)" options={{ headerShown: false }} />'),
);
check(
  "W3: appMode includes the student mode",
  has(appMode, '"volunteer" | "liveboard" | "student"'),
);
check(
  "W4: launch gate resolves the student branch to /(student)",
  has(launch, 'mode === "student" ? "student" : "picker"') &&
    has(launch, '<Redirect href="/(student)" />'),
);
check(
  "W5: mode picker offers Student Portal as a third choice",
  has(modePicker, 'mode: "student"') && has(modePicker, 'title: "Student Portal"'),
);
check(
  "W6: mode picker targetFor routes student to /(student)",
  has(modePicker, '"/(student)"'),
);
check(
  "W7: gate trusts only a confirmed /me session",
  has(gate, "studentApi.me(token)") && has(gate, "studentApi.homePath(me)"),
);
check(
  "W8: welcome offers signup, sign-in, recovery and mode change",
  has(welcome, "/(student)/verify") &&
    has(welcome, "/(student)/login") &&
    has(welcome, "/(student)/recovery") &&
    has(welcome, "/mode-picker"),
);

// S — session security ----------------------------------------------------
check(
  "S1: bearer token stored in SecureStore (native) with WHEN_UNLOCKED",
  has(studentSession, 'import * as SecureStore from "expo-secure-store"') &&
    has(studentSession, "SecureStore.setItemAsync(KEY_TOKEN") &&
    has(studentSession, "SecureStore.WHEN_UNLOCKED"),
);
check(
  "S2: studentSession never touches AsyncStorage",
  !has(stripComments(studentSession), "AsyncStorage"),
);
check(
  "S3: no (student) screen or student API module touches AsyncStorage",
  [gate, welcome, login, verify, codeScreen, recovery, profile, home, studentApi].every(
    (s) => !has(stripComments(s), "AsyncStorage"),
  ),
);
check(
  "S4: no password is ever persisted (no storage write involves it)",
  !has(stripComments(studentSession), "password") &&
    !has(stripComments(studentApi), "setItemAsync"),
);
check(
  "S5: logout clears the local session unconditionally (finally)",
  has(studentApi, "finally") && has(studentApi, "await clearToken()"),
);
check(
  "S6: ApiError surfaces status + server code for error routing",
  has(client, "export class ApiError") &&
    has(client, "this.status = status") &&
    has(client, "this.code = code"),
);
check(
  "S7: gate maps 401 → sign-out, other failures → retryable error state",
  has(gate, "e.status === 401") &&
    has(gate, "await clearToken()") &&
    has(gate, "Connection problem") &&
    has(gate, "onRetry"),
);
// Phase 28 upgraded S8 from a literal-string pin to a behavioural contract.
// The old check matched the exact source text "studentApi.photoSource(token)",
// so it broke the moment the call site renamed the variable it passed (it now
// passes load.token) even though the owner-only behaviour never changed.
// The contract that actually matters: the endpoint is fetched with a bearer
// header, and the token handed in is the SESSION token — not a literal, a
// caller-supplied guess, or nothing at all.
const photoCall = profile.match(/studentApi\.photoSource\(\s*([^)]+?)\s*\)/);
check(
  "S8: profile photo is fetched with the auth header (owner-only route)",
  has(studentApi, "photoSource(token: string)") &&
    has(studentApi, "headers: auth(token)") &&
    photoCall !== null &&
    /\bload\.token\b/.test(photoCall[1]) &&
    has(profile, "setPhoto("),
);

// A — API contract --------------------------------------------------------
check(
  "A1: studentApi calls every server endpoint",
  CLIENT_ENDPOINTS.every((p) => has(studentApi, p)),
);
check(
  "A2: Flask blueprint exposes the same endpoint set",
  CLIENT_ENDPOINTS.every((p) => has(studentRoutes, `@bp.route("${p}"`)),
);
check(
  "A3: verify posts university_email (server field name)",
  has(studentApi, "university_email") && has(verify, "university_email"),
);
check(
  "A4: code screen sends numeric challenge ids",
  has(codeScreen, "Number(p.challenge_id)") &&
    has(studentApi, "challenge_id: number"),
);
check(
  "A5: recovery completes by email + code + password (both layers)",
  has(studentApi, "email: string") &&
    has(recovery, "completeRecovery") &&
    has(studentRoutes, 'if "challenge_id" in payload') &&
    has(studentRoutes, 'payload.get("email"'),
);
check(
  "A6: photo upload prechecks the 2 MB cap client-side",
  has(studentApi, "2 * 1024 * 1024") && has(studentApi, '"photo"'),
);
check(
  "A7: routing rule shared — no claim → verify, incomplete → profile, done → home",
  has(studentApi, '"/(student)/verify"') &&
    has(studentApi, '"/(student)/profile"') &&
    has(studentApi, '"/(student)/home"'),
);
check(
  "A8: screens navigate only through typed hrefs (all four core routes)",
  has(home, "/(student)/profile") &&
    has(profile, "/(student)/home") &&
    has(login, "studentApi.homePath(session)") &&
    has(codeScreen, "studentApi.homePath(session)"),
);

// E — email fail-closed ---------------------------------------------------
check(
  "E1: emailer exposes an availability probe",
  has(emailer, "def available()"),
);
check(
  "E2: unconfigured delivery raises EmailUnavailable (routes answer 503)",
  has(emailer, "Email delivery is not configured") &&
    has(studentRoutes, "email_unavailable") &&
    has(studentRoutes, "503"),
);
check(
  "E3: fake provider is gated behind LGU_TESTING",
  has(emailer, "LGU_TESTING") && has(emailer, "disabled"),
);
check(
  "E4: verify fails closed before any account row exists",
  has(studentRoutes, "fails closed BEFORE any row exists"),
);
check(
  "E5: /recovery/request never returns a challenge id",
  !has(studentApi, "challenge_id") ||
    (() => {
      const block = studentApi.slice(
        studentApi.indexOf("export function requestRecovery"),
        studentApi.indexOf("export function completeRecovery"),
      );
      return !has(block, "challenge_id");
    })(),
);

// D — intelligent dashboard ----------------------------------------------
check(
  "D1: dashboard_metrics exists on the exam blueprint",
  has(examRoutes, "def dashboard_metrics(db)"),
);
check(
  "D2: metrics run real COUNT queries over claims + imports",
  has(examRoutes, "COUNT(*) FROM registration_claims") &&
    has(examRoutes, "COUNT(*) FROM import_batches"),
);
check(
  "D3: data issues carry url_for hrefs (upload/review/history/registrations)",
  ['url_for("exam.import_upload"', 'url_for("exam.import_history"',
   'url_for("exam.registrations"'].every((n) => has(examRoutes, n)) &&
    has(examRoutes, 'url_for("exam.import_review"'),
);
check(
  "D4: inactive convocation is stated, never faked as zero",
  has(examRoutes, "No active convocation is configured"),
);
check(
  // Phase 6 adds 4 medalist KPI tiles → 7 registration + 4 = 11; Phase 7
  // adds 4 event/announcement tiles → 15; Phase 9 adds 7 support tiles →
  // 22; Phase 29 adds 2 annual-cycle occasion tiles (ceremony + rehearsal
  // admissions) → 24.
  "D5: template keeps exactly 24 KPI tiles (15 base + 7 support + 2 occasions)",
  count(dashboardTpl, "kpi-tile") === 24,
);
check(
  "D6: template keeps Latest import + Data issues cards",
  has(dashboardTpl, "Latest import outcome") &&
    has(dashboardTpl, "Data issues") &&
    has(dashboardTpl, "No outstanding data issues"),
);

// V — volunteer preservation ---------------------------------------------
check(
  "V1: VISIBLE_TABS is exactly the five volunteer destinations",
  has(volLayout, 'const VISIBLE_TABS = ["home", "scanner", "search", "guests", "more"];'),
);
check(
  "V2: tab bar still filters routes through VISIBLE_TABS",
  has(volLayout, ".filter((route) => (VISIBLE_TABS as readonly string[]).includes(route.name))"),
);
check(
  "V3: no student destination leaked into the volunteer tabs",
  !has(volLayout, "student"),
);
check(
  "V4: mode picker keeps the existing Live Dashboard choice + display type",
  has(modePicker, "Live Dashboard") && has(modePicker, "displayMedium"),
);

console.log(`\n${passed} checks, ${failed} failures`);
process.exit(failed === 0 ? 0 : 1);
