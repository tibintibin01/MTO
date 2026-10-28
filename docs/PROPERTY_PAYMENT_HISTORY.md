# Property payment history - v2.1.24

Integrated into Payment & Receipt Ledger through **PAYMENT HISTORY**. This
development does not alter the finalized v2.1.23 package or activate a release.
The existing loaded-table Excel export remains a separate function.

## Scope and workflow

1. Load one property account, using the duplicate-TD account selector when needed.
   A selected payment row can also identify one account from a broad search.
2. Open Payment History. The dialog binds the immutable internal property ID,
   freshly requests all recorded payment years, and previews oldest receipt date
   first. Undated entries remain visible at the end and are counted explicitly.
3. Optionally include previous TDs. Only a locally resolvable, chronological,
   one-to-one chain is accepted. Cycles, ambiguous legacy TD matches, missing
   references, conflicting ID/TD references and branching successors block
   expansion. Export the selected account alone or review accounts separately.
   No owner-name matching or automatic descendant inclusion occurs. Archived
   predecessors remain identifiable in separate account sections. Link validation
   is not independent proof that two declarations cover the same physical parcel.
4. Review each account section, recorded cash total and limitations. Export PDF
   or Excel using its corresponding save-dialog default. Cancellation does not
   request or write a report. A wrong filename extension is rejected.
5. Export re-reads the scope and compares its fingerprint to the reviewed preview.
   A change requires reloading and reviewing. The exported capture has its own
   generation timestamp. The fingerprint is a change detector, not a signature
   or compliance certificate.

## Meaning of the amounts

The source is `payments`, one entry per Payment ID. Allocation joins and retained
PDF history never multiply cash. Distinct payments with the same OR text are not
collapsed. Penalty and discount remain their recorded adjustment values and are
not added to cash. No outstanding-balance or tax computation is introduced.

The existing ledger's Basic/SEF fields use current property values and are not
stored historical cash portions. This report explicitly marks that breakdown
unavailable instead of fabricating it. Owner and address are labeled current
stored account details. Unencoded receipts and deleted payment entries are not
reconstructed. This is an office reference, not an official receipt or clearance.

## Technical boundaries

- Authenticated read routes: `GET /payments/property/{id}/history` and
  `/history/export?format=pdf|xlsx&fingerprint=...&include_previous=false|true`.
  They use the same authenticated access scope as the existing ledger.
- No schema changes, financial writes, receipt regeneration, cloud upload,
  stored server export, task changes or source activation. Responses are no-store.
- Exports are generated in memory with existing ReportLab/openpyxl runtime
  dependencies. No new dependency is required. The spreadsheet is a fixed
  recorded-data snapshot with numeric cash/date cells and literal identifier,
  owner, OR and remark text, including formula-like text.
- Desktop network/file work runs in a worker. A queue is polled on the Tk thread.
  The selected ID is fixed for the dialog, preventing a later ledger search from
  switching its account. Closing the dialog does not schedule worker Tk calls.

## Verification and release boundary

Use synthetic SQLite fixtures only, cloud disabled and a nonexistent test vault.
Test account isolation, historical/archived scopes, unsafe links, multi-year
allocations and multiple PDFs, zero/undated and long histories, snapshot changes,
authentication, save-dialog cancellation/defaults, and literal Excel values.
Render generated PDF and spreadsheet test output for visual inspection.

Source publication, PR/merge and a new versioned build were authorized on
2026-10-29. Server deployment and a genuine installed-client pilot remain
separate controlled steps. Do not claim this feature is present in the installed
v2.1.23 client or that a source/build check is production acceptance.

## Local verification completed (2026-10-29, Asia/Manila)

- Full CI-style regression run: **1,307 passed**, zero failures/errors. This
  includes the native dialog layout check. The separate legacy UI module suite
  was also exercised during development (60 combined UI/history checks passed
  before the last four additional safety tests).
- Latest focused report/status/export run: **112 passed**.
- Black, fatal-error Flake8, desktop/server trust-boundary checks and the
  all-severity Bandit review passed with zero findings. Existing dependency deprecation
  warnings remain; no dependency or security-exception changes were made.
- Application-generated synthetic PDF: six pages, repeated account/table
  headers, long remarks, archived previous account and zero-payment account.
  All pages rendered and visually checked.
- Application-generated Excel: inspected structurally and opened read-only in
  native Excel. Leading-zero OR text, literal formula-like remarks, numeric cash,
  real date cells, separate account worksheets, filters and frozen panes checked.
- Native disconnected dialog preview visually inspected. Test UI and workbook
  windows closed after inspection. No production database, vault or cloud was
  used. Export QA follows the PDF/spreadsheet guidance for readability and typed
  values, while retaining the application's existing runtime libraries.

The development branch is `codex/property-payment-history`, based on
`05937331c7288c40d4ce0d9c6ab2c495be895b2f`. The verification above records
pre-publication development checks. v2.1.24 advances only the product identity
and explicit immediate-predecessor publisher/workflow allowlists. It preserves
the original publisher tools, four daily triggers and evidence. No runtime
dependency, risk exception, schema or financial-calculation change is included.

Production remains the separately finalized v2.1.23 release until an approved
maintenance window, deployment, genuine pilot and final acceptance. These local
checks are not production pilot acceptance or compliance certification.

Release-preparation regression on 2026-10-29: **1,318 passed**, including the
explicit v2.1.23-to-v2.1.24 and interrupted publisher-approval transitions.
Future, unreviewed v2.1.25 remains rejected. The original manual/finalization,
financial invariant, backup and immutable-source gates are unchanged.

## Approved build-only security patch

The first PR CI run found CVE-2026-114613 in development-only `msgpack` 1.2.2.
On 2026-10-29 the owner approved updating only that package to 1.2.3 and
regenerating the reviewed development hash lock. The universal lock was rebuilt
with the existing pinned uv tool. All other resolved package versions, runtime
requirements/lock, website dependencies and risk exceptions remain unchanged.
The direct development pin, dependency policy and regression tests prevent a
silent return to the affected version. No vulnerability is ignored or waived.

Primary advisory:
https://github.com/msgpack/msgpack-python/security/advisories/GHSA-j586-36cw-2gc2
