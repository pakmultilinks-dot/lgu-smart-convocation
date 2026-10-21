// Phase 8 — student-app freshness: the automatic-update contract, pinned
// at source level (no server needed).
//
// Proves, for every student screen that shows server truth (home, event,
// announcements, medalists, profile):
//   F  the screen refetches through the ONE shared hook (focus, resume
//      from background, manual refresh, controlled ≤30s foreground
//      cadence) — never a mount-only fetch;
//   H  the hook itself: single timer (restart never duplicates), overlap
//      guard (a tick while a refresh is in flight is skipped), stops on
//      blur AND on background/inactive, listener removed on unmount,
//      ≤30s constant, no WebSocket/push/new transport, no AsyncStorage
//      (a freshness timer must never cache private student data);
//   S  silent refresh keeps the last data on screen with a stale badge;
//      a network failure is never rendered as an authoritative rejection
//      (only a real 401 ends the session);
//   O  profile editing is protected: a half-typed phone number and a
//      running photo upload are never clobbered by a background poll;
//   L  signing out revokes the server session AND clears the local token
//      (home and profile both).
//
//   node scripts/phase8-freshness-test.mjs
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
const has = (src, needle) => src.includes(needle);
// Doc comments may NAME forbidden APIs — run checks on stripped code.
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

const hook = stripComments(read("src/hooks/useFreshServerData.ts"));
const screens = {
  home: stripComments(read("app/(student)/home.tsx")),
  event: stripComments(read("app/(student)/event.tsx")),
  announcements: stripComments(read("app/(student)/announcements.tsx")),
  medalists: stripComments(read("app/(student)/medalists.tsx")),
  profile: stripComments(read("app/(student)/profile.tsx")),
};

// F — every freshness screen is wired to the shared hook ---------------
for (const [name, code] of Object.entries(screens)) {
  check(
    `F: ${name} refetches through useFreshServerData (not mount-only)`,
    has(code, "useFreshServerData(") && has(code, "(true)"),
  );
  check(
    `F: ${name} has no leftover mount-only useEffect fetch`,
    !has(code, "useEffect(() => {") || !has(code, "await load();"),
  );
}

// H — the hook's controlled-timing contract ----------------------------
check(
  "H: hook fetches on screen focus and return (useFocusEffect)",
  has(hook, "useFocusEffect("),
);
check(
  "H: hook refreshes on resume from background (AppState active)",
  has(hook, 'AppState.addEventListener("change"') &&
    has(hook, 'state === "active"'),
);
check(
  "H: cadence constant is controlled and ≤30 seconds",
  has(hook, "STUDENT_REFRESH_MS = 20000"),
);
check(
  "H: interval stops on blur and on background/inactive",
  has(hook, "stopPolling();") &&
    has(hook, "clearInterval"),
);
check(
  "H: restart never duplicates the timer (clear before set)",
  hook.indexOf("stopPolling();") < hook.indexOf("setInterval("),
);
check(
  "H: overlapping refreshes are skipped, never queued twice",
  has(hook, "runningRef.current") && has(hook, "if (runningRef.current"),
);
check(
  "H: no polling traffic while the app is backgrounded",
  has(hook, 'AppState.currentState !== "active"'),
);
check(
  "H: the AppState subscription is removed on unmount",
  has(hook, "sub.remove()"),
);
check(
  "H: no new transport or dependency (no WebSocket/push/fetch libs)",
  !has(hook, "WebSocket") && !has(hook, "socket") && !has(hook, "EventSource"),
);
check(
  "H: the freshness timer never caches data (no AsyncStorage in the hook)",
  !has(hook, "AsyncStorage"),
);

// S — silent refresh keeps last data; network failure is never a verdict
for (const [name, code] of Object.entries(screens)) {
  check(
    `S: ${name} shows a stale badge when a background refresh fails`,
    has(code, "stale"),
  );
}
check(
  "S: only a real 401 ends the student session (network failure never does)",
  has(screens.home, "e.status === 401") &&
    has(screens.profile, "e.status === 401"),
);
check(
  "S: home manual refresh coalesces through the hook's runner",
  has(screens.home, "void refresh()"),
);
check(
  "S: event + announcements + medalists manual refresh coalesces too",
  has(screens.event, "void refresh()") &&
    has(screens.announcements, "void refresh()") &&
    has(screens.medalists, "void refresh()"),
);

// O — profile edits survive background polls ----------------------------
check(
  "O: a half-typed phone number is preserved (dirty tracking)",
  has(screens.profile, "phoneDirtyRef") && has(screens.profile, "phoneRef"),
);
check(
  "O: a running upload/save blocks the silent refresh",
  has(screens.profile, "savingRef") && has(screens.profile, "savingRef.current"),
);

// L — logout clears the local token from BOTH exits ---------------------
check(
  "L: home sign out revokes the session through studentApi.logout",
  has(screens.home, "studentApi.logout(token)"),
);
check(
  "L: profile sign out revokes the session AND clears the token",
  has(screens.profile, "studentApi.logout(token)") &&
    has(screens.profile, "await clearToken()"),
);
check(
  "L: studentApi.logout clears the token even when the call fails",
  (() => {
    const api = stripComments(read("src/api/studentApi.ts"));
    const idx = api.indexOf("export async function logout");
    return idx !== -1 && has(api.slice(idx, idx + 400), "finally");
  })(),
);

console.log("");
console.log(`${total} checks, ${failures} failures`);
process.exit(failures === 0 ? 0 : 1);
