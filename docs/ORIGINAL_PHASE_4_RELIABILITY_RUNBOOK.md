# Original Phase 4 — Reliability closure

This runbook closes the original roadmap objective: make background jobs,
migrations, and PDF generation reliable. It is separate from the later
dependency-hardening runbook also named Phase 4.

## Safety boundary

- Ordinary preflight is read-only and rolls back its database session.
- Preflight never submits a job, runs a migration, starts or stops a service,
  generates a document, or changes business data.
- Failure/recovery tests use an isolated test database. Never crash a worker or
  edit a job row on production to prove recovery.
- A live PDF exercise requires separate approval and may create only one normal
  `pdf_soa` job row and its generated document.
- Reports contain counts, statuses, timings, and findings only. They exclude
  taxpayer identifiers, job payloads/errors, document contents, credentials,
  tokens, and filesystem paths.

## Active-job recovery invariant

- Worker ownership uses the exact job ID internally. The health response keeps
  showing only the historical eight-character identifier.
- Maintenance never returns a job to `PENDING` while a live in-process worker
  owns that exact ID, even when the job has exceeded the stale-time threshold.
- A job whose worker thread has exited is recoverable after the threshold. A
  job left by a process crash is recoverable on the next single-process API
  startup because no live ownership survives the process boundary.
- A live but hung handler is not executed a second time automatically. Treat a
  persistent dead/stale health result as an incident and use the controlled
  managed-runtime restart procedure after preserving evidence.
- This implementation depends on the certified single API process. Do not
  enable multiple Uvicorn worker processes or multiple API instances without a
  separately reviewed database-backed ownership lease and fencing token.

## Implementation verification — no live action

Use the reviewed project environment:

```bat
python -m pytest -q tests\test_phase4_reliability_preflight.py tests\test_job_service_reliability.py tests\test_pdf_job_reliability.py tests\test_week3_architecture.py tests\test_server_migration_entrypoint.py tests\test_payment_record_pdf.py
python -m pytest -q
python -m scripts.check_dependency_policy
git diff --check
```

Required results:

- Atomic claiming and stale recovery tests pass.
- An active long-running job is never returned to `PENDING`.
- Healthy, stale, and dead worker states are classified correctly.
- Migration tracking fails closed and completed migrations are idempotent.
- PDF jobs reach exactly one terminal state and valid PDFs start with `%PDF-`.
- Full tests, dependency policy, and diff checks pass.

Do not commit or deploy a gate with a failing reliability regression test. A
discovered implementation defect requires a separately approved hotfix.

## Read-only server preflight

After implementation review, commit/push approval, and server-sync approval:

```bat
cd /d C:\mto
call venv\Scripts\activate
python -m scripts.phase4_reliability_preflight --require-ready --output logs\remediation-phase-4-reliability-preflight.json
echo Exit code: %ERRORLEVEL%
```

Exit codes:

- `0`: `PASS`; eligible for the separately approved live acceptance exercise.
- `4`: `REVIEW`; inspect and document recent failed jobs, then rerun. Do not
  ignore the result or increase a threshold merely to obtain a pass.
- `2`: `FAIL`; preserve the report and stop.

The report must show `PASS` for source, database, job queue, API, and runtime.
It also requires current backup/restore evidence, financial invariants, audit
integrity, all migrations, the job schema/indexes, no stale work, authenticated
readiness, and the managed supervisor.

## Live queued-SOA acceptance — separate approval required

Do not run this section as part of preflight. Before the exercise:

1. Create a new Hybrid Backup and require protected server/cloud storage and
   current successful restore verification.
2. Capture a financial baseline.
3. Confirm System Health reports three healthy fast workers and one healthy
   slow worker.
4. Select one existing property appropriate for an SOA without recording its
   taxpayer identifiers in the acceptance report.

Through the authenticated normal application/API workflow, submit exactly one
`pdf_soa` job. Require:

- One job identifier and one terminal `COMPLETED` state.
- Completion within 30 seconds under normal pilot load.
- Progress 100 and a completion timestamp.
- One non-empty output inside the approved document area.
- A `%PDF-` file signature and successful pilot desktop opening.
- Polling or client reconnection does not submit or execute a duplicate job.

Then log out, close/reopen the pilot desktop, log in, and confirm readiness.
Rerun the reliability preflight, Phase 5 audit preflight, and financial baseline
comparison. Required results are reliability `PASS`, audit chain `VERIFIED`,
and financial invariant comparison `PASS`.

## Completion gate

Original Phase 4 is complete only after:

1. Focused and full tests pass.
2. Read-only server preflight passes.
3. Four expected workers are healthy.
4. The single queued-SOA exercise passes.
5. Post-exercise reliability, audit, and financial checks pass.
6. Privacy-safe evidence is retained.
7. The original Phase 0–9 traceability matrix is updated.
8. Any application change made to fix a defect is followed by a renewed Phase
   9 immutable-package production certification.

## Failure rule

Do not retry a failed job repeatedly, edit the job row, launch Uvicorn manually,
or restore a database without incident approval. Preserve the privacy-safe
report and sanitized logs. Diagnose first; implement a defect correction only
under a separately approved hotfix.
