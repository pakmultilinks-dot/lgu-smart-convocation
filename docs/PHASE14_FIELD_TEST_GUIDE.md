# Phase 14/19 — Volunteer Scanner Field-Test Guide

This guide covers **on-device acceptance of the Phase 14 scanner access
control**: logging a volunteer in with a per-account PIN, scanning a real QR
code, and confirming the server enforces gate authorization — plus the
**Phase 19 staff portal** used to create, gate-assign, reset and revoke those
accounts.

> **Status of physical-device testing: NOT PERFORMED.**
> No Android device, `adb`, emulator, or Android SDK is present in this
> environment, so real camera scanning has **not** been verified end-to-end.
> Everything below is what a human with a device must run. Do not treat the
> passing automated suites as proof that on-device scanning works — they drive
> the HTTP API and app source, not a physical camera.

---

## 1. What Phase 14 changed (what you are testing)

Previously `/api/scan` and `/api/sync` trusted a client-supplied `volunteer`
name and `gate_id` with **no authentication**. Now:

- A volunteer signs in with a scanner **username + PIN** → receives a
  short-lived session token (`X-Scanner-Token`).
- The **server** derives the volunteer identity from the session — the name
  the device sends is ignored.
- The server only lets a scanner admit through **its authorized gates**;
  another real gate → `403 GATE NOT AUTHORIZED`; a non-existent gate →
  `UNKNOWN GATE` (unchanged legacy behaviour).
- `/api/sync` (offline queue flush) is protected the same way, per item.
- There is **no shared/default credential**. Accounts are provisioned locally
  (below) and the PIN is shown once at creation.

## 2. Provision a scanner account

Two supported paths. Both store only a scrypt hash and print or render the PIN
**once**; neither ships a default or shared credential.

### 2a. Staff portal (authenticated — preferred)

1. Sign in to the Examination Department portal (`/exam/login`) with a staff
   username and password.
2. From the dashboard, **Scanner accounts** (or go straight to
   `/exam/scanners`) → **Create a scanner account** (`/exam/scanners/new`).
3. Enter a **Username** (the volunteer types this on the device), a
   **Volunteer display name**, and tick the gates they will actually staff.
4. Choose how the initial credential is provisioned:
   - **Leave the PIN blank** — a one-time PIN is generated and shown **once**
     on the next screen. Write it down and hand it over. It cannot be
     retrieved again; use **Replace PIN** if it is lost.
   - **Type a PIN yourself** — only if you will pass it to the volunteer out
     of band. It is never echoed back on screen.
   - **Tick "Create with no usable credential yet"** — the account exists and
     its gates are set, but it **cannot sign in** until you open the account
     and choose **Establish PIN**. Use this when the volunteer has not
     arrived yet.
5. On `/exam/scanners/<id>` you can change the gate set, replace the PIN,
   revoke all live sessions, and disable or re-enable the account.

### 2b. Local CLI (server host, attested operator)

From `app/` (uses the repo venv; writes to the configured DB):

```
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py create ^
    --username gateA-ana --name "Ana Cruz" --gates 1,2
```

- The **PIN is printed once** and never stored in plaintext. Record it for the
  volunteer; reset any time with `pin <id>`.
- Other commands: `list`, `gates <id> --gates 2,3`, `pin <id>`,
  `revoke <id>`, `activate <id>`, `sessions <id>`.
- Gate ids map to `/api/gates` (seeded `G1..G7` → ids `1..7`). Give each
  volunteer only the gates they actually staff.

### Provenance: portal vs CLI

Every lifecycle action is written to `audit_log` with the actor and a `via=`
tag:

| Path | Actor recorded | `via=` | What it proves |
|---|---|---|---|
| Staff portal | The authenticated staff **session** username | `via=portal` | Verified identity — the submitted `actor`/`staff_id` form fields are never read. |
| Local CLI | The `--actor` string typed by the operator | `via=cli` | **Local attestation, not verified identity.** Anyone with shell access can type any name. |

For accountability that must survive scrutiny, use the portal. The CLI is for
break-glass provisioning on the server host and is distinguishable in the
trail precisely because it is attested rather than authenticated.

