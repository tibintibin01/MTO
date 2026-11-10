# Tax Bills for new and future-effective declarations

The Compliant list remains a paid-billing view through its **AS OF YEAR**. A new
declaration effective in 2027 need not appear there in 2026, and a declaration
without paid billing history is not automatically compliant. Do not change its
effectivity or create a dummy payment just to obtain a bill.

## Desktop workflow

1. Open **Compliant Properties → GENERATE TAX BILL**. This button works even
   when the compliant table is empty; no compliant row is required.
2. Search by TD, PIN, owner, lot, barangay or location. The search includes all
   non-deleted declarations, including new, unpaid and future-effective ones.
   It reads the server afresh, not the general property's list cache.
3. Select the exact account using **Account #**, TD, owner, PIN, lot/block,
   location and effectivity. A TD alone is not an account identity. Identical
   TDs remain separate rows; the first matching row is never silently chosen.
4. Set **TAX BILL YEAR**, e.g. 2027. This does not change the compliance AS OF
   YEAR. The default is one year after the current compliance scope.
5. Click **Generate PDF**, check the account/year confirmation, then confirm.
   A preselected compliant row is only a search convenience, not a requirement.

Search pages use descending account-ID cursors, with **Load more matches**.
Changing search text invalidates the previous selection. Downloads retain the
confirmed ID/year even if the main page subsequently changes.

## Server behavior and boundaries

- Authenticated GET `/properties/tax-bill-candidates` returns minimal account
  descriptors. Searches are literal, case-insensitive, limited to 100 input
  characters and 100 rows per API page (50 in the desktop).
- Discovery is not proof of tax-year eligibility, payment, exemption or
  compliance. The existing Tax Bill endpoint rechecks the selected account.
- A future-year bill with no posted billing uses the existing virtual-advance
  calculation. It requires the configured target-year Tax Policy and an
  assessment effective for that year. No default policy is invented.
- A superseded account cannot receive a newly invented advance bill from its
  old assessment when its linked successor is already effective. The operator
  must explicitly select that successor; the system does not silently retarget.
- Existing posted-year billing and discount/payment-date calculation rules are
  preserved. Current/past years without billing are not newly synthesized by
  this change. Missing policy/assessment is an operator-visible refusal.
- Native DATE/DATETIME and legacy year/date text effectivity values are supported
  without changing the database schema.
- No billing, payment, allocation, TD, receipt history, tax rate, financial
  calculation rule, compliance filter, count or stored balance is changed.
  Accounts with no earlier billing history are not labelled compliant through
  the prior year merely because a virtual bill was requested.
- Search performs database reads only. Explicit PDF generation retains the
  existing document output/download/storage behavior; it is not a payment and
  is not advertised as having no file/storage side effects.

## Validation and release

Synthetic tests cover native DATE/DATETIME, new 2027 declarations without any
billing/payment, duplicate-account isolation, stable pagination, authentication,
literal wildcard search, policy/effectivity/refused successor requests, unchanged
compliance membership and absence of financial writes. Headless desktop tests
cover invalid years, confirmation/cancel, stale results, closed windows and exact
ID/year download scope.

Local implementation and automated tests are not server activation or a genuine
client pilot. Build/publication/activation must follow a separately approved
release. Ordinary office entry need not pause for this development work.
