# Free HTTPS LGU Smart Convocation demo — PythonAnywhere

**Purpose:** A small public *synthetic-only* demo backend for the Android
preview APK. This is NOT the campus production server. PythonAnywhere's
new free accounts allow one HTTPS website, one worker, 512 MiB disk and
a one-month app expiry/renewal; do not use it for real event attendance.

## Get your free demo running (authorized account holder only)

1. Create/login to a free PythonAnywhere account at
   https://www.pythonanywhere.com/. No Railway, credit card, or campus
   database is needed. Keep real university/student files off this host.
2. Transfer the reviewed repo source files to
   `/home/YOURUSERNAME/lgu-smart-convocation`. You can upload a source
   ZIP through PythonAnywhere Files. **Never upload** your laptop .env,
   local database, student photos, APK or `TEST-LOGIN-DETAILS.txt`.
   Alternatively, if permitted by the free account's outbound allowlist,
   use a shallow git clone of the reviewed main branch.
3. From **Consoles → Bash** create a backend-only virtual environment
   compatible with the Python version your account offers:

   ```bash
   python3 -m venv ~/lgu-preview-venv
   ~/lgu-preview-venv/bin/python -m pip install -r ~/lgu-smart-convocation/app/requirements.txt
   ```

4. Provision **a brand-new disposable database** directly on PythonAnywhere,
   never copy an actual campus DB:

   ```bash
   ~/lgu-preview-venv/bin/python ~/lgu-smart-convocation/app/scripts/create_preview_demo.py --output-dir ~/lgu-preview-private
   ```

   It refuses to overwrite an existing directory. Store the private file
   `~/lgu-preview-private/TEST-LOGIN-DETAILS.txt` privately. It contains
   randomized Student, Scanner and Admin demo credentials. Do not paste
   them in GitHub issues, commit them, or send them in group chats. If
   credentials were previously exposed, create a **new** disposable demo
   in a separate private host/account or safely destroy the old synthetic
   demo directory after preserving nothing needed.

5. Go to **Web → Add a new web app → Manual configuration**, select the
   Python version matching your virtualenv. Set the **Virtualenv** path
   to `/home/YOURUSERNAME/lgu-preview-venv`.
6. Edit the **WSGI file** linked in the Web tab. Replace the default
   application code with (replace only `YOURUSERNAME`):

   ```python
   import sys
   sys.path.insert(0, "/home/YOURUSERNAME/lgu-smart-convocation/app")
   from scripts.pythonanywhere_preview_wsgi import application
   ```

   The WSGI helper loads the separately generated private settings and
   points at the v14 synthetic DB only. It enforces secure cookies and
   disabled email, and refuses missing DB/secret settings. No `app.run()`,
   schema upgrade, or automatic demo re-seeding takes place on startup.

7. Reload the web app. On your phone, check
   `https://YOURUSERNAME.pythonanywhere.com/api/health`. It should
   respond with JSON including `"ok":true` and
   `"app":"LGU Smart Convocation"`.
8. In your new APK go to **Connect to demo server**, and save
   `https://YOURUSERNAME.pythonanywhere.com` (without `/api/health`).
   Use generated Student email/password, Scanner username/PIN, and Admin
   PIN from the private `TEST-LOGIN-DETAILS.txt` on the host.

## Verify each role instead of trusting the build status

Student: login → registration claim/profile → QR pass. Scanner: login →
gate-1 permissions → real camera QR → duplicate rejection → offline
queue/sync. Admin: PIN → settings and dashboard. The PythonAnywhere free
worker is constrained; load/performance results do NOT certify it for the
event-day campus server.

If email verification or password recovery is attempted, it should
fail with **email unavailable**, because real email is deliberately
disabled for this preview. These workflows will need a separate SMTP test
before campus deployment.

## Security notes

- Repo code and public web URL may be shared; **never** share secrets or
  private DB files. All demo records must be fictional.
- Do not set `LGU_ALLOW_DEMO_SECRETS=1` on a public service.
- Code accepts the secret file only from the host user's fixed private
  `~/lgu-preview-private` directory; never read a system-wide DB.
- This workflow tests the Flask routes on CI *only*. It does not upload
  anything to a PythonAnywhere account, publish a demo URL, obtain an Expo
  EAS build URL, or validate a physical phone.
