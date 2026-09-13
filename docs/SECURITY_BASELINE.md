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

The 2026-07-22 `pip-audit` run reported 51 advisories across 10 installed
packages. The Phase 4 source remediation supersedes that dependency baseline:
both SHA-256-locked Python graphs and the npm lock report zero known
vulnerabilities as of the final 2026-09-14 review, and dependency audits now
block CI. See
`docs/REMEDIATION_PHASE_4_RUNBOOK.md` for activation and rollback controls.

## Required Phase 4 operational acceptance

The source upgrade and blocking audit gates are implemented. Phase 4 is not
operationally accepted until the runbook's separate server activation is
approved and completes a fresh backup/restore attestation, hash-locked server
install, financial preflight, secure desktop rebuild, pilot workstation smoke
test, and staging soak.
