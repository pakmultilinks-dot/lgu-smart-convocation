// Phase 12 — convocation QR issuance + scanner integration: cross-layer
// contract pins (source-level, no server needed).
//
// Proves:
//   P  passApi mints the convocation QR via POST /api/student/pass/issue,
//      the response carries a backend payload, and the pass screen renders
//      that payload as a QR — gated on the eligible state, cleared when
//      eligibility is lost, and reissued only by an explicit user action.
//   S  The volunteer scanner still posts the RAW payload to /api/scan with
//      no client-side validity claim, and the BACKEND dispatches LGU2:
//      convocation passes to convocation_qr (a separate path from the
//      legacy LGU1 roster) — verifying against the registration ledger and
//      never storing the plaintext token.
//   A  A repeat convocation scan surfaces the backend "ALREADY ADMITTED"
//      title as the already-used state.
//
//   node scripts/qr-pass-source-test.mjs
//
// Exit code 0 = every check passed.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
let cwd = process.cwd();
if (!cwd.endsWith("mobile")) cwd = root;
const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const readRepo = (rel) => readFileSync(join(cwd, "..", rel), "utf8");
const has = (src, needle) => src.includes(needle);
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

let failures = 0;
let total = 0;
const check = (label, ok, detail = "") => {
  total += 1;
  if (ok) console.log(`ok   ${label}`);
  else {
    failures += 1;
    console.log(`FAIL ${label}${detail ? ` :: ${detail}` : ""}`);
  }
};

const passApi = stripComments(read("src/api/passApi.ts"));
const passCode = stripComments(read("app/(student)/pass.tsx"));
const clientCode = stripComments(read("src/api/client.ts"));
const resultLogic = stripComments(read("src/scanner/scanResultLogic.ts"));
const routesPy = readRepo("app/web/routes.py");
const convQrPy = readRepo("app/convocation_qr.py");

// P — QR issuance wiring (mobile) -----------------------------------------
check(
  "P1: passApi mints the QR via POST /api/student/pass/issue",
  has(passApi, "issuePass") &&
    has(passApi, "`${PASS}/issue`") &&
    has(passApi, 'method: "POST"'),
);
check(
  "P2: the issued pass exposes a backend payload for the QR value",
  has(passApi, "payload: string") && has(passApi, "IssuedPass"),
);
check(
  "P3: the pass screen renders the issued payload as a QR",
  has(passCode, 'from "react-native-qrcode-svg"') &&
    has(passCode, "value={qr.payload}"),
);
check(
  "P4: the QR is gated on the eligible state and cleared when eligibility is lost",
  has(passCode, 'pass.state === "eligible"') && has(passCode, "setQr(null)"),
);
check(
  "P5: reissue is an explicit user action, not the freshness refresh",
  has(passCode, 'label="Refresh QR"') &&
    has(passCode, "void issue()") &&
    has(passCode, "useFreshServerData(() => load(true))"),
);

// S — scanner still posts raw payload; backend dispatches by version ------
check(
  "S1: the scanner posts the raw payload to /api/scan (the backend decides)",
  has(clientCode, '"/api/scan"') &&
    has(clientCode, "payload: string") &&
    has(clientCode, "JSON.stringify(input)"),
);
check(
  "S2: the backend dispatches LGU2 convocation passes to convocation_qr",
  has(routesPy, "convocation_qr") &&
    has(routesPy, "is_convocation_payload") &&
    has(routesPy, "verify_scan"),
);
check(
  "S3: convocation QR is a separate version-prefixed path from legacy LGU1",
  has(convQrPy, 'PAYLOAD_VERSION = "LGU2"') && has(routesPy, "ids.verify_payload"),
);
check(
  "S4: the pass stores only a sha256 hash, never the plaintext token",
  has(convQrPy, "sha256") &&
    has(convQrPy, "token_hash(token)") &&
    !has(convQrPy, "token_hash, token,"),
);

// A — repeat scan surfaces the already-used state -------------------------
check(
  "A1: ALREADY ADMITTED maps to the already-used scan state",
  has(resultLogic, 'includes("ALREADY")') &&
    has(resultLogic, '"already-used"') &&
    has(convQrPy, "ALREADY ADMITTED"),
);

console.log("");
console.log(`${total} checks, ${failures} failures`);
process.exit(failures === 0 ? 0 : 1);
