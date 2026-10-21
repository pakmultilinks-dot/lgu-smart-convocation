// Phase 6 — Medalist Board: mobile wiring + cross-layer contract pins.
//
// Proves (source-level, no server needed):
//   B  medalistApi hits exactly the public student endpoints, carries no
//      auth headers, and the screen renders every state (loading, error,
//      empty, convocation-missing, board) with themed award pills.
//   H  home links to the board through a typed href; back navigation
//      exists on the board header.
//   S  server privacy: public_payload exposes only card-safe fields, the
//      publish gate requires a picture, and the CSRF guard covers the
//      medalists blueprint (registered in create_app).
//   V  volunteer pins intact — VISIBLE_TABS unchanged, no student tab.
//
//   node scripts/medalist-board-test.mjs
//
// Exit code 0 = every check passed.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const cwd = join(here, "..");
const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const readRepo = (rel) => readFileSync(join(cwd, "..", rel), "utf8");
const has = (src, needle) => src.includes(needle);

const board = read("app/(student)/medalists.tsx");
const home = read("app/(student)/home.tsx");
const medalistApi = read("src/api/medalistApi.ts");
const volLayout = read("app/(volunteer)/_layout.tsx");
const studentRoutes = readRepo("app/web/student_routes.py");
const medalistRoutes = readRepo("app/web/medalist_routes.py");
const medalists = readRepo("app/medalists.py");
const routes = readRepo("app/web/routes.py");
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

console.log("\nPhase 6 — medalist board (mobile source pins)");

// B — API + screen states -------------------------------------------------
check(
  "B1: medalistApi hits the public board + picture endpoints",
  has(medalistApi, 'const BASE = "/api/student/medalists"') &&
    has(medalistApi, "fetchBoard") &&
    has(medalistApi, "/photo"),
);
check(
  "B2: board request carries no auth (public display data)",
  !has(medalistApi, "Authorization") && !has(medalistApi, "getToken"),
);
check(
  "B3: payload types are card-safe only (no reference/publication)",
  has(medalistApi, "has_photo") &&
    !has(medalistApi, "reference_number:") &&
    !has(medalistApi, "publication:"),
);
check(
  "B4: screen loads through the typed fetcher with filters",
  has(board, "medalistApi.fetchBoard") && has(board, "category"),
);
check(
  "B5: every screen state is handled",
  ["LoadingState", "ErrorState", "EmptyState"].every((c) => has(board, c)) &&
    has(board, "No convocation configured"),
);
check(
  "B6: error state is retryable",
  has(board, "onRetry") && has(board, "void load()"),
);
check(
  "B7: award pills use the theme palette (gold/silver/bronze)",
  has(board, "colors.gold") && has(board, "colors.track") && has(board, "colors.amber"),
);
check(
  "B8: photo placeholder renders for records without a picture",
  has(board, "placeholder") && has(board, "initials"),
);
check(
  "B9: header exposes back navigation",
  has(board, "onBack") && has(board, "router.back()"),
);
check(
  "B10: category filter is a SegmentedControl over server categories",
  has(board, "SegmentedControl") && has(board, "board.categories"),
);

// H — home wiring ---------------------------------------------------------
check(
  // Phase 31 Part B: the board link moved from Home to the More tab.
  "H1: the board is linked through a typed href (More tab)",
  has(read("app/(student)/more.tsx"), '"/(student)/medalists"') &&
    has(read("app/(student)/more.tsx"), "Medalist board"),
);
check(
  "H2: home still guards its own session (no auth bypass)",
  has(home, "studentApi.me(token)") && has(home, "clearToken()"),
);

// S — server privacy + wiring ---------------------------------------------
check(
  "S1: public payload selects only card-safe columns",
  has(medalists, "SELECT id, department, student_name, award_category, position"),
);
check(
  "S2: publishing requires an approved picture (domain gate)",
  has(medalists, "Upload and approve a picture before publishing"),
);
check(
  "S3: photo route serves published records only",
  has(medalists, 'row["publication"] != "published"') &&
    has(studentRoutes, "/medalists/photo/"),
);
check(
  "S4: board endpoint filters the active convocation only",
  has(studentRoutes, 'if conv is None:') && has(studentRoutes, "public_payload"),
);
check(
  "S5: medalists blueprint registered in create_app",
  has(routes, "medalist_routes") && has(routes, "register_blueprint(medalist_routes.bp)"),
);
check(
  "S6: CSRF guard covers the medalists blueprint",
  has(examRoutes, 'request.blueprint not in ("exam", "medalists")'),
);
check(
  "S7: staff_required guards every medalists view",
  (medalistRoutes.match(/@staff_required/g) || []).length >= 8,
);
check(
  // 11 base (7 registration + 4 medalist) + 4 Phase 7 event tiles +
  // 7 later-phase tiles + 2 Phase 29 per-occasion admission tiles = 24.
  "S8: dashboard keeps the 24 KPI tiles (22 + 2 Phase 29 occasion tiles)",
  (dashboardTpl.match(/kpi-tile/g) || []).length === 24,
);

// V — volunteer preservation ---------------------------------------------
check(
  "V1: VISIBLE_TABS is exactly the five volunteer destinations",
  has(volLayout, 'const VISIBLE_TABS = ["home", "scanner", "search", "guests", "more"];'),
);
check(
  "V2: no student/medalist destination leaked into the volunteer tabs",
  !has(volLayout, "student") && !has(volLayout, "medalist"),
);

console.log(`\n${passed} checks, ${failed} failures`);
process.exit(failed === 0 ? 0 : 1);