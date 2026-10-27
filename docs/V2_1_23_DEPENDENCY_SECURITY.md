# v2.1.23 dependency security review

The year-aware TD status release exposed current audit findings in unchanged
dependency locks. The operator separately authorized the minimal Python build
tool updates and the website dependency security fixes. No audit gate is
weakened, advisory ignored, or risk acceptance renewed.

## Reviewed updates

| Area | Before | After |
| --- | --- | --- |
| Black (development) | 26.3.1 | 26.10.1 |
| Brotli (development graph) | 1.2.0 | 1.2.1 |
| filelock (development) | 3.32.6 | 4.2.1 |
| setuptools (build backend) | 84.0.0 | 84.1.0 |
| Next.js and matching ESLint package | 16.3.8 | 16.4.3 |
| Undici (website Blob SDK dependency) | 6.28.1 | 6.29.1 |
| Zod (website Serwist dependency) | 4.4.3 | 4.6.6 |

Python runtime requirements and their hash lock remain unchanged. The universal
development lock retains the same 135 package names and only the four approved
version changes. The build backend uses the same patched setuptools pin.

The website lock changes only Next.js's matching package family, Undici and Zod.
Serwist remains 9.5.12; no major downgrade or unreviewed cross-major override is
used. Exact transitive overrides ensure the Serwist and Blob SDK consumers use
the patched copies. Tests reject old, missing or unreviewed-major copies even
when nested in another dependency. Existing security overrides and the reviewed
braces source backport remain intact.

## Verification and scope

Keep both Python lock audits and the strict full/production npm audit policy
enabled. Dependency regression tests use small synthetic inputs to verify Zod
checks collection bounds before visiting elements and Undici rejects a malformed
loopback response without an unhandled stream error. They also check the actual
Serwist/Blob dependency resolution, webpack integration and the sensitive-route
network-only service-worker rule. These do not certify every use of a library.

Run existing website lint/build, publication protocol, icons, duplicate-account
lookup, property-workspace and service-worker tests. The CSS backport baseline
must remain identical; do not update it merely to make the test pass. Existing
Python/financial/RCD tests and the desktop/server trust boundary remain required.

No site layout/source redesign, tax calculation, receipt date, TD history,
financial record, backup/retention setting, publisher schedule, secret or risk
exception is changed by these dependency fixes. Audit findings are not evidence
of exploitation or proof every vulnerable path was used. Do not distribute the
unsigned desktop binaries publicly or deploy the municipal API server merely
because source checks pass.

## Primary upstream references

- [Next.js v16.4.3](https://github.com/vercel/next.js/releases/tag/v16.4.3)
- [Next.js cache-function advisory](https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr)
- [Undici excessive-content-encoding advisory](https://github.com/nodejs/undici/security/advisories/GHSA-xjj6-f33q-929c)
- [Undici v6.29.1](https://github.com/nodejs/undici/releases/tag/v6.29.1)
- [Zod v4.6.6](https://github.com/colinhacks/zod/releases/tag/v4.6.6)
- [Zod bounds-check fix](https://github.com/colinhacks/zod/commit/a0ebf97)
