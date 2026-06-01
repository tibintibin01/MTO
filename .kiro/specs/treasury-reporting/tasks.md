# Implementation Plan

## Overview

Phase 4 delivers a reporting layer and dashboard interactivity over data the
backend already computes. Backend foundations (CSV guard, Excel receivables
export) come first because the frontend export buttons depend on them. Then the
charting dependency and component, then dashboard drill-downs, then the report
views and the hub, then navigation wiring, then final verification.

Each task is independently testable and cites the requirements it satisfies.

## Tasks

- [x] 1. Add CSV formula-injection guard helper
  - Add `csv_safe_cell(value)` to `utils/sanitizer.py` that prefixes a single
    quote when the stringified value starts with `=`, `+`, `-`, `@`, tab, or CR;
    returns the value unchanged otherwise.
  - Write unit tests in `tests/test_reporting.py` covering each risky leading
    character, tab/CR, and safe values left untouched.
  - _Requirements: 7.2, 3.4 (Property 4)_

- [x] 2. Add `receivables` report type to the Excel exporter
  - Extend `ExportReportRequest.report_type` to accept `"receivables"` in
    `backend/routes/billing.py`.
  - In `_build_workbook`, add a `receivables` branch that calls
    `bill_svc.get_rpt_receivables_summary(data.year, db_session=...)` and writes
    a roll-forward sheet (Beginning, Current-Year Assessment, Collections,
    Adjustments, Ending) with title, year, generated-on timestamp, reusing the
    existing styles.
  - Keep generation on `asyncio.to_thread` (already in place).
  - _Requirements: 2.4, 6.1, 6.2, 6.3, 7.3_

- [x] 3. Test the receivables Excel export (single computation path)
  - In `tests/test_reporting.py`, build an in-memory DB with billing rows for a
    year, call `get_rpt_receivables_summary(year)`, and assert the workbook
    builder embeds the same five figures (parse the produced `.xlsx` with
    openpyxl) — proving Property 1 / Property 2 hold through the export.
  - Add a regression assertion that `collections`/`delinquents`/`assessment_roll`
    still build without error.
  - _Requirements: 6.1, 2.1 (Properties 1, 2)_

- [x] 4. Add Recharts dependency
  - Add `recharts` (pinned version) to `frontend/package.json` dependencies and
    install.
  - Confirm `next build` still succeeds with the new dependency present.
  - _Requirements: 5.4_

- [x] 5. Build the RevenueTrendChart component
  - Create `frontend/app/components/RevenueTrendChart.tsx` as a client component
    wrapping a Recharts responsive bar/line chart.
  - Props: `data: {month: string; total: number}[]`; render an explicit
    "no data" state when empty; peso-format the Y axis and tooltip.
  - _Requirements: 5.1, 5.2, 5.3, 5.5_

- [x] 6. Wire charts and drill-downs into the dashboard
  - In `frontend/app/admin/dashboard/page.tsx`, replace the hand-built trend
    `<div>` bars with `<RevenueTrendChart data={data.trend} />`.
  - Surface an "Active Delinquencies" KPI (from `summary.active_delinquencies`)
    and make it navigate to `/admin/collections`; make each barangay row a
    keyboard-operable control navigating to
    `/admin/collections?barangay=<name>`. Apply clickable affordances only to
    interactive elements.
  - _Requirements: 4.1, 4.2, 4.3, 4.5, 5.1_

- [x] 7. Honor the `barangay` query param on the collections page
  - In `frontend/app/admin/collections/page.tsx`, initialise `selectedBarangay`
    from `?barangay=` on mount so dashboard drill-down lands pre-filtered.
  - _Requirements: 4.4_

- [x] 8. Build the RPT Receivables report view
  - Create `frontend/app/admin/reports/receivables/page.tsx`: year select
    (default current year), fetch `/billing/receivables-summary?year=`, render
    the five roll-forward lines peso-formatted, explicit error state (no zero
    fallback), and an "Export Excel" button POSTing
    `{report_type:"receivables", year}` to `/billing/export/excel` with a guarded
    blob download.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 6.4 (Property 5)_

- [x] 9. Build the Aging report view
  - Create `frontend/app/admin/reports/aging/page.tsx`: barangay select (from
    `/properties/barangays` + "All"), fetch `/billing/collections?barangay=`,
    render bucket | amount | % of total, and an "Export CSV" button building the
    CSV client-side with formula-safe cells and filter context.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 10. Build the Reports hub page
  - Create `frontend/app/admin/reports/page.tsx`: card grid of the six reports
    with title/description/formats; RPT Receivables, Aging, Receivables-by-
    Barangay link to detail views; Collections / Assessment / Delinquents offer
    direct Excel export buttons (guarded blob download).
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 6.3, 6.4_

- [x] 11. Add Reports to navigation and route protection
  - Add a "Reports" item to the admin sidebar in
    `frontend/app/admin/layout.tsx`.
  - Add `/admin/reports` to `PROTECTED_PREFIXES` in `frontend/middleware.ts`.
  - _Requirements: 1.5_

- [x] 12. Verify the full feature
  - Run the backend test suite (`pytest`) — all existing + new reporting tests
    pass.
  - Run `tsc --noEmit` and `next build` for the frontend — both succeed with
    Recharts and the new routes.
  - _Requirements: 7.6_

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": "A", "tasks": ["1", "2", "4"], "dependsOn": [] },
    { "wave": "B", "tasks": ["3", "5"], "dependsOn": ["A"] },
    { "wave": "C", "tasks": ["6", "8", "9"], "dependsOn": ["A", "B"] },
    { "wave": "D", "tasks": ["7", "10"], "dependsOn": ["C"] },
    { "wave": "E", "tasks": ["11"], "dependsOn": ["D"] },
    { "wave": "F", "tasks": ["12"], "dependsOn": ["B", "D", "E"] }
  ]
}
```

Visual reference:

```
1 (csv guard) ─────────────► 9 (aging report uses formula-safe CSV)
2 (excel receivables) ─► 3 (export test)
2 ───────────────────────► 8 (receivables view exports via this)
2 ───────────────────────► 10 (hub export buttons)
4 (recharts dep) ─► 5 (chart component) ─► 6 (dashboard wiring)
6 ─► 7 (collections reads ?barangay= from drill-down)
8, 9 ─► 10 (hub links to the detail views)
10 ─► 11 (nav + middleware expose the hub)
all ─► 12 (final verification)
```

## Notes

- No new mutation endpoints; all reporting is read-only (NFR-1).
- Reuse `get_rpt_receivables_summary`, `get_collections_worklist`,
  `get_receivables_by_barangay`, `get_report_details`, `get_assessment_roll`,
  `get_delinquent_accounts` — do not reimplement financial math.
- No new hardcoded `0.01`/`0.02` literals; rates come from `TaxPolicy` helpers
  (Property 6).
- No mock-data fallbacks on error in any new view (Property 5).
- Frontend follows the established cookie-auth pattern: `credentials: "include"`
  + `X-Requested-With: XMLHttpRequest`; 401 redirects to `/admin/login`.
