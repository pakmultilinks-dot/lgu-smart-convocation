# Testing all three mobile logins

**No universal APK password exists.** The Android APK is only a client.
The Student, Volunteer/Scanner and Admin logins are authenticated by the
Flask backend. Connecting to a backend is essential.

## One-time isolated demo setup (no actual university records)

On your own staging computer or private hosting instance with Python installed:

```powershell
cd <repository-folder>
python -m pip install -r app/requirements.txt
python app/scripts/create_preview_demo.py --output-dir "$env:USERPROFILE\LGU-Preview-Test-Only"
```

The **new private directory must not exist already**, and must be outside
the Git repository. The command refuses existing databases and production
environments, and never reads or alters `app/lgu.db`.

It creates exactly one fictional student account, one authorized gate-1
scanner account, a random admin PIN and a synthetic SQLite schema-v14 DB.
It writes randomized credentials to
`LGU-Preview-Test-Only/TEST-LOGIN-DETAILS.txt` (never committed). The server
needs the matching settings from `PRIVATE-BACKEND-ENV.txt`, supplied in its
private process environment; it does **not** automatically load the file.
Don't share these files, even though their accounts are synthetic.

## Using the APK with a real staging backend

1. Deploy the Flask backend to a **private HTTPS demo host**, with no actual
   student database, and provision the newly generated v14 SQLite preview DB.
   Secure environment variables must match the private generated settings.
   Set `LGU_APP_ENV=production`, `LGU_COOKIE_SECURE=1` and a real
   `LGU_DB_PATH` pointing to that preview DB on the server. The user must
   approve the host and load the credentials outside GitHub.
2. Confirm `https://<demo-host>/api/health` returns `{"ok":true}` in the
   phone browser. This endpoint **does not prove sign-in works**.
3. In the APK, go to **Admin → Backend Connection** and save the HTTPS root
   URL (no `/api/health` suffix). No backend means no working sign-in.
4. Sign in under **Student** with the generated email and password. That
   account is linked to a **fictional active registration**. Profile/QR pass
   issuance may require further steps, so test each flow individually.
5. Sign in under **Volunteer/Scanner** with the generated username and PIN;
   this account is assigned gate 1 only.
6. Open **Admin** using the generated admin PIN, configured on the same
   staging backend.

Only the local tester should see login/password files; never post login
details or secret environment values in issues, screenshots or CI logs.
Delete the disposable demo after testing. Do not attempt an actual campus
migration until an institutional operator approves backups/recovery.

## Limitations

This helper **does not deploy** a server, register a hosting account, set up
TLS/SMTP or install the APK on a phone. Demo email sending is disabled.
Never point a staging instance at real students or use generated demo
credentials on the production campus server.
