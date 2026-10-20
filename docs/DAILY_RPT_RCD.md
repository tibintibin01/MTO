# Daily RPT RCD: booklet owner and official receipt date

## Scope

The Reports collection workspace has a separate **DAILY RCD (100 / 200)**
window. It reads encoded RPT payments, fills the collection amounts for General
Fund 100 (Basic RPT portion) and SEF 200, and exports those two forms plus a
supporting receipt list. It does not require retyping collection totals.

The existing monthly/period export remains available and unchanged in scope.
Trust Fund 300 and the office workbook's unrelated denomination sheet are not
included. The two printed forms reproduce the office-supplied layout. Only a
data-only description of its blank geometry, styles and static labels is bundled;
the private workbook, VBA, names, signatures and receipt data are not included.

## Printed office form

The 100 and 200 sheets retain their distinct original layouts: 72 and 67 rows,
respectively, A:M print areas, original merged cells, fonts, borders, column
widths, row heights, Legal paper, margins and print scale. The section wording,
certification, verification/acknowledgment and signature positions are preserved.
No blue redesign, added warning banner or extra rows are inserted into either
printed form. Draft status and limitations appear in the app and supporting
Receipt Details sheet instead.

The selected fixed OR date goes in K5; the report number and collector remain in
K6 and E6. Recorded receipt ranges/amounts populate section A. Section C contains
only recorded OR quantities and ranges, not inferred complete physical stock.
Section D's collection total is populated, while cash/check classification,
actual remittance, opening/closing balances and receipt acknowledgment remain
blank until office verification. Names are text, not copied signatures.

### Cash/check and full handover review inside MTO

The office confirmed that checks are accepted occasionally, that all daily
collections are remitted, and that the bank deposit is normally the following
morning. The report remains tied to the OR date, not the deposit/encoding date.

Before a new daily export, the app opens a report-only review. List each check's
OR, bank, number, payee, whole check amount and portion of that OR. Every check's
allocations must equal its whole amount before export. A shared check involving
other dates/officers or non-RPT collections is blocked for office review rather
than guessed. Mixed cash/check, several checks
on an OR, and one check allocated across several ORs are supported. An explicit
confirmation classifies only the remaining receipt amounts as cash; all-cash is
not silently assumed. Fund amounts reconcile to recorded net receipts, with
cumulative cent rounding and no changes to charges or payments.

Opening accountability is entered separately per fund, or explicitly confirmed
as zero. Unknown opening/closing balances remain blank. Full actual handover
requires its own confirmation, receiving officer and actual date. Only then are
the full-remittance and resulting balance lines filled. The app does not treat
the collector's declaration as the receiver's signed acknowledgment. The planned
bank-deposit date defaults to the next calendar morning and is editable, appears
only on the supporting sheet, and never creates a BankDeposit record or changes
OR dates. Actual bank evidence remains a separate workflow.

The reviewed export uses a POST body rather than exposing check details in the
URL. The server rebuilds the receipt snapshot, revalidates all input, and retains
the report declarations and their source-bound digest in the existing export
audit transaction before releasing the file. No offline financial mutation is
queued. More than nine distinct checks blocks export without dropping rows.
The exact printed form layout does not change.

Exports remain dated source snapshots. A late/backdated receipt requires a new
preview and review; this phase does not automatically amend a previously signed
RCD or assert that an exported draft is a finalized official record.

The SEF form has room for six ranges. If a selected report exceeds six ranges,
export stops without omitting receipts or changing the accepted layout. A
continuation-form convention needs office approval before it can be automated.
No macro, volatile TODAY(), or original CEILING-based stock inference is copied.

On 2026-10-19 the operator confirmed that the sample Excel layout matched the
supplied original. This is layout acceptance only, not evidence of live feature
installation, financial certification, receiver acceptance or a completed pilot.

## One-time setup from the official booklet issuance log

1. Register the actual collecting officer, independently of an app login or
   encoder username. Administrative access is required, as for the existing RCD
   export.
2. Enter each AF 56 booklet's actual first and last OR and its issue date.
   Exactly 50 consecutive serials are supported. Preserve any printed prefix
   and leading zeroes; do not round a range to a multiple of 50.
