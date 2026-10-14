# Reports accuracy correction

## Scope

This changes Collection, RPT Receivables Summary, Receivables by Barangay, and Reconciliation. It also corrects the shared aggregation of receipt penalties/discounts used by billing calculations.

It does not change tax rates, discount eligibility, or the monthly penalty policy. It contains no database migration, mass recalculation, automatic historical repair, secret rotation, or scheduled-task change.

## Report definitions

- `Payment.amount` is the cash received, including penalty and net of discount. Never add penalty or subtract discount a second time when reporting cash.
- The collection register and COA RCD include genuine recorded cash even when the related property was subsequently removed from the registry. A property deletion is not a cancellation of a receipt.
- Receivables retain the current non-deleted-property scope. Selected-year views include available billing years through the fiscal year and apply receipt-date cutoffs at December 31. They are reconstructed from current stored yearly assessments and recorded adjustments, not immutable archived statutory year-end statements.
- These are recorded-charge reports, not live SOA accrued-interest estimates. An SOA calculated for today's date can legitimately differ.
- Earlier prepayments applied to the current tax year are separate from cash received in the fiscal year. Future-year prepayments are excluded from that year's receivables equation.
- Positive receivables and credits are separate. A credit on one billing/account does not settle another account's debt.
- Prior-year adjustment movements and changes in credit balances are explicit roll-forward lines.
- Older receipts contain only total penalty/discount, not exact year-specific adjustments. Use the existing equal-share convention across linked billing rows, with deterministic cent remainders. This is a disclosed application convention, not recovered official per-year evidence.
- A receipt with nonzero adjustment cannot include selected years receiving no cash allocation. Remove unallocated years or post those years separately. The operation must roll back on rejection. Multi-year partial payments that allocate cash to every selected year remain supported.

## Reconciliation status

`BALANCED` requires equation/tracker agreement to the cent, no cash/allocation difference, no detected receipt-link or sequence problems, no undated stored adjustments, and no positive receipts with missing dates. This remains a working-paper check, not production certification or statutory sign-off.

Cash received includes closed accounts; cash applied to active receivables does not. Closed-account cash is reported separately. Timing differences and genuine credits can be valid. Do not delete genuine receipts, force their dates, or invent billing rows to make a status turn green.

All report components are read in one repeatable-read transaction. Diagnostic counts cover the full issue population even when screen detail is sampled. Full exports request complete details and the PDF no longer stops at 40 rows.

## Export and UI corrections

- COA cash totals and current/prior principal classifications follow stored cash and actual billing allocations. Basic/SEF splits use the relevant configured yearly rates.
- Ambiguous mixed-year RCD receipts without adequate allocations fail with an actionable error.
- The generic collection Excel export uses the actual eight-field collection schema and fetches every cursor page. It no longer treats a username as a number or stops at 500 records.
- Receivables Excel and screen include prepaid credits and separate credit movements.
- Barangay screen/Excel/PDF use fiscal cutoffs and expose separate credits. The legacy backend billing-year service default remains available for compatibility.
- Stale asynchronous responses cannot overwrite a newer request. Pagination cannot skip ahead while a request is pending. Failed collection/barangay loads clear older visible results.
- The RCD All/All filter covers all recorded receipt dates instead of substituting the current year. A specific month with All years requires a year selection because the RCD/deposit workflow uses a contiguous date range.
- Barangay exports retain direct references to the real buttons for feedback/disable behavior.
- Fixed-format report buttons must offer only their selected format in the Save dialog: Excel means `.xlsx`, PDF means `.pdf`. The client copies the generated document; changing the Save-as filter never converts its bytes. A mismatched generated or destination extension must be rejected, and cancel/save failures must restore the export button.
- Reconciliation PDF tables wrap the equation, retain complete diagnostic detail, escape untrusted text, and carry page numbers. Barangay PDF columns fit landscape A4.
- Untrusted taxpayer/bank/username strings remain literal in Excel. Trusted COA total formulas are preserved. Empty COA detail exports use numeric zero totals, not circular formulas.

## Read-only impact review

The helper `scripts.review_reports_accuracy_impact` reports counts only. It does not disclose names, TD/OR numbers, credentials, or financial row data. It never rewrites a prior report or financial record and refuses to overwrite an existing output file.

Its counts identify cached adjustment drift, missing or unbalanced links, cross-account links, missing receipt dates, undated billing adjustments, and multi-year adjustment receipts needing convention review. A flagged count is not proof that every flagged record is wrong.

Use the helper only after its source is supplied through an approved, verified release/staging process. It is not present in the old installed source and must not be copied piecemeal into the production checkout. On the intended API server, the eventual invocation is:

```text
python -m scripts.review_reports_accuracy_impact --output logs/reports-accuracy-impact-UNIQUE-RUN-ID.json
```

