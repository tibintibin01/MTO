# Remediation Phase 0 — Baseline and recovery gate

This runbook belongs to the security and production-readiness remediation. It
is separate from the Verified Duplicate TD Phase 4 rollout.

Phase 0 makes no business-data changes. Its purpose is to create a repeatable,
privacy-safe reference before any security, architecture, or database fix is
deployed.

## Safety properties

- Source-only capture is the default.
- Database access requires the explicit `--database` option.
- Database mode sends SELECT statements only and rolls back before closing.
- Reports contain aggregate counts and monetary totals, not taxpayer names,
  TD/PIN values, OR numbers, credentials, database URLs, or signing keys.
- Reports are written under `logs/`, which is excluded from Git because it may
  contain operational metadata.
- The tool never starts a backup, changes a setting, runs a migration, commits,
  pushes, installs, or deploys anything.

## 1. Development baseline

From the development worktree:

```bat
call venv\Scripts\activate
python scripts\capture_remediation_baseline.py
python -m pytest tests
```

The first command records the commit, branch, working-tree state, runtime, and
dependency-manifest checksums. It does not load database configuration.

## 2. Server recovery gate

On the API/database server, first use **Start Hybrid Backup** and wait until the
application shows all of the following:

- Cloud Sync has the new timestamp.
- Restore Test is `SUCCESS`.
- Storage is protected on server and cloud.

Then run from the server checkout:

```bat
cd /d C:\mto
call venv\Scripts\activate
python scripts\capture_remediation_baseline.py --database --require-ready --output logs\remediation-phase-0-server.json
```

`Database readiness: PASS` is required. A REVIEW result must be investigated;
do not begin Phase 1.

The client PC must not run the database command unless it is intentionally
configured as the API/database server. Source-only capture is safe on a client
checkout.

## 3. Recorded invariants

The server report records:

- Alembic revision and required-schema presence.
- Total and active property counts.
- Payment count, amount, penalty, and discount totals.
- Billing count and assessed-value/payment totals.
- Payment-allocation count and total.
- Cross-property allocation count.
- Verified and unverified duplicate-TD group counts.
- Redacted backup filename, checksum presence, age, protection status, and
  restore-attestation state.

The report intentionally records no row-level taxpayer data.

## 4. Post-phase comparison

After a later phase is deployed, capture a second report and compare it with
the preserved Phase 0 server report:

```bat
python scripts\capture_remediation_baseline.py --database --require-ready --compare-to logs\remediation-phase-0-server.json --output logs\remediation-post-phase.json
```

The command exits with code 4 when any protected financial invariant changes.
An expected business transaction performed between captures must be reconciled
and documented; never dismiss a difference without explaining it.

## Phase 0 completion gate

Phase 0 is complete only when:

1. The repository revision and clean/dirty state are recorded.
2. The full automated test suite passes.
3. A new Hybrid Backup is protected on server and cloud.
4. Restore verification is current and successful.
5. The server baseline returns `Database readiness: PASS`.
6. The report is preserved in the server's protected operational records.
7. The Phase 0 code changes are reviewed before any commit or Phase 1 work.

Do not commit, push, deploy, or begin Phase 1 until the reviewer explicitly
approves this gate.