3. Assign the booklet to its recorded collecting officer. A new booklet may
   belong to the same officer or a different officer.

Overlapping ranges are rejected, including the same numeric range with
different zero-padding. Existing assignment records cannot be changed or
deleted in this first version. Verify the confirmation screen before saving.
If an assignment was entered incorrectly, preserve the log and seek an audited
correction workflow; do not edit SQL or reassign old receipts to bypass a gate.
Reused serials from an indistinguishable series need review rather than an
automatic assignment. A partial-booklet handover is not supported in this phase.

## Daily preparation

- Choose an OR date (defaults to today in Philippine time) and a registered
  collecting officer. Enter the office-assigned report number.
- Load the preview. Selection is based on `Payment.date_paid` within that
  calendar day, never `created_at` or `posted_by`. Thus an October 18 OR encoded
  October 19 belongs to the October 18 report.
- The booklet range determines the collecting officer. Correctly assigned
  receipts belonging to other officers are excluded and counted separately.
- Missing/ambiguous assignments, ORs before booklet issuance, unsupported OR
  identities and the same physical OR under different receipt dates block a
  complete export. Unassigned entries for the date must be reviewed before
  asserting that an officer's report is complete.
- One physical OR with several same-day property/payment entries appears once
  in the receipt list, with all supporting payment IDs and combined cash. This
  does not assert that duplicate encoding is genuine; staff must review source
  receipts. No record is automatically deleted or repaired.
- Receipt ranges are split at gaps and booklet boundaries. No missing or
  cancelled receipt is invented between the first and last recorded OR.
- The exporter rebuilds the data and checks the preview signature. Changes to
  payments, rates or the register require a fresh preview instead of a stale
  export. The workbook's date and amounts are fixed snapshot values.

## Amounts and limitations

Recorded `Payment.amount` is already cash net of recorded discounts and
inclusive of recorded penalties. The report does not calculate a new charge
or apply today's interest/discount rules to an old receipt.

Fund allocation reuses the existing RCD receipt-component method: linked tax
years, their configured Basic/SEF rates, and the existing equal-share convention
for multi-year recorded adjustments. A missing rate configuration blocks the
daily report; an equal fund split is not invented as a fallback. Equal rates
normally produce matching amounts, but cent rounding or genuinely unequal
configured rates are not forcibly overwritten. Office review against official
receipts is still required, especially for historical per-year adjustments.

This phase automatically completes **collections, reviewed cash/check and
full-handover amounts, and reviewed physical-stock arithmetic**, not every field
of an accepted official RCD. Payments alone do not establish the complete physical
booklet-stock history, cancellations, actual cash/check mix, opening custody
balance or actual remittance acceptance. Draft status is shown in the app and
supporting sheet. Unknown amounts stay blank, not zero.
No bank deposit is assumed to be the same event as remittance to the liquidating
officer. No automatic signature, acknowledgment or COA certification is made.

## Receipt stock and cancelled/spoiled forms

The Receipt stock tab is report-only. It does not cancel a Payment or write a
financial correction. Register assignments are the one-time source of actual
booklet boundaries and officer ownership. For each daily report:

1. Identify the official stock log / prior RCD reference. Enter every unused
   opening range actually held before the OR date, including idle booklets.
   Do not include previously exhausted, returned or transferred stock. The app
   does not infer that all historic registered booklets remain unused.
2. Select full 50-OR booklets actually received on the OR date. Their registered
   issue date must match. A booklet cannot be both opening and received stock.
3. Record each actual cancelled/spoiled serial, status, reason and log reference.
   Explicitly confirm that the original and duplicate copies are retained for
   RCD submission. No cash amount is entered for these forms.
4. Confirm completeness against the office log. The draft calculates
   `opening + received - paid ORs - listed cancelled/spoiled ORs = unused ending`.
   Section C's issued/used ranges include paid and listed cancelled/spoiled
   serials, while collection totals remain from recorded payments only. The
   supporting sheet separately identifies every cancellation at zero collection.

The same physical-stock series is shown on 100 and 200. These are two fund
presentations, not two independent physical issuances. Gaps and booklet bounds
remain separate. More than six stock rows blocks export without stretching
ranges or dropping forms; an office-approved continuation convention is not yet
implemented.

