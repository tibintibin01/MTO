# v2.1.25 website dependency security review

The operator separately approved the website security fixes on 2026-11-03 after
CI blocked the Payment History native-DATE hotfix. Twenty moderate dependency
findings included transitive parents of two root advisories; these are not twenty
independent vulnerabilities and are not evidence of exploitation.

- `glob@13.0.6` is replaced with upstream `14.0.2` for the AbortSignal cancellation
  fix (GHSA-3g3m-2fjr-6pw4).
- Modern minimatch consumers use upstream `11.0.1` for bounded globparts
  preprocessing (GHSA-g3hv-75wg-m249), replacing `10.2.6`.
- Legacy minimatch 3 consumers use a private, development-only callable export
  adapter backed solely by upstream `minimatch@11.0.1`. It does not copy, rename or
  retain a vulnerable matching engine. An explicit npm alias pins the engine.

The adapter is needed because ESLint and its import/React/accessibility plugins
still call the CommonJS default function, while upstream now exposes named
exports. A blind global major-version override would break that interface.
Upstream 11 also removed regex compilation. The adapter preserves the existing
import linter's `makeRe(...).test(path)` operation using an immutable tester that
delegates to upstream matching; it is not a RegExp and restores no regex engine.
No Next.js, Serwist, ESLint or Python dependency upgrade/downgrade is authorized
or needed for this remediation. No compiler, rule or CSS baseline is relaxed.

Check the actual installed nested copies, legacy callable/class/helper/defaults
APIs, glob cancellation and bounded preprocessing. Run lint, build, unchanged CSS
baseline, service-worker, publication, property-workspace and duplicate-account
regressions. Full and production npm audits must pass without ignoring an
advisory or extending a risk exception. Keep existing financial/RCD and release
checks enabled. These tests do not certify arbitrary patterns or all library uses.

This change does not alter site design, financial calculations or records,
schema, receipt/TD history, backup/retention settings, publisher schedules,
secrets or risk acceptance. A source check does not authorize office deployment.

## Primary upstream evidence

- [Glob advisory](https://github.com/isaacs/node-glob/security/advisories/GHSA-3g3m-2fjr-6pw4)
- [Glob v14.0.2](https://github.com/isaacs/node-glob/releases/tag/v14.0.2)
- [Minimatch advisory](https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249)
- [Minimatch v11.0.1](https://github.com/isaacs/minimatch/releases/tag/v11.0.1)
- [Minimatch bounded preprocessing fix](https://github.com/isaacs/minimatch/commit/77a0f5c)
