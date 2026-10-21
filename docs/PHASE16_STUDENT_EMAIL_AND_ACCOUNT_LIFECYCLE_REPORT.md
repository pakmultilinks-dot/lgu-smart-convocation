# Phase 16 — Student Email Verification & Account Lifecycle Readiness

**Objective:** Verify and harden the actual student signup, university-email
verification, login, and account-recovery workflows so they are ready for a
real email provider. Remove demonstrated defects, improve operational
configuration, and test the complete account lifecycle without using
production student data.

**Outcome:** The provider layer was hardened (TLS validation, explicit TLS
modes, timeouts, stage-classified failures), an operator configuration tool
with `check` / `probe` / `test-send` was added and validated, the code-entry
endpoints gained the missing per-IP limit, the mobile screens now state all
nine account states from authoritative responses, and the whole lifecycle is
covered by a new 52-check disposable-database suite. **Actual external email
delivery was NOT performed** — every SMTP variable is unset on this machine,
so §8 is reported as *not performed*, not passed.

---

## 1. Confirmed existing email-provider architecture

Read before changing anything: `app/emailer.py`, `app/student_auth.py`,
`app/web/student_routes.py`, `app/config.py`, `app/migrations.py`,
`app/scripts/test_student_accounts.py`, the `(student)` screens,
`mobile/src/api/studentApi.ts`, `mobile/src/store/studentSession.ts`, and
`mobile/app.json`.

| Layer | Confirmed behaviour (unchanged unless stated) |
|---|---|
| Delivery | Single subsystem `app/emailer.py`. Modes: `disabled` (default), `fake`, `smtp`. No dotenv, no console mode, no second mailer. |
| Fail-closed | `available()` is probed **before any account lookup**, so an unconfigured service is never an "email exists" oracle. Failure → `EmailUnavailable` → routes answer `503 email_unavailable`. |
| `fake` | In-process `OUTBOX` of `(to_email, code)`, refused outside `LGU_TESTING=1` **or** on the production DB. |
| Codes | `secrets.randbelow` 6-digit, stored only as HMAC-SHA256 keyed by `SECRET_KEY`; single-use; TTL `LGU_VERIFICATION_TTL` (600 s); `CODE_MAX_SENDS=3`, `CODE_MAX_ATTEMPTS=5`. |
| Sessions | `secrets.token_urlsafe(32)`, sha256 digest only, bearer header, no cookies/CSRF; 168 h; password reset revokes every session. |
| Login | 5 fails → 15-minute per-account lockout; dummy hash for unknown accounts; uniform `401 credentials` text. |
| Recovery | Identical `200` + identical body for known and unknown email; reset token is a single-use recovery challenge. |
| Password rule | `exam_auth.MIN_PASSWORD_LENGTH = 12` (single source of truth). |

The brief's premise was confirmed: the module existed and could speak SMTP,
but **no SMTP variable is configured on this machine** and the module had
gaps (see §2) that a real provider would have exposed at runtime.

## 2. Configuration changes and operator instructions

**`app/config.py`** (additive only):

| New knob | Env var | Default | Why |
|---|---|---|---|
| `SMTP_TLS` | `LGU_SMTP_TLS` | `auto` | Explicit `auto` / `starttls` / `ssl` / `none`; previously STARTTLS was implicit and unconfigurable. |
| `SMTP_TIMEOUT` | `LGU_SMTP_TIMEOUT` | `10` | A dead provider no longer hangs a signup indefinitely. |
| `STUDENT_RATE_MAX_CONFIRM` | `LGU_STUDENT_MAX_CONFIRM` | `20` | Budget for code entry itself (§5). |

**`app/emailer.py`** (hardened in place — no second subsystem):

- `_connect()` now uses `ssl.create_default_context()` for STARTTLS **and**
  for implicit TLS (`smtplib.SMTP_SSL`). *Behaviour change:* certificates are
  now verified; the historical `starttls()` call passed no context.
- `_classify()` maps every failure to a secret-free `(stage, detail)` pair —
  `config` / `connect` / `tls` / `auth` / `send` — and the raise uses
  `from None`, so no provider exception (with its arguments) can bubble into
  a response or a traceback log.
- `smtp_problems()` validates mode, host, port, TLS mode, timeout ≥ 1,
  sender-vs-username consistency, and TTL ≥ 60.
- Nothing in the module logs or prints; the routes discard stage/detail and
  answer one generic student message.

**New operator tool — `app/scripts/check_email_config.py`** (no network
unless asked, prints `set (N chars)` / `not set` for secrets, never a value):