Before a reviewed export the server checks claimed unused stock against saved
payment history. Earlier/undated usage blocks it. A saved payment under any date
blocks a proposed zero-collection cancellation, including zero-value payments.
Future use is permitted for a genuine historical ending balance, e.g. an OR
unused October 18 and used October 19. No conflicting payment is edited/deleted.
The stock declarations are included in the export audit and review hash; this is
not a persistent, accepted daily-stock ledger or an automatic carry-forward.

The office must review the issued/used presentation and supporting cancellation
list in its genuine pilot. Retained cancelled copies are not destruction or
relief evidence. BLGF's *Local Treasury Operations Manual, Book 2* (2nd edition,
printed pp. 109-110) directs that cancelled original/duplicate non-fixed-value
forms, including AF 56, accompany the RCD with cancellation noted. See
https://blgf.gov.ph/wp-content/uploads/2022/10/LTOM-Book-2-E-Copy.pdf .
This implementation and the office's accepted print layout do not constitute a
COA certification, approval of a stock write-off, or approval of legal compliance.

## Server schema and safety

Three additive tables hold collecting officers, immutable booklet assignments
and a singleton revision/locking row. The approved server migration entrypoint
creates and validates them. Reads never create or repair schema. The register
POSTs and their audit events commit in the same transaction; an audit failure
rolls back the registration. A MySQL row lock serializes range registrations.

There is no payment/billing column change, no historical data backfill, and no
financial write from preview/export. The existing export audit mechanism is
retained. The desktop only calls authenticated APIs and contains no server DB
access. Source publication and a versioned build are not production activation
or certification. Deploy only through the separately approved maintenance
workflow; do not rerun an old release helper to activate unversioned changes.

## v2.1.21 release and pilot

The immediate supported predecessor is finalized v2.1.20. The existing owned
R4 publisher is reapproved for the new immutable source through the same guarded
workflow; its four daily triggers, historical tools/intents and other tasks are
preserved. Source publication/build does not run that server workflow.

After a fresh backup, the approved updater adds only the three RCD register
tables. It does not alter Payment/Billing columns, backfill officer ownership or
infer a stock balance. Schema rollback is not an instruction to drop these new
tables or their audit history. Preserve the original workbook and all old release
evidence. The approved blank layout contains no macros, original entered
receipts, signatures or personal workbook values.

Before accepting the installed client, review these cases privately against
existing official records. Use an isolated synthetic environment for cases not
present in genuine office records. Never create fake production payments:

- Both 100 and 200 match the accepted original print geometry and paper settings.
  Report number and collecting officer are correct. OR date, including a
  backdated receipt encoded later, is not replaced by encoding/deposit date.
- Actual 50-OR booklet bounds, prefixes and leading zeros match the issuance log;
  the collector is its recorded owner, not the encoder. Include idle unused stock.
- Collections, Basic/SEF portions and all cash/check allocations tally with the
  official receipts. A whole check covering several ORs appears once in the
  form's check list; no amount is guessed or counted twice.
- Opening/received/issued/ending stock reconciles on every printed row.
  Cancelled/spoiled ORs are separately noted at zero collection, with copies
  retained for submission. Review this issued/used convention with the office's
  liquidating officer. Missing serials are never silently classified as cancelled.
- Blank opening cash is not zero. An actual full handover is distinct from the
  receiving officer's acknowledgment and the next morning's bank deposit.
  No unverified signature, bank evidence or received amount is auto-filled.
- Changed date/officer/source disables a stale export. More than six collection
  or stock ranges or nine checks blocks without omitting records. Corrections to
  a mistakenly registered booklet, partial booklet transfers and persistent
  accepted-stock carry-forward need a separate audited workflow; do not edit SQL.
- Existing Collection, Receivables, Barangay, Reconciliation and period RCD
  Excel/PDF workflows continue to work. Verify minimum-window size, scaling and
  response time on the actual client/server; hidden local Tk/SQLite tests are
  not a MariaDB concurrency, office performance or installed-client pilot.

Return `V2.1.21 DAILY RCD PILOT PASS` only after the genuine pilot and evidence
review pass. Then Finalize the same WorkflowId, not a second activation. This
does not certify the whole app as COA-compliant.
