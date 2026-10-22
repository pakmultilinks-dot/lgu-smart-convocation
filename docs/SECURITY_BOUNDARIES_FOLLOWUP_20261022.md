# Security boundaries after the latest-source publication

The original publication PR #10 is already merged. This follow-up starts at
GitHub main `3fa8b2f`, preserving merged numeric-configuration, production-seed
and Android-bundle improvements from PRs #11, #14 and #15.

## Verified defects and fixes

- QA scanner provisioning, signed fixture records and attendance resets now
  require explicit `LGU_TESTING=1`, a non-production environment and an isolated
  database path. A custom database filename alone grants no test capability.
  The separately opted-in demo QR helper retains its development-only policy.
- Restore protects both the default production path and the configured active
  database, including canonical aliases. Existing destination files are always
  refused. Exclusive creation prevents an intervening operator or hard link
  from turning restore into an overwrite. All restore tests use disposable
  synthetic files; no actual production backup is used.
- Student, scanner and admin authentication reject non-object JSON instead of
  raising attribute errors. Admin PIN fields must be text. Recovery continues
  to fail closed when email is unavailable; no lookup occurs in that state.
- Student API rate-limit state is partitioned by `(operation, remote IP)`;
  one client no longer consumes every student's verification, login, support,
  readiness or pass-issuance budget. Expired clients are removed under the same
  lock that reserves hits. Arbitrary forwarded headers cannot reset budgets.
- Operations guidance now correctly identifies database backups as sensitive
  student records and credential hashes. Only the manifest is metadata.

The QA-tool and custom-restore fixes incorporate the relevant work from open
PRs #12 and #13, with additional auth/client-isolation and restore-race coverage.
Those PRs are not merged or closed by this work.

## Tests

Initial auth/client-isolation tests reproduced failures before the fix. After
the fix, combined unittest discovery ran 88 tests successfully, with one
Windows symlink-privilege skip. The final restore suite ran eight tests
successfully with the same skip, including an additional destination-creation
race regression. Linux CI exercises symbolic links independently.

Selected backend regression suites passed: student accounts; Phase 16 lifecycle;
Phase 18 window semantics; Phase 37 startup secrets; Phase 38 analytics;
Phase 39 security, database, browser E2E and HTTP load. The backup/restore CLI
round trip passed 40 checks. Mobile TypeScript, release-safety, database
isolation, master-audit and Phase 38 regressions passed. ESLint also passed.
All 15 selected checks/suites exited successfully. Python compilation and
staged Gitleaks scanning passed, with no leaks found.

The combined run also exposed two fixture defects: SQLite context managers in
production-seed tests did not close their connections on Windows, and the
QA-boundary test inherited `LGU_TESTING` from earlier modules. Tests now close
connections explicitly and specify the intended environment per case.

## Design limits and safety

Rate limiting remains in-process; multiple workers do not share a distributed
budget. Clients behind the same NAT share an IP budget. Trusted reverse-proxy
address handling must be configured deliberately; accepting untrusted
`X-Forwarded-For` is not a substitute. This follow-up does not introduce a
distributed dependency or claim event-day capacity certification.

The previous publication's long legacy Phase 21 benchmark remains incomplete;
production-content audits require intentionally excluded production data.
Physical Android camera and event-network acceptance remain separate checks.
Passing these regressions is not a guarantee that every possible design flaw
has been found.

All work uses a separate Git worktree. Original local changes are preserved.
No production database migration, restore, initialization or write is performed;
no production database, backup, real credentials or student records are uploaded.
No main push, merge or deployment is performed.
