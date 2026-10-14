# Reports workspace redesign (local implementation)

This builds on the completed v2.1.19 Reports hotfix. It is not a new deployed
release or production certification. The immutable v2.1.19 package, workflow
evidence, office database, portal publisher, tasks and secrets are unchanged.

## User-facing changes

- Four existing report destinations remain; no global sidebar redesign.
- Consistent Ready, Loading, Loaded, No matches, Error and Filters changed states.
  Selected filters never relabel an older result. Changing filters invalidates
  in-flight responses and disables exports until a matching report is loaded.
- Capture timestamps are explicitly Philippine time, independent of the PC zone.
- Collection search covers the complete selected period (OR, TD or owner).
  Cash totals and receipt counts are not page totals. Newest/oldest **posted**
  order uses receipt IDs, not the encoded OR date. Cursor pages are pinned to
  the first read's highest matching receipt ID; Generate starts a fresh view.
- COA RCD remains a whole-period official export. Clear the search before using
  it. The new screen search does not change official RCD calculation or scope.
- Fiscal summary shows three headline figures; its existing detailed calculation,
  advance-payment coverage and barangay comparison are expandable.
- Barangay report has key/all-column views, full-table column sorting, separate
  credits and direct read-only credit review. Its PDF belongs in this tab.
- Reconciliation retains its original financial equation, status and complete
  export diagnostics. Department papers, timing details and diagnostic samples
  are expandable. Saving a PDF is labelled Export PDF, not Print PDF.

## Credit review basis and privacy

The authenticated private API requires the existing `property_view` read-role
guard. It is not a public portal endpoint. No records are modified, credits
transferred, refunds authorised, or financial repairs performed.

Recorded charge = stored yearly assessed value × that year's Basic + SEF rates
+ the existing effective recorded penalty − the existing effective discount.
Applied payment uses linked allocations on dated receipts through the fiscal
cutoff. All Years removes that cutoff. Non-deleted properties and all available
billing years are included, matching the existing summary/barangay basis.
The existing equal-share adjustment convention is not changed.

Credit = positive excess of applied payment over recorded charge **per billing**.
The complete positive set includes PHP 0.01; the older sampled diagnostic view
is not used as a complete credit list. Credits do not settle another year/account.

The parent report captures a fingerprint of the complete credit set in the same
repeatable-read transaction as its totals. Paging/search/ledger reads must match
that fingerprint. A changed set returns HTTP 409; refresh the parent report.
The fingerprint is a consistency aid, not a sealed audit event or certification.
Each detail read has its own capture time. Other non-credit ledger balances can
reflect later postings; the entire database is not frozen between UI requests.

Rows include internal property ID and billing ID. Duplicate TDs remain separate.
Open Ledger reads the selected internal ID, never a first match by TD, and shows
recorded billing balances only. It has no edit, delete, refund or allocation action
and is not a live accrued-interest SOA estimate.

## Export and rollout boundaries

Exports preserve their existing format and financial calculation. They reread
the selected period and can include postings made after the screen capture.
Excel/PDF remain format-specific. No office data was used in development tests.

Public push, PR, merge, version bump, packaging and deployment still require
separate explicit approval for this redesign. Do not re-activate v2.1.19 to apply
it. A future release must use a fresh backup, the existing guarded updater,
automated financial invariants, a genuine client Reports/credit/export pilot,
restore/operations evidence and final certification. Copy, never Cut, installer
artifacts from the server's immutable distribution folder.

Native geometry/runtime checks do not replace visual review and the installed
client pilot. Production-sized MariaDB latency remains an office pilot gate.
