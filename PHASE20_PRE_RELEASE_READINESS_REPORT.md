# Phase 20 — Pre-Release Readiness, Migration Rehearsal & Go/No-Go Audit

**Date:** 2026-10-10
**Branch:** `main` @ `298c272d53485ba4473c2defe72db70c02733a2c` (unchanged — nothing committed)
**Verdict:** **NO-GO for production deployment.** The codebase is internally consistent and the
automated suite is green, but five release gates remain open (§9). This report is the deliverable;
work stops here for review.

---

## 1. Baseline and release discipline

| Item | Baseline (start of phase) | End of phase | Status |
|---|---|---|---|
| Git HEAD | `298c272d53485ba4473c2defe72db70c02733a2c` | same | **PASS** |
| Branch | `main` | `main` | **PASS** |
| Stashes | 0 | 0 | **PASS** |
| Commits ahead of HEAD | 0 | 0 | **PASS** |
| Production DB size | 278528 | 278528 | **PASS** |
| Production DB SHA-256 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | identical | **PASS** |
| Production DB mtime | `2026-10-10T19:35:21.8392785Z` | `2026-10-10T19:35:21.839278+00:00` | **PASS** |
| Production DB `PRAGMA integrity_check` | ok | ok | **PASS** |
| Production DB `PRAGMA user_version` | 6 | 6 | **PASS** (see §3) |

Nothing was reset, cleaned, stashed, amended, committed, pushed, or deployed. No production
credential was read or altered. `app/lgu.db` was opened **read-only** (`mode=ro` URI) for every
check in this phase; its bytes are unchanged.

Working tree: **157 entries** (150 tracked-modified + 7 new Phase 20 files), up from the 149-entry
baseline. The 8-entry delta is exactly this phase's deliverables:

```
app/backup.py
app/scripts/backup_db.py
app/scripts/test_phase20_migration_rehearsal.py
app/scripts/test_phase20_backup_restore.py
app/scripts/test_phase20_config_audit.py
app/scripts/test_phase20_authz_matrix.py
docs/OPERATIONS.md
PHASE20_PRE_RELEASE_READINESS_REPORT.md   (this file)
```

No file was deleted. No stray artifacts remain (test temp dirs removed; `app/backups/` was never
created outside a temp directory).

---

## 2. Migration rehearsal — **PASS** (51 checks, 0 failures)

Suite: `app/scripts/test_phase20_migration_rehearsal.py`. Every run uses a disposable database in a
temp directory with `LGU_TESTING=1` and `config.require_test_db()`; the production database is
never a target.

| # | Scenario | Result |
|---|---|---|
| 1 | Fresh `init_db()` reaches the latest version | **PASS** |
| 2 | Re-running `migrate()` on an up-to-date DB is a no-op (idempotent) | **PASS** |
| 3 | v10 → v11 upgrade preserves existing rows (data not dropped) | **PASS** |
| 4 | **Every historical version** (1→11) upgrades cleanly from its own starting point | **PASS** |
| 5 | A failing migration rolls back **both** schema and `user_version` | **PASS** |
| 6 | A database at a **newer** version than the build is refused | **PASS** (defect fixed, §7) |
| 7 | A malformed non-SQLite file is rejected with a clean error | **PASS** |
| 8 | Post-migration constraints hold (NOT NULL / UNIQUE / FK) | **PASS** |
| 9 | The application behaves correctly on an upgraded database | **PASS** |
| 10 | Temp artifacts cleaned up | **PASS** |

**What this does not prove:** migration 11 has been applied to **production**. It has not. The
production database is at `user_version = 6`. Rehearsal on a disposable database is evidence that
the upgrade path *works*, not evidence that it has *run*.

---

## 3. Backup and restore workflow — **PASS** (40 checks, 0 failures)

New module `app/backup.py` + CLI `app/scripts/backup_db.py`.

| # | Scenario | Result |
|---|---|---|
| 1 | Fixture creation | **PASS** |
| 2 | Backup taken under **concurrent write churn** is consistent (online backup API, not a file copy) | **PASS** |
| 3 | `validate()` rejects: missing file, empty/too-small file, non-SQLite magic, corrupt body | **PASS** (defect fixed, §7) |
| 4 | Restore targets a **separate** directory; source untouched | **PASS** |
| 5 | Manifest exposes sizes, digests and row counts — **no secrets** | **PASS** |
| 6 | CLI round trip (`create` → `verify` → `restore` → `list`) | **PASS** |
| 7 | `restore()` **refuses** to write over the production database path | **PASS** |

Properties the workflow guarantees: online (non-blocking) copy, SHA-256 manifest, read-only
validation before any restore, restore-to-new-path only, and a CLI that prints digests rather than
data.

---

## 4. Deployment & runtime configuration audit — **PASS** (84 checks, 0 failures)

Suite: `app/scripts/test_phase20_config_audit.py`.

