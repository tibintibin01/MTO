# Coastal civic landing-page preview

Status: landing appearance accepted; property-workspace extension is now in
local review (see `PORTAL_PROPERTY_WORKSPACE_PREVIEW_20261008.md`). No public push, PR, deployment,
office source update, release-tag change, publisher task change, or financial
record modification was performed for this design.

Branch: `codex/portal-landing-coastal-20261008`, based on the approved
`66f2545bbc718fd721a69d200ec53985b1db8ac6` source.

## Direction

A new editorial identity rather than a recreation of the previous landing page:
deep coastal navy, warm gold, sea-green actions, dimensional property plots and
an abstract record card. The illustration contains no real account, payment,
balance or financial claim. Desktop artwork is original SVG/CSS. Mobile keeps
the search prominent and carries the dimensional treatment through action
cards. There is no canvas, WebGL, video, graphics dependency, or animation loop.

The original illustration is rendered by the server and passed as a React node
to the existing interactive home component; SVG drawing instructions are not
included in the interactive client JavaScript. Search identifiers, API paths,
timeouts, request guards, owner lookup, announced errors, and separate-account
selection are preserved. The public publication-status logic is unchanged.
CSS changes to shared chrome are scoped to the home route.

A native `noscript` assistance paragraph replaces a hydration-only warning,
avoiding the warning's normal-load layout jump while preserving help for
visitors without JavaScript. The no-JavaScript regression checks the visible
paragraph and assistance link directly because Playwright's text engine skips
`noscript` subtrees. A blocked service-worker registration initially caused a
test-browser error; the design harness now allows normal registration and
bypasses worker caching only for its measured cold-navigation runs. No
production worker or security setting was changed.

## Verification

- Production webpack build and TypeScript: passed.
- Portal regression suite: 81 checks passed with synthetic records on localhost.
- Design/performance suite: 48 checks passed, including four viewport widths,
  first-viewport search access, horizontal overflow, keyboard focus, browser
  runtime errors, owner-search availability, reduced motion, no-JavaScript help,
  narrow-width reflow, six text-contrast pairs and synthetic search interactions.
- Lint: zero errors, six unchanged warnings in legacy admin pages.
- Whitespace and test-script syntax: passed.
- Actual browser preview and desktop/mobile rendered screenshots inspected.

Three cold navigations at 390x844, 4x CPU slowdown, 100ms simulated latency,
1.6Mbps download and the same Chrome/runtime produced these local medians:

| Measure | Existing page | Preview |
| --- | ---: | ---: |
| Largest-contentful-paint time | 1,356ms | 960ms |
| Cumulative layout shift | 0.0651 | 0.0031 |
| Encoded resource bodies | 314,406 bytes | 291,556 bytes |
| Encoded JavaScript | 155,314 bytes | 156,134 bytes |
| HTML, locally gzip-compressed | 7,002 bytes | 10,585 bytes |
| Resources plus that HTML estimate | 321,408 bytes | 302,141 bytes |
| Observed aggregate long-task time | 246ms | 282ms |

The preview adds 820 compressed JavaScript bytes and slightly more initial CPU
work; it is not literally zero-cost decoration. Its combined payload estimate
is about 6% lower, main-content appearance was earlier, layout was more stable,
and each synthetic validation click measured 32ms in Event Timing. These are
small-sample local lab measurements, not Lighthouse scores, field Core Web
Vitals, a guarantee of every visitor's speed, or proof of improved retention.
The HTML estimate uses Node gzip and is not a measured CDN transfer size.

Budgets were not relaxed for the candidate: layout shift <=0.05, no increase in
resource payload, <=2.5KB extra compressed route JS, LCP within the predeclared
variance tolerance, and synthetic interaction duration <=200ms. The first
client-bundled artwork version exceeded the JS budget and was revised rather
than accepted. Measured attempt reports are retained separately.

The baseline and preview reports/screenshots are generated outside the source
checkout in `work/design-preview/portal-landing-20261008`. No real municipal
records, credentials, live uploads, or actual taxpayer searches were used.

## Reproduce and review

From `frontend`, build with `npm run build`. The existing portal suite is
`npm run test:portal`. The manual before/after design harness is
`node tests/landing-design.cjs --baseline` on the original build, followed by
`node tests/landing-design.cjs` on the candidate build. Baseline comparison
requires that saved baseline; it is not presented as a fresh-clone CI command.
`--screenshots-only` recaptures visual views without replacing performance data.

`node tests/serve-landing-preview.cjs` starts a production preview on a free
127.0.0.1 port with explicitly marked artificial demo records for the full
home-to-property journey. The console prints its URL. Blob credentials are
disabled. Only the generated local fixture date is refreshed; there is no publication.

The preview should receive human visual approval before preparing the public
website-only PR/deployment. Do not install another desktop release or run office
deployment/maintenance commands to review this design. Existing v2.1.17 server,
client certification, publication approval and original evidence remain intact.

Animation choices follow the browser rendering guidance for
[transform/opacity effects](https://web.dev/articles/animations-guide) and
[reduced-motion preferences](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion).
