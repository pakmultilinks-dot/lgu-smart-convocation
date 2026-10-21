# PHASE 30 — Physical Android Acceptance and Student Journey Verification

**Scope:** verify Phase 29 in the actual Android app using the disposable test
environment; fix reproducible defects only; preserve project state.

**Verification tiers used throughout this report:**

- **[AUTOMATED]** — project test suites run headlessly (no device).
- **[API-LEVEL]** — live HTTP verification against the running Flask server on the
  disposable Gate 1 database (`verify.py`, 54 checks, 0 failures).
- **[DEVICE-REQUIRED]** — must be performed by a human on the physical phone.
  These are **NOT** claimed as verified; each has exact instructions + expected
  result in §7 and the report **STOPS** there for the operator.

**Constraints honoured:** no reset / clean / stash / revert / commit / push /
deploy; production `app/lgu.db` never opened by any test; existing disposable
world inspected before use (none survived — temp had been cleaned — so a fresh
Gate 1 world was built, which is the sanctioned reason to recreate test data);
no unrelated processes killed; no signing keys / tokens / secret env values
printed.

---

## 1. State preservation (inspected before any action)

| Item | Baseline (Phase 29) | Now | Status |
|---|---|---|---|
| `git rev-parse HEAD` | `298c272d53485ba4473c2defe72db70c02733a2c` | same | ✅ unchanged |
| Stashes | 0 | 0 | ✅ |
| Working tree | Phase 29 changes uncommitted (64 modified + 140 untracked) | same set — **no file in the repo was edited this session**; only the new report file is added | ✅ preserved |
| Production `app/lgu.db` | 278528 bytes, SHA-256 `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | identical | ✅ untouched |
| Migration 12 | applied | `PRAGMA user_version = 12` on the disposable DB | ✅ |
| Phase 29 suites | 42/42 exit 0 | not re-run (unchanged code; [AUTOMATED] baseline carried forward) | ✅ |

No commit, push, stash, revert, reset or deploy was performed.

## 2. Environment prepared for the phone

### 2.1 Servers (both left running for the operator)

| Process | State | Address |
|---|---|---|
| Flask (`app/run.py`) | running, `LGU_TESTING=1`, `LGU_DB_PATH=%TEMP%\lgu-p30-field\field.db`, `LGU_EMAIL_MODE=fake` | `http://192.168.100.5:5000` (binds 0.0.0.0) |
| Expo (`npx expo start --lan`, `mobile/`) | running, Metro bundler up | `exp://192.168.100.5:8081` |

