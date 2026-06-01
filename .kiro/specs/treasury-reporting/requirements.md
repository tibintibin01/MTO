# Requirements Document

## Introduction

The MTO Treasury portal computes several authoritative figures (RPT receivables
roll-forward, per-barangay receivables, aging) but does not surface them in a
form treasury management and COA auditors can use. The admin dashboard shows
KPIs and a hand-built trend, but the KPIs are not drillable and the COA-standard
RPT Receivables statement is invisible in the UI.

This feature (Phase 4) adds a **Reports hub** that surfaces the standard
treasury reports with on-screen views and CSV/PDF export, surfaces the **COA RPT
Receivables statement**, adds an **aging report**, makes the **dashboard KPIs
and barangay rows drillable**, and replaces the hand-built trend bars with
**real charts**.

**In scope:** read-only reporting and dashboard navigation built on existing
computed data; one new charting dependency; CSV/PDF export of reports.

**Out of scope:** changing how balances/penalties are computed; new financial
write operations; payment posting; the desktop client.

## Glossary

- **RPT Receivables roll-forward**: Beginning Receivable + Current-Year
  Assessment − Collections (± Adjustments) = Ending Receivable. The COA-standard
  statement, already computed by `get_rpt_receivables_summary(year)` and exposed
  at `/billing/receivables-summary?year=`.
- **Aging bucket**: CURRENT / 30 / 60 / 90 / 120+ days, dated from Feb 1 of the
  earliest unpaid tax year (RA 7160), already computed by
  `get_collections_worklist()` and exposed at `/billing/collections`.
- **Reports hub**: a new `/admin/reports` page that lists and runs the standard
  treasury reports.
- **Treasury Admin**: staff with the `admin` role; needs COA statements and
  management dashboards.
- **Collections Staff**: staff acting on delinquent accounts; needs aging and
  delinquency reports.
- **Viewer/Auditor**: read-only role (`viewer`); needs standard reports and
  exports.
- **COA**: Commission on Audit (Philippines) — the audit body that consumes the
  receivables statement.

## Requirements

### Requirement 1: Reports Hub

**User Story:** As a treasury admin, I want a single Reports page listing all
standard treasury reports, so that I can find and run any report without hunting
across different admin screens.

#### Acceptance Criteria
1. WHEN an authenticated staff user navigates to `/admin/reports` THEN the system
   SHALL display a list of available reports: RPT Receivables, Aging Report,
   Receivables by Barangay, Collections Report, Assessment Roll, Delinquent
   Accounts.
2. WHEN the Reports page renders THEN the system SHALL show, for each report, a
   title, a one-line description, and the available export formats (CSV and/or
   PDF/Excel).
3. IF the current user's role is `viewer` THEN the system SHALL still allow
   access to all read-only reports (read_only gate).
4. WHEN a report requires a parameter (e.g. year, barangay) THEN the system
   SHALL present the parameter control before the report is run or exported.
5. WHEN the admin sidebar renders THEN the Reports hub SHALL be reachable from it
   and SHALL be guarded by the edge middleware like all other `/admin/*` routes.

### Requirement 2: COA RPT Receivables Statement

**User Story:** As a treasury admin, I want to view and export the RPT
Receivables roll-forward for a selected year, so that I can report to COA in the
expected format.

#### Acceptance Criteria
1. WHEN the admin selects a tax year on the RPT Receivables report THEN the
   system SHALL display Beginning Receivable, Current-Year Assessment,
   Collections, Adjustments, and Ending Receivable for that year, sourced from
   the existing `/billing/receivables-summary?year=` endpoint.
2. WHEN no year is selected THEN the system SHALL default to the current
   calendar year.
3. WHEN the figures are displayed THEN the system SHALL format all monetary
   values as Philippine pesos with two decimals and thousands separators.
4. WHEN the admin requests an export THEN the system SHALL produce a downloadable
   file (PDF or Excel) containing the same figures, the report year, and a
   generated-on timestamp.
5. IF the receivables-summary endpoint returns an error THEN the system SHALL
   display an explicit error state and SHALL NOT display fabricated or zero
   figures as if they were real.

### Requirement 3: Aging Report

**User Story:** As collections staff, I want an aging report that groups
outstanding receivables into CURRENT/30/60/90/120+ buckets, optionally by
barangay, so that I can prioritise and report on collection risk.

#### Acceptance Criteria
1. WHEN staff open the Aging Report THEN the system SHALL display total
   outstanding balance broken down by aging bucket, using the existing
   `/billing/collections` summary (`aging_totals`).
