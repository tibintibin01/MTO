# Design Document

## Overview

Phase 4 adds a reporting layer and dashboard interactivity on top of data the
backend already computes. The guiding principle is **single computation path**:
the UI and exports read from the same service functions that already exist
(`get_rpt_receivables_summary`, `get_collections_worklist`,
`get_receivables_by_barangay`, `get_report_details`, `get_assessment_roll`,
`get_delinquent_accounts`). No financial math is reimplemented.

Three thin additions are needed:
1. A small extension to the existing Excel exporter to add a `receivables`
   report type (so the COA statement can be exported through the one export
   endpoint).
2. A CSV formula-injection guard helper (shared, used by all CSV exports).
3. A `recharts` dependency for real charts.

Everything else is frontend composition over existing endpoints.

### Design Goals
- Reuse existing endpoints/services; avoid duplicate computation.
- No new mutation endpoints; reporting is strictly read-only.
- No mock-data fallbacks; explicit error states.
- Rates always via `TaxPolicy` shared helpers.
- Verifiable: backend tests + `tsc --noEmit` + `next build`.

### Confirmed Decisions
- **COA statement export = Excel**, via a new `receivables` report type on the
  existing `/billing/export/excel` endpoint (consistent with the auditor-facing
  export path; single export surface).
- **Charting library = Recharts** (React-native, responsive container,
  SSR-friendly with Next 14 client components, small footprint).
- **Barangay drill-down destination = `/admin/collections?barangay=<name>`**
  (the collections worklist already supports a barangay filter).

## Architecture

```
                         /admin/reports  (hub)
                                │
        ┌───────────────┬───────┴────────┬─────────────────┐
        ▼               ▼                ▼                 ▼
 RPT Receivables    Aging Report   Receivables/Brgy   Collections /
 (year select)      (brgy filter)  (year select)      Assessment / Delinquents
        │               │                │                 │
        ▼               ▼                ▼                 ▼
 GET /billing/      GET /billing/   GET /reports/      GET /billing/report-details
 receivables-       collections     receivables-       GET /billing/assessment-roll
 summary?year=      (aging_totals)  by-barangay        GET /billing/delinquents
        │                                                  │
        └──────────────── Export ──────────────────────────┘
                                │
                POST /billing/export/excel
                {report_type: collections|delinquents|
                 assessment_roll|receivables}        (+ client-side CSV for aging)
```

Dashboard drill-downs are pure client-side navigation (`router.push`) into
existing pages with query params; no new endpoints.

## Components and Interfaces

### Backend

#### B1. Excel exporter — add `receivables` report type
**File:** `backend/routes/billing.py` (`export_billing_excel`)

- Extend `ExportReportRequest.report_type` to accept `"receivables"`.
- When `report_type == "receivables"`: call
  `bill_svc.get_rpt_receivables_summary(data.year, db_session=...)` and write a
  single-section sheet:
  - Title row: "MUNICIPAL TREASURY OFFICE — RPT RECEIVABLES STATEMENT"
  - Subtitle: `Report Year: <year>   Generated: <UTC timestamp>`
  - Rows: Beginning Receivable, Current-Year Assessment, Collections,
    Adjustments, Ending Receivable — label column + peso-formatted value column.
- Reuses the same styles (`header_fill`, `currency_fmt`, `auto_width`) already
  defined in the function.
- No change to existing report types.

#### B2. CSV formula-injection guard (shared helper)
**File:** `utils/sanitizer.py` (new function `csv_safe_cell`)

- Signature: `csv_safe_cell(value: Any) -> str`.
- If the stringified value begins with one of `= + - @ \t \r`, prefix with a
  single quote (`'`) so spreadsheet apps do not interpret it as a formula.
- Used by any server-side CSV building. (Client-side CSV in React is lower risk,
  but the aging CSV will apply the same neutralisation inline.)

#### B3. No new query functions required
All read endpoints already exist:
- `/billing/receivables-summary?year=` → roll-forward
- `/billing/collections?barangay=&min_age_days=` → `summary.aging_totals`
- `/reports/receivables-by-barangay?year=`
- `/billing/report-details`, `/billing/assessment-roll`, `/billing/delinquents`

### Frontend

#### F1. Reports hub — `/admin/reports/page.tsx` (new)
- Card grid of report definitions: `{ id, title, description, formats[], href }`.
- RPT Receivables, Aging, Receivables by Barangay link to detail report views;
  Collections / Assessment / Delinquents offer direct Excel export buttons that
  POST to `/billing/export/excel`.
- Uses the established admin dark theme and `apiFetch` patterns
  (`credentials: "include"`, `X-Requested-With`).

#### F2. RPT Receivables report — `/admin/reports/receivables/page.tsx` (new)
- Year `<select>` (default current year).
- Fetches `/billing/receivables-summary?year=`.
- Renders the five roll-forward lines, peso-formatted, with an explicit error
  state (no zero fallback).
- "Export Excel" button POSTs `{report_type:"receivables", year}` to
  `/billing/export/excel` and downloads the blob.

#### F3. Aging report — `/admin/reports/aging/page.tsx` (new)
- Barangay `<select>` (from `/properties/barangays`, plus "All").
- Fetches `/billing/collections?barangay=` and reads `summary.aging_totals` +
  `summary.total_balance`.
