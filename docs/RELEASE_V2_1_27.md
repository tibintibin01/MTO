# v2.1.27 — Tax Bills for new and future-effective declarations

This is a source release. A Git tag, passing CI or a merged pull request is not
server activation, a verified installer, office acceptance or release certification.

## Change

**Compliant Properties → GENERATE TAX BILL** now opens an independent account
search. New declarations effective in a future year can be found even without
paid billing history. The operator chooses the exact account and Tax Bill year
and confirms both before PDF generation. The Compliant list itself retains its
existing paid-through-year filters and counts.

The existing virtual-advance calculation handles a future-year declaration with
no posted billing, provided its assessment and target-year Tax Policy exist.
No payment, billing, allocation, TD, receipt history or stored balance is edited.
No schema migration, tax-rate change, new discount rule or data repair is added.
Discovery does not certify compliance or legal correctness. See
[Tax Bill search](TAX_BILL_PROPERTY_SEARCH.md) for limits and refusal behavior.

## Compatibility and release boundaries

- Product identity: **2.1.27**. API protocol and minimum-client contracts remain
  **1.0**, unchanged: existing client/server endpoints remain compatible.
- The new desktop search requires the matching server's added authenticated
  read-only endpoint. Do not install the new desktop against an older server
  and expect the new search to work.
- Portal publisher compatibility is extended only for the reviewed transition
  **v2.1.26 → v2.1.27**. Exact predecessor source/version/verified intent checks
  remain in force. No task, schedule, setting or publication is changed by
  source publication.
- Existing v2.1.26 bounded-window tools and older immutable evidence remain
  untouched and version-locked. They are not v2.1.27 activation tools. A matching
  deployment package must be separately prepared and reviewed before activation;
  do not rename an old kit or replace a baseline to bypass a gate.
- This source-only PR/tag does not include installers, database files, municipal
  records, credentials, protected evidence or risk-acceptance changes. It does
  not request a maintenance window or authorize a server restart/deployment.
- Continue office work during source review and release preparation. Any later
  activation follows a separately approved bounded pause, essential read-only
  pilot and explicit Resume before later full acceptance.

## Regression coverage

Synthetic SQLite fixtures exercise legacy year/date strings and native DATE /
TIMESTAMP columns; declarations with no billing/payment; duplicate TD accounts;
literal search and stable cursor paging; authentication and parameter bounds;
target-year policy/effectivity checks; and refusal to invent advance bills for
superseded accounts. SQL capture verifies no financial writes in discovery or
virtual Tax Bill data generation. Desktop tests cover account/year confirmation,
cancel, stale results, closed windows and server refusals. Prior payment/history,
compliance, bounded-release and portal transition tests are retained.
