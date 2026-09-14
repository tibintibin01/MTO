# Remediation Phase 5 — Audit Integrity and Operational Observability

Phase 5 makes the application audit trail tamper-evident, replaces destructive
undo with compensating events, minimizes public health responses, bounds metric
labels, and prevents taxpayer or credential data from entering telemetry.

## Safety boundaries

- Implementation and tests do not modify the production database.
- Live schema activation requires a separate explicit approval.
- The API must be stopped while the audit history is sealed.
- A current server-and-cloud backup with successful restore verification is a
  mandatory activation gate.
- Existing audit content is preserved. Migration only adds deterministic seal
  metadata and records the legacy-chain boundary.
- Do not run an older API against a Phase 5 database after activation. An old
  build can create unsealed audit rows.

## Server activation preflight

Run in an Administrator Command Prompt on the server:

```bat
cd /d C:\mto
call venv\Scripts\activate
git status --short
git branch --show-current
git pull --ff-only origin master
git rev-parse --short HEAD
python -m scripts.capture_remediation_baseline --database --require-ready --output logs\remediation-phase-5-before.json
python -m scripts.phase5_audit_observability_preflight --require-ready --output logs\remediation-phase-5-preflight.json
```

Expected before activation:

- Backup readiness: `PASS`
- Audit chain: `INACTIVE` or `VERIFIED`
- Phase 5 schema: `NOT YET ACTIVE` or `ACTIVE`
- No audit-chain failure

Stop and investigate if the preflight reports a failed chain or backup gate.

## Live schema activation

Only after explicit live-activation approval:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File C:\mto\scripts\stop_mto_runtime.ps1 -ProjectRoot C:\MTO
python -m migration_manager
schtasks /Run /TN "MTO Treasury API"
powershell -NoProfile -ExecutionPolicy Bypass -File C:\mto\scripts\wait_for_mto_api.ps1 -TimeoutSeconds 90
python -m scripts.phase5_audit_observability_preflight --require-ready --require-active --output logs\remediation-phase-5-active.json
python -m scripts.capture_remediation_baseline --database --require-ready --compare-to logs\remediation-phase-5-before.json --output logs\remediation-phase-5-after.json
```

Required results:

- Migration `phase5_audit_integrity_observability_v1`: applied
- API authenticated readiness: passed
- Audit chain: `VERIFIED`
- Phase 5 schema: `ACTIVE`
- Financial invariant comparison: `PASS`

## Pilot acceptance

Build and deploy the signed-off client through the existing secure desktop build
process, then verify:

1. Login and logout.
2. Property search and Payment Ledger.
3. Add one authorized test audit event through a normal application action.
4. Open System Health; Audit Integrity must show `Verified`.
5. Run Data Integrity Audit; Audit Trail Issues must be `0`.
6. Confirm `/readyz` returns only `{"status":"ready"}`.
7. Confirm an unauthenticated request to `/api/v1/system/health` is rejected.
8. Generate one document/PDF and reopen the desktop application.
9. Rerun the Phase 5 preflight with `--require-active --require-live-event`;
   it must remain verified and report at least one live Phase 5 event.

## Timestamp-precision incident recovery

MariaDB `DATETIME(0)` cannot store the microseconds used by the Phase 5 hash
payload. If the first live events fail only with `CURRENT_HASH_MISMATCH`, keep
the API stopped and use the dedicated recovery utility. Do not run the generic
updater or `migration_manager` for this incident; automatic migration refuses
to rewrite evidence without the recovery utility's explicit confirmation.

Run the read-only preflight first:

```bat
python -m scripts.phase5_audit_timestamp_recovery --preflight --output logs\remediation-phase-5-audit-timestamp-preflight.json
```

The preflight must report only timestamp-hash failures, one cryptographically
recoverable timestamp for every affected live event, backup readiness `PASS`,
and the API stopped. After separate live-recovery approval, run:

```bat
python -m scripts.phase5_audit_timestamp_recovery --apply --output logs\remediation-phase-5-audit-timestamp-recovery.json
```

The apply operation creates and restore-verifies a fresh server-and-cloud
hybrid backup before changing the schema. It upgrades the audit timestamp and
chain-state timestamps to `DATETIME(6)`, restores only timestamps whose exact
microseconds reproduce the original hashes, and records migration
`phase5_audit_timestamp_precision_recovery_v1`. It never changes an event UUID,
previous hash, current hash, action, user, old/new snapshot, or other
non-timestamp field. The restored timestamp is the unique value that reproduces
the event's original hash.

Before restarting the API, rerun the Phase 5 preflight and financial baseline
comparison. Required results are audit chain `VERIFIED`, timestamp precision
`6`, at least one live Phase 5 event, backup readiness `PASS`, and financial
invariant comparison `PASS`.

## Incident and rollback rule

If verification fails, stop the API immediately and preserve the Phase 5 report,
application logs, database, and backup artifacts. Do not repair or delete audit
rows in place. Restore the pre-activation database backup and matching prior code
together only after incident review. Code-only rollback to an older writer is not
safe after Phase 5 schema activation.
