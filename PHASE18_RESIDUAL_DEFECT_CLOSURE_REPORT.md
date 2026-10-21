# Phase 18 — Residual Defect Closure & Operational Hardening

**Date:** 2026-10-10
**Branch:** `main` · **HEAD:** `298c272d53485ba4473c2defe72db70c02733a2c` (unchanged — nothing committed)
**Scope:** the four residual findings carried out of `PHASE17_CROSS_ROLE_PRODUCT_ACCEPTANCE_REPORT.md`.
**Release discipline:** no commit, no push, no deploy, no destructive git, no production credential change.

---

## 1. The four findings and their confirmed causes

### Finding 1 — `PASS_ISSUE_RATE_WINDOW_SECONDS` was unreachable *(fixed)*

**Reported:** `[Low — config hygiene]` the pass-issue window is declared but shadowed.
**Cause confirmed at source.** `app/web/student_routes.py::_limited()` hard-coded
`window = config.STUDENT_RATE_WINDOW_SECONDS` for **every** bucket. The seven buckets
(`send`, `recovery`, `login`, `support`, `readiness`, `passissue`, `confirm`) all ran on
the shared 60 s window, so:

- `PASS_ISSUE_RATE_WINDOW_SECONDS` (60) was **dead config** — it was never read.
- `SUPPORT_RATE_WINDOW_SECONDS` (300) was **silently weakened 5×** — the support limiter
  ran on a 60 s window instead of its documented 300 s, admitting roughly five times the
  intended request volume over a five-minute span.

This is not merely hygiene. `test_phase9_support.py` documents the intent as a
five-minute budget; the code was enforcing a one-minute budget.

### Finding 2 — `readiness.tsx::act()` swallowed mark failures *(fixed)*

**Reported:** `[Low — UX only]` a failed "mark read / dismiss" is indistinguishable from success.
**Cause confirmed at source.** `mobile/app/(student)/readiness.tsx::act()` wrapped the whole
mark call in a **bare `catch {}`**. On a dropped connection the row simply stayed put with no
explanation, no retry affordance, and no distinction from a successful no-op. The student was
given no way to know the server had not recorded the change.

### Finding 3 — badge contrast *(reported defect does not reproduce — coverage gap closed instead)*

**Reported:** `[Low — cosmetic, pre-existing]` `.badge.queued` uses `#9a6a00` where the test
wants `#6b4c00`; deferred since Phase 8 "awaiting a product decision".

**Traced before any change was made**, as instructed. The finding is **stale**:

- The literal `#9a6a00` no longer exists in any source file. A repo-wide search for
  `9a6a00|9A6A00|9a6b1a|9A6B1A|6b4c00|6B4C00` returns **7 files, all non-source**: two
  historical docs (`docs/phase34-product-reset/UI_INVENTORY.md`,
  `docs/phase34-product-reset/VISUAL_SYSTEM.md` — a record of the pre-reset palette),
  `PHASE8_INTEGRATION_REPORT.md` and `PHASE17_..._REPORT.md` (the findings themselves), the
  retired-hex guard in `layout-p8-source-test.mjs`, the explanatory comment in
  `layout-p9-source-test.mjs`, and the "was #9A6B1A" changelog comment in `colors.ts`.
- The token is now `--amber: #7c5a15` / `amber: "#7C5A15"` in both palettes. The p9 test was
  already rewritten to be token-aligned and was passing.

**What was actually wrong was the coverage, not the colour.** The test measured the
`queued` variant *only*. The other three status variants were never measured by any test, so
a regression in any of them would have shipped silently. Rather than leave an unverified
claim, the audit was completed for every variant (§5).

### Finding 4 — scanner PIN provisioning ownership *(fixed)*

**Reported:** `[Operational] Scanner PIN provisioning ownership ... remains assigned to operations, not code.`

