# Email configuration — verification codes and recovery (Phase 16)

The portal emails a 6-digit verification code at signup and at password
recovery. Delivery is **fail-closed**: with the default settings the server
answers `503 email_unavailable` and creates no account, instead of pretending
a message went out. There is no "console"/"dev" mode that prints codes.

## 1. Settings and what they do

All settings are read from the **process environment** (`os.environ`). There
is no `.env` loader in this project, so exporting them in the service unit /
shell / platform secret store is what actually configures the app. The
repository ships `.env.example` at the root as a **placeholder template
only** — copy the names, never commit real values (`.env` is git-ignored).

| Variable | Default | Purpose |
| --- | --- | --- |
| `LGU_EMAIL_MODE` | `disabled` | `disabled` (fail closed), `fake` (test-only outbox), `smtp` (real provider). |
| `LGU_SMTP_HOST` | *(empty)* | SMTP hostname. Required when the mode is `smtp`. |
| `LGU_SMTP_PORT` | `587` | TCP port. `587` with STARTTLS, `465` with implicit TLS, `25`/`1025` for a local test relay. |
| `LGU_SMTP_TLS` | `auto` | `auto` = STARTTLS only when a username is set; `starttls` = always upgrade; `ssl` = implicit TLS from connect (port 465); `none` = plaintext (local relay only). |
| `LGU_SMTP_TIMEOUT` | `10` | Seconds allowed for the connect + send hop. Keeps a dead provider from hanging a signup. |
| `LGU_SMTP_USER` | *(empty)* | Account name for AUTH. Leave empty only for an unauthenticated relay. |
| `LGU_SMTP_PASSWORD` | *(empty)* | App password / SMTP secret. Secret-store only. |
| `LGU_MAIL_FROM` | *(empty)* | Sender address shown in the `From` header. Required when no `LGU_SMTP_USER` is set; it may differ from the authenticated user (noreply@…). |
| `LGU_VERIFICATION_TTL` | `600` | Seconds before a code expires (minimum 60). |
| `LGU_CODE_MAX_SENDS` | `3` | Codes issued per challenge before resend is refused. |
| `LGU_CODE_MAX_ATTEMPTS` | `5` | Wrong entries per challenge before it locks. |

Per-IP limits (per `LGU_STUDENT_WINDOW`, default 60 s): `LGU_STUDENT_MAX_VERIFY`
(6), `LGU_STUDENT_MAX_RECOVERY` (3), `LGU_STUDENT_MAX_LOGIN` (5),
`LGU_STUDENT_MAX_CONFIRM` (20 code-entry attempts).

TLS certificates are validated with Python's default trust store — set
`LGU_SMTP_TLS=none` only against a local test relay, never in production.

## 2. Local testing vs production

| | Local / test | Production |
| --- | --- | --- |
| Mode | `fake` inside `LGU_TESTING=1` with a disposable DB, or `smtp` to a local relay (MailHog, `python -m aiosmtpd`, provider sandbox) | `smtp` with the real provider |
| TLS | `none` or `auto` against localhost | `auto`/`starttls`/`ssl`, certificate validation on |
| Credentials | sandbox credentials in the shell | platform secret configuration, never in a file |
| Guard | `fake` refuses to run outside `LGU_TESTING=1` or against the production DB | `LGU_EMAIL_MODE` unset ⇒ `disabled` ⇒ HTTP 503 |

Never point a test run at `app/lgu.db`.

## 3. Validate without sending anything

```powershell
cd app
..\.venv\Scripts\python.exe scripts\check_email_config.py check
```

Static only: no connection, no message. It prints every setting (credentials
are shown as `set (N chars)`, never in clear) and lists missing or
inconsistent combinations, e.g. mode `smtp` without `LGU_SMTP_HOST`, or a
username with an empty password. Exit `0` = usable, `1` = fix the `[x]` lines.

To also prove connectivity, TLS and authentication **without sending**:

```powershell
..\.venv\Scripts\python.exe scripts\check_email_config.py probe
```

It connects, upgrades to TLS, authenticates if a username is configured,
quits — and reports which hop failed (`connect`, `tls`, `auth`).

## 4. Explicit delivery test

Only on request, only to a mailbox you control:

```powershell
..\.venv\Scripts\python.exe scripts\check_email_config.py test-send --to you@example.edu.pk
```

`--to` is mandatory, `LGU_EMAIL_MODE` must be `smtp`, and exactly one message
is sent. Nothing is sent because the app started or a test suite ran. Check
the mailbox for arrival — the command reports what the provider accepted, not
what landed in the inbox.

## 5. Diagnosing failures without disclosing secrets

| Symptom | Meaning | Where to look |
| --- | --- | --- |
| Student sees "Verification email could not be sent." (503) | Delivery unavailable — fail closed, no account created | `check` first, then `probe` |
| `config` stage | Mode/host/sender/username-password combination incomplete | `[x]` lines from `check` |
| `connect` stage | DNS, port or firewall — server refused or timed out | `probe`, `LGU_SMTP_HOST`/`LGU_SMTP_PORT`/`LGU_SMTP_TIMEOUT` |
| `tls` stage | Certificate or STARTTLS mismatch | `LGU_SMTP_TLS` (try `starttls`, `ssl`, or `none` only against localhost) |
| `auth` stage | Credentials rejected (often an app password, not the login password) | `LGU_SMTP_USER`/`LGU_SMTP_PASSWORD` in the secret store |
| `send` stage | Server accepted the connection but refused the message | `LGU_MAIL_FROM` accepted by the provider |

The stage/detail pair is for the operator tool only. Routes answer a single
generic message, nothing is logged, and no password, app password, token or
verification code is printed by any of these commands.

## 6. What has *not* been proven

In this environment every SMTP variable is unset, so **external delivery was
not performed** — the fake provider, configuration validation, probe failure
paths and failure-mode tests are the evidence. Run §4 against a real
mailbox before treating live-provider integration as verified.
