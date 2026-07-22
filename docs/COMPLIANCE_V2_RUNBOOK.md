# Compliance Classification Deployment Runbook

This change is intentionally split into two production stages. Do not combine
them during office hours.

## Stage 1: currency-safe legacy classifier

1. Keep `MTO_ENABLE_COMPLIANCE_V2=0`.
2. Deploy the release normally.
3. Confirm `/readyz` and `/healthz` return HTTP 200.
4. Search for a known fully paid TD and confirm it appears in the compliant
   list. Also check an account with a real unpaid cent or larger balance and
   confirm it does not appear.
5. Compare the compliant list count with the barangay summary count.

This stage fixes sub-cent calculation tails and does not activate the stricter
per-tax-year policy.

## Stage 2: review and activate V2

The conservative defaults are:

```env
MTO_COMPLIANCE_DATA_START_YEAR=0
MTO_COMPLIANCE_EXCLUDE_ARCHIVED_BILLINGS=0
```

With these values, old and archived billings remain obligations. Change them
only after a written policy decision and a new impact preview.

1. Create a backup through the MTO backup function and wait for verification.
2. Generate the exact preview:

   ```powershell
   python scripts\report_compliance_impact.py --year 2026 --detail-limit 5000 --output logs\compliance-impact-2026.json
   ```

3. Review every `newly_compliant` and `removed_from_compliant` account. Newly
   compliant accounts block activation. Every removal must have a documented
   business reason.
4. Create an approval file outside Git, for example
   `C:\MTO\logs\compliance-v2-approval-2026.json`:

   ```json
   {
     "as_of_year": 2026,
     "billing_data_start_year": null,
     "exclude_archived_billings": false,
     "approved_removed_td_numbers": ["TD-NUMBER-REVIEWED-1"],
     "approved_by": "Municipal Treasurer",
     "approved_at": "2026-07-22T16:00:00+08:00"
   }
   ```

5. Run the fail-closed activation preflight:

   ```powershell
   python scripts\validate_compliance_v2_activation.py --year 2026 --approval logs\compliance-v2-approval-2026.json --output logs\compliance-v2-preflight-2026.json
   ```

6. Only if the command prints `COMPLIANCE V2 ACTIVATION PREFLIGHT PASSED`, set
   `MTO_ENABLE_COMPLIANCE_V2=1` and restart the API.
7. Repeat the health checks, known-TD checks, count comparison, and a normal
   payment lookup before staff resume work.

## Immediate rollback

If any unexpected account disappears, counts diverge, or the API becomes
unhealthy:

1. Set `MTO_ENABLE_COMPLIANCE_V2=0`.
2. Restart the API.
3. Verify `/readyz`, `/healthz`, and the compliant list.
4. Preserve the preflight report and API logs for investigation.

No database restore is needed to roll back classification logic because both
stages are read-only and do not update payment, property, or billing records.