**Cause confirmed at source** — and it is narrower than "operations should own it". Every
scanner lifecycle function in `app/scanner_auth.py` took `actor="system"` as its default, and
`app/scripts/manage_scanner_staff.py` **never passed an actor at all**. Consequently
`scanner_created`, `scanner_pin_reset`, `scanner_gates_set`, `scanner_revoked` and
`scanner_activated` were all written into `audit_log` with `actor = "system"`.

The audit trail therefore could not answer *"who provisioned or reset this credential?"* for
**any** scanner, ever. Worse, the value `"system"` actively misleads: it reads as a trusted
automated provisioning process when a human at a shell performed the action. The ownership
gap was in the audit record, which is precisely the artifact operations would rely on to
establish ownership.

---

## 2. Files modified and behaviour changed

| File | Change | Behaviour |
|---|---|---|
| `app/config.py` | Added `positive_int(name, default)`; applied it to all 11 rate-limit ints | A mistyped limit (non-numeric, `0`, negative) falls back to the safe default instead of disabling the limiter |
| `app/web/student_routes.py` | Added `_BUCKET_WINDOWS` map + `_bucket_window(bucket)` validator; `_limited()` now resolves a per-bucket window | Each of the 7 buckets honours its own documented window; support back to 300 s, pass-issue window now reachable |
| `mobile/app/(student)/readiness.tsx` | Added `acting` + `actError` state; rewrote `act()`; error `Text`; `loading`/`disabled` on the reminder buttons | A failed mark/dismiss is reported, the controls lock while in flight, the list stays usable, success re-reads server state |
| `app/scanner_auth.py` | Added `UNKNOWN_ACTOR` + `_actor(actor)` normaliser; all five lifecycle functions default to `UNKNOWN_ACTOR` and audit through `_actor()` | No code path can record a scanner lifecycle action as `"system"`; empty/placeholder actors collapse to `unknown-operator` |
| `app/scripts/manage_scanner_staff.py` | Added `--actor` to every mutating subcommand (defaults to the OS login via `getpass`); `by=<actor>` in output; clean `ValueError` handling instead of a traceback | Provisioning, PIN reset, gate change and revocation are attributable to a named operator |
| `mobile/scripts/layout-p9-source-test.mjs` | Replaced the single-variant queued check with a four-variant audit + mobile `StatusPill` check | Every badge variant is measured for token-alignment **and** WCAG AA |
| `mobile/scripts/readiness-source-test.mjs` | Check 15 corrected (it pinned the old silent behaviour); added checks 25–29 | The failure path — error state, error rendering, control locking, `finally` release, retained server state — is pinned |
| `app/scripts/test_phase18_residual_closure.py` | **New** — 43-check regression suite for all four findings | Pins windows, config guard, readiness-independent buckets, and scanner ownership |

**Deliberately not changed:** `--muted`, `--valid`, `--invalid`, `--amber` and every badge
token are untouched. All four variants already pass AA (§5), so changing a token would have
been a regression dressed as a fix.

---

## 3. Rate-limit boundary and independence results — **14/14 pass**

Per-bucket windows resolve to their own documented values:

| Bucket | Window | Result |
|---|---|---|
| `send` | 60 s | ok |
| `recovery` | 60 s | ok |
| `login` | 60 s | ok |
| `confirm` | 60 s | ok |
| `support` | **300 s** | ok |
| `readiness` | 60 s | ok |
| `passissue` | **60 s** | ok |

**Boundary — the decisive test.** A hit is aged to **100 s** (older than the shared 60 s
window, younger than the 300 s support window):

- support hits at 100 s old → **still limited** (proves the 300 s window is live; under the
  old code these would have expired and the flood would have been admitted).
- student `send` hits at 100 s old → **expired, allowed** (proves the 60 s window still holds
  for that bucket, so the fix is per-bucket and not a blanket lengthening).
- pass-issue hits at 30 s old → **still limited** (proves the previously unreachable window
  is now enforced).

**Independence.** Exhausting `support` leaves `send` and `readiness` fully usable;
exhausting `readiness` leaves `support` fully usable. Buckets do not share a clock.