```powershell
cd app
..\.venv\Scripts\python.exe scripts\check_email_config.py check              # static, no send, no connect
..\.venv\Scripts\python.exe scripts\check_email_config.py probe               # connect + TLS + AUTH, still no message
..\.venv\Scripts\python.exe scripts\check_email_config.py test-send --to you@example.edu.pk
```

`test-send` requires `--to` **and** `LGU_EMAIL_MODE=smtp`, otherwise it
refuses. Nothing is sent because the app starts or a suite runs.

**Documentation:** `docs/EMAIL_CONFIGURATION.md` covers the required provider
settings and purpose, hostname/port/TLS/sender/auth/timeout, local-vs-
production, no-send validation, the explicitly requested delivery test, and
failure diagnosis without disclosing secrets. `.env.example` at the repo root
is a **placeholder template** — consistent with the project, which reads
`os.environ` only and has no `.env` loader (`.env` is git-ignored; real
secrets belong in the process/hosting secret store). `app/README.md` gained a
short pointer section.

## 3. Student signup and verification results

All from `app/scripts/test_phase16_lifecycle.py` (disposable DB, synthetic
registrations, fake transport):

| Brief case | Result |
|---|---|
| 1. eligible synthetic student begins signup | `200`, challenge id + masked email returned, **no account row yet** |
| 2. identity verified against authoritative registration | wrong roll → `404 unmatched`; wrong name → `404`; altered email → `404`; non-active registration → `410`; already-claimed → `409` |
| 3. message generated by the configured test transport | exactly one `OUTBOX` entry for the university address, 6-digit code, code absent from the HTTP response |
| 4. token consumed successfully | `200` + session token, `consumed_at` set, replay → `410` |
| 5. sign in only after verification | `401` before `/complete`, `200` after |
| 6. invalid/expired/reused/forged tokens | wrong code `400 code` (attempt counter), forged challenge id `404`, expired `410 expired`, reused `410` |
| 7. resend rate limiting | `CODE_MAX_SENDS` honoured (`429 send_limit`), then per-IP `429 rate_limited` |

Regression: `test_student_accounts.py` still **92 checks, 0 failures** — the
identity-matching, digest-only storage, mask and "code never in the response"
assertions were kept, not rewritten.

## 4. Login and recovery security results

| Brief case | Result |
|---|---|
| 8. provider failure honest and safe | `503 email_unavailable`; **no account and no challenge row** created; recovery answers byte-identical for known and unknown email |
| 9. recovery reveals no account existence | `200` + identical body both ways; only the known account generates a message |
| 10. valid recovery resets password | `200` |
| 11. previous password stops working | `401` for the old password, `200` for the new one |
| 12. expired/consumed reset token | both rejected `410` |
| 13. rate limiting and abuse protection | per-IP login limit, per-IP recovery limit, **new** per-IP code-entry limit, and the 5-fail account lockout all engage — including against the *correct* password while locked |
| 14. no claiming another registration | mixed identity fields → `404`; extra `university_email` / `registration_number` fields injected into `/complete` cannot redirect the account created; a claimed registration cannot be claimed again (`409`) |
| 15. no credentials or tokens leak into logs | a capturing log handler saw **no** password, reset password, verification code or session token across a failed delivery, a malformed body and a bad login; malformed JSON answers JSON, never a traceback; `emailer.py` contains no logger and no `print` |
| 16. logout / session behaviour | logout revokes; revoked token → `401`; a password reset invalidates every earlier session |
| 17. rest of the student surface | `/pass`, `/history`, `/readiness`, `/support`, `/announcements`, `/medalists`, `/event`, `POST /profile` all `200` |

**Defect fixed this phase:** `/complete` and `/recovery/complete` had **no
per-IP limit** — only the per-challenge attempt cap. A client that requested
a fresh challenge after every guess could brute-force a 6-digit code. Both
routes now check `_limited("confirm", config.STUDENT_RATE_MAX_CONFIRM)`
before any lookup. (Safe for every existing suite: `reset_limits()` iterates
`sr._HITS`, so the new bucket clears automatically.)

**Known residual (documented, not "fixed"):** when a *configured* provider is
down, recovery returns `503` for a known email and `200` for an unknown one —
a narrow enumeration signal that only exists during an outage. Closing it
would require sending a message for unknown addresses or failing all mail
asynchronously; the brief prioritises not pretending success, so current
behaviour is kept and reported honestly.

## 5. Provider-failure and rate-limiting behaviour

Failure paths exercised in this environment (no live provider):

