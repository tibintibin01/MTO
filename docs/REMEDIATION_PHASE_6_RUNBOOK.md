# Remediation Phase 6 — Final production certification

Phase 6 is the closeout phase for the current security and production-readiness
remediation. It introduces no business feature and no database migration. Its
purpose is to produce a repeatable, privacy-safe acceptance record for the
deployed server and pilot desktop package.

Historical documents also mention an older development phase named “Phase 6.”
That roadmap predates this remediation and is not this certification phase.

## Safety boundaries

- The certification runner is read-only.
- It does not stop or start services, run migrations, create backups, rotate
  credentials, change certificates, or write business data.
- Database sessions are rolled back and supported database transactions are
  marked read-only.
- Query results are reduced to counts and timings. Taxpayer names, TD/PIN
  values, OR numbers, receipt data, credentials, secrets, and private keys are
  excluded from the report.
- A failed gate blocks certification. It does not attempt an automatic repair.
- Any discovered defect is handled as a separately approved Phase 6 hotfix.

## Automated gates

The runner checks all of the following:

1. `master` is checked out and the production worktree is clean.
2. Every registered server migration is recorded as applied.
3. Phase 3 financial invariants and schema are valid.
4. Phase 5 audit schema is active, timestamps use `DATETIME(6)`, at least one
   live event exists, and the complete chain verifies.
5. The latest server-and-cloud backup is less than 24 hours old, has a valid
   checksum, is present on the server, and has current restore verification.
6. Python, frontend, and CI dependencies satisfy the pinned dependency policy.
7. Desktop sources, PyInstaller configuration, and the selected distribution
   contain no server-only modules or secret/private-key material.
8. Authenticated TLS configuration, key/certificate match, certificate chain,
   identities, and expiry window are valid.
9. The HTTPS `/readyz` endpoint succeeds within the latency threshold.
10. The active compliant, compliant-summary, and delinquent database queries
    complete within the latency threshold.
11. The Windows scheduled task is running as `SYSTEM`, launches
    `scripts.run_api_supervisor`, and uses the MTO project as its working
    directory.

Default limits are three seconds for authenticated readiness, five seconds for
each critical database query, and at least 30 days of certificate validity.
Changing a threshold requires an explicit operational decision and must not be
used merely to hide a regression.

## Server preflight

Use Command Prompt as Administrator. The API must be online. First create a
fresh Hybrid Backup through the application and wait for cloud protection and
restore verification to report success. Then run:

```bat
cd /d C:\mto
call venv\Scripts\activate
python -m scripts.phase6_production_certification --preflight --distribution C:\MTO\dist --output logs\remediation-phase-6-preflight.json
```

The command must report every automated component as `PASS` and the overall
status as `READY_FOR_MANUAL_ACCEPTANCE`. A dirty worktree is intentionally a
blocking finding. Review local files rather than deleting or moving them
without confirming their purpose.

## Manual desktop acceptance

After automated preflight passes, use the deployed pilot client to verify:

1. Login and dashboard loading.
2. Property search.
3. Payment and Receipt Ledger.
4. Both verified duplicate TD accounts remain separate.
5. Delinquent and compliant dashboards load within an acceptable time.
6. One applicable PDF or non-financial report can be generated.
7. Logout, close, reopen, and log in again.

Do not create, edit, or delete a financial transaction solely for this smoke
test.

## Final certification

After the manual checklist succeeds, rerun all automated gates and record the
operator confirmation:

```bat
python -m scripts.phase6_production_certification --final --confirm-desktop-smoke --distribution C:\MTO\dist --output logs\remediation-phase-6-final.json
```

The final command must report `PHASE 6 PRODUCTION CERTIFICATION PASSED`. Preserve
the preflight and final JSON reports with the Phase 0–5 remediation reports.

## Failure and rollback rule

Certification itself makes no production change and therefore requires no
rollback. If any component fails, preserve its report and investigate the
named finding. Stop the API only when the finding indicates active audit-chain,
financial-integrity, TLS-private-key, or database corruption risk. Do not run a
repair, migration, credential rotation, or destructive cleanup without a
separate approved procedure and a current verified backup.

## Completion

Phase 6 closes when automated preflight passes, the desktop checklist is
confirmed, final certification passes, and the report is retained. No further
remediation phase follows; later changes are routine maintenance or separately
approved product work.
