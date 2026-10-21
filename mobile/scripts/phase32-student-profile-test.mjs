// Phase 32 — Student registration, profile, help & readiness (mobile source pins)
//
// Source-level checks for the required verifications in Part F. Like the
// other scripts in these are honest source pins: they assert what the
// shipped code actually contains, not what a screenshot might suggest.
// Run: node scripts/phase32-student-profile-test.mjs
import { readFileSync } from "node:fs";
import { join } from "node:path";

const cwd = process.cwd();
const read = (rel) => readFileSync(join(cwd, rel), "utf8");
const has = (src, needle) => src.includes(needle);
const stripComments = (src) =>
  src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const reg = stripComments(read("app/(student)/registration.tsx"));
const profile = stripComments(read("app/(student)/profile.tsx"));
const support = stripComments(read("app/(student)/support.tsx"));
const detail = stripComments(read("app/(student)/support-detail.tsx"));
const ready = stripComments(read("app/(student)/readiness.tsx"));

let passed = 0;
let failed = 0;
function check(name, ok) {
  if (ok) {
    passed += 1;
    console.log(`ok   ${name}`);
  } else {
    failed += 1;
    console.error(`FAIL ${name}`);
  }
}

// A — My Registration -----------------------------------------------------
check(
  "A1: official details are honest about missing fields",
  has(reg, 'const official = (v: string) => v.trim() || "Not provided on the official list"') &&
    has(reg, "official(reg.registration_number)") &&
    has(reg, "official(reg.roll_number)") &&
    has(reg, "official(reg.department)"),
);
check(
  "A2: the correction route is always available with a named action",
  has(reg, 'label="Request a correction"') &&
    !/reg\.status\s*!==\s*"active"/.test(reg),
);
check(
  "A3: the screen explains a request never changes the record itself",
  has(reg, "a request never changes your") &&
    has(reg, "by the Examination Department"),
);
check(
  "A4: status vocabulary and shared freshness rules are preserved",
  has(reg, "const REG_STATUS") &&
    has(reg, "useFreshServerData(") &&
    has(reg, "e.status === 401") &&
    has(reg, '"/(student)/welcome"') &&
    has(reg, "stale"),
);

// B — Manage Profile ------------------------------------------------------
check(
  "B1: the heading reflects the real completion state",
  has(profile, 'title={complete ? "Profile complete" : "Complete your profile"}'),
);
check(
  "B2: official record section is read-only with the correction caveat",
  has(profile, '<SectionEyebrow>Official record</SectionEyebrow>') &&
    has(profile, "never changes the record on its own"),
);
check(
  "B3: photo states are distinct — upload success never claims verification",
  has(profile, "setPhotoFailed(true)") &&
    has(profile, 'setNote("Photo uploaded.")') &&
    !has(profile, "Photo verified") &&
    !has(profile, "photo verified"),
);
const saveBody = profile.slice(
  profile.indexOf("const savePhone"),
  profile.indexOf("const pickPhoto"),
);
check(
  "B4: phone save has duplicate-submit guard, length rule and no auto-navigate",
  has(profile, "if (saving) return;") &&
    has(profile, "32 characters or fewer") &&
    has(profile, 'setNote("Phone saved.")') &&
    saveBody.length > 0 &&
    !has(saveBody, "router."),
);
check(
  "B5: a completed profile stays on screen with an explicit home action",
  has(profile, 'label="Go to home"') &&
    has(profile, '"/(student)/home"') &&
    has(profile, "phoneDirtyRef") &&
    has(profile, "useFreshServerData("),
);

// C — Help & corrections --------------------------------------------------
check(
  "C1: full-width stacked category selector with a11y radio semantics",
  has(support, 'accessibilityRole="radio"') &&
    has(support, "accessibilityState={{ selected: active }}") &&
    !has(support, "SegmentedControl"),
);
check(
  "C2: per-category guidance tells the student what to include",
  has(support, "const GUIDE: Record<supportApi.Category") &&
    has(support, "GUIDE[category].include") &&
    has(support, "GUIDE[category].evidence"),
);
check(
  "C3: success shows the server-confirmed reference, never optimistic",
  has(support, "setSent(res.request)") &&
    has(support, "Request sent · {sent.reference}") &&
    has(support, "if (sending) return;"),
);
check(
  "C4: detail distinguishes acknowledged from decided",
  has(detail, "resolved_at") &&
    has(detail, "Decided ") &&
    has(detail, "Acknowledged "),
);

// D — Convocation readiness ------------------------------------------------
check(
  "D1: checklists are split into Profile setup and Event readiness",
  has(ready, '<SectionEyebrow>Profile setup</SectionEyebrow>') &&
    has(ready, '<SectionEyebrow>Event readiness</SectionEyebrow>') &&
    has(ready, "PROFILE_KEYS"),
);
check(
  "D2: the entry pass gets one callout with the real reason and an action",
  has(ready, 'label={passCallout.status === "todo" ? "Get Entry Pass" : "Open invitation"}') &&
    has(ready, "{passCallout.detail}") &&
    (ready.match(/passCallout\.detail/g) || []).length === 1,
);
check(
  "D3: no false zeros — summary and status come from the server payload",
  has(ready, "data.summary.required_done") &&
    has(ready, "data.summary.required_total") &&
    has(ready, "STATUS_PILL[item.status]") &&
    !has(ready, "setRegistration") &&
    !has(ready, "setEvent"),
);
check(
  "D4: reminders keep their single-flight actions and honest empty state",
  has(ready, "if (acting) return;") &&
    has(ready, "finally {") &&
    has(ready, 'title="No reminders"') &&
    has(ready, "actError"),
);

// E — shared interaction consistency --------------------------------------
check(
  "E1: all four areas share stale, 401 and freshness rules",
  [reg, profile, support, ready].every(
    (s) => has(s, "stale") && has(s, "e.status === 401") && has(s, "useFreshServerData("),
  ),
);
check(
  "E2: no screen navigates away right after a successful save",
  !/setNote\("Phone saved\."[\s\S]{0,400}router\.(replace|push)/.test(profile),
);

console.log(`\n${passed + failed} checks, ${failed} failures`);
if (failed > 0) process.exit(1);