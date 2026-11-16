# MTO v2.1.28 — Automatic Add Payment calculation

## What changes

In **Add Payment**, enter a tax year and OR number, then finish the OR date and
press **Tab** or move to another field. For a single tax year, MTO verifies the
intended property account and fetches the existing server calculation.
**Recalculate** beside the date retries or refreshes the result.

The calculated annual due is not the remaining balance after previous payments.
If the operator has entered **Amount Paid**, the preview leaves it unchanged.
For installments, enter only the amount actually received. Multi-year receipts
remain manual. Nothing is posted until the operator uses **Save Payment**.

Input changes invalidate old calculations. Late results cannot update the form
for a newer receipt or tax year. Single-year Save stays disabled if the current
preview is unavailable. The payment-posting request and idempotency key are
unchanged.

## Compatibility and pilot

- This change uses the existing payment-target and compute-payment endpoints.
  API and minimum-client versions, backend code, tax rules, schema, and
  dependencies are unchanged.
- The local test client is not an official installer or an activated release.
  Do not replace the installed client with it or use it for office collections.
- Before office rollout, validate the packaged client against a test system:
  a single-year preview, a changed OR date, a partial payment, a multi-year
  receipt, and an account with a linked or duplicate TD. Confirm that changing
  inputs alone never posts a payment.
- A production package must pass the existing tagged-source, artifact, and
  distribution controls. Keep v2.1.27 and its release evidence intact.