| Area | Finding | Status |
|---|---|---|
| **Demo secrets** | `run.py` **fails closed** (exit 1) when `LGU_SECRET_KEY`, `LGU_HMAC_SECRET` or `LGU_ADMIN_PIN` still hold their committed demo values — checked **before** `init_db()`/`seed()`, so a misconfigured start never touches a database (verified `db-created=False`). Local dev opts in with `LGU_ALLOW_DEMO_SECRETS=1`. | **PASS** (defect fixed, §7) |
| **Session cookie** | `HttpOnly` set, `SameSite=Lax`, `Secure` off by default (plain-HTTP LAN deployment) and configurable via `LGU_COOKIE_SECURE=1` for TLS. | **PASS** (defect fixed, §7) |
| **CORS** | Allowlist enforced: foreign origin denied, same-host/loopback granted, never `*`, `Vary: Origin` present. | **PASS** |
| **Health endpoint** | `{"app":"LGU Smart Convocation","ok":true,"version":"LGU1"}`; unknown paths return 404 with no leakage. | **PASS** |
| **CSRF** | Missing token → 403; forged token → 403 and **no account created**. | **PASS** |
| **Rate limiting** | Repeated bad logins → `401,401,401,401,401,429`. | **PASS** |
| **Test tooling** | Test-only routes return 404 on the production path; `require_test_db()` exits rather than opening a real DB. | **PASS** |
| **Email fail-closed** | With `LGU_EMAIL_MODE` unset/disabled, verification send raises `EmailUnavailable` and the student API surfaces 503 `email_unavailable`. Every `smtp_problems()` validator exercised. | **PASS** |
| **Scanner sessions** | Session creation, gate enforcement, revoke → 401. | **PASS** |
| **Secret leakage** | 7 endpoints scanned for `password_hash`, `pin_hash`, `token_hash`, `code_hash`, `secret_key`, `hmac_secret`, demo-key material — none present. | **PASS** |
| **Upload caps** | Photo limits positive and storage dirs live **outside** `static/`. | **PASS** |
| **Config degradation** | `positive_int()` degrades safely for `0`, `-3`, `not-a-number`, `""`. | **PASS** |

---

## 5. Authorization matrix — **PASS** (35 checks, 0 failures)

Suite: `app/scripts/test_phase20_authz_matrix.py`. Enumerates **every** non-static route × method
from `app.url_map` (~90+) and probes each anonymously with no credentials.

Every route falls into exactly one of three buckets:

1. **Explicitly public** — present in a written allowlist with a per-route justification (kiosk
   display, health, gates/guests read, registration, pre-auth student flows, `/scan` GET).
2. **Refuses** — returns `401 / 403 / 404 / 405 / 415 / 429 / 503`.
3. **Redirects to login** — `302` to a URL containing `/login` (the documented refusal for browser
   surfaces such as `staff_required` → `/exam/login`; a redirect to a login page is a denial, not a
   grant).

Additional assertions:

- Every allowlisted endpoint **still exists** (stale-allowlist detection).
- Protected surfaces refuse an anonymous caller.
- A **staff session cannot** reach `/api/student/me`, `/api/student/pass`, or `/api/scan`.
- Audit provenance is **server-stamped**: `via=portal` is written by the server; caller-supplied
  `via=cli` / `actor=root` are ignored.
- `_audit_mgmt_denied` is capped: flooding `_DENY_MAX_PER_WINDOW + 25` attempts writes at most
  `_DENY_MAX_PER_WINDOW` rows.

**Authorization model, stated honestly:** multi-tier — (a) public kiosk/display reads, (b)
`ADMIN_PIN` mutations, (c) staff session, (d) scanner token, (e) student Bearer. `staff_users` has
**no role column**; single-tier staff authorization is a deliberate, documented decision
(`docs/OPERATIONS.md` §4), not an omission. `via=cli` is an operator **attestation**, not
authentication.

---

## 6. Operations documentation — **PASS**

`docs/OPERATIONS.md` (new), 9 sections: runtime model & network topology; secrets fail-closed
table; database / migrations / backup; provisioning (staff single-tier decision, scanner CLI,
audit provenance, seeded gates); event-day procedures; email modes; health checks & shutdown;
troubleshooting table; **outstanding release gates**. It explicitly warns: *do not read a green
automated suite as production readiness.*

---

## 7. Defects found and fixed in this phase

| # | Defect | Severity | Fix |
|---|---|---|---|
| 1 | `migrations.migrate()` silently accepted a database at a **higher** schema version than the build supports — running an older build against a newer DB could corrupt data. | **High** | Raises `RuntimeError` and refuses to open it; also asserts migration versions are strictly ascending. Covered by rehearsal step 6. |
| 2 | `backup.validate()` leaked a raw `sqlite3.DatabaseError` on corrupt input instead of a clean, reportable error. | Medium | Wrapped into `ValueError("database is corrupt: …")`. Covered by backup test step 3. |
| 3 | `run.py` started the server with **publicly-known committed demo secrets** (only a console warning), while binding `0.0.0.0`. `SECRET_KEY` signs Flask cookies and student recovery HMACs, `HMAC_SECRET` signs QR codes, `ADMIN_PIN` gates broadcasts/settings. | **High** | Fails closed with exit 1 **before** any database is touched, unless `LGU_ALLOW_DEMO_SECRETS=1`. Covered by config audit step 1. |
| 4 | Staff session cookie had **no `SameSite` attribute**, riding along on cross-site requests behind only the explicit CSRF tokens. | Medium | `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE="Lax"`, `SESSION_COOKIE_SECURE=config.COOKIE_SECURE`. Covered by config audit step 2. |
| 5 | The new startup guard broke 7 mobile harnesses that spawn `run.py` with deliberately-demo secrets. | Test-infra | Harnesses opt in with `LGU_ALLOW_DEMO_SECRETS=1` on their throwaway databases — the guard was **not** weakened. This empirically proved the guard works. |

