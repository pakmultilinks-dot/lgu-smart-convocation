# Operations Runbook — LGU Smart Convocation

Authoritative operating instructions for the Examination Department portal and
the volunteer scanner fleet. Everything here is either enforced by code that
has an automated test, or explicitly marked as an **outstanding release gate**.

Release discipline: nothing in this document mutates production during a
readiness phase. Backup/restore, migration and configuration commands are run
against **disposable copies** until the operator deliberately promotes them.

---

## 1. Runtime model

| Item | Value |
| --- | --- |
| Entry point | `app/run.py` → `python run.py`, binds `0.0.0.0:5000` |
| Framework | Flask 3.1.3, Python 3.13, SQLite |
| Database | `app/lgu.db` (override with `LGU_DB_PATH`) |
| Student photos | `app/data/student_photos/` — outside `static/`, served only to the owning session |
| Medalist photos | `app/data/medalist_photos/` — outside `static/` |
| Health probe | `GET /api/health` → `{"app": …, "ok": true, "version": "LGU1"}` |

### Network topology (as designed)

The service is intended for a **trusted campus LAN over plain HTTP**. The
session cookie is therefore **not** `Secure` by default — marking it `Secure`
would make it undiscoverable over `http://` and lock every member of staff out.

For a live release, configure HTTPS with valid certificates and set
`LGU_APP_ENV=production` and `LGU_COOKIE_SECURE=1`. The production startup
guard refuses to serve staff sessions unless Secure cookies are enabled.
This flag **does not prove** that HTTPS or the reverse proxy actually works;
verify TLS and backend reachability from the real client devices.
Plain HTTP is a development/LAN rehearsal option only.

Set these before starting a production service:

```
LGU_APP_ENV=production
LGU_COOKIE_SECURE=1
LGU_SECRET_KEY=…          # required in every environment
LGU_HMAC_SECRET=…         # required in every environment
LGU_ADMIN_PIN=…           # required in every environment
```

---

## 2. Secrets — startup fails closed

`run.py` refuses to start while any of the three committed **demo** values is
still in place, and it does so **before** `init_db()`/`seed()` touch any
database. The values are never printed — only the setting names.

```
FATAL: refusing to start with committed demo secrets: LGU_SECRET_KEY, LGU_HMAC_SECRET, LGU_ADMIN_PIN.
Set LGU_SECRET_KEY, LGU_HMAC_SECRET and LGU_ADMIN_PIN in the environment (see docs/OPERATIONS.md),
or set LGU_ALLOW_DEMO_SECRETS=1 for local development only.
```

| Setting | Guards |
| --- | --- |
| `LGU_SECRET_KEY` | Flask session cookies **and** the student password-recovery HMAC |
| `LGU_HMAC_SECRET` | Convocation pass QR codes |
| `LGU_ADMIN_PIN` | Broadcasts, event settings, gate rename |

`LGU_ALLOW_DEMO_SECRETS=1` is a **development-only** escape hatch. It prints a
loud `WARNING: running with demo secrets` line. Never set it on a host that
serves the portal.

Verify a configuration before starting, without printing any value:

```
..\.venv\Scripts\python.exe -c "import config; print(config.demo_secrets())"
```

An empty list `[]` is the only acceptable result.

---

## 3. Database, migrations, backup

### Schema version

Migrations are tracked with `PRAGMA user_version` and applied inside one
transaction each together with the version bump, so a failure rolls back **both**
the schema and the version. Current latest: **version 11**.

`migrate()` **refuses to open** a database whose version is newer than the build
supports. This is deliberate: silently applying nothing would let the app run
against a schema it does not understand and fail later on a missing column with
a far less diagnosable error.

### Rehearsing a migration (never against production)

`scripts/test_phase20_migration_rehearsal.py` builds disposable databases at
every historical version, upgrades each to the latest, and proves data
preservation, idempotency, transactional rollback of a failing migration, and
the forward-compatibility refusal.

### Backup

