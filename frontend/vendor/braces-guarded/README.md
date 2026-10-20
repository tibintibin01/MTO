# MTO build-only braces backport

This is a local MIT-licensed fork of `braces@3.0.3`, not an upstream patched
release. It replaces every development-only `braces` dependency using an explicit
npm file override. The normal parser/compile/expand algorithms are unchanged.

Upstream archive and original-file SHA256 hashes are in `UPSTREAM.json`; the
archive's SHA512 matches the previously locked npm package. The original MIT
copyright/license is retained. No package is published to npm.

## Security changes

- A non-disableable 64-level parser/AST depth bound prevents recursive stack
  exhaustion under GHSA-vfj7-8cjw-p6xm (CVE-2026-93687).
- Iterative AST preflight rejects deep/cyclic/shared child graphs and bounds
  supplied trees to 30,000 nodes before any recursive compile/expand/stringify.
- Both expansion parent-link loops are independently bounded.
- Existing input-length, expansion-range and normal matching behavior remain.

Deep/invalid ASTs now fail with a controlled SyntaxError/TypeError. This does not
claim arbitrary expansion is resource-free. Build patterns remain trusted
repository source; this package must not become a public pattern-processing API.
There is no fallback to the unpatched package when validation fails.

`npm run test:build-backport` checks all installed dependency copies, rejects
runtime placement, tests deep strings/ASTs/cycles/options and verifies the
recorded upstream compatibility fixtures. CI runs this check before the existing
unmodified security audit policy. No advisory is ignored, risk exception renewed,
version falsified, linter rule disabled or compiler/browser support changed.

The approved source commit pins this code. Review this fork whenever changing
the lock or glob consumers. Remove the override after an upstream fixed version
is available and verified. The expired historical exception stays expired.