Exit 2 means `REVIEW_REQUIRED`, not a request to repair data. `NO_FLAGGED_CASES` is also not a production certificate. Return only the aggregate JSON for review. Keep private receipt evidence on the office system.

## Rollout requirements

1. Publish/review the source and pass CI only with explicit authorization. Assign and build a new release version; do not distribute a changed executable as the old v2.1.17.
2. Perform the aggregate impact review using verified staged tools/source. Review the legacy allocation convention and date/source limitations with the responsible operator/accounting reviewer.
3. Any proposed historical cache or allocation repair needs a separate plan, verified backup, retained original evidence, audit treatment, and explicit approval. This change contains no such repair.
4. Use the existing guarded release workflow in an approved maintenance window, with financial entry paused and a fresh backup/baseline. Coordinate the new source approval for the owned portal publisher; do not edit its approval files to bypass identity checks.
5. Update the server before installing the new verified client. New UI report consistency depends on the new report-payload endpoint. Use Copy, not Cut, when distributing the installer, preserving the server package.
6. Pilot using existing known receipts/accounts and private official evidence. Do not post fake production payments to test the reports. Check cash with penalties/discounts, prepayments, multiple years, separate credits, duplicate-account isolation, export completeness, and historical cutoffs.
7. Complete automated checks and manual acceptance for the same workflow. Do not bypass a blocked financial comparison or delete a genuine collection to obtain PASS.

Normal receipt posting can refresh cached billing totals for the affected billing rows, as it already did before this change. The corrected aggregation applies there too. No activation step silently recalculates the entire historical database.

## Reading the receivables indicators

`Applied Cash/Credit Coverage` belongs to the RPT Receivables Summary, not the Collection register. It is `(cash applied to active current/prior-year receivables in the selected fiscal year + earlier payments allocated to that year's billings) / (beginning receivable + net current collectible + prior-year/credit movements) * 100`. It is not the percentage of taxpayers paid, a current-year-only cash collection rate, or proof of reconciliation. Future-year payments are excluded from this coverage numerator.

`Separate Credit` aggregates positive excesses of recorded paid amounts over recorded charges on individual billing rows within the selected report cutoff. It is kept separate from positive debt: a credit on one account/year does not automatically pay another account/year's balance. It is not a discount, new revenue, an approved refund, or proof that an overpayment was intentional. Overpayments, timing/adjustment effects, and incorrect amounts or allocations require review against official evidence before any correction or transfer.

The Reports wording hotfix labels these same values `Receivables Coverage (including advance payments)` and `Recorded Credit Balance`. Screen guidance and Excel/PDF credit headings use the shared plain-language labels; calculations, payload keys, fiscal cutoffs and recorded values remain unchanged. The long PDF credit heading wraps without reducing the font size. This hotfix must be delivered as a new immutable release, not an edited v2.1.18 package.

The v2.1.18 workflow holds the existing publisher byte-range mutex during source activation, then explicitly reapproves v2.1.18 for the immutable R4 transport. It requires the previously verified v2.1.17 bridge, keeps that original migration intent unchanged, uses a separate release-specific intent and evidence folder, and tests both a demand-only SYSTEM task and the real daily publisher. Its four triggers and unchanged action are preserved. Verify/Finalize recognize an already completed reapproval without uploading again. Approval remains an operator prompt, not a release HTTP parameter.

The v2.1.19 wording/export-dialog hotfix follows the same guarded workflow from v2.1.18. It requires the exact v2.1.18 tag, source approval, and verified `app-bridge-migration-v2.1.18.json`, and writes only its own v2.1.19 intent and new evidence. Interrupted reapproval accepts only the verified previous approval or the explicitly approved current version. The v2.1.18 installer, tag, workflow, baselines and old evidence remain untouched; an unfinished v2.1.18 pilot is not silently certified. No report mathematics, receipt values, historical cutoffs, tax policy, API compatibility or minimum client version change in this hotfix.

Pilot v2.1.19 with genuine existing records, without creating test production payments. Check the RPT Receivables and Barangay Excel buttons open `.xlsx`-only Save dialogs, the PDF buttons open `.pdf`-only dialogs, cancellation restores each button, and saved files open in their intended applications. Compare amounts to the same report/year before the upgrade and verify the clearer coverage/credit guidance. Keep financial entry paused through final comparisons and manual acceptance, then resume only after the workflow passes.

## Validation boundaries

Regression tests use synthetic in-memory databases and actual export functions. Excel output is inspected and rendered, and PDF output is rendered and extracted. The synthetic performance benchmark uses FK-equivalent indexes in SQLite; it is not a MariaDB production performance certification. The real server, native Excel pilot, historical impact population, and release activation require subsequent verification.