**Config hygiene (5/5).** A string, `0`, a negative value and a boolean window all fall back
to the shared window instead of disabling limiting; the real value restores correctly.

---

## 4. Readiness success and failure results

**Failure path — 5/5 new source checks pass** (`readiness-source-test.mjs`, 29/29 overall):

- `act()` keeps an explicit error state; **no bare `catch {}`** remains anywhere in the screen.
- A failed dismissal is rendered to the student (`styles.actError`, `colors.invalid`, 13 px —
  the same convention as `support.tsx`).
- Controls lock while in flight: `loading={acting === r.key}`, `disabled={acting !== null}`,
  and `if (acting) return;` blocks duplicate submits.
- `finally { setActing(null); }` guarantees the screen never wedges.
- The failure path clears the error and retains the previously loaded server state, so the
  student can retry in place.

**Success path.** After a successful mark the screen calls `await load(true)` — a
server-confirmed re-read — so the row reflects backend state, never a local assumption.

**Honest limitation.** These are **source-level** checks. No device or emulator run was
performed (§8), so the runtime rendering of the error text has not been visually confirmed.

---

## 5. Badge contrast calculations — **all variants, computed not asserted**

WCAG 2.x relative luminance, contrast $=\dfrac{L_1+0.05}{L_2+0.05}$, threshold 4.5:1.

| Variant | Foreground | Background | Ratio | Verdict |
|---|---|---|---|---|
| `.badge.entry` | `--valid` `#177245` | `--valid-bg` `#e6efe7` | **5.06:1** | PASS |
| `.badge.exit` | `--muted` `#5c5642` | `--neutral-bg` `#ece5d3` | **5.83:1** | PASS |
| `.badge.bad` | `--invalid` `#b3261e` | `--invalid-bg` `#f8e9e6` | **5.54:1** | PASS |
| `.badge.queued` | `--amber` `#7c5a15` | `--amber-bg` `#f4ecd8` | **5.36:1** | PASS |
| mobile `StatusPill` label | `colors.ink` `#1B1A16` | `colors.track` `#E3DCC6` | **13.0:1** | PASS |

**Lowest margin:** `.badge.queued` at 5.36:1 — comfortably above the 4.5:1 requirement for
normal-size text. **No token was changed**, because none needed to be.

The test now parses each `.badge.<variant>` rule from the real CSS, resolves its actual
`var(--…)` references against the token block, and measures the pairing — so a future token
edit that breaks any variant fails the build. `layout-p9-source-test.mjs` is **24/0**
(was 16/0).

---

## 6. Scanner PIN ownership results — **23/23 pass**

**Ownership is now recorded.** Creating with `--actor p18-ops-lead` writes
`audit_log.actor = "p18-ops-lead"` for `scanner_created`; a PIN reset and a revocation are
attributed the same way. Omitting `--actor` attributes the action to the real OS login
(`getpass.getuser()`), verified against the live value — never `"system"`.

**The gap cannot be re-opened.**

- `--actor system` is normalised to `unknown-operator` at the library boundary, so the
  placeholder cannot be re-introduced from the CLI.
- A library caller passing `None`, blank, `"system"` or `"SYSTEM"` all resolve to
  `scanner_auth.UNKNOWN_ACTOR`; a genuine operator string survives normalisation untouched.

**Security properties retained** (verified, not assumed):

- PIN stored only as a scrypt hash; plaintext PIN never in `audit_log`, output, or any query.
- Session tokens stored only as sha256; the audit log contains no token material.
- Revocation invalidates every live session and a revoked token no longer resolves.
- Gate authorization is unchanged and still server-side.
- **No unauthenticated provisioning bypass exists**: `/api/scanner/*` exposes only `login` and
  `logout`; provisioning is CLI-only, run on the server host. No web endpoint can create,
  reset or alter a scanner credential.