> **Authorization model (honest limitation).** `staff_users` has no role or
> permission column, so the rule implemented is the smallest defensible one:
> **any authenticated, active Examination Department staff account** may
> manage scanner accounts. If your institution later needs a separate
> "scanner admin" permission, that requires a schema and policy decision — do
> not assume it exists today.

## 3. Start the app (dev machine)

```
cd mobile
npm install
npx expo start
```

Then open in **Expo Go** on the Android device (same Wi-Fi), or press `a` for
an emulator if one is configured. To reach the volunteer scanner: **mode
picker → Volunteer**, then the **Scanner** tab.

**Backend URL — the app finds it automatically in dev; you do not edit
`config.ts`.** In dev/Expo Go the app reads Metro's own host
(`Constants.expoConfig.hostUri`) and targets `http://<that-host>:5000`
(`mobile/src/store/settings.ts`). Because it reuses the phone's live DHCP
address, a Wi-Fi change never needs a source edit. Two requirements:

- Flask must bind a LAN-reachable address. `app/run.py` uses `0.0.0.0`, so
  the phone reaches it at the laptop's LAN IP (e.g. `http://192.168.100.5:5000`)
  — **not** the phone's own `localhost`.
- The laptop firewall must allow inbound TCP on the Flask port (5000) on the
  Wi-Fi/private profile.

To point at a different machine, set a **Custom server** URL in the app's
Settings/Admin screen (validated `http://` address) — still no source edit.

### Keeping test and real environments separate

- **Test/field backend:** point `LGU_DB_PATH` at a disposable file and set
  `LGU_TESTING=1`; startup then refuses to run against `app/lgu.db`, and the
  demo/test endpoints (`/api/demo-payload`, `/api/test-records`,
  `/api/test-scanner-session`) are enabled. This is the only mode used for
  the procedures below.
- **Real backend:** leave `LGU_DB_PATH` unset (uses `app/lgu.db`) and never
  set `LGU_TESTING`. Test tooling then returns **404**, so a test phone can
  never mint a scanner or read a demo payload against production.

**Never point the test phone at `app/lgu.db`, and never display real student
records.** The disposable DB is seeded only with synthetic roster/guest data.

## 4. Test cases (run on the device)

| # | Steps | Expected |
|---|-------|----------|
| T1 | First open of Scanner, no session | A **sign-in** prompt (username + PIN) appears; scanning is blocked until signed in. |
| T2 | Enter the provisioned username + the printed PIN, **Sign in** | Prompt dismisses; the volunteer-name prompt (or the scanner) appears. |
| T3 | Scan a student's **legacy LGU1** QR at an **authorized** gate | Green **ENTRY RECORDED** (or EXIT for exit mode). Volunteer shown is the account's display name. |
| T4 | Repeat the **same** student QR immediately | Amber **ALREADY INSIDE** (never a second entry). |
| T5 | Attempt a scan at a **real gate the scanner is not authorized for** | Red **GATE NOT AUTHORIZED** (403). No admission is recorded. |
| T6 | Scan a student's QR while **offline**, reconnect, let the queue sync | Each queued item is authorized per-item; unauthorized gates are refused; duplicates collapse to **ALREADY SYNCED**. |
| T7 | Scan a **convocation LGU2** pass (eligible student) at an authorized gate | Admitted once; a second scan of the same pass is refused (admitted exactly once). |
| T8 | Force a wrong PIN 5+ times quickly | Further login attempts are **rate-limited** (429) within the window. |
| T9 | Sign out (or revoke the account via `revoke <id>`), then scan | The scanner is re-locked; the next scan is rejected (401) until a fresh sign-in. |

## 4b. Operator runbook (what to do at the gate)

**A scan comes back red/amber — read the screen title; it tells you the action:**