```
cd app
..\.venv\Scripts\python.exe scripts\backup_db.py create            # app/backups/convocation-<stamp>.db
..\.venv\Scripts\python.exe scripts\backup_db.py verify <path>
..\.venv\Scripts\python.exe scripts\backup_db.py list
..\.venv\Scripts\python.exe scripts\backup_db.py restore <path> --to <new-file>
```

Properties, each with an automated test in
`scripts/test_phase20_backup_restore.py`:

- Uses SQLite's **online backup API**, so it is safe while the service is running.
- The snapshot is **transactionally consistent** — concurrent writes are never
  torn, and foreign keys are never orphaned.
- Produces a `<name>.manifest.json` sidecar with the SHA-256, size, schema
  version and row counts.
- **Verifying never mutates** the file (read-only connection) and rejects
  anything that is not a valid, current-or-older SQLite database.
- **Restore refuses to overwrite the production database path.** Restore to a
  new file, verify it, then promote deliberately.

The database backup contains student records and credential hashes. Protect it
with restricted access and never commit or share it publicly. Only the manifest
contains digests, counts and schema metadata rather than record contents. The
CLI prints sizes and row counts, never individual records. Restore requires a
new destination and refuses existing files and the configured active database.

---

## 4. Provisioning

### 4.1 Staff accounts (Examination Department)

There is **no public signup and no default staff account**. Create the first
one on the server host:

```
cd app
..\.venv\Scripts\python.exe scripts\manage_exam_staff.py --username j.dela-cruz --display "J. Dela Cruz"
```

The password is read from a hidden prompt and is never accepted as an argument.

**Authorization model — single tier.** `staff_users` has no role column. Every
staff account has identical authority over the portal. This is a deliberate
decision, not an omission: a convocation department has one duty roster, and a
role hierarchy would imply an approval workflow the product does not perform.
If delegated authority is ever required, it is a **new feature with its own
migration**, not a configuration change.

### 4.2 Scanner accounts (volunteer gate devices)

Scanners are the only way to obtain a scan-authorized session. There is no
shared or default credential.

```
cd app
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py create --username gateA-ana --name "Ana Cruz" --gates 1,2 --actor j.dela-cruz
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py list
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py gates 1 --gates 2,3 --actor j.dela-cruz
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py pin 1 --actor j.dela-cruz
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py sessions 1
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py revoke 1 --actor j.dela-cruz
..\.venv\Scripts\python.exe scripts\manage_scanner_staff.py activate 1 --actor j.dela-cruz
```

Accounts can also be managed from the portal at **Exam → Scanners**, behind the
staff session and CSRF protection.

| Fact | Detail |
| --- | --- |
| PIN | Printed once at creation, stored only as a hash, never logged |
| Session | 12 h TTL (`LGU_SCANNER_SESSION_HOURS`); only the SHA-256 of the token is stored |
| Gate scope | **Server-enforced.** The client's `gate_id` is only a request; it must be one of the scanner's authorized gates or the scan is refused |
| Volunteer name | **Server-enforced.** Taken from the authenticated identity, never from the request body |
| Lost device | `revoke 1` kills every session for that account instantly — the TTL is only a backstop |
| Failed logins | Per-account lockout plus a per-IP rate limit |

**Audit provenance.** Portal actions are recorded with `via=portal` and an actor
taken from the server session. CLI actions are recorded with `via=cli`. The
`via=cli` tag is **local operator attestation, not verified identity** — the
shell proves only who can run the file on the host. Neither marker can be
supplied by a web request.

### 4.3 Gates

Gates are seeded by `database.seed()`, not created by migration. Gate names are
edited in the portal or via `PATCH /api/gates/<id>/rename` behind the
administrator PIN.

---

## 5. Event-day procedures

### 5.1 Convocation event

**Exam → Event** — create, edit, then **publish**, then **activate**. Only one
convocation is active at a time; student verification, claiming and pass
issuance all resolve against the active convocation.

### 5.2 Registration import

1. **Exam → Registrations → Template** to download the CSV template.
2. Upload the CSV. Rows are staged in a batch and validated first.
3. Review the error rows, correct and re-upload.
4. **Commit** the batch. History records every committed batch.

