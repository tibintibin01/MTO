# v2.1.23: year-aware dashboard TD counts

This change is a read-only display calculation. It does not delete, archive,
deactivate, update or repair any TD, payment, allocation, assessment or billing.
No schema migration, billing computation or scheduled activation job is added.
The existing TD records and links remain the source of historical tracing.

## Status definitions

All counts are **property account / TD record IDs**, not deduplicated TD-number
strings and not a claim about the number of physical parcels. Separate valid
accounts sharing a TD remain distinct. Status is not payment/compliance status.

- **Active:** effective for the current Philippine tax year and not replaced by
  an effective successor. Missing or unsafe lineage is not guessed.
- **Inactive / replaced:** a retained predecessor with an effective, safely
  linked successor. It is not moved into Archive or deleted.
- **Future-effective:** a known TD whose effectivity tax year has not arrived.
- **Archived:** a record already in the application's Archive (`deleted_at`).
  This feature does not put any record there.
- **Needs review:** no recognizable effectivity/tax year or usable own assessment
  history; or an ambiguous, self-referential, cyclic, mismatched or chronologically
  inconsistent predecessor link. No record is repaired to resolve this count.

These five categories partition all stored property records. The response also
reports registered (non-archived) records and total records. External Previous TD
references without a local record are permitted and counted separately as a
diagnostic, not invented as local predecessors. Multiple matching legacy Previous
TD records require review; an explicit Previous Property ID disambiguates them.

For a correctly linked one-for-one replacement encoded in 2026 but effective in
2027: 2026 has one Active and one Future; 2027 has one Active and one Inactive /
replaced. Both TDs stay stored. A genuine one-to-many split may instead increase
the active-record count; the code does not force every change to net zero.

An older assessed-value snapshot on a **new replacement TD** must not backdate
that TD's effectivity. A linked future TD with earlier history is **Needs review**
along with its possible predecessor until the recorded replacement year: the
existing fields cannot prove whether the history is copied prior AV or that
same TD's earlier existence. An undated successor also makes its possible parent
uncertain. An existing TD with no predecessor can use its own older assessment
history to remain active before a later revaluation. No new issuance dates or
historical identity are inferred from row creation/update timestamps.

## API and compatibility

`get_dashboard_summary` adds `property_status_counts` format version 1. It reads
only property metadata and positive-assessment history years with autoflush
disabled. It never commits or invokes billing, payment or archive operations.
Only aggregate counts leave the service, not TDs, owners or property identifiers.

The existing `total_properties` cached API field retains its registered-record
meaning for compatibility. The updated desktop's Active Properties headline
uses only the new validated year-aware contract. It does not silently fall back
to the old registered-record total. Missing or inconsistent status data shows an
unavailable message and a dash, not a misleading active count.
Both the server and client must be updated: an older v2.1.22 desktop still uses
the legacy total. Updating the server alone does not correct that older card.

Status is recomputed on each dashboard refresh independently of the legacy
five-minute statistics cache. January rollover follows Philippine time and
requires no property mutation or new job. The year is visible in the status strip.

## Verification and rollout boundary

Tests must cover 2026/2027 rollover, duplicate-account isolation, explicit and
legacy links, splits/chains, archived records, malformed/ambiguous lineage,
historical valuations, old-server responses and no database writes. Existing
dashboard collections, receipt dates, reports and financial tests must still pass.

The reviewed predecessor is finalized v2.1.22, source
`f76169d6d8e8510ed471ddbbd4017b779a090e42`. The v2.1.23 source, guarded publisher
transition, server tools and client must be packaged as a new immutable release.
The four daily publisher triggers and original R4 evidence remain unchanged.
No re-deployment or alteration of the v2.1.22 package is needed or permitted.

Publishing and building this new release were authorized. Production deployment
still needs an approved maintenance window, fresh backup/baseline, automated
gates, genuine installed-client count/trace/history and existing RCD/Reports
pilot, and final acceptance. Do not delete old TDs, repair lineage merely to
make the totals match, or change taxes/backup/retention policy as part of this
release. Keep all old release, publisher, workflow and correction evidence.
