# Property workspace preview — 8 October 2026

Status: both appearances approved by the user; website-only PR/check/deployment
workflow is being prepared. Landing-page appearance was accepted by the user;
the user then requested a corresponding property-result redesign and expressly
allowed removal of irrelevant elements, including decorative photographs.
The property workspace was then approved. No office activation is authorized or
needed for this website publication workflow.

## Presentation changes

- A coherent navy/gold/sea-green account workspace, matching the landing page.
- Municipal-hall background photograph, dot grid, large glass overlays, emoji
  watermarks, floating card animations, repeated office-hours/reminder panels,
  and the redundant inner official-site footer note removed from this view.
  Original image files are preserved; the official header/footer seals remain.
- Property identity, masked owner, location, classification, current/future
  assessment, actual record publication time, balance, unapplied credit, paid
  and billed totals, payment metadata, billing detail and SOA access retained.
- "Discount applied" describes the stored snapshot values rather than implying
  a newly estimated discount. Unapplied credits remain distinct by tax year.
- Last Payment emphasizes the recorded payment date, with the covered tax year
  underneath. No payment date or amount is recalculated.
- Yearly cards on small screens and bounded tables on larger screens. Header
  cells and row headers have scope, tables have accessible captions, and the
  billing disclosure has an explicit expanded state and controlled region.
- Missing data, pending records, genuinely empty history, unavailable history,
  and snapshot mismatch remain different states. No unknown count becomes zero.
- Clipboard feedback is shown only after a successful write; failure explains
  how to copy the identifier manually. No-JavaScript assistance is retained.

## Unchanged boundaries

The property loader's complete request/history effect and its financial value
selection/formatting block were compared directly with the approved source and
are unchanged. Snapshot identity, obsolete-request cancellation, timeouts,
no-store fetches, selected opaque account keys, checked-history validation,
readiness guards and SOA source/account parameters remain intact.

Backend calculations, database records, public disclosure/masking, API route
logic, schema, secrets, publisher tasks, office runtime, desktop version and
immutable release/certification evidence were not changed. The existing worker
still places all /api/ and /admin requests under NetworkOnly before other rules.

## Verification

- Production build / TypeScript passed.
- Original synthetic portal regressions: 81 checks passed.
- Property workspace suite: 83 checks passed, covering four widths, unchanged
  published amounts, credit isolation, current/future assessment, payment-date
  distinction, receipt values, SOA selectors, no decorative photos, paid and
  unbilled accounts, empty vs failed history, successful retry, snapshot mismatch
  withholding and recovery from a missing account.
- Landing suite after shared style changes: 48 checks passed.
- Lint: zero errors, six unchanged legacy admin warnings. Whitespace and script
  syntax checks passed. Desktop/mobile screenshots and actual browser preview
  were inspected.

Worker-owned NetworkOnly fetches are not Playwright page-route fetches after
clientsClaim. Initial fault injections therefore use independent fresh browser
contexts, with counters confirming that the synthetic faults were actually
injected. The app's worker/cache/security settings were not relaxed to pass tests.

Property lab medians from three 390x844 cold navigations, 4x CPU slowdown,
100ms latency and 1.6Mbps download, using the same artificial records:

| Measure | Original property view | Workspace preview |
| --- | ---: | ---: |
| LCP | 2,488ms | 1,960ms |
| Encoded JavaScript | 205,067 bytes | 164,270 bytes |
| Encoded resource bodies | 437,490 bytes | 398,888 bytes |
| CLS | 0 | 0.00078 |

The preview loaded about 40KB less JavaScript and 39KB fewer resource-body bytes.
These small-sample localhost measurements are not field Core Web Vitals,
Lighthouse scores or a guarantee for every visitor/network. No tax formula or
financial computation was modified for the performance comparison.

The shared landing-page styles still meet its original budgets. Its latest
measured LCP was 1,148ms vs 1,356ms baseline, resource bodies 293,970 vs 314,406
bytes, JS 155,574 vs 155,314 bytes, and CLS 0.00313 vs 0.06511. Initial CPU work
is not literally zero-cost; no claim of unchanged CPU use is made.

## Local review

`frontend/tests/property-preview-fixture.cjs` contains only three explicit demo
accounts, including two that share a fake TDN to exercise account isolation.
It is not municipal data and must not be used for publication. The local preview
runner disables blob credentials and reads this temporary fixture only.

Run `node tests/serve-landing-preview.cjs` from frontend; the console prints a
free 127.0.0.1 URL. Example routes are `/property/DEMO-A`, `/property/DEMO-B` and
`/property/DEMO-PENDING`. Screenshots and measured reports are kept outside the
source checkout under `work/design-preview/property-workspace-20261008`.

At this implementation checkpoint, no GitHub push, PR, merge, public deployment,
office update, or new application release has been performed for this design.
The PR pipeline now runs the original portal regressions and baseline-independent
property contracts after building and installing the lockfile-pinned browser.
Use `npm run test:property-workspace` for those synthetic contracts. Full local
performance comparisons still use the saved baseline and are not simulated in CI.
Do not run server deployment or financial maintenance commands for this website
publication. Website deployment status must be verified separately after merge.
