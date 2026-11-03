# Callable minimatch compatibility entry point

This private, first-party adapter delegates matching to **unmodified upstream**
`minimatch@11.0.1`. Its matching engine and security limits come entirely from
that exact upstream dependency. The npm alias `minimatch-modern` avoids a dependency cycle.
The lock pins its registry archive integrity.

Only existing `<4` consumers use this adapter, and it must remain development
only. Modern consumers receive upstream `minimatch@11.0.1` directly. Do not
misrepresent this adapter as a patched release of minimatch 3, publish it to npm,
or add a fallback to the vulnerable engine. No local matching algorithm or
upstream source is copied here.

Compatibility is intentionally limited to the existing build/lint consumers.
Upstream 11 removed regex compilation. Existing import-linter code uses only
`makeRe(pattern).test(path)`, so the adapter supplies an immutable pattern tester
that delegates to upstream matching. This is NOT a RegExp and does not support
`.exec`, `.source` or regex serialization. No old regex engine is retained.
Default-option factories and class instances retain this same tester interface.
The tests exercise callable and class APIs, helpers, defaults, normal matching,
ESLint's real imports and Serwist's glob dependency. They retain the existing CSS
baseline and strict full/production audit policy. This is not a claim of full
semantic equivalence between every possible minimatch 3 and 11 pattern or API.

Remove this adapter when all legacy consumers accept upstream's named export.
Review it and its exact upstream pin when changing dependency resolution.

Upstream advisory:
https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249
