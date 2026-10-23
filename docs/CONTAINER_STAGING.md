# Container release staging — not a production deployment

This image is a reproducible *backend* package for LGU Smart Convocation.
It uses Gunicorn with a single worker for SQLite and exposes port 8000.
The Expo Android app is built separately; a successful backend container smoke
test **does not** demonstrate a signed APK, physical QR scanner, or SMTP.

## Safe automated staging check

The workflow `Staging container and startup safety` builds the Docker image
from the repository and runs two checks with **no volumes or real data**:

1. An isolated development-mode service with a temporary SQLite database at
   `/tmp/lgu-staging-ci.sqlite3` starts and returns `{"ok":true}` from
   `/api/health`. Synthetic fixtures only.
2. A production-mode service with a missing, **synthetic** database refuses
   startup and does not silently initialize or migrate it.

The image is never published or deployed by this workflow. The build
excludes untracked files such as databases, student/medalist photos, backups,
secrets, exports and mobile builds via `.dockerignore`.

## Manual rehearsal (no production records)

From the repository root on a staging computer with Docker:

```sh
docker build -t lgu-convocation:staging .
docker run --rm -p 127.0.0.1:8000:8000 \
  --read-only --tmpfs /tmp \
  -e LGU_APP_ENV=development \
  -e LGU_ALLOW_DEMO_SECRETS=1 \
  -e LGU_DB_PATH=/tmp/lgu-staging-ci.sqlite3 \
  lgu-convocation:staging
```

Open http://127.0.0.1:8000/api/health on that staging computer. This
development-only example uses publicly known demo credentials and must **never
be exposed to the internet**, used with institutional data, or reused as a
production command. Stop the container after testing.

## Live-release requirements (not automated here)

- An institution/hosting operator chooses the server/host, reachable HTTPS
  domain and reverse proxy. Verify valid TLS from phones and browsers.
  Configure `LGU_APP_ENV=production` and `LGU_COOKIE_SECURE=1`.
- Supply independently strong `LGU_SECRET_KEY`, `LGU_HMAC_SECRET`, and
  `LGU_ADMIN_PIN` from the platform's secret store. No real secrets in
  Dockerfile, build arguments, git or logs.
- The production SQLite file is **not included** in the image. Provision the
  protected persistent volume and photo storage separately. Mount the
  database directory at a persistent path; set `LGU_DB_PATH` to the exact
  already-approved v14 SQLite file. Never use the container's ephemeral
  filesystem for actual student data. Keep a verified private backup.
- **Do not start against an outdated production database.** Startup refuses
  missing and older schemas. Migration v6→v14 needs a separate, documented,
  operator-approved offline procedure with tested restore and institutional
  GO, not a `docker run` side effect.
- Configure and verify real SMTP delivery, Android backend reachability,
  a signed preview APK installed on physical Android devices, QR camera scans
  and offline/online sync on synthetic staging, and event-day LAN capacity.

This PR only packages and tests the service; it does not supply hosting,
TLS certificates, credentials, production database approval or signed APKs.
The release is **NO-GO** until external acceptance evidence is recorded.
