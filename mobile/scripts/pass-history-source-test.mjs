// Phase 11 — digital convocation pass + student history: mobile wiring +
// cross-layer contract pins (source-level, no server needed).
//
// Proves:
//   R  The pass + history routes exist, are wired into the student stack
//      and reachable from home (both buttons).
//   A  passApi hits exactly the Flask student routes (/api/student/pass,
//      /api/student/history) via the shared authenticated request().
//   S  Both screens render loading / server-error states and an in-app
//      Refresh, and refetch through the ONE shared Phase 8 freshness hook
//      (focus + resume + manual + controlled ≤30s cadence — no polling).
//   Q  The pass stays a read-only invitation (qr_available false, qr null in
//      GET /pass) and the roster-link blocker is surfaced. Phase 12: while
//      eligible the screen may mint a real convocation QR (POST /pass/issue)
//      and render it from the backend payload; it never claims validity from
//      a visible QR and the QR is gated on the eligible state only.
//   H  History keeps expected dates provisional (never confirmed), shows
//      active vs past grouping and honours, and is per-account only.
//   T  Dashboard keeps the 24 KPI tiles (22 + 2 Phase 29 occasion tiles).
//
//   node scripts/pass-history-source-test.mjs
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
// Doc comments NAME forbidden APIs ("no QR") — checks run on stripped code.
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

let failures = 0;
let total = 0;
const check = (label, ok, detail = "") => {
  total += 1;
  if (ok) {
    console.log(`ok   ${label}`);
  } else {
    failures += 1;
    console.log(`FAIL ${label}${detail ? ` :: ${detail}` : ""}`);
  }
};

const passScreen = read("app/(student)/pass.tsx");
const histScreen = read("app/(student)/history.tsx");
const homeScreen = read("app/(student)/home.tsx");
const passApi = read("src/api/passApi.ts");
const passCode = stripComments(passScreen);
const histCode = stripComments(histScreen);
const apiCode = stripComments(passApi);
const hookCode = stripComments(read("src/hooks/useFreshServerData.ts"));

// R — routes + navigation -----------------------------------------------
check(
  "R1: pass + history screens exist",
  existsSync(join(cwd, "app/(student)/pass.tsx")) &&
    existsSync(join(cwd, "app/(student)/history.tsx")),
);
check(
  // Phase 31 Part B: Home keeps the pass as its primary action; the history
  // entry point moved to the More tab (secondary destination).
  "R2: home offers the pass entry point; history lives on More",
  has(homeScreen, 'label="View Entry Pass"') &&
    has(read("app/(student)/more.tsx"), '"/(student)/history"'),
);
check(
  "R3: home pushes the pass route; More pushes history",
  has(homeScreen, 'router.push("/(student)/pass")') &&
    has(read("app/(student)/more.tsx"), '"/(student)/history"'),
);

// A — API contract mirrors the Flask student routes ----------------------
check("A1: passApi calls /api/student/pass", has(apiCode, "/api/student/pass"));
check(
  "A2: passApi calls /api/student/history",
  has(apiCode, "/api/student/history"),
);
check(
  "A3: fetches go through the shared authenticated request()",
  has(apiCode, 'from "./client"') && has(apiCode, "request<"),
);
check(
  "A4: pass state is a typed union covering every backend state",
  has(apiCode, '"eligible"') &&
    has(apiCode, '"pending_review"') &&
    has(apiCode, '"event_unpublished"') &&
    has(apiCode, '"registration_cancelled"') &&
    has(apiCode, '"registration_revoked"'),
);

// S — loading / error / refresh states, freshness hook -------------------
for (const [name, code] of [
  ["pass", passCode],
  ["history", histCode],
]) {
  check(`${name} screen renders a loading state`, has(code, "<LoadingState"));
  check(`${name} screen renders a server-error state`, has(code, "<ErrorState"));
  check(
    `${name} screen offers an in-app Refresh action`,
    has(code, 'label="Refresh"') && has(code, 'icon="refresh"'),
  );
  check(
    `${name} screen refreshes through the shared freshness hook`,
    has(code, "useFreshServerData") && has(code, "load(true)"),
  );
  check(
    `${name} screen has no uncontrolled polling`,
    !has(code, "setInterval") && !has(code, "setTimeout"),
  );
}
check("history screen renders an empty state", has(histCode, "<EmptyState"));
check(
  "hook fetches on focus + resume (AppState) and stops when hidden",
  has(hookCode, "useFocusEffect") &&
    has(hookCode, 'AppState.addEventListener("change"') &&
    has(hookCode, "stopPolling"),
);
check(
  "hook cadence is controlled and ≤30s, cleared on blur/background",
  has(hookCode, "STUDENT_REFRESH_MS = 20000") && has(hookCode, "clearInterval"),
);

// Q — invitation stays read-only; any QR is backend-issued and gated --------
check(
  "Q1: a QR renders only from a backend-issued payload, gated on eligibility",
  has(passCode, 'from "react-native-qrcode-svg"') &&
    has(passCode, "value={qr.payload}") &&
    has(passCode, 'pass.state === "eligible"') &&
    !has(passCode, 'value="LGU'),
);
check(
  "Q2: the API types pin qr_available to false and qr to null",
  has(apiCode, "qr_available: false") && has(apiCode, "qr: null"),
);
check(
  "Q3: the pass surfaces the roster-link QR blocker and gates the QR on eligible",
  has(passCode, "qr_blocker") && has(passCode, 'pass.state === "eligible"'),
);
check(
  "Q4: the pass states it is not a scannable entry code",
  has(passCode, "not a scannable entry code"),
);
check(
  "Q5: no screen claims a pass is valid because a QR is visible",
  !has(passCode.toLowerCase(), "valid because") &&
    !has(passCode, "isValid"),
);

// H — history correctness ------------------------------------------------
check(
  "H1: an expected date is explicitly labelled provisional",
  has(histCode, "(provisional)") && has(passCode, "(provisional)"),
);
check(
  "H2: history renders active vs past grouping",
  has(histCode, '"active"') && has(histCode, '"past"'),
);
check(
  "H3: history renders published honours",
  has(histCode, "honours") && has(histCode, "award_category"),
);
check(
  "H4: history shows the registration status",
  has(histCode, "registration.status") &&
    has(histCode, "REG_PILL"),
);

// T — dashboard tile preservation ----------------------------------------
const dashboardTpl = readRepo("app/web/templates/exam_dashboard.html");
check(
  "T1: dashboard keeps the 24 KPI tiles (22 + 2 Phase 29 occasion tiles)",
  (dashboardTpl.match(/kpi-tile/g) || []).length === 24,
  (dashboardTpl.match(/kpi-tile/g) || []).length,
);
check(
  "T2: dashboard reports convocation QR entry status + legacy roster prerequisite",
  has(dashboardTpl, "Convocation QR entry") &&
    has(dashboardTpl, "Legacy operational-QR prerequisite not satisfied"),
);

console.log("");
console.log(`${total} checks, ${failures} failures`);
process.exit(failures === 0 ? 0 : 1);