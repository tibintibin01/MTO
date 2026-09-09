# Phase 3 — Financial Transaction Safety

## Purpose

Phase 3 prevents duplicate, cross-user, partial, and silently queued financial
changes. A disconnected desktop may use cached GET data, but it cannot save,
queue, or later replay payments, edits, or deletions. Every financial mutation
requires a UUID v4 idempotency key bound to the authenticated user, HTTP
operation, and canonical request data.

The idempotency claim, payment mutation, billing allocation, and stored response
commit in one MariaDB transaction. Repeating the same request returns the
original response. Reusing the key with different data returns HTTP 409.

## Implemented safeguards

- No POST, PUT, PATCH, or DELETE is placed in the desktop offline queue.
- Legacy pending queue rows become `BLOCKED_LEGACY` and are never replayed.
- Payment create, edit, delete, and batch delete reuse stable operation keys.
- Batch deletion is all-or-nothing.
- Payment and billing rows are locked while allocations change.
- Allocations must equal the payment amount and may reference only the same
  property and matching tax year.
- Unique database indexes reject duplicate receipt identities and duplicate
  payment-to-billing links.
- Migration activation fails closed if duplicate receipts, duplicate links,
  cross-property links, or unbalanced allocations already exist.

## Implementation verification — no live cutover

Run from the isolated implementation worktree:

```bat
set MTO_ENVIRONMENT=test
set ENVIRONMENT=test
set MTO_JWT_SECRET=ci_only_not_for_production_0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ
set MTO_API_KEY=ci_only_test_api_key
set MTO_DB_PASSWORD=
venv\Scripts\python.exe -m pytest tests\test_financial_idempotency.py tests\test_financial_safety_migration.py tests\test_connectivity_recovery.py tests\test_billing_service.py tests\test_payment_cleanup.py -q --basetemp .pytest-phase3
venv\Scripts\python.exe -m pytest -q --basetemp .pytest-all
git diff --check
```

Do not commit, push, run migrations, restart the server, or build the live
desktop package until the implementation review is approved.

## Controlled server activation

Activation requires a separate approval and maintenance window.

1. Run Hybrid Backup and require a new cloud timestamp, restore verification
   `SUCCESS`, and protected server/cloud storage.
2. Capture the pre-activation financial baseline:

   ```bat
   python -m scripts.capture_remediation_baseline --database --require-ready --output logs\remediation-phase-3-before.json
   ```

3. Run the read-only Phase 3 preflight:

   ```bat
   python -m scripts.phase3_financial_preflight --output logs\remediation-phase-3-preflight.json
   ```

   Every invariant count must be zero. `NOT YET ACTIVE` is expected before the
   migration. Do not continue if the command says `BLOCKED`.
4. Stop the MTO runtime and confirm ports 8001 and 3000 are available.
5. Apply the migration:

   ```bat
   python -m migration_manager
   ```

6. Run the post-migration check:

   ```bat
   python -m scripts.phase3_financial_preflight --require-active --output logs\remediation-phase-3-active.json
   ```

7. Start the `MTO Treasury API` scheduled task and require authenticated HTTPS
   readiness.
8. Before entering new payments, capture and compare the post-migration
   baseline. Schema activation must not change financial counts or totals:

   ```bat
   python -m scripts.capture_remediation_baseline --database --require-ready --compare-to logs\remediation-phase-3-before.json --output logs\remediation-phase-3-after.json
   ```

9. Build to a staging directory and deploy to one pilot client only.
10. Pilot-test login, property search, one payment post, one payment edit, one
    payment delete, duplicate-TD account separation, PDF generation, logout,
    and reopen. Disconnect the pilot from the LAN and verify a financial change
    is rejected as not saved and the status says read-only cache only.
11. Reconnect and confirm no delayed payment/edit/delete appears.
12. Expand only after the pilot and database invariants pass.

## Rollback

If activation or the pilot fails:

1. Stop deployment to additional clients.
2. Restore the prior API/client build and restart authenticated HTTPS.
3. Leave the additive columns and stricter indexes in place unless a reviewed
   rollback migration is specifically approved; older code can ignore them.
4. Do not change `BLOCKED_LEGACY` rows back to `PENDING`.
5. If any financial invariant changed, stop financial entry and investigate
   before considering a database restore. Use the fresh verified backup only
   under an explicitly approved restore procedure.

The schema migration itself does not intentionally alter payment, billing, or
allocation amounts.