- Table: bucket | amount | % of total. "Export CSV" builds the CSV client-side
  with formula-safe cells.

#### F4. Charts — `frontend/app/components/RevenueTrendChart.tsx` (new)
- Client component wrapping Recharts `ResponsiveContainer` + `BarChart`
  (or `LineChart`) for the monthly trend.
- Props: `data: {month: string; total: number}[]`.
- Renders an explicit empty state when `data.length === 0`.
- Peso formatter for Y axis + tooltip.

#### F5. Dashboard drill-downs — `frontend/app/admin/dashboard/page.tsx` (edit)
- Wrap the "Active Delinquencies" figure (currently `summary.active_delinquencies`
  — note: confirm it is rendered; if absent, surface it) in a button/link to
  `/admin/collections`.
- Make each barangay row a keyboard-operable button navigating to
  `/admin/collections?barangay=<name>`.
- Replace the hand-built trend `<div>` bars with `<RevenueTrendChart>`.
- Add `cursor-pointer`/hover only to interactive elements.

#### F6. Collections page — read `barangay` query param
**File:** `frontend/app/admin/collections/page.tsx` (edit)
- On mount, initialise `selectedBarangay` from `?barangay=` if present so
  dashboard drill-down lands pre-filtered.

#### F7. Navigation + middleware
- Add "Reports" to the admin sidebar (`frontend/app/admin/layout.tsx`).
- Add `/admin/reports` to `PROTECTED_PREFIXES` in `frontend/middleware.ts`.

## Data Models

No schema changes. Response shapes consumed (already produced by the backend):

```
ReceivablesSummary {
  report_year: int
  beginning_receivable: float
  current_year_assessment: float
  collections: float
  adjustments: float
  ending_receivable: float
}

CollectionsSummary.summary {
  delinquent_count: int
  total_balance: float
  aging_totals: { CURRENT, "30", "60", "90", "120+": float }
}
```

## Error Handling

- Each report view has three states: loading, error (explicit message + retry),
  loaded. No fabricated/sample rows on error (NFR-5).
- Export failures: surface a toast/error and do not trigger a download of an
  empty blob (R6.4). Check `res.ok` before reading the blob.
- 401 on any report fetch → redirect to `/admin/login` (existing pattern).

## Security Considerations

- All report endpoints stay behind auth; `export/excel` and `collections` are
  `read_only`-gated; no new mutations (NFR-1).
- CSV/Excel: `csv_safe_cell` neutralises formula-injection in untrusted text
  cells (owner names, locations) (NFR-2).
- Heavy Excel build already runs via `asyncio.to_thread` (NFR-3) — the new
  `receivables` branch inherits this.

## Testing Strategy

### Backend (pytest, SQLite in-memory)
- `csv_safe_cell`: leading `= + - @`, tab, CR are neutralised; safe values
  untouched.
- Excel `receivables` export: returns non-empty `.xlsx` bytes for a year with
  billing data; figures equal `get_rpt_receivables_summary` for the same year
  (single computation path, R6.1).
- Regression: existing export types (`collections`, `delinquents`,
  `assessment_roll`) still build.

### Frontend
- `tsc --noEmit` passes.
- `next build` passes with `recharts` added (R5.4).
- Manual/visual: empty-trend renders the no-data state; drill-down lands
  pre-filtered.

## Dependencies

- Add `recharts` (pinned) to `frontend/package.json`.
- No new Python dependencies (`openpyxl` already present).

## Correctness Properties

These are invariants the reporting layer must hold, suitable for property-style
and example-based tests.

### Property 1: Single computation path
For any year Y, the RPT receivables figures shown on screen and in the Excel
export SHALL equal `get_rpt_receivables_summary(Y)` field-for-field. No
alternate arithmetic exists in the report or export code paths.

**Validates: Requirements 2.1, 6.1**

### Property 2: Roll-forward identity
`ending_receivable == beginning_receivable + current_year_assessment -
collections + adjustments` (within float tolerance), for any year. The export
SHALL NOT alter this relationship.

**Validates: Requirements 2.1, 2.4**

### Property 3: Aging partition
The sum of the `aging_totals` buckets SHALL equal `total_balance` (within
rounding tolerance) for any barangay filter — the buckets partition the
outstanding balance, never overlapping or dropping amounts. (Already asserted in
`test_collections.py`; the aging report SHALL NOT break it.)

**Validates: Requirements 3.1, 3.2, 3.5**

### Property 4: CSV injection safety
For any input string `s`, `csv_safe_cell(s)` SHALL begin with `'` whenever `s`
begins with `=`, `+`, `-`, `@`, tab, or carriage return; and SHALL return `s`
unchanged otherwise.

**Validates: Requirements 3.4, 7.2**

### Property 5: No fabrication on error
When a source endpoint errors, the rendered figure set SHALL be empty/error —
never a synthesized non-empty dataset.

**Validates: Requirements 2.5, 7.5**

### Property 6: Rate provenance
Any tax amount appearing in a report SHALL derive from `TaxPolicy` via the shared
rate helpers; there SHALL be no literal `0.02` or `0.01` introduced in Phase-4
code paths.

**Validates: Requirements 7.4**



