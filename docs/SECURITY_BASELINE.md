# Security and type-checking baseline

Baseline captured on 2026-07-22 while preparing the compliance-currency fix.
This document prevents a green CI badge from being mistaken for complete
production hardening.

## Blocking CI gates

- Black on changed, non-exempt Python modules.
- Flake8 fatal errors across the repository.
- Mypy on the new compliance impact and activation-preflight modules, with
  legacy imports skipped.
- Bandit findings of medium severity or higher across `backend/`.
- Backend tests and frontend lint/build.

The narrow Black exemption names legacy files that are not yet Black-formatted.
It does not exempt them from Flake8 or Bandit.

## Known legacy debt

The repository-wide Mypy command currently reports 368 errors in 39 files.
Those errors must be burned down module by module; making all 368 changes in
the compliance rollout would create an unsafe and unreviewable operational
change.

The 2026-07-22 `pip-audit` run reports 51 advisories across 10 installed
packages. Dependency auditing remains visible in CI but advisory until the
upgrade work below is completed. This is not acceptance of the risk.

## Required dependency-remediation phase

1. Create a dependency-only branch and restore a recent production backup into
   an isolated staging database.
2. Upgrade one compatible dependency family at a time (FastAPI/Starlette,
   authentication/cryptography, upload handling, HTTP, and image processing).
3. Run the full backend suite, authentication and upload tests, backup/restore
   verification, frontend build, desktop smoke tests, and a staging soak.
4. Rebuild and sign `Treasury.exe`, then deploy to one pilot workstation.
5. Make `pip-audit` blocking only after the advisory list reaches zero or every
   remaining advisory has a documented, time-bounded exception.