| Screen title | Meaning | Operator action |
|---|---|---|
| `ALREADY INSIDE` | This student already entered (duplicate scan). | No action — do **not** re-scan. One admission already exists. |
| `ALREADY USED` | Guest pass already consumed (guests are one-entry). | No action — direct the guest to the volunteer desk if they dispute. |
| `NOT INSIDE` | Exit scanned for someone with no active entry. | Ask them to scan **Entry** first, or check the correct mode toggle. |
| `INVALID CODE` | QR failed the signature check — tampered/forged/photographed badly. | Do not admit. Re-scan the original pass; if it still fails, send to the volunteer desk. |
| `UNKNOWN CODE` | Valid signature but not in this system's roster/ledger. | Do not admit. Verify the person's registration at the desk. |
| `GUEST PASS IS ENTRY ONLY` | Exit mode used on a guest pass. | Switch the scanner to **Entry** mode. |
| `GATE NOT AUTHORIZED` (403) | This scanner account is not allowed at the selected gate. | Confirm the gate selector matches your post. If it is correct, an Examination Department staff member opens `/exam/scanners/<id>` and ticks the missing gate under **Gate access** (or run `gates <id> --gates ...` on the server). The change takes effect on the next scan. |
| `Scanner sign-in required` (401) | Session expired/revoked (12 h TTL, or an admin revoked it). | Sign in again with your username + PIN. If sign-in is refused, contact the admin — your account may be disabled or its PIN replaced. |
| `Too many attempts` (429) | Repeated wrong PINs (5 per 60 s per device, plus a 15-min account lock after 5 wrong). | Wait out the window (or the 15-minute lock), then retry carefully. An admin can also open the account and choose **Replace PIN**. |

**Backend or network unavailable:** the scanner queues scans offline and
retries; queued items sync when the connection returns (each item is
re-authorized server-side, duplicates collapse to `ALREADY SYNCED`). If the
app cannot reach the server at all: confirm the laptop is running the Flask
server, the phone is on the **same Wi-Fi**, and the firewall allows the port.
Do not switch the phone to a custom URL unless an admin tells you the server
address has changed.

**Provisioning / session administration:** §2a covers the staff portal
(`/exam/scanners`), which is the authenticated path. §2b covers the
break-glass CLI on the server host.

## 4c. Managing a scanner account from the portal

Sign in at `/exam/login`, then **Scanner accounts**. The page lists every
account with its status (`Active`/`Disabled`), credential state
(`Established` / `Not yet set`), authorized gates, live session count and last
sign-in, plus the recent management history.

Open an account (`/exam/scanners/<id>`) for:

| Need | Action | Effect |
|---|---|---|
| Volunteer arrives, account created earlier with no credential | **Establish PIN** (blank = generated one-time value) | Account becomes usable; the PIN is shown once. |
| PIN was lost, shared by mistake, or a volunteer left | **Replace PIN** | New value takes effect immediately; the previous PIN stops working on the very next attempt. Live sessions are **not** automatically killed — use **Revoke sessions** for that. |
| Device lost, stolen, or a session must be cut now | **Revoke all sessions** | Every live token stops resolving at once. The account stays usable and can sign in again — this is the fast cut, not a disable. |
| Volunteer leaves or is suspended | **Disable account** | Sign-in refused, all live sessions dead, no failure budget consumed. **Enable account** later restores the *same* credential — it was never reset. |
| Post change | **Gate access** checkboxes → Save | Server-side gate set replaced on the next scan. Submitting no gates means "no gates", not "keep as-is". |

**Confirming authorized gates:** the account page's gate list is the source of
truth the server enforces. Cross-check it against `/api/gates` on the device —
a gate ticked in the portal but not in `/api/gates` does not exist and will be
refused as `UNKNOWN GATE`.

**Investigating a denied attempt without exposing credentials:**

1. **Account-level.** On the account page, check `Active`/`Disabled`, the
   credential badge, `Locked until`, failed attempts and last sign-in. The
   **History for this account** table shows gate changes, PIN resets, session
   revocations, disables and activations with the acting staff username.
2. **Server log.** `audit_log` carries `scanner_login_success`,
   `scanner_login_failed` and `scanner_login_blocked` rows for the username.
   These are investigation records and are deliberately **not** shown in the
   management history list.