- Flask was restarted once during this session (to lift in-process rate limits
  with the documented test-backend overrides `LGU_STUDENT_MAX_LOGIN=200`,
  `LGU_PASS_ISSUE_MAX=200`, etc. so repeated verification runs don't trip 429).
  Production defaults are untouched; the overrides exist only in that
  disposable server process.
- **[API-LEVEL]** `GET http://192.168.100.5:5000/api/config` → **200** from the
  LAN address (the exact URL the phone will use).
- **[API-LEVEL]** Metro answers on the LAN: `http://192.168.100.5:8081/status`
  → `packager-status:running`.
- Laptop LAN IP confirmed: **192.168.100.5** (Wi-Fi interface).

### 2.2 Disposable world (Gate 1 field test)

Built fresh in `%TEMP%\lgu-p30-field\` (`field.db`, `handoff.json`,
`qr-sheet.html`, `verify.py`) — the previous Gate 1 world no longer existed
(temp cleaned), so recreating test data was necessary and sanctioned.

- Convocation **"Release Gate 1 Field Test"**, both occasions published:
  - **Rehearsal** — 2026-10-19 10:00, Rehearsal Hall B, announced.
  - **Main convocation** — 2026-10-20 09:00, Main Auditorium, confirmed.
- Countdown honesty **[API-LEVEL]**: server reports rehearsal `days_until=2`,
  ceremony `days_until=3`, both `phase="upcoming"`, `starts_at` UTC instants
  ending in `Z`, `portal_tz="Asia/Karachi"`.
- Students FG-001 Zara / FG-002 Hina / FG-003 Usman, accounts active
  (Usman was cancel→reinstate exercised and is active again).
- Scanners: `gateA-ana` (PIN 481902, gate 1 only), `gateC-bilal`
  (PIN 735164, gate 3 only).
- Staff: `p30 officer` / `phase30-officer-pw` (exam portal).
- QR/pass signing config: demo secrets allowed only because
  `LGU_ALLOW_DEMO_SECRETS=1` on the disposable server — matches the test
  fixture; production config unchanged.

### 2.3 Backend discovery on the phone

`mobile/src/store/settings.ts` reads the Expo `hostUri` host in dev and targets
`http://<host>:5000` — with Metro at `exp://192.168.100.5:8081` the app
discovers `http://192.168.100.5:5000` **without any source edit**. Phone must
join the same Wi-Fi as the laptop.

## 3. Two-occasion lifecycle — verification status

### 3.1 [API-LEVEL] — 54/54 checks, 0 failures (`%TEMP%\lgu-p30-field\verify.py`)

Full lifecycle proven against the live server with real scanner tokens:

| Behaviour | Result |
|---|---|
| Rehearsal scan → `REHEARSAL ENTRY RECORDED`, occasion-scoped ledger row, pass stays **active** | ✅ |
| Ceremony scan with the same pass → `CONVOCATION ENTRY RECORDED`, second row, pass marked **used** | ✅ |
| Rehearsal admission ≠ ceremony admission (2 rows, one per occasion) | ✅ |
| Duplicate re-scan per occasion → `ALREADY ADMITTED` ×2, ledger still exactly 2 rows | ✅ |
| Wrong gate (`gateC-bilal` at gate 1) → 403 `GATE NOT AUTHORIZED` | ✅ |
| Unknown pass code → `PASS INVALID`; malformed payload → `INVALID CODE` | ✅ |
| Reissued (revoked) pass → `PASS INVALID` | ✅ |
| Unknown occasion → 400 `UNKNOWN OCCASION` on `/api/scan`, refused per-item in `/api/sync` | ✅ |
| Offline queue: queued rehearsal records once (`source=queued`); replay → `ALREADY SYNCED`, no double count | ✅ |
| Legacy scan with no occasion → records the main convocation; never a third row | ✅ |
| Recovery fail-closed (200 no-leak, wrong code refused); logout → 401; anonymous scan/sync/settings 401, exam pages 302, guest directory gated | ✅ |

### 3.2 [DEVICE-REQUIRED] — physical Android journey

**NOT YET VERIFIED.** Exact instructions in §7.1 (operator performs, then this
report is updated).

## 4. Student-dashboard options — inventory and results

Inventory from PHASE29 report §5. "API actual" = live HTTP result this session;
"Device" = physical tap, pending §7.2.

| Option | Tap (phone) | Expected | API actual [API-LEVEL] | Device |
|---|---|---|---|---|
| Registration lookup / claim | Sign-up → enter registration details | matching registration opens code step; mismatch refused | correct details recognised (fixtures already claimed → 409 "sign in instead"); mismatch → 404 `unmatched` | pending |
| Sign-in / sign-out | email + password → logout | token works, dead after logout | FG-001 token 200; logout → 401 | pending |
| Session state | open app / Home | registration + profile + completion | `/me` returns all three | pending |
| Profile / phone save | edit phone → save | persists in `/me` | saved + persisted | pending |
| Photo upload / view | pick photo | stored, shown back | upload 200, served back 200 | pending |
| Corrections | staff cancels registration | student sees "cancelled", cannot issue | cancelled on `/me`, issue → 403; reinstate restores | pending |
| Event information | Event Details | two occasions + times/venues + countdown | rehearsal 2 d / ceremony 3 d, venues correct, `starts_at` Z | pending |
| Readiness | open readiness | items + reminders from real data | items + reminders present | pending |
| Reminder dismiss | dismiss a reminder | `dismissed`; unknown key fails closed | dismissed; unknown key → 400 | pending |
| Digital pass | issue pass | serves both occasions; ineligible → 403 | pass carries both occasions; cancelled → 403 | pending |
| History | open history | event with both occasions listed | history includes both occasions | pending |
| Announcements | open feed | published rows only | feed answers with `total` | pending |
| Medalist results | open medalists | published only, no PII | board answers | pending |
| Help / support | submit request → view | create/list/detail; staff resolves | create/list/detail 200; staff resolve executed | pending |
| Recovery | forgot password | fail-closed flow | request 200 no-leak; wrong code refused | pending |
| Refresh / retry | toggle network | stale banner, no crash | client logic unchanged from Phase 29 [AUTOMATED] | pending |
| Settings / staff surfaces | anonymous probes | 401/302, gated | scan/sync/settings 401, exam 302, directory gated | pending |

No broken or misleading action found; **no fake success state exists**.

## 5. Defects fixed this phase

**None.** Every failure encountered during verification was a defect in my own
verification script (malformed base64 PNG constant; wrong auth header
`Bearer` instead of `X-Scanner-Token`; urllib auto-following a 302 on anonymous
probes; non-idempotent re-runs; rate-limit 429s from repeated runs) — each fixed
in `verify.py`, never by changing product code. **Zero product defects found**;
the repository is byte-identical to the Phase 29 baseline.

## 6. Production readiness

**NO-GO.** Unchanged and correctly so: physical-device verification (§7) and
institutional-provider checks (real email provider, production secrets, WSGI
deployment) are not complete. The disposable environment uses demo secrets and
fake email mode by design.

## 7. Physical-device steps — PERFORM ON YOUR PHONE, THEN STOP

> Everything below runs against the disposable world; production is untouched.
> Phone and laptop must be on the **same Wi-Fi**. If a check fails, allow
> **inbound TCP 5000 and 8081** for the Wi-Fi/private firewall profile
> (see `docs/PHASE14_FIELD_TEST_GUIDE.md`).

### 7.0 Phone-browser reachability (do this first)

1. On the phone, open the browser and go to **`http://192.168.100.5:5000/api/config`**.
2. **Expected:** HTTP 200 with a small JSON object (`{"ok": true, ...}`).
   - If it loads → backend reachable from the phone ✅.
   - If it times out → firewall: allow inbound TCP 5000 on the Wi-Fi profile, retry.

### 7.1 Two-occasion lifecycle on Android

1. Install/open **Expo Go** on the phone → scan the QR in the Expo terminal
   (or enter `exp://192.168.100.5:8081`).
   **Expected:** the LGU app bundles and opens; Home shows the event with
   **"2 days"** countdown to rehearsal (2026-10-19 10:00, Rehearsal Hall B)
   and Event Details also lists the main convocation (2026-10-20 09:00,
   Main Auditorium, "3 days").
2. Sign in as a **fresh** student for the journey: **`usman.tariq@lgu.edu.pk` /
   `FieldTest2026!`** (FG-003 — Zara and Hina were consumed by API
   verification; alternatively re-run `verify.py` to reset the ledger).
   **Expected:** dashboard opens, registration active.
3. Issue the digital pass. **Expected:** pass issued, wording covers both
   occasions.
4. On a second device (or the same phone after signing out), open the scanner:
   sign in **`gateA-ana` / PIN `481902`**, select **Rehearsal** occasion,
   scan the pass. **Expected:** green **`REHEARSAL ENTRY RECORDED`**.
5. Re-scan the same pass for Rehearsal. **Expected:** **`ALREADY ADMITTED`**
   (duplicate blocked for that occasion).
6. Switch occasion to **Main convocation**, scan the same pass.
   **Expected:** **`CONVOCATION ENTRY RECORDED`** — rehearsal admission did
   **not** consume ceremony admission.
7. Re-scan for Main convocation. **Expected:** **`ALREADY ADMITTED`**.
8. Sign in as **`gateC-bilal` / PIN `735164`** (gate 3 only), attempt a scan
   at gate 1. **Expected:** **`GATE NOT AUTHORIZED`** (403).
9. Scan a garbage string. **Expected:** **`INVALID CODE`** (or
   `PASS INVALID` for an LGU2-shaped but unknown payload).
10. Airplane mode → scan (occasion Rehearsal, student with no admission yet,
    e.g. reissue a pass for Hina first) → **Expected:** scan queued as
    pending; restore network → sync → recorded **once**; replay shows
    **`ALREADY SYNCED`**.

### 7.2 Every student-dashboard option on Android

Walk the §4 table top to bottom on the phone: for each row, perform the
**Tap** column and confirm the **Expected** column. Record actual result per
row (works / error text / screenshot). Pay special attention to: photo upload
round-trip, reminder dismiss + unknown-key failure, support request create →
detail, and History showing both occasions.

### 7.3 When you are done

Report back the per-step results (pass/fail + any error text or screenshot).
Only confirmed, reproducible defects will be fixed, with regressions re-run —
then this report's §3.2/§4 Device columns get updated. **Nothing will be
committed or pushed; production `app/lgu.db` stays untouched.**

---

**Report status:** API-level verification complete (54/54). Physical-device
verification **pending operator action (§7)**. Production readiness: **NO-GO**.
