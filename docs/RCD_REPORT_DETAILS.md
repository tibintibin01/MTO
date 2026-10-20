# RCD report identity

These settings apply to the existing period-based RCD export. The separate
daily, booklet-owner-based 100/200 workflow is documented in
[DAILY_RPT_RCD.md](DAILY_RPT_RCD.md). Trust Fund (300) and the unrelated
denomination worksheet remain outside the current scope.

## Desktop export

- Report number is entered by the operator. No official sequence is invented.
  Leading zeroes, slashes and hyphens are retained as text.
- Accountable officer (preparer) defaults to the signed-in user's full name and
  can be changed before each export. It is separate from the existing signing
  liquidating officer and Municipal Treasurer fields.
- Report date defaults to the current Philippine date (UTC+08:00), independent
  of the desktop's configured time zone. An operator preparing an earlier
  report may select its date explicitly.
- The selected collection period continues to determine which receipts are
  included. Changing report identity or report date does not change that period.
- The date is exported as a fixed Excel date value, not `TODAY()`. Reopening an
  existing export does not change its date. A new export receives a new default.

## API and compatibility

`GET /reports/rcd` accepts optional `report_number`, `accountable_officer`, and
`report_date` (`YYYY-MM-DD`) query parameters. Existing clients can continue to
omit the new identity fields; omitted report dates use the current Philippine
date. New desktop exports require a report number and accountable officer.

Inputs are bounded to 64 and 120 characters, respectively, and reject control
characters. New identity cells are explicit text, including formula-like input.
No names, report numbers or default settings are written back to payment,
billing, user, or configuration records. The existing export audit event is
unchanged. These metadata-only settings do not require new database tables.
The separate daily workflow has an additive server-only register migration.
No tax computation, publication or scheduled-task change is included, and no
compliance certification is implied.
