# Public portal dependency security — 2026-11-18

This change is limited to the public website's package graph, dependency
validation, and build tests. No desktop version, backend, schema, publication
controls, or payment code is changed.

## Next.js production dependencies

`next` and `eslint-config-next` are pinned together at `16.4.6`. This is on the
existing Next.js release line and includes the fixes from `16.4.5` for
[GHSA-mfr8-8qww-v76h](https://github.com/advisories/GHSA-mfr8-8qww-v76h) and
[GHSA-vc7v-qv4w-wrv8](https://github.com/advisories/GHSA-vc7v-qv4w-wrv8).
The Node contract, Serwist integration, and sensitive-route caching are unchanged.

## Build-only Picomatch mitigation

[GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf)
has no published upstream patch at the time of this change. The old development
dependency graph had unpatched v2 and v4 copies. The `picomatch` file override
uses one private MIT-licensed fork of official upstream `4.0.7`, with its
original license. Its distinct name and `4.0.7+mto.1` version identify MTO
source, not an upstream fix. `frontend/vendor/picomatch-build-source.json`
records the original npm archive integrity and the reviewed source hashes.

The local parser rejects extended groups in both compiler entry paths and
does not allow options to re-enable their parser. Ordinary glob matching
remains available. This is a deliberately restricted compiler for trusted
build patterns, not a general guarantee for arbitrary pattern processing or
a package for runtime use. Verify all legacy and modern build consumers resolve
exactly the reviewed fork. The repository policy rejects registry fallbacks,
runtime placement, source drift, extra files, or lifecycle hooks.

Full and production npm audits remain mandatory and their policy is unchanged.
Do not use an audit exemption or force-install an incompatible package. Remove
the local fork after an upstream fix is published and the existing callers pass
against it. Hosted CI and an approved website preview still precede any merge.
