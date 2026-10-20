# Build-only brace-expansion security backport

The RCD release's CI exposed the pre-existing GHSA-vfj7-8cjw-p6xm build-only
finding after the historical exception expired on October 14, 2026. The owner
separately approved build-dependency remediation, not an exception renewal or
a site redesign. The advisory still lists no upstream patched release:
https://github.com/advisories/GHSA-vfj7-8cjw-p6xm .

The compatible, narrow remediation is an explicit local fork of MIT-licensed
braces 3.0.3, named `@mto/braces-guarded` version 0.1.0. This is not represented
as an upstream release. No package is published to npm. The original archive's
SHA512 and per-file SHA256 provenance and MIT copyright are retained in
`frontend/vendor/braces-guarded/UPSTREAM.json` and `LICENSE`.

The fork is a development-only root file dependency, and `overrides.braces`
references that root dependency so npm hoists every affected consumer to the
same source. No registry package versions, framework/compiler configuration,
website components, class names or financial calculations are changed.

## Actual code remediation

- Fixed, non-disableable 64-level parser/AST bounds, checked before deeper
  allocations and recursive compile/expand/stringify calls.
- Iterative AST preflight rejecting deep/cyclic/shared child graphs and trees
  over 30,000 nodes. Normal parent/prev backlinks are not recursive child edges.
- Bounded parent-link loops in expansion, including supplied malformed ASTs.
- Existing normal parsing, compilation, expansion and range/input limits remain.
  This does not assert arbitrary expansion is resource-free or expose a public
  pattern-processing API. Build patterns remain trusted repository inputs.

This changes the code that caused stack exhaustion. It does not suppress an
advisory, renew the expired approval, falsify a registry version or disable
lint/security rules. The original `audit-policy.cjs`, its expiry checks and the
historical risk document remain unchanged.

## Verification and maintenance

`npm ci` must install the local override reproducibly. CI first runs
`test:build-backport`, then the existing complete dependency audit. The backport
test checks all installed lock entries, development-only placement, source
provenance, 90 upstream normal-pattern compatibility cases, deep strings and
ASTs, cyclic graphs, attempted option bypasses, and byte-identical compiled CSS
against the pre-backport v2.1.20 source baseline (normalizing only Git CRLF/LF
line endings for Windows/Ubuntu portability). The general dependency policy
also validates the exact local path, complete source/checksum allowlist, package
identity and absence of lifecycle hooks. Arbitrary file/URL dependencies remain
blocked. Source checksum checks normalize only Git line endings.

The fork's full source is part of the immutable reviewed Git commit. Changes
to it, glob consumers or the lock require review of the provenance, guards and
compatibility tests. Future intended site changes may legitimately require a
new reviewed CSS baseline; do not change security limits or remove assertions
to make tests pass. Revert to an upstream release only after a genuine fix is
available and verified, then remove the local override and its special policy
case together. A missing or altered backport must block rather than silently
fall back to the vulnerable registry package.

Source/CI publication is not production deployment or security certification.