### 5.3 Student self-service

Students verify with their university email, receive a 6-digit code, complete
their registration claim, and upload a profile photo. Password recovery follows
the same code flow.

### 5.4 Announcements

**Exam → Announcements** — create, edit, archive. Published announcements appear
on the public feed and in the student app.

### 5.5 Scanning at the gate

Each device logs in with its own username and PIN. A revoked or deactivated
account is refused on the very next request. Duplicate and failed scans are
reported with a reason and an audit record rather than silently dropped.

### 5.6 Passes and rejection

Students request a convocation pass once their profile is complete. The pass
carries an HMAC-signed QR. Staff can review issued passes in the portal.

### 5.7 Support queue

**Exam → Support** — review, respond, and close student support requests. A
per-IP creation limit prevents a single client from filling the queue.

---

## 6. Email

`LGU_EMAIL_MODE` is one of `disabled`, `fake`, `smtp`.

| Mode | Behaviour |
| --- | --- |
| `disabled` | No delivery. Verification and recovery raise `EmailUnavailable` and the API returns **503** — the request is refused, never silently accepted |
| `fake` | Test-only. Refuses to engage against the production database |
| `smtp` | Real delivery over `LGU_SMTP_TLS` = `auto` / `starttls` / `ssl` |

Check a configuration without printing any credential:

```
cd app
..\.venv\Scripts\python.exe scripts\check_email_config.py check
```

The tool reports presence and length only, e.g. `LGU_SMTP_PASSWORD ......... set (24 chars)`.
It never prints a value.

**An unconfigured email service cannot be used as an "email exists" oracle** —
routes probe availability *before* any account lookup.

---

## 7. Health checks and shutdown

- **Liveness:** `GET /api/health` → `200` and `"ok": true`. Returns no
  configuration, no counts and no secrets.
- **Safe shutdown:** stop the process. SQLite is in WAL-safe single-file mode
  and every mutation is a committed transaction, so there is no flush step.
  Take a backup before and after any planned stop.
- **Log reading:** no stack trace is ever returned to a client. Server-side
  traces go to the process stdout/stderr only.

---

## 8. Troubleshooting

| Symptom | Cause and action |
| --- | --- |
| Exit 1 at start, `FATAL: refusing to start with committed demo secrets` | Set the three secrets, or `LGU_ALLOW_DEMO_SECRETS=1` for local development only |
| `Database schema version N is newer than this build supports` | The database came from a newer release. Deploy the matching build, or restore a supported backup |
| `503 email_unavailable` on verification | `LGU_EMAIL_MODE` is `disabled`, or SMTP is misconfigured. Run `check_email_config.py check` |
| `429 Too many attempts` | Per-IP rate limit. Wait for the window, or raise the documented tunable |
| `403` on a management POST | Missing or forged CSRF token. Reload the page and retry |
| Scanner `401` on every scan | Session expired, account deactivated, or sessions revoked. Re-login; if it still fails, `activate` the account or issue a new `pin` |
| Scanner `403`/refused on one gate only | That gate is not in the account's authorization. `gates <id> --gates …` |
| `Unknown gate(s): …` at startup in a script | Gates are seeded, not migrated. Call `database.seed()` |
| Staff member cannot log in | Repeated wrong passwords lock the account for the lockout window |

Every tunable degrades to a **safe default**, never to "unlimited": a zero,
negative or non-integer rate limit falls back to the documented default.

---

## 9. Outstanding release gates

These are **not** cleared by a passing test suite and must be closed by a human
before production use:

| Gate | Status |
| --- | --- |
| Real SMTP delivery with the university mail server | **NOT TESTED** — no SMTP reachable from this environment |
| Android device / emulator validation of the mobile app | **NOT TESTED** — no `adb`, emulator or JDK available |
| Migration 11 applied to the production database | **NOT APPLIED** — rehearsed only on disposable databases |
| Performance and capacity under event-day load | **NOT TESTED** |
| Production credentials provisioned by the operator | **NOT DONE** — the service will not start until they are |

Do not read a green automated suite as production readiness.