---

## 8. Full regression battery — **PASS**

### Python — 24 suites, **0 failing**

| Suite | Result |
|---|---|
| convocation_migration | PASS |
| event_announcements | 58 |
| exam_auth | ALL PASSED |
| exam_dashboard | 31 |
| exam_registration | PASS |
| medalist_management | 55 |
| phase10_readiness | 52 |
| phase11_pass_history | 75 |
| phase12_qr_scanner | 41 |
| phase13_e2e | 53 |
| phase14_scanner_access | 48 |
| phase16_lifecycle | 52 |
| phase17_cross_role | 156 |
| phase18_residual_closure | production db unchanged: True |
| phase19_scanner_management | 105 |
| **phase20_authz_matrix** | **35 / 0** |
| **phase20_backup_restore** | **40 / 0** |
| **phase20_config_audit** | **84 / 0** |
| **phase20_migration_rehearsal** | **51 / 0** |
| phase8_acceptance | 85 |
| phase8_integration | 57 |
| phase9_support | 58 |
| student_accounts | 92 |

### Mobile — 33 suites, **0 failing**

admin-lockout, api-test, camera-states 18, cycle4-fixes 18, data-truth 53, db-isolation 29,
display-admin-auth 16, event-announcements 25, gate-integrity 23, layout-p5 28, layout-p6 23,
layout-p7 39, layout-p8 44, layout-p9 24, master-audit-regression ALL PASSED, medalist-board 22,
navigation-broadcast, pass-history 31, phase16-account-states 17, phase8-freshness 33, progress,
qr-pass-source 10, readiness-source 29, release-safety ALL CHECKS PASSED, scanner-logic 58,
student-screens 39, ui-35h, ui-35i, ui-35j 83, ui-35k 39, ui-35l 13, ui-35m, ui-35r 11.

### Tooling

| Check | Result |
|---|---|
| `npm run tsc` | exit 0 |
| `npm run lint` (eslint) | exit 0 |
| `git diff --check` | exit 0 — 3 pre-existing LF/CRLF warnings on `mobile/app.json`, `mobile/package-lock.json`, `mobile/package.json` (untouched this phase) |
| `ruff check` | **No Python lint gate exists in this repo.** 186 project-wide findings, overwhelmingly pre-existing `UP031` (percent-format is the house style). Per-file comparison against HEAD shows no new *class* of finding introduced by this phase's code. Not treated as a gate. |

---

## 9. Go / No-Go audit

| # | Gate | Status | Evidence / gap |
|---|---|---|---|
| 1 | Automated regression (Python + mobile + tsc + eslint) | **PASS** | §8 — 0 failures across 57 suites |
| 2 | Migration rehearsal on disposable DBs | **PASS** | §2 — 51 checks |
| 3 | Backup / restore workflow | **PASS** | §3 — 40 checks |
| 4 | Runtime configuration audit | **PASS** | §4 — 84 checks |
| 5 | Authorization matrix closed or classified | **PASS** | §5 — 35 checks |
| 6 | Operations runbook exists | **PASS** | §6 — `docs/OPERATIONS.md` |
| 7 | Production DB integrity preserved | **PASS** | §1 — byte-identical, `integrity_check ok` |
| 8 | **Real SMTP delivery** | **NOT TESTED** | No SMTP server available; only `fake`/`disabled` modes exercised. Fail-closed behaviour is proven; actual delivery is not. |
| 9 | **Android device / emulator validation** | **NOT TESTED** | No `adb`, no emulator, no `java` in this environment. |
| 10 | **Migration 11 applied to production** | **NOT APPLIED** | Production is at `user_version = 6`; build supports 11. Rehearsal ≠ deployment. |
| 11 | **Performance / capacity under event-day load** | **NOT TESTED** | No load testing performed. |
| 12 | **Production credentials provisioned** | **NOT DONE** | Demo secrets still in place; the guard now blocks an accidental start. |

### Verdict: **NO-GO**

Gates 8–12 are open. In particular, gate 10 means the running production database is **five schema
versions behind** the code, and gate 12 means the server will refuse to start until an operator
sets real secrets. Both are correct, deliberate refusals — not defects.

**Do not declare production readiness solely because automated tests pass.**
**Do not describe migration 11 as production-applied merely because it passed on a disposable database.**

---

## 10. Hard stop

Phase 20 is finished and this report is written. Stopping for review.

Not done, by instruction: Phase 21 not begun; no commit; no push; no deploy; production credentials
unaltered; `app/lgu.db` unmodified.