- No default or shared credential; accounts are minted per-account by the CLI.

**Denial / misuse cases.** An unknown gate is refused *before* any account row is written;
revoking an unknown id fails cleanly with a message rather than a traceback; and no scanner
lifecycle action anywhere in the trail is left attributed to `"system"`, `""` or `None`.

**One regression introduced and caught by the battery.** Adding `--actor` to the mutating
subparsers made `args.actor` unset for the read-only `list` subcommand, which crashed it —
caught by Phase 17 (`156 checks, 1 failures`). Fixed with `getattr(args, "actor", None)`, and
a guard check was added to the Phase 18 suite so it cannot recur. Phase 17 re-run: **156/0**.

---

## 7. Exact commands and counts

```
# Python — 18 suites, 1,063 checks, 0 failures, 0 non-zero exits
cd app && ..\.venv\Scripts\python.exe scripts\test_<suite>.py      (×18)
```

| Suite | Checks | Exit |
|---|---|---|
| `test_convocation_migration.py` | 17 | 0 |
| `test_event_announcements.py` | 58 | 0 |
| `test_exam_auth.py` | 29 | 0 |
| `test_exam_dashboard.py` | 31 | 0 |
| `test_exam_registration.py` | 104 | 0 |
| `test_medalist_management.py` | 55 | 0 |
| `test_phase10_readiness.py` | 52 | 0 |
| `test_phase11_pass_history.py` | 75 | 0 |
| `test_phase12_qr_scanner.py` | 41 | 0 |
| `test_phase13_e2e_acceptance.py` | 53 | 0 |
| `test_phase14_scanner_access.py` | 48 | 0 |
| `test_phase16_lifecycle.py` | 52 | 0 |
| `test_phase17_cross_role_acceptance.py` | 156 | 0 |
| **`test_phase18_residual_closure.py`** | **43** | **0** |
| `test_phase8_acceptance.py` | 85 | 0 |
| `test_phase8_integration.py` | 57 | 0 |
| `test_phase9_support.py` | 58 | 0 |
| `test_student_accounts.py` | 92 | 0 |
| **Total** | **1,063** | **0** |

```
# Mobile — 33/33 .mjs suites pass, 0 failed
cd mobile && node scripts\<name>.mjs                              (×33)
  incl. layout-p9-source-test.mjs  24/0   (was 16/0)
  incl. readiness-source-test.mjs  29/0   (was 24/0)

npm run tsc      # tsc --noEmit → exit 0
npm run lint     # expo lint    → exit 0
git diff --check # exit 0
```

All suites were run in a clean environment: no leaked `LGU_DB_PATH`, `LGU_EMAIL_MODE` or SMTP
variables (`Get-ChildItem env: | Where-Object { $_.Name -like "LGU_*" }` → empty after the
runs). Every suite self-sets `LGU_TESTING=1`, a temp DB path, and calls `config.require_test_db()`.

---

## 8. Outstanding: Android and email delivery

**Android / emulator — NOT PERFORMED.** `adb`, `emulator` and `java` are all absent from this
machine (`Get-Command` → not found for each). No device or emulator was attached, so:

- the readiness error state has **not** been visually confirmed on a device;
- scanner field test **T1–T9** (physical gate operation) remains **assigned to operations**.

**Email delivery — NOT PERFORMED.** `scripts/check_email_config.py` (no network, no message
sent) reports `LGU_EMAIL_MODE = disabled` with host, user, password and sender all unset. The
configuration is self-consistent and **fails closed**: signup and recovery answer HTTP 503
until SMTP is configured. No credentials were requested, supplied, or written. Real
delivery was not exercised and no success is claimed for it.

---

## 9. Production database — before and after

| | Size | SHA-256 | mtime (UTC) |
|---|---|---|---|
| **Baseline (Phase 18 start)** | 278,528 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | `2026-10-10T19:35:21.8392785Z` |
| **After full battery** | 278,528 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | `2026-10-10T19:35:21.8392785Z` |