3. **Denied management attempts.** Unauthenticated or CSRF-failing writes to
   `/exam/scanners*` are recorded as `scanner_mgmt_denied` with the route and
   reason. These **are** in the management history, so a probe is visible. The
   record is bounded at 20 per client per 5 minutes so an anonymous flood
   cannot grow `audit_log` without limit.

No PIN, PIN hash, session token or token hash is ever rendered on a
management page, written to `audit_log`, or printed by the CLI list command.
If you need a PIN, the only supported routes are **Replace PIN** (portal) or
`pin <id>` (CLI).

**Rehearse on a disposable DB first.** Point `LGU_DB_PATH` at a throwaway file
and set `LGU_TESTING=1` (see §3), exercise the whole create → gate → reset →
disable cycle, then start over.

## 5. Evidence to capture

- Photo/screenshot of the **sign-in prompt** (T1) and a **successful admission**
  (T3) showing the derived volunteer name.
- Screenshot of **GATE NOT AUTHORIZED** (T5).
- A screenshot of the offline→sync path (T6) if you exercise it.
- The `manage_scanner_staff.py create` output **redacted** (never publish the
  PIN or a token).
- A screenshot of `/exam/scanners/<id>` with the account showing
  `Credential established` and the intended gate list — **with the PIN field
  and any one-time value out of frame**.
- The **History for this account** table showing who changed the gates and
  when.

## 6. What is already proven WITHOUT a device

Run from `app/` (repo venv):

```
..\.venv\Scripts\python.exe scripts\test_phase14_scanner_access.py
```

This drives the real routes on a disposable temp DB and proves the server side
of every case above: 401 on no/forged/revoked/expired session, 429 on repeated
login failures, 403 on an unauthorized gate, server-derived volunteer identity,
legacy LGU1 + convocation LGU2 admitted exactly once, expired/forged passes
rejected, and no bypass via `/api/sync` or malformed bodies — **48 checks, 0
failures**.

The mobile side is covered by source + real-HTTP fixtures under `mobile/scripts/`
(`scanner-logic-test.mjs`, `api-test.mjs`, `data-truth-test.mjs`,
`gate-integrity-test.mjs`, `master-audit-regression.mjs`) plus `tsc --noEmit`
and eslint, all clean.

### Proven WITHOUT a device — Phase 19 management workflow

Run from `app/` (repo venv):

```
..\.venv\Scripts\python.exe scripts\test_phase19_scanner_management.py
```

This drives the real portal routes, sessions, persistence and audit trail on a
disposable temp DB and proves: unauthenticated management is refused and
recorded; a pending-credential account cannot authenticate; a one-time PIN is
rendered exactly once and cannot be recovered by refresh; replacing a PIN
invalidates the previous value; disabling kills sign-in and live sessions while
re-enabling restores the same credential; revoking sessions signs the device
out without disabling the account; an out-of-scope gate is still refused
server-side and a newly added gate takes effect; a forged `actor`/`staff_id`
field never changes the recorded actor; no PIN, PIN hash, token or token hash
reaches a page, the audit trail or a log; racing creates yield one account;
the CLI path still works and is distinguishable via `via=cli`; and the legacy
LGU1, convocation LGU2, student and readiness surfaces are unchanged —
**105 checks, 0 failures**.

## 7. Outstanding before "device-verified"

- [ ] Real Android camera scan of a legacy LGU1 QR (T3, T4).
- [ ] Real Android camera scan of a convocation LGU2 pass (T7).
- [ ] Offline→sync reconciliation on a real device (T6).
- [ ] Confirm the Expo camera permission + cold-start login persistence on a
      fresh install.
- [ ] Walk a real account through the Phase 19 portal on a disposable DB:
      create with no credential → **Establish PIN** → sign in on the device →
      **Replace PIN** → confirm the old PIN fails → **Revoke sessions** →
      confirm the device is signed out but can sign in again → **Disable
      account** → confirm sign-in is refused.

Until those boxes are ticked by a human on hardware, Phase 14/19 is
**server- and source-verified only**, not device-verified.
