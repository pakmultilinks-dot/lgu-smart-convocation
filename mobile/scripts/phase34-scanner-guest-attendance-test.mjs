// Phase 34 — scanner, guest passes & attendance integrity: source-level
// pins (no server needed) for the mobile surfaces touched by the backend
// fixes. A successful scan, a valid pass, a recorded entry, a currently
// admitted attendee, and a synchronized record are DIFFERENT concepts and
// are never conflated on screen.
//
//   1  guest lifecycle: Guest + GuestPass carry a `status` the UI reads
//   2  revoked guest pass shows a distinct "Revoked" state (never Ready)
//   3  offline queue treats "GUEST PASS REVOKED" as a PERMANENT rejection
//      (never retried / never silently requeued)
//   4  manual lookup (search) requires a scanner session (no anon access)
//   5  SearchResult no longer ships a bearer qr_id; status is optional
//   6  DashboardData surfaces convocation admissions as a SEPARATE ledger
//   7  LiveBoard never labels admissions "currently inside" / merges them
//   8  Phase 12 scanner pass classification re-pinned (regression)
//
//   node scripts/phase34-scanner-guest-attendance-test.mjs
//
// Exit code 0 = every check passed.

import { readFileSync, readdirSync } from "node:fs";
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

const client = read("src/api/client.ts");
const offline = read("src/store/offlineQueue.ts");
const guests = read("src/screens/GuestsScreen.tsx");
const guestPass = read("src/screens/GuestPassScreen.tsx");
const search = read("src/screens/SearchScreen.tsx");
const live = read("src/screens/LiveBoardScreen.tsx");
const scan = read("src/screens/ScannerScreen.tsx");

// ---- 1  guest lifecycle status on the wire -------------------------------
check(
  "Guest interface carries a lifecycle `status`",
  has(client, "export interface Guest") && /interface Guest[^}]*status:/.test(client),
);
check(
  "GuestPass interface carries a lifecycle `status`",
  has(client, "export interface GuestPass") &&
    /interface GuestPass[^}]*status:/.test(client),
);

// ---- 2  revoked guest pass is a distinct state, never Ready --------------
{
  const code = stripComments(guestPass);
  check(
    "GuestPassScreen renders a distinct 'Revoked' label",
    has(code, '"Revoked"'),
  );
  check(
    "GuestPassScreen Revoked takes precedence over Used/Ready",
    /pass\.status === "revoked"/.test(code) || /status === "revoked"/.test(code),
  );
  const g = stripComments(guests);
  check("GuestsScreen lists 'Revoked' in its StatusPill", has(g, '"Revoked"'));
  check(
    "GuestsScreen excludes revoked passes from the Ready filter",
    /statusFilter === "ready" && !isReady/.test(g) ||
      /isReady\(guest\)/.test(g),
  );
  check(
    "GuestsScreen exposes a revoke action wired to revokeGuestPass",
    has(g, "revokeGuestPass") && has(client, "revokeGuestPass"),
  );
}

// ---- 3  revoked is a PERMANENT offline rejection -------------------------
check(
  "offline queue marks 'GUEST PASS REVOKED' permanent",
  has(offline, '"GUEST PASS REVOKED"'),
);

// ---- 4  manual lookup requires a scanner session -------------------------
check(
  "searchAttendees attaches a scanner session header",
  /searchAttendees[\s\S]*scannerAuthHeaders/.test(client),
);
check(
  "SearchScreen surfaces an explicit sign-in-required state",
  has(stripComments(search), "needsSignIn"),
);

// ---- 5  SearchResult never ships a bearer qr_id --------------------------
{
  const block = (client.match(/interface SearchResult[^}]*\}/) || [""])[0];
  check("SearchResult has no required qr_id field", !has(block, "qr_id"), block);
  check(
    "SearchResult exposes an optional lifecycle status",
    /status\?:/.test(block),
  );
  check(
    "SearchScreen no longer keys results on a bearer qr_id",
    !has(stripComments(search), "hit.qr_id"),
  );
}

// ---- 6  convocation admissions surfaced as a separate ledger -------------
check(
  "DashboardData carries ceremony_admitted",
  /interface DashboardData[\s\S]*ceremony_admitted:/.test(client),
);
check(
  "DashboardData carries rehearsal_admitted",
  /interface DashboardData[\s\S]*rehearsal_admitted:/.test(client),
);

// ---- 7  LiveBoard honest labeling (never conflates) ----------------------
{
  const code = stripComments(live);
  check("LiveBoard labels admissions distinctly", has(code, "Main ceremony"));
  check(
    "LiveBoard keeps admissions out of the 'Inside now' hero",
    !/Inside now[\s\S]{0,400}ceremony_admitted/.test(code),
  );
  check(
    "LiveBoard hero still reads inside_total (occupancy)",
    has(code, "inside_total"),
  );
  check(
    "LiveBoard keeps guests separate from student occupancy",
    has(code, "guests_inside"),
  );
}

// ---- 8  regression: scanner result classification intact ----------------
// ScannerScreen renders the server's title/tone generically (it does not
// hardcode each verdict) but special-cases the two credential-failure
// titles and handles the 401 lock. Pin that those stay intact so a new
// verdict like "GUEST PASS REVOKED" flows through the generic red tone.
{
  const code = stripComments(scan);
  check(
    "ScannerScreen special-cases INVALID/UNKNOWN CODE",
    has(code, '"INVALID CODE"') && has(code, '"UNKNOWN CODE"'),
  );
  check(
    "ScannerScreen re-locks on a revoked/expired scanner session",
    has(code, "scanner_auth_required") || has(code, "401"),
  );
}

console.log(`\n${total - failures}/${total} checks passed, ${failures} failures`);
process.exit(failures === 0 ? 0 : 1);
