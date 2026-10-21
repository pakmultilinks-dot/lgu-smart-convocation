# Latest local application review publication — 2026-10-22

This review branch publishes the latest local Phase 37, 38 and 39 source, including the earlier uncommitted student, exam, scanner, guest, event and mobile work. It is a review snapshot, not deployment approval. Earlier phase reports are historical evidence, not a claim that their checks were repeated unchanged.

## Provenance and preservation

- Original local `main` stays at `298c272`, with its modified and untracked source preserved. No checkout, merge, stash or commit was performed in that original working tree.
- All origin branches were fetched, including outstanding draft heads. GitHub `main` was verified again at `3f09dda7ffc753320b5185f0ee411963180739c8` before publication.
- New branch: `review/latest-phase37-39-20261022`, built in a separate Git worktree from `origin/main`. A curated source snapshot avoids publishing the 31 local-only commits and their historical screenshots/assets.
- PRs #1–#5 are merged on GitHub. Their upload bounds, XSS escaping, batch input validation, offline-queue preservation and demo QR controls are retained.
- PRs #6–#9 remain open drafts. Their guest-registration transaction, database-authoritative scan admission, explicit-production secret validation and admin JSON validation were reconciled into the newer local implementations. Their regression tests and workflows are included. No existing PR was merged or closed.

## Conflict decisions

Overlaps in `app/web/routes.py`, `dashboard.html`, `scanner.html`, and `mobile/scripts/api-test.mjs` were resolved explicitly after normalizing line endings. Local, merge-base and remote source copies remain outside the upload in the local publication evidence directory.

- Preserve authenticated scanner sessions, authorized gate scope, server-derived volunteer identity, event lifecycle checks, guest pass capabilities, analytics, rate limits and busy responses from the local implementation.
- Preserve remote escaping together with local PKT labels. Escape authenticated scanner gate labels too.
- Preserve remote offline queue reconciliation and in-flight additions, while retaining local scanner authentication and expired-session handling.
- Reject structurally invalid sync batches before any scan writes; semantically invalid scan objects still receive individual verdicts and rejection analytics. The Phase 17/38 and mobile regressions now assert this combined contract.
- Keep the local v14 guest UNIQUE index and duplicate-identity checks, adding PR #6's write reservation before eligibility checks. Keep the local process lock and cleanup while adding PR #7's authoritative SQLite transaction for cross-process admission integrity.
- Keep the local database-path secret guard alongside PR #8's explicit-production weak/reused-key guard, before bootstrap and in the WSGI factory.
- Carry forward source deletions already made in local history, including obsolete mobile components. This prevents stale GitHub screens from reappearing in the latest app.

## Exact upload contents

See [FILES.md](review-20261022/FILES.md) for every file in the final source tree and [CHANGES.md](review-20261022/CHANGES.md) for every change relative to GitHub main. Includes backend modules/templates, Expo student and volunteer screens, scanner/auth/storage code, Python and Node test suites, lockfile, CI workflows, local font/branding assets, historical phase documentation, a placeholder-only `.env.example`, and development dependency instructions.

Intentionally excluded: real `.env` files and credentials; production SQLite, WAL/SHM/journals and all backups/manifests; `app/data` and uploaded student/medalist photographs; student spreadsheets/CSV imports; screenshots and raw evidence; slide decks, logs and scratch outputs; `node_modules`, virtual environments, caches and native build packages. Existing tracked screenshots/slide decks are deleted from this branch's final tree; their original local files are preserved. `.gitignore` now covers those categories. The original repository's previously published history is not rewritten.

## Validation performed for this snapshot

- Backend: 54 script suites attempted — 51 passed, 2 explicitly skipped production-content audits, 1 timed out.
- GitHub regression suites from PRs #1–#9: all 8 suites passed (58 individual tests), including real Chromium queue/XSS/button tests. Fixtures authenticate against the newer app; application authorization is not bypassed.
- Mobile: all 42 checks/suites passed, including TypeScript, ESLint, the master audit, source regressions and isolated API/database tests. Source assertions were updated to recognize escaped timestamps and strict JSON errors.
- Phase 37 startup/security and Phase 38 analytics/database/rate-limit suites passed. Phase 38 analytics exercised 60 assertions. Production-boundary checks compare before/after stamps or verify the file remains absent, so a production database is not required to test source.
- Phase 39 browser E2E: **60/60 passed**; route matrix: 52 tested, 49 explicitly not tested by that browser suite. These are not claims of full native-device or route coverage.
- Phase 39 database: **37 checks passed**; security suite passed; real HTTP load: **13/13 passed** (concurrent scanners, duplicates, dashboard polling, spikes and aborted sockets).
- The legacy Phase 21 3000-registration synthetic load benchmark exceeded the runner's **240-second limit** while other suites were running. It remains **INCOMPLETE**, not a successful benchmark or a proven capacity result. No thresholds were relaxed.
- Production-content migration rehearsal and historical production-stamp audit are **SKIPPED**, because production data/backups are intentionally absent. Separate synthetic v6 migration, migration/rollback, backup/restore, contention and integrity tests passed.
- Gitleaks v8.30.1 scanned the staged source: **no leaks found**. Initial findings were synthetic test literals; those fixtures now generate per-run credentials. Raw logs and redacted scan findings remain local and are not uploaded.

Machine-readable suite results: [TEST_RESULTS.json](review-20261022/TEST_RESULTS.json). Local results were produced on Windows with Python 3.13.7 and Node 24.14.0; the new GitHub workflow will independently exercise Python 3.12/Linux and Node 22. CI results are separate from these local results.

## Reproduce safely

Create and activate your own virtual environment, then from the repository root:

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m compileall -q app
python -m unittest discover -s app/tests -p 'test_*.py' -v
```

For phase scripts, use a test shell with `LGU_TESTING=1`, `LGU_ALLOW_DEMO_SECRETS=1`, `LGU_APP_ENV=test`, and `LGU_ENABLE_DEMO_QR=1`, then run scripts from `app/`, e.g. `python scripts/test_phase39_e2e_web.py`. These scripts choose temporary database paths. Never point `LGU_DB_PATH` at a real database. For mobile, run `npm ci`, `npm run tsc`, `npm run lint`, and the scripts in `mobile/scripts/`. The API test harness boots its own temporary backend; it intentionally ignores external-server URL arguments. CI smoke tests were updated to use that harness.

## Safety and remaining limits

The original production database and backup hashes were verified unchanged before publication, and the original source working-tree status matches the initial capture. No real database was initialized, migrated, restored or written. No real credentials, student records, photographs or backups are included. No deployment, force push, reset, clean, destructive stash or merge occurred. Only the new review branch is authorized for push, with a draft PR targeting main.

Native Android camera, device storage and real event-network behavior remain unverified in this publication. The incomplete legacy benchmark and skipped production-content audits are review limitations. Existing phase reports describe other release risks; this branch makes the actual latest source available to investigate them and does not declare production readiness.