| Scenario | Observed |
|---|---|
| `LGU_EMAIL_MODE` unset (`disabled`) | `check` → exit **0** ("usable as written" for a disabled mode), signup/recovery → `503 email_unavailable`, no rows written |
| `smtp` without `LGU_SMTP_HOST` | `check` → exit **1** with `[x]` lines, secrets still masked |
| `test-send` while disabled | refuses, exit **1**, no message |
| `probe` against an unreachable port (`127.0.0.1:25999`) | `[x] connect failed: network error reaching the SMTP server (ConnectionRefusedError)`, exit **1** — stage named, no credentials printed |

Rate limits (all per client IP, in-process, window `LGU_STUDENT_WINDOW=60`):
verify/send 6, recovery 3, login 5, **confirm 20** (new), plus the
per-account lockout and the per-challenge send/attempt caps.

## 6. Mobile changes and test results

Reviewed all nine `(student)` screens, `src/api/studentApi.ts`,
`src/api/client.ts` (which already surfaces `ApiError.code`), session
storage, navigation and the Expo deep-link configuration.

| Required state | Where it now comes from |
|---|---|
| Account creation in progress | `code.tsx` submit for a new account → "Account creation in progress..." |
| Email verification required | `code.tsx` subtitle states it before the code is typed |
| Verification successful | `code.tsx` renders success **only after** `/complete` returned 200 |
| Verification link or token expired | the server's own 410 text ("expired" / "already been used" / "no longer exists") rendered verbatim |
| Resending verification | dedicated "Resending verification..." loading state on the resend button |
| Invalid credentials | uniform server `401` text |
| Recovery request submitted | neutral server note ("If that email has an account, a recovery code is on its way") — never a success claim |
| Password reset completed | `login.tsx` confirms it (`reset=1`) only after `/recovery/complete` answered 200 and the old session was cleared |
| Network / provider unavailable | explicit branches: `status === 0` (network) and `code === "email_unavailable"` (provider), which also states that no code was sent and no account was created |

Also fixed: both password hints said "At least 8 characters" while the server
enforces **12** (`code.tsx`, `recovery.tsx`). No client-side password length
check exists, so nothing else contradicted the rule.

**Deep links (honest finding):** the verification and recovery mail contain
**only a 6-digit code — no URL** (`emailer.py` has no link), no verification
link route exists on the server, `app.json` declares `scheme:
"lgu-smart-convocation"` but has no `intentFilters`, and the app registers no
`Linking` listener. Therefore **no deep-link handling is required, none was
added, and no external link is claimed to work**. A link-based flow would be
a new feature (new route + consent-reviewed URL in mail), not a fix.

New source-level suite `mobile/scripts/phase16-account-states-test.mjs` →
**17 checks, 0 failures** pins all of the above.

## 7. Exact test commands and pass/fail counts

```powershell
# Python (from app/), each with ..\.venv\Scripts\python.exe scripts\<file>
test_exam_auth.py                  ALL PASSED
test_student_accounts.py           92 checks, 0 failures
test_exam_registration.py          PASS
test_exam_dashboard.py             31 checks, 0 failures
test_phase8_integration.py         57 checks, 0 failures
test_phase8_acceptance.py          85 checks, 0 failures
test_phase9_support.py             58 checks, 0 failures
test_phase10_readiness.py          52 checks, 0 failures
test_phase11_pass_history.py       75 checks, 0 failures
test_phase12_qr_scanner.py         41 checks, 0 failures
test_phase13_e2e_acceptance.py     53 checks, 0 failures
test_phase14_scanner_access.py     ok (production database untouched)
test_event_announcements.py        58 checks, 0 failures
test_medalist_management.py        55 checks, 0 failures
test_convocation_migration.py      PASS
test_phase16_lifecycle.py          52 checks, 0 failures      # NEW
# → 16 suites, 0 failures

# Email tool (from app/)
..\.venv\Scripts\python.exe scripts\check_email_config.py check            # exit 0
..\.venv\Scripts\python.exe scripts\check_email_config.py probe            # exit 1 (no host configured)
..\.venv\Scripts\python.exe scripts\check_email_config.py test-send --to … # refused (exit 1)

# Mobile (from mobile/)
node scripts\phase16-account-states-test.mjs      # 17 checks, 0 failures   # NEW
node scripts\<each of the 33 .mjs suites>        # 33 scripts, 0 failures
npx tsc --noEmit                                  # 0
npx eslint .                                     # 0 errors (2 pre-existing
                                                 #  warnings in
                                                 #  event-announcements-test.mjs
                                                 #  and phase8-freshness-test.mjs)
```