2. WHEN staff select a barangay filter THEN the system SHALL recompute the aging
   breakdown for that barangay only.
3. WHEN the aging report is displayed THEN the system SHALL show both the peso
   amount and the percentage of total receivable in each bucket.
4. WHEN staff request an export THEN the system SHALL produce a CSV of the aging
   breakdown including the filter context (barangay, generated-on date).
5. WHEN aging is presented THEN it SHALL use the Feb-1 RA 7160 dating already
   implemented server-side, AND the frontend SHALL NOT re-derive aging
   independently.

### Requirement 4: Dashboard Drill-Downs

**User Story:** As a treasury admin, I want to click dashboard KPIs and barangay
rows to jump to the underlying records, so that I can move from a number to the
list behind it without re-navigating.

#### Acceptance Criteria
1. WHEN the admin clicks the "Active Delinquencies" KPI THEN the system SHALL
   navigate to `/admin/collections`.
2. WHEN the admin clicks a barangay row in the dashboard's Barangay Contribution
   table THEN the system SHALL navigate to a collections or property view
   filtered to that barangay.
3. WHEN a KPI or row is interactive THEN the system SHALL present an affordance
   (cursor, hover state) indicating it is clickable, AND it SHALL be operable via
   keyboard (Enter/Space) for accessibility.
4. WHEN navigation occurs THEN the destination screen SHALL apply the passed
   filter (e.g. barangay query param) on load.
5. WHERE a KPI is non-interactive THEN the system SHALL NOT present a misleading
   clickable affordance.

### Requirement 5: Real Charts

**User Story:** As a treasury admin, I want the dashboard trend and efficiency
visuals rendered as proper charts, so that the data is easier to read than the
current hand-built bars.

#### Acceptance Criteria
1. WHEN the dashboard loads THEN the system SHALL render the monthly revenue
   trend as a chart (line or bar) using a charting library, replacing the
   hand-built `<div>` bars.
2. IF trend data is empty THEN the system SHALL render an explicit "no data"
   state rather than an empty or broken chart.
3. WHEN the chart renders THEN it SHALL remain readable on mobile widths
   (responsive container) AND SHALL NOT break the existing dashboard layout.
4. WHEN the charting library is added THEN it SHALL be a pinned dependency AND
   SHALL NOT regress the production build (verified by a successful `next build`).
5. WHEN monetary values appear on axes or tooltips THEN they SHALL be
   peso-formatted.

### Requirement 6: Export Integrity and Consistency

**User Story:** As an auditor, I want exported reports to match exactly what I
see on screen, so that I can trust the documents I submit.

#### Acceptance Criteria
1. WHEN a report is exported THEN the exported figures SHALL equal the on-screen
   figures for the same parameters (single computation path, no duplication).
2. WHEN an export is generated THEN the file SHALL include the report title, the
   parameter context (year/barangay), and a generated-on timestamp.
3. WHERE the existing `/billing/export/excel` endpoint already produces a report
   (collections, delinquents, assessment roll) THEN the Reports hub SHALL reuse
   it rather than duplicating export logic.
4. IF an export fails THEN the system SHALL surface a clear error AND SHALL NOT
   download an empty or partial file silently.

### Requirement 7: Non-Functional Requirements

**User Story:** As the system owner, I want reporting to be secure, consistent,
and verifiable, so that it is safe to rely on in production and during audits.

#### Acceptance Criteria
1. WHEN any report endpoint is called THEN the system SHALL require
   authentication AND SHALL NOT introduce new mutation endpoints.
2. WHEN CSV is generated from untrusted text THEN the system SHALL guard against
   spreadsheet formula injection (neutralise risky leading characters such as
   `= + - @`).
3. WHEN report queries run THEN they SHALL reuse existing indexed queries AND
   SHALL NOT introduce an unbounded full-table scan beyond what already exists;
   heavy file generation SHALL run off the event loop (thread).
4. WHEN tax amounts are computed for a report THEN rates SHALL come from
   `TaxPolicy` via the shared helpers, with no new hardcoded `0.02`/`0.01`
   literals.
5. WHEN a report or dashboard view encounters an error THEN it SHALL NOT fall
   back to fabricated sample rows (consistent with the Phase-1 integrity fix).
6. WHEN the feature is delivered THEN new backend logic SHALL ship with tests AND
   the frontend SHALL pass `tsc --noEmit` and `next build`.
