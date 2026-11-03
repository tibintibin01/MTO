# Property payment-history metadata compatibility - v2.1.25

The v2.1.24 pilot exposed a report-serialization error on an existing database
whose `properties.effectivity_date` is a native SQL `DATE`. The ORM declares
this field as `String`, but the driver can still return a Python `date`.
Payment History put that value directly in its metadata and then passed the
payload to `json.dumps` to calculate its preview/export fingerprint. That
raises `TypeError` before the preview can be returned.

The issue was reproduced with a database-enforced read-only office diagnostic
on November 3, 2026, then with synthetic native-driver fixtures. This is not a
billing discrepancy and needs no data repair or column migration. The earlier
bounded exact-route log search did not find it; the broader review reported two
unmatched-route `TypeError` events, without proving their historical origin.

The narrow fix converts only native effectivity `date`/`datetime` metadata to
ISO text before calculating the fingerprint. It preserves existing text,
datetime precision and timezone information. The stored effectivity value,
previous-account chronology, receipt dates, financial amounts, allocations,
receipt records and audit records are unchanged.

Regression coverage uses real DBAPI native DATE/TIMESTAMP conversion while the
model stays String. It checks authenticated preview, PDF/Excel responses,
stable/review-sensitive fingerprints, selected-account isolation, archived
previous-TD sections, multi-year payment counting and unchanged financial rows.
This does not replace a genuine installed-client pilot after a separately
approved versioned deployment. Do not edit the immutable v2.1.24 release or
finalize its failed pilot to bypass the defect.

The v2.1.25 release advances only the product identity and explicit immediate-
predecessor publisher/workflow allowlists alongside this fix. It requires the
verified v2.1.24 source/bridge and preserves the exact unfinished v2.1.24 pilot
workflow and financial-correction evidence. Unreviewed future releases remain
rejected. Runtime/development/site dependencies, schema, calculations, backup
policy, credentials, risk acceptance and original R4 transport are unchanged.
