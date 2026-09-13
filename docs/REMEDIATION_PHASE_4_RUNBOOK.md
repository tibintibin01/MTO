# Remediation Phase 4 — Dependency and Supply-Chain Hardening

This phase is separate from the earlier verified-duplicate-TD rollout that also
used the label “Phase 4.” It changes application dependencies and delivery
controls only. It does not modify treasury records or the database schema.

## Security baseline

The 2026-09-10 baseline found:

- 53 Python advisories across 10 installed package versions.
- 22 vulnerable npm dependency paths: 1 critical, 18 high, 1 moderate, 2 low.
- An abandoned PWA integration that could cache authenticated or financial pages.
- Unlocked Python transitive dependencies and non-blocking Python audits in CI.
- Mutable GitHub Actions tags, including an unversioned `master` reference.
- Conflicting Python dependency versions between `requirements.txt` and `pyproject.toml`.

The remediated source has zero known vulnerabilities in the runtime Python
lock, development Python lock, and npm lock at the time of review. A future
advisory will intentionally fail CI instead of being silently accepted.
All third-party GitHub Actions are pinned to reviewed 40-character commit SHAs;
the dependency policy rejects mutable tags or branches.

## Dependency ownership

- `requirements.txt`: exactly pinned direct runtime dependencies.
- `dev-requirements.txt`: exactly pinned direct test and security tooling.
- `requirements.lock`: generated runtime graph with SHA-256 artifact hashes.
- `dev-requirements.lock`: generated runtime plus development graph with hashes.
- `frontend/package.json`: exactly pinned direct npm dependencies.
- `frontend/package-lock.json`: npm's integrity-locked complete graph.
- `pyproject.toml`: package metadata; runtime dependencies are loaded from
  `requirements.txt` to prevent a second conflicting manifest.

Regenerate Python locks only in a reviewed dependency change:

```powershell
python -m pip install uv==0.12.12
uv pip compile requirements.txt --generate-hashes --python-version 3.11 --output-file requirements.lock
uv pip compile requirements.txt dev-requirements.txt --generate-hashes --python-version 3.11 --output-file dev-requirements.lock
python -m scripts.check_dependency_policy
python -m pip_audit -r requirements.lock --progress-spinner off
python -m pip_audit -r dev-requirements.lock --progress-spinner off
```

Regenerate the npm lock only after reviewing `package.json`:

```powershell
cd frontend
npm install
npm audit --audit-level=moderate
npm run lint
npm run build
```

## Server activation preflight

Do not activate this phase until it is committed, pushed, pulled by the server,
and separately approved. On the server, before stopping the API:

```bat
cd /d C:\mto
call venv\Scripts\activate
python -m scripts.check_dependency_policy --output logs\remediation-phase-4-dependencies.json
python -m pip_audit -r requirements.lock --progress-spinner off
python -m pip install --dry-run --require-hashes -r requirements.lock
python -m scripts.phase3_financial_preflight --require-active --output logs\remediation-phase-4-financial-preflight.json
```

Required result: policy `PASS`, no known runtime vulnerabilities, hash-locked
dry run succeeds, and all Phase 3 financial invariants remain zero.

## Activation and acceptance

1. Run and verify a fresh hybrid backup and isolated restore test.
2. Stop the MTO API using `scripts\stop_mto_runtime.ps1`.
3. Install with `python -m pip install --require-hashes -r requirements.lock`.
4. Start the scheduled API task and wait for authenticated readiness.
5. Re-run the Phase 3 financial preflight.
6. Pilot login, property search, duplicate-TD separation, payment ledger,
   delinquency, compliant properties, one PDF, logout, and restart.
7. Build/deploy the secure client only under a separate approval.

## Rollback boundary

If dependency installation, readiness, or the pilot fails, keep the API stopped,
restore the prior reviewed source revision and its matching lock, reinstall that
lock, then restart and repeat authenticated readiness and financial preflight.
Do not restore the database unless a database invariant changed; this phase has
no schema migration.

## Exceptions

No vulnerability exception, suppressed advisory, or non-blocking audit is
approved by this phase. Pre-existing frontend lint warnings and deprecation
warnings are recorded technical debt; they do not suppress dependency audits or
production build failures.
