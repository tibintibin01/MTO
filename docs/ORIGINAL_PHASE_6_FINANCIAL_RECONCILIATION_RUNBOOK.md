# Original Roadmap Phase 6 — financial reconciliation

## Objective

Original Roadmap Phase 6 strengthens database integrity and financial
reconciliation. It is distinct from the earlier numbered final-production
certification work. The first gate is deliberately read-only: it identifies
data or schema gaps before any repair migration or data correction is proposed.

The gate emits aggregate counts and monetary totals only. It does not include
taxpayer names, TD numbers, OR numbers, file paths, credentials, or row-level
financial records.

## Automated checks

The scripts.phase6_financial_reconciliation_preflight command verifies:

- the Phase 3 duplicate-payment, duplicate-allocation, cross-property, and
  allocation-balance invariants;
- required financial tables, unique indexes, fixed-point money columns, and
  core foreign keys;
- orphaned payments, billings, allocations, assessments, and receipt links;
- duplicate property/year billings and allocation tax-year mismatches;
- non-positive payments or allocations and negative billing values;
- billing paid, penalty, and discount summaries against linked transactions;
- aggregate payment, allocation, and billing-paid totals;
- duplicate-TD approval isolation;
- receipt/payment property identity;
- Phase 5 audit-chain integrity and protected-backup readiness.

The current schema does not enforce receipt_history.payment_id as a foreign
key. Until that is closed by a separately reviewed migration, the gate reports
REVIEW even when all financial data reconciles.

## Initial read-only assessment

Run on the server from an Administrator Command Prompt:

~~~bat
cd /d C:\mto
call venv\Scripts\activate
git rev-parse --short HEAD
git status --short
python -m scripts.phase6_financial_reconciliation_preflight --output logs\remediation-original-phase-6-preflight.json
echo Exit code: %ERRORLEVEL%
~~~

Expected statuses:

- PASS: no blocking or review findings;
- REVIEW: no financial corruption was found, but a non-blocking schema or
  legacy-data item still needs a documented closure decision;
- FAIL: financial, audit, backup, or core schema integrity is not ready.

The assessment command exits zero for PASS and non-blocking REVIEW.
FAIL exits 2. Closure mode is stricter:

~~~bat
python -m scripts.phase6_financial_reconciliation_preflight --require-ready --output logs\remediation-original-phase-6-final.json
~~~

With --require-ready, unresolved review findings exit 3.

## Response to findings

Do not directly edit production financial rows. Preserve the JSON report and
classify each finding:

1. confirm whether it is a schema protection gap or an actual data mismatch;
2. capture a fresh protected backup before any approved repair;
3. implement schema changes as an idempotent migration with rollback limits;
4. implement data repair as a dry-run-first, bounded, auditable command;
5. rerun Phase 3, Phase 5, and this Phase 6 gate;
6. compare financial invariants to the pre-change baseline.

Every repair, migration, or production-data change requires a separately
reviewed hotfix. The read-only gate itself never commits a database
transaction.

## Closure evidence

Retain:

- the initial privacy-safe Phase 6 report;
- any approved migration and repair dry-run reports;
- before/after financial baselines;
- Phase 3 invariant and Phase 5 audit-chain reports;
- the final Phase 6 PASS report;
- commit, release tag, and deployment evidence for any required hotfix.
