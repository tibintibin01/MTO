# v2.1.22: daily RCD stock-history DATE compatibility

## Defect and bounded fix

The v2.1.21 reviewed daily Excel export validates the claimed unused OR stock
against saved payment history. The ORM declares `Payment.date_paid` as DATETIME,
but legacy MariaDB DATE columns can return Python `datetime.date` objects.
Comparing those directly with a `datetime.datetime` midnight boundary raises
`TypeError`. The route then rolls back and returns its generic HTTP 500 without
releasing a workbook. Ordinary SQLite DATETIME tests did not cover this native
driver representation.

The failure was reproduced with DATE-shaped rows against the original validator,
including the POST export route returning the same generic HTTP 500. This is a
confirmed compatibility defect; reproduction is not a capture of the original
office server's exception or proof that no other export failure is possible.

The fix compares the recorded calendar day of either native DATE or DATETIME
with the selected OR date. It does not shift receipt dates across time zones,
guess missing dates or parse arbitrary strings. Prior/undated use still blocks
claimed unused stock. Any saved payment, including a future-dated payment, still
blocks treating that OR as a zero-collection cancellation. Unsupported date
types fail closed with a validation error rather than an unhandled comparison.

No payment, allocation, amount, receipt identity, OR date, discount, penalty,
tax computation, printed form geometry, schema or website dependency changes
are included. Existing immutable booklet assignments and audit history remain.
Product identity and the release-specific guarded publisher transition advance
to v2.1.22 from v2.1.21; earlier release guards remain supported.

## Verification and office handoff

Regression coverage includes native DATE, naive/aware DATETIME, same/future and
prior calendar days, null/unsupported values, saved-payment cancellation blocks,
and real in-memory 100/200 workbook downloads through the reviewed POST route.
Driver-shaped synthetic rows are used where SQLite would normalize DATETIME;
tests do not connect to the office database or certify MariaDB concurrency.

The locked Python 3.11 local suite passed 1,206 tests (six existing warnings).
The focused pre-fix run reproduced the native DATE export as HTTP 500; the same
POST path now returns a readable 100/200 workbook with unchanged recorded cash.
Dependency-policy, desktop/server trust-boundary, critical lint and medium/high
backend security checks passed. CI/build and the actual installed-client pilot
remain separate gates; no office server was changed by these tests.

Build and distribute a new immutable v2.1.22 internal package after source checks
pass. Do not patch the running server, modify its schema to fit the ORM, replace
the v2.1.21 package, edit receipts to avoid the check or skip stock validation.

The intended predecessor is active v2.1.21 with its bridge verification intact.
Its daily-RCD pilot may remain incomplete because this bug blocked download.
Preserve its original workflow, baseline, register, private review/correction
evidence and all historical publisher tools. Do not falsely Finalize that pilot.
The hotfix uses a new workflow and fresh backup/baseline under an approved
maintenance window, then requires its own genuine installed-client RCD pilot
and Finalize. Version publication/build alone does not deploy or certify it.

Privately compare exported 100/200 forms with genuine receipts, booklet stock,
cash/check records and the accepted office print layout. Confirm no financial
records changed during the update. Review a historical date where later receipt
use is legitimate, as well as the selected daily report. Keep missing-date and
saved-payment cancellation safeguards intact; do not invent production test
receipts or cancellations. Existing Reports/PDF/Excel workflows must still pass.
