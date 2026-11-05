# Same-year TD succession and new-year payments

## Failure reproduced

A current TD and its predecessor can both have the same annual effectivity year.
For example, a synthetic chain has an older 2023 record, a 2025 predecessor and
its 2025 successor. These are three distinct TD numbers, not duplicate accounts.

An existing 2026 billing on the selected account resolves directly. If 2027 has
no billing yet, resolution expands the TD chain and used to reject the two 2025
records as a tie. The error incorrectly claimed that both records used the same
TD number. Changing an official effectivity year or deleting a predecessor is
not an appropriate workaround.

## Resolution rule

The existing requested-account/non-archived-billing rule remains authoritative.
When that rule does not apply, the existing annual-effectivity selection remains
in place. Only a tie at the latest eligible year uses the new successor rule:

- Follow explicit `previous_property_id` links, or legacy Previous TD text only
  when it identifies exactly one non-deleted account.
- Choose a unique candidate only if every other tied candidate is its ancestor
  through known, nondecreasing effectivity years.
- Never infer succession from record ID, owner/PIN/lot similarity, insertion
  order, encoding timestamps or full-date sorting.
- Keep real duplicate-TD selection, multiple-successor/subdivision, conflicting
  references, cycles, reversed chronology and unprovable ties blocked.
- An unknown-year gap cannot prove precedence between tied candidates. A missing
  older reference does not invent an account or rewrite office history.

Cycles and disagreement between an explicit parent ID and Previous TD text are
also rejected while expanding a chain. A blocked history uses a history-specific
message, not an unsupported duplicate-TD claim. A payment save returns HTTP 409
after rolling back the failed transaction; it is not reported as an internal
server error. Actual duplicate TD lookups keep their existing selection message.

## Boundaries

This is an account-resolution code fix. It does not migrate the schema, rewrite
TD relationships, delete/archive records, change official effectivity dates,
repair old payments or alter financial calculation/allocation conventions. A
normal, authorized future payment still creates its own payment, billing and
allocation records under the existing transaction/idempotency controls.

Resolution/preview itself creates no billing or payment rows. Existing direct
billing authority and historical-year routing remain covered by regressions.

## Verification and rollout

`tests/test_same_year_td_resolution.py` uses only synthetic in-memory databases.
Coverage includes explicit and unique legacy links, reordered IDs, selection
from different points in a chain, longer same-year histories, future successors,
historical direct billings, archived billings, successful new-payment allocation,
unchanged old TD/payment/billing/allocation snapshots, blocked unsafe graphs,
duplicate account isolation and HTTP conflict handling.

No production records were used to create the fixtures. Screenshots informed the
shape of the regression, not a certified diagnosis of every live account.

This source change is not a deployed release. Before activation, prepare and
verify the matching approved release and preserve existing v2.1.25 controlled
continuation evidence. Never re-run old correction/Finalize helpers, create an
artificial billing, or change a baseline to bypass a gate. A genuine live-account
pilot and any maintenance window must be separately planned. The future
short-window release-workflow redesign is not implemented by this patch.
