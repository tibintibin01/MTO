# Post-certification operations and maintenance

This runbook begins after the successful Phase 6 production certification. It
does not create another remediation phase. Its purpose is to preserve the
certified security, financial-integrity, availability, and recovery posture of
the Municipal Revenue System.

## Safety boundaries

- Operations checks are read-only and privacy-safe.
- Health checks never restart a service, create or restore a backup, run a
  migration, repair data, rotate credentials, or change configuration.
- Database-backed checks use the existing Phase 3 and Phase 5 preflights and
  roll their sessions back.
- Reports contain counts, timings, statuses, hashes, and generic findings. They
  must not contain taxpayer names, TD/PIN values, OR numbers, credentials,
  secret values, private keys, or absolute backup paths.
- A failed check blocks the related change or maintenance action. It does not
  authorize an automatic repair.

## Service objectives

The initial operating targets are:

- authenticated API readiness during office hours;
- ordinary page and API operations within five seconds;
- escalation for any repeated operation exceeding ten seconds;
- a protected backup less than 24 hours old with a valid checksum, server
  presence, cloud protection, and current restore verification;
- zero Phase 3 financial-invariant violations;
- a fully verified Phase 5 audit chain;
- at least 15 percent and 10 GiB free on application and backup storage;
- certificate renewal review beginning at least 60 days before expiry.

The current daily-backup design supports an interim recovery point objective
of no better than 24 hours. A shorter target requires separately designed and
tested incremental backup or MariaDB point-in-time recovery. The proposed
recovery time objective is four hours and must be measured during restore
drills rather than assumed.

## Read-only health checker

Run the checker from an Administrator Command Prompt on the API server:

```bat
cd /d C:\mto
call venv\Scripts\activate
python -m scripts.operations_health_check
```

The default report is written atomically under `logs\operations` with a UTC
timestamp. An explicit evidence path can be supplied:

```bat
python -m scripts.operations_health_check --output logs\operations\daily-health.json
```

Default gates:

- one authenticated `/readyz` sample, maximum five seconds;
- one sample of each certified delinquent/compliant query, maximum ten seconds;
- at least 60 days of server-certificate validity;
- at least 15 percent and 10 GiB free disk space;
- financial-safety schema and invariants;
- audit schema, `DATETIME(6)` precision, live events, and complete chain;
- protected backup freshness and restore readiness;
- supported automatic backup schedule;
- dependency policy and clean source state;
- the SYSTEM scheduled supervisor and its authenticated TLS configuration.

Exit codes are operational signals:

- `0`: `PASS` — every gate passed;
- `1`: `WARN` — no high-risk failure, but operator action is required;
- `2`: `FAIL` — a high or critical control failed.

Warnings and failures must be reviewed from the JSON report. Do not weaken a
threshold merely to make a check pass.

## Frequency and ownership

### Daily — System Administrator

1. Run the operations health check.
2. Confirm the authenticated API and scheduled supervisor are online.
3. Confirm the latest backup is less than 24 hours old and restore verification
   is current.
4. Review failed or abandoned background jobs and available disk capacity.
5. Escalate any `FAIL` before normal processing continues when financial,
   audit, TLS, backup, or database integrity is involved.

### Weekly — System Administrator and service owner

1. Review the seven daily reports for recurring warnings.
2. Run the Phase 6 automated preflight against the retained certified desktop
   package.
3. Review critical-query timings and user-reported latency.
4. Review failed authentication and privileged administrative events.
5. Confirm the server source remains on an approved commit with a clean
   worktree.

### Monthly — System Administrator and maintainer

1. Review Windows, MariaDB, Python, and frontend security updates.
2. Run the dependency policy and vulnerability gates before approving updates.
3. Review user and privileged access with the Municipal Treasurer.
4. Review certificate validity and begin renewal no later than 60 days before
   expiry.
5. Record availability, backup success, latency, storage, and incident trends.

### Quarterly — Service owner and independent reviewer

1. Create and verify a fresh hybrid backup.
2. Restore it into an isolated database; never overwrite production during a
   drill.
3. Verify checksums, record recovery point and recovery time, and run financial
   and audit integrity checks against the restored copy.
4. Conduct an incident-response tabletop exercise and privileged-access review.

### Annually

- arrange an independent penetration test;
- review privileged credential and signing-key rotation;
- review certificate and CA lifecycle;
- review the approved municipal records-retention schedule;
- repeat production certification after resolving any finding.

## Incident thresholds

Treat these as critical and escalate immediately:

- any financial invariant above zero;
- audit-chain verification failure or invalid audit timestamp precision;
- missing, corrupt, unprotected, or stale backup with no current verified copy;
- TLS validation, key/certificate, or public-CA mismatch;
- suspected credential compromise or unauthorized privileged access;
- database corruption or unexplained financial-data change.

Preserve logs and reports, record the time and observed symptoms, and limit
further change. Do not restore the database, rotate credentials, or delete
evidence without a separately approved incident procedure and a verified
backup.

High-priority operational issues include API unavailability, repeated query
latency over ten seconds, failed scheduled backups, a non-running supervisor,
or storage below the configured threshold. Investigate the same business day.

## Change control

Every production release requires:

1. reviewed and tested source on an approved commit;
2. a clean production worktree;
3. current backup and restore readiness;
4. a documented rollback procedure;
5. authenticated readiness after activation;
6. financial and audit invariant verification;
7. a pilot desktop smoke test when desktop behavior changes;
8. retained privacy-safe evidence.

Schema changes, restores, credential rotation, certificate rotation, cleanup,
and scheduled-task activation remain separate approval events.

## Monitoring activation boundary

Workstream 1 adds only this runbook, the read-only checker, and tests.

Workstream 2 adds a scheduler definition, a single-instance scheduled runner,
and bounded operations-report retention. Adding these files does not itself
register or start a Windows task and does not enable or alter automatic
backups. Production activation remains a separate approval event.

## Workstream 2 scheduler and report retention

The approved scheduler design is:

- Windows task name: `MTO Operations Health Check`;
- daily execution at 06:30 local server time by default;
- execution as the Windows `SYSTEM` service account with highest privileges;
- at most one instance, enforced by both Task Scheduler `IgnoreNew` and a
  non-blocking process lock;
- a 30-minute execution limit without automatic repair or retry loops;
- a privacy-safe JSON report for each completed run;
- 400 days of operations-health reports retained by default.

Retention is deliberately narrow. The runner deletes only regular, non-linked
files directly inside `logs\operations` whose names exactly match
`operations-health-YYYYMMDDTHHMMSSZ.json` and whose embedded UTC timestamp is
older than the approved retention period. It does not delete certification,
remediation, audit, application, or backup evidence. The allowed retention
range is 30 through 3,650 days.

Run the scheduler preflight from an Administrator PowerShell session after the
approved source is synchronized to the server:

```powershell
cd C:\mto
.\venv\Scripts\Activate.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File `
  C:\mto\scripts\install_operations_health_task.ps1 -Preflight
```

Preflight is read-only. It verifies the managed Python executable, runner, and
any existing task configuration. It does not run the health check, create a
report, or register, replace, start, or stop a task.

Task registration is permitted only after a separately approved activation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  C:\mto\scripts\install_operations_health_task.ps1 -Apply
```

The activation requires the exact interactive confirmation phrase and
registers the task without immediately starting it. A separately approved
post-activation smoke test must start the task once, verify its task result,
inspect the newly written JSON status, and confirm that financial and audit
invariants remain intact.
