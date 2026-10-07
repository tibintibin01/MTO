# Public portal reliability and UX improvements

Implementation branch: `codex/public-portal-reliability-20261006`, isolated from
the approved v2.1.16 source (`66efbeefd7624d59edf1615a95085ac4441b5046`).
The live site, municipal database, vault, scheduled tasks and release workflow
evidence were not changed by this implementation.

## Implemented

- Shared timestamp validation, timezone-aware Philippine publication dates,
  rejection of unknown/future publication times and the existing 36-hour
  freshness threshold. All property, history, owner lookup and statement routes
  use the same stale-data guard and no-store responses.
- A public publication-status banner with bounded requests, focus refresh and
  periodic refresh. Stale/unavailable data is explained rather than presented
  as current. Publication time replaces the misleading current-calendar-date
  property header.
- A snapshot identifier ties history to the property record. A changed snapshot
  requests a refresh instead of mixing financial data from different exports.
- Durable loading/ready-empty/ready-populated/error history states, inline retry,
  bounded fetches and cancellation of obsolete account requests. An unavailable
  history no longer produces a zero count or an empty-history assertion.
- Compact mobile-first home/search; visible Search/How to Pay/Help navigation;
  input labels, announced errors, visible keyboard focus, a skip link, zoom
  support, reduced-motion handling, stronger small-text colors and no misleading
  decorative arrows. Home content and assistance remain visible without JS.
- Correct TDN digit aliases with duplicate-account isolation. Exact PIN lookup
  remains supported; colliding identifiers prompt account selection rather than
  choosing or merging financial accounts.
- Unicode/NFKC owner token handling shared by publisher and consumer. Names
  remain masked; lookup indexes remain keyed hashes. A legacy index without the
  new version marker gives an update-required response for accented-name queries
  rather than a false no-result assertion.
- Neutral shared payment guidance replaces contradictory dates/rates pending an
  office-approved notice. No tax policy, billing calculation or stored financial
  record was changed. The compliant-status FAQ explains unapplied yearly credit.
- Appropriately sized logos, optimized decorative photography, a public-only
  sitemap and noindex/robots handling for property account routes. Robots are
  crawler instructions, not access control or proof of privacy compliance.
- A standard `npm run test:portal` synthetic regression suite with lockfile-pinned
  development-only Playwright. Set `MTO_TEST_BROWSER_EXECUTABLE` to an installed
  browser, or install Chromium with `npx playwright install chromium` for CI.
- Minimal `source-map-js` 1.2.2 override for the high-severity indexed-source-map
  denial-of-service advisory GHSA-68fv-2mgg-jv7q. No unrelated runtime dependency
  upgrade or bulk `npm audit fix` was applied. This is dependency hardening, not
  evidence of exploitation of the live portal.
- Read-only publication diagnostics; generated test artifacts and TypeScript
  cache are excluded from source tracking. The local cache file is preserved.

## Validation

- Production Next.js build and TypeScript check: success.
- Local production-server browser/API checks: **73 passed**, using synthetic
  records, a temporary local snapshot and an isolated 127.0.0.1 server.
- Python publisher/financial-inquiry/diagnostic/dependency-policy tests: **44 passed**, using
  in-memory SQLite and child-process-only synthetic authentication settings.
- Separate diagnostic bundle/function/allowlist/hash-chain tests: **9 passed**.
- Production dependency audit after the targeted patch: zero known vulnerabilities
  returned by the current npm advisory data. This is not a penetration test.
- Lint: zero errors; six pre-existing warnings in legacy admin pages that remain
  redirected away from public access. Build still emits the existing Next.js
  middleware convention deprecation warning. Neither is claimed fixed here.
- `git diff --check`: success.

The primary search button starts at y=552px on 320x700, y=494.5px on 390x844,
and y=369px on 1440x844. It fits each initial viewport. No real taxpayer search,
database write, live upload or credential change was made in the browser tests.

## Remaining deployment prerequisites

1. Run the read-only server diagnostic outside C:\mto and review configuration,
   local vs hosted publication times, and publisher task metadata. The current
   local-refresh script does not upload to Vercel; an older hosted snapshot alone
   does not prove which configuration/scheduling/network issue stopped uploads.
2. Restore a verified publication process under explicit operator approval;
   preserve the existing secrets and financial records. Do not rotate secrets or
   run the updater as an attempted publication repair.
3. A newly generated snapshot is needed for Unicode index version 2. Server
   publisher changes require an approved delivery path; the frontend alone cannot
   reconstruct missing raw owner-name tokens from an older masked snapshot.
4. Supply Treasury-approved deadline/discount/penalty wording and verified office
   phone/email details. Until then, guidance stays neutral and no contact detail
   is invented. Financial calculation rules remain unchanged.
5. Approve and execute the live deployment, then repeat live readiness/freshness,
   duplicate-account isolation, failure-state and mobile checks. The stale-data
   guard will intentionally withhold lookups while records exceed the limit.
6. Public disclosure scope, abuse/rate-limit controls and the formal privacy
   notice require separate owner/privacy-officer approval. No legal compliance
   or security certification is asserted by this code/UI change.

Do not claim a higher live-site rating or a completed publishing repair until
the deployed site and server publication process have actually been verified.