Evidence classes, separated as required:

- **Automated tests** — everything in §7 above. Green.
- **Test-provider results** — fake transport (`OUTBOX`) and the
  configuration tool's failure paths. Green, and they prove fail-closed
  behaviour, not delivery.
- **Actual external email delivery** — **NOT PERFORMED** (§8).

## 8. Was actual external email delivery tested?

**No — not performed, and therefore not verified.**

`Get-ChildItem Env:` for `LGU_EMAIL_MODE`, `LGU_MAIL_FROM` and `LGU_SMTP*`
returns **0 variables** on this machine; no provider credentials were
supplied, none were requested from the operator, and none were written
anywhere. `probe`/`test-send` were only exercised against a deliberately
unreachable local port to prove the diagnosis path. **No claim of live SMTP
integration is made.**

## 9. Production database — before / after

| | Size (bytes) | SHA-256 | mtime (UTC) |
|---|---|---|---|
| Before Phase 16 | 278528 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | 2026-10-10T19:35:21.8392785Z |
| After Phase 16 | 278528 | `820113702B02CB2EA87BD5BC8253BA8733F89696DDED209465E94B5EE8CB915F` | 2026-10-10T19:35:21.8392785Z |

Identical. Every suite used its own temp `LGU_DB_PATH` with
`config.require_test_db()`; `app/lgu.db` was never a test or migration
target. Synthetic registrations only — no production student data.

## 10. Final Git status and changed-file summary

`git status --porcelain` → **141 entries** (the substantial uncommitted work
from earlier phases is fully preserved; nothing was reset, stashed, amended
or discarded). `git diff --check` → **exit 0** (only three LF→CRLF notices on
files this phase did not touch: `mobile/app.json`, `mobile/package.json`,
`mobile/package-lock.json`). Note that `git diff --check` inspects tracked
changes only; the new untracked files were validated by the test suites,
`npx tsc --noEmit` and `npx eslint .`.

Phase 16 files:

| File | Kind |
|---|---|
| `app/emailer.py` | hardened in place (TLS context, explicit modes, timeout, stage classification, `from None`) |
| `app/config.py` | modified — `SMTP_TLS`, `SMTP_TIMEOUT`, `STUDENT_RATE_MAX_CONFIRM` |
| `app/web/student_routes.py` | modified — `"confirm"` bucket + limit on `/complete` and `/recovery/complete` |
| `app/scripts/check_email_config.py` | **new** operator tool (`check` / `probe` / `test-send --to`) |
| `app/scripts/test_phase16_lifecycle.py` | **new** 52-check disposable-DB suite (brief §5 cases 1–17) |
| `docs/EMAIL_CONFIGURATION.md` | **new** operator documentation |
| `.env.example` | **new** placeholder-only configuration template |
| `app/README.md` | modified — pointer section |
| `mobile/app/(student)/code.tsx` | account-creation / success / resending states, 12-char hint |
| `mobile/app/(student)/verify.tsx` | provider-unavailable state |
| `mobile/app/(student)/recovery.tsx` | provider-unavailable state, 12-char hint |
| `mobile/scripts/phase16-account-states-test.mjs` | **new** 17-check source suite |
| `docs/PHASE16_STUDENT_EMAIL_AND_ACCOUNT_LIFECYCLE_REPORT.md` | this report |

## 11. Remaining provider configuration and device-level prerequisites

Before live delivery can be claimed:

1. Set `LGU_EMAIL_MODE=smtp`, `LGU_SMTP_HOST`, `LGU_SMTP_PORT`,
   `LGU_SMTP_TLS`, `LGU_SMTP_USER`, `LGU_SMTP_PASSWORD`, `LGU_MAIL_FROM` in
   the deployment's secret configuration (not in a file, not in git).
2. Run `check`, then `probe`, then `test-send --to <operator mailbox>` and
   confirm the message actually lands — only then is §8 satisfiable.
3. Decide whether the provider accepts the app's sender address (SPF/DMARC)
   for the university domain.
4. If a link-based verification flow is ever wanted, it is a new feature:
   a signed route, `intentFilters`, and a `Linking` listener — none exists
   today, and none was invented here.
5. Device-level: no Android device, emulator or SDK was available in this
   environment (see the Phase 15 report), so the mobile state changes were
   verified at source level only; on-device verification of the new labels
   remains open.

---

*Per the brief: no Phase 17 work, no commit, no push, no deployment, and no
production secrets were configured.*
