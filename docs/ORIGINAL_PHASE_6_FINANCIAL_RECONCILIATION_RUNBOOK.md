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

The Phase 6 release enforces receipt_history.payment_id as a foreign key with
ON DELETE SET NULL. Legacy stale references must first be detached by the
approved recovery command; receipt records and their historical fields remain
preserved.

Unique-index checks are semantic. Any unique constraint protecting the exact
required column sequence is accepted, regardless of its historical database
name. A same-column non-unique lookup index neither satisfies nor invalidates
the guard.

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

## Deterministic legacy recovery

Keep the API stopped for preflight and apply. The recovery command refuses
ambiguous data, requires a verified audit chain, creates a fresh hybrid backup,
recaptures the candidate fingerprint after backup, and writes one sealed audit
event for every changed record.

When the active server is on the preceding release, export the recovery script
from the approved target tag without switching the checkout. Run that immutable
copy with the active production Python and set MTO_PROJECT_ROOT so imports come
only from the active checkout:

~~~bat
cd /d C:\mto
powershell -NoProfile -Command "New-Item -ItemType Directory -Path 'C:\ProgramData\MTO\release-tools' -Force | Out-Null"
git archive --format=zip --output=C:\ProgramData\MTO\release-tools\phase6-recovery.zip refs/tags/v2.1.7 scripts/phase6_financial_reconciliation_recovery.py
powershell -NoProfile -Command "Expand-Archive -LiteralPath 'C:\ProgramData\MTO\release-tools\phase6-recovery.zip' -DestinationPath 'C:\ProgramData\MTO\release-tools\v2.1.7-phase6-recovery'"
set MTO_PROJECT_ROOT=C:\mto
C:\mto\venv\Scripts\python.exe C:\ProgramData\MTO\release-tools\v2.1.7-phase6-recovery\scripts\phase6_financial_reconciliation_recovery.py --preflight --output C:\mto\logs\remediation-original-phase-6-recovery-preflight.json
~~~

~~~bat
python -m scripts.phase6_financial_reconciliation_recovery --preflight --output logs\remediation-original-phase-6-recovery-preflight.json
python -m scripts.phase6_financial_reconciliation_recovery --apply --output logs\remediation-original-phase-6-recovery.json
~~~

Run apply from the same immutable external copy before activating v2.1.7.
After it passes, leave the API stopped and invoke the immutable release
updater. The v2.1.7 migration then adds the receipt/payment foreign key and the
post-activation Phase 6 preflight must return PASS.

Apply mode can:

- align a billing penalty/discount summary only when each linked payment has
  exactly one billing allocation;
- restore a missing payment tax year only from exactly one allocation year,
  after checking that the protected payment identity will not collide; and
- set a missing receipt payment reference to NULL without deleting or changing
  the receipt evidence.

It never changes payment amounts or allocation rows. The receipt/payment
foreign-key migration is installed only after the recovery has proven that no
stale references remain.

## Closure evidence

Retain:

- the initial privacy-safe Phase 6 report;
- any approved migration and repair dry-run reports;
- before/after financial baselines;
- Phase 3 invariant and Phase 5 audit-chain reports;
- the final Phase 6 PASS report;
- commit, release tag, and deployment evidence for any required hotfix.
