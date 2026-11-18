# MTO v2.1.29 — Payment and property feedback

This desktop-only change adds shared in-app feedback in **Add Payment** from
the Ledger and **Add/Edit Property** from the Assessment Roll. The API, tax
calculations, duplicate policy, property version checks, and payment idempotency
keys are unchanged.

- **Confirmed save:** Close the editor, show the OR and amount or the TD,
  and refresh without another dialog. Ledger refresh uses the account returned
  by the server. Assessment Roll keeps its filters and highlights the saved
  account by record ID when it is present on the refreshed page. If the follow-up
  read fails, keep the saved result and report that the view could not refresh.
- **Confirmed duplicate:** Keep the form and show that no new payment was
  saved. When the server supplies an existing payment ID, the review action
  reads and shows the recorded receipt only if account, OR number, date and tax
  years all match. Otherwise, ask the operator to review the ledger manually.
- **Validation or uncertain save:** Inline feedback keeps the entered values.
  If the server did not confirm the outcome, the form cannot resubmit; review
  the current record or receipt before opening a new form. An uncertain result
  does not mean the server failed to save the record.
- **Confirmation:** Existing consequential actions and closing a modified form
  use a themed confirmation with explicit action text. Cancel, Escape, or
  closing the confirmation window preserves the current state.

Verify both themes and keyboard operation. Exercise known duplicate, rejected
edit, changed-version, and lost-response cases using synthetic test accounts.
Never submit a test payment or edit in production just to exercise a notice.

## Desktop rollout

The API and minimum-client versions stay at `1.0`. The desktop candidate uses
the same API as v2.1.28 and does not require an API restart or database change.
Keep the verified v2.1.28 installer available for rollback. After publishing
the approved tag and passing the release artifact checks, install on one
approved pilot workstation first. Confirm that it reports v2.1.29, reconnects,
and can open the Ledger and Assessment Roll. Check payment preview and record
review without submitting a fabricated production transaction or edit.