**Byte-identical.** `app/lgu.db` was only stat'ed and hashed — never opened, never migrated.
The Phase 18 suite re-verifies this independently and prints `production db unchanged: True`.

---

## 10. Final git status and diff check

```
branch : main
HEAD   : 298c272d53485ba4473c2defe72db70c02733a2c      (unchanged — nothing committed)
dirty  : 145 entries                                   (144 baseline + 1 new test file)
git diff --check : exit 0                              (no whitespace errors)
```

`git diff --check` emits three pre-existing `LF will be replaced by CRLF` **warnings** on
`mobile/app.json`, `mobile/package-lock.json` and `mobile/package.json`. These are line-ending
advisories on files untouched by this phase, not whitespace errors, and the exit code is 0.

Modified (tracked): `app/config.py`, `mobile/scripts/layout-p9-source-test.mjs`.
New/untracked: `app/scripts/test_phase18_residual_closure.py`.
Edited in place among the pre-existing untracked Phase 5–17 work:
`app/scanner_auth.py`, `app/web/student_routes.py`, `app/scripts/manage_scanner_staff.py`,
`mobile/app/(student)/readiness.tsx`, `mobile/scripts/readiness-source-test.mjs`.

Nothing was committed, pushed, deployed or stashed. No history was rewritten.

---

## 11. Remaining defects, with priority and evidence

| # | Defect | Priority | Evidence / why it remains |
|---|---|---|---|
| 1 | **Physical scanner field test T1–T9** never executed | **High — operations** | No `adb`/`emulator`/`java` on this machine (§8). Gate operation, printed-PIN handover and pass/fail on real hardware are unverified. Assigned to operations. |
| 2 | **Distributed multi-IP PIN brute force is not globally rate-limited** | Medium — accepted | Pre-existing, accepted for LAN deployment in Phase 14. The Phase 18 fix restores the *per-session* support window but does not add a distributed limiter. |
| 3 | **No TLS in this environment** | Medium — deployment | Bearer and scanner tokens require TLS in production; this environment is HTTP loopback only. Unchanged by this phase. |
| 4 | **Email delivery unexercised** | Medium — operations | `LGU_EMAIL_MODE = disabled`, fail-closed 503 (§8). The Phase 16 outage semantics are tested in software; a real provider has never been driven. |
| 5 | **Readiness error state not visually verified** | Low — cosmetic risk | Source-level checks only (§4). The error text, button loading and disabled states are pinned at source but never rendered on a device. |
| 6 | **`--actor` is attestation, not authentication** | Low — design accepted | The CLI records *who ran it*; it does not *prove* it. A user on a shared account can supply any `--actor` string. Adding real operator auth would contradict the deliberate local-command design and was explicitly out of scope. The default (OS login) makes the honest case the easy case. |
| 7 | **Historical docs still name the retired `#9a6a00`/`#9A6B1A` hexes** | Informational | `docs/phase34-product-reset/*`, `PHASE8_*`, `PHASE17_*` and two in-code changelog comments. These are a deliberate record of the pre-reset palette and of the findings themselves; correcting them would erase the audit trail. No source uses them. |

---

### Summary

All four Phase 17 findings are closed. Two were genuine defects with a confirmed single-line
root cause (window shadowing; bare `catch`), one was a stale finding whose real defect was a
**coverage** gap that is now closed with computed evidence for every variant, and one turned
out to be an **audit-trail ownership** gap rather than a process gap — now fixed at the
library boundary so it cannot be re-introduced.

**This report does not declare the product production-ready.** The automated suite is green
(1,063 Python + 33 mobile suites, tsc 0, lint 0, production DB byte-identical), but a green
suite is not production readiness: the physical field test has never been run, no TLS is
configured, no real email provider has been exercised, and the scanner `--actor` mechanism is
attestation rather than authentication. Those four items sit above the code and remain open.

**Phase 19 was not started. Nothing was committed.**
