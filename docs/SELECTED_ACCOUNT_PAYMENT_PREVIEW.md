# Selected-account preview for branched TD history

## Root cause

An exact selected property can have an existing, non-archived billing for the
requested tax year, while its former TD has several successor properties (for
example, a subdivision). Payment ownership already resolves directly to the
selected property's billing. The preview previously then expanded the entire
connected history and rejected the parent's multiple successors. It returned
HTTP 409 even though no choice among sibling accounts was required.

## Narrow preview rule

- An explicit active property ID must agree with the requested TD. A missing or
  deleted ID does not fall back to another account; a mismatched ID/TD conflicts.
- Only when the selected account owns an active billing for the exact requested
  year does preview use the selected account and its validated ancestors.
- Cycles, contradictory parent ID/text, and ambiguous legacy parents still
  conflict. The new path does not select a sibling or infer an account from an
  owner, PIN, parcel description, record order, or tax calculation.
- Without that concrete obligation, original full-history/effectivity rules
  still apply. Archived or different-year billings do not qualify. Looking up
  a shared parent without a child account still conflicts on multiple children.
- The response retains `chain` and adds `chain_scope`. The new scope is
  `selected_account_ancestors`; it does not claim to contain all connected
  properties. Unchanged full-history responses have scope `connected_history`.

This is a server-side preview fix, compatible with the installed v2.1.29
client's existing endpoint. It does not change payment posting, amounts,
allocation, idempotency, schema, receipt history, assessment history, or the
property payment history export. No billing is created by preview. Do not
repair lineage or create an artificial billing to bypass a conflict.

## Verification and activation

`tests/test_selected_account_preview.py` uses in-memory synthetic records:
nine successors, explicit and unique legacy parents, reordered IDs, different
selected children, duplicate TDs, missing/archived/different-year obligations,
deleted or mismatched selection, unsafe ancestors, HTTP preview, tax calculation,
and a simulated payment whose siblings and old property rows stay unchanged.
Existing strict-history and financial regression tests remain in scope.

Source implementation and local tests are not production activation. An API
update, any source publication or release tag, and an authorized server window
require separate approval. Preserve v2.1.27 server evidence and the v2.1.29
client package. No replacement client or manual financial correction is needed
merely to use this resolver change after an approved API update.
