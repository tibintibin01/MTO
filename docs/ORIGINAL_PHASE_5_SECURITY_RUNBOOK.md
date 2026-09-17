# Original Phase 5 — Supply-Chain Security Runbook

## Purpose

Original remediation Phase 5 secures application builds, dependencies, release
artifacts, and production updates. This first gate is intentionally read-only.
It identifies the remaining controls required before any signing, packaging, or
updater change is approved.

The gate does not fetch source, build binaries, install packages, sign files,
start or stop services, change configuration, run migrations, or alter business
data. Its only optional write is a privacy-safe JSON report.

## Scope of this preflight

The preflight verifies four independent components:

1. **Source identity** — approved origin, clean `master`, local
   `origin/master` equality, and an immutable semantic version tag at `HEAD`.
2. **Dependency policy** — complete runtime, development, frontend, container,
   and workflow-action pinning through the existing dependency-policy gate.
3. **Release controls** — tag-only production release, protected production
   approval, vulnerability scanning, SHA-tagged images, hash-locked desktop
   builds, signing enforcement, manifest/SBOM creation, and rollback-capable
   updates.
4. **Desktop release** — required files, HTTPS and public-CA configuration,
   private-key exclusion, valid Authenticode signatures, a complete immutable
   hash manifest, and a valid CycloneDX SBOM.

## Run the read-only development assessment

From the approved MTO source checkout:

```bat
cd /d C:\mto
call venv\Scripts\activate
python -m scripts.phase5_supply_chain_preflight --distribution C:\MTO\dist --output logs\remediation-original-phase-5-supply-chain.json
echo Exit code: %ERRORLEVEL%
```

This assessment is expected to report the current gaps until later Phase 5
workstreams implement them. A failing assessment is evidence for the closure
plan; it is not authorization to alter production.

## Production acceptance gate

Use the fail-closed form only after the separately approved release-hardening
workstreams are complete:

```bat
python -m scripts.phase5_supply_chain_preflight --require-ready --distribution C:\ProgramData\MTO\releases\<approved-version> --output logs\remediation-original-phase-5-supply-chain-final.json
echo Exit code: %ERRORLEVEL%
```

Exit codes:

- `0` — every required gate passed.
- `4` — medium-severity review remains and `--require-ready` was not used.
- `2` — a high/critical control failed, or strict readiness was not achieved.

## Required closure workstreams

The preflight establishes evidence for these separately approved changes:

1. **Immutable release identity** — versioned tag, exact source commit, and
   version propagated into all packages.
2. **Reproducible desktop build** — complete hash-locked build environment,
   CycloneDX SBOM, and artifact hash manifest.
3. **Trusted signing** — Authenticode signing and fail-closed verification for
   `Treasury.exe`, the installer, and the uninstaller.
4. **Safe updater** — stage an immutable release, verify its manifest and
   signature before service interruption, capture backup and financial
   baseline evidence, perform an atomic switch, verify readiness, and retain a
   tested rollback target.
5. **Release governance** — production deployment only from approved version
   tags through the protected production environment.

## Signing trust decision

A signing certificate is an external security prerequisite. A public-code-
signing certificate is preferred. A private organizational CA is acceptable
only when its root and publisher trust are deployed through managed policy and
the private key is hardware-backed or otherwise access-controlled. An ad-hoc
self-signed certificate must not be treated as enterprise production trust.

The preflight reports only signature status, a shortened certificate
thumbprint, and certificate expiry. It never reports or copies private keys.

## Acceptance criteria

Phase 5 supply-chain closure requires all of the following:

- clean, tagged, approved source identity;
- dependency-policy PASS;
- tag-only protected production deployment;
- hash-locked build and runtime dependencies;
- valid signatures on executable, installer, and uninstaller;
- complete manifest hashes matching every required artifact;
- valid CycloneDX SBOM;
- no private key or secret material in the package;
- staged, verified, baseline-protected, rollback-capable updater;
- post-update authenticated readiness, audit-chain verification, and financial
  invariant comparison.

Any signing, updater, deployment, server sync, or activation action requires a
separate explicit approval and its own before/after evidence.

## Immutable release build implementation

The approved build foundation provides the following controls:

- production deployment is triggered only by an immutable `vX.Y.Z` tag;
- desktop and installer versions are derived from that exact tag;
- the source must be clean and match local `origin/master` before building;
- the complete desktop build environment is installed from
  `dev-requirements.lock` with `--require-hashes`;
- `Treasury.exe`, the installer, and the generated uninstaller use the same
  managed Authenticode identity when signing is enabled;
- unsigned output requires the explicit
  `-AllowUnsignedDevelopmentBuild` switch and cannot pass production preflight;
- the final package receives `release-manifest.json` with SHA-256 hashes for
  every required artifact and reviewed build material;
- the final package receives a deterministic CycloneDX 1.5 SBOM generated from
  the hash-locked runtime dependency graph.

The normal production build is intentionally fail-closed:

```powershell
$buildPython = '.\.phase5-release-venv\Scripts\python.exe'
py -3.11 -m venv .\.phase5-release-venv
$env:MTO_CODE_SIGNING_CERT_THUMBPRINT = '<managed-certificate-thumbprint>'
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_installer.ps1 `
  -PythonPath $buildPython
```

The dedicated build environment prevents development and packaging tools from
being installed into the production API virtual environment. The build script
then installs the complete reviewed dependency graph from
`dev-requirements.lock` with hashes before packaging.

Do not store a certificate password, private key, PFX, or thumbprint override in
Git. The signing certificate must be separately approved and provisioned before
the production build is authorized.

## Immutable production updater

`update_mto.bat` no longer pulls mutable `master`. It requires an explicitly
approved stable release tag and the matching signed release directory:

```bat
cd /d C:\mto
call venv\Scripts\activate
call update_mto.bat vX.Y.Z C:\ProgramData\MTO\releases\vX.Y.Z
```

Before interrupting the API, the updater verifies that the selected tag is the
exact fetched `origin/master` commit and a fast-forward descendant of the
active source. It validates the release manifest hashes, CycloneDX SBOM,
private-key exclusion, and Authenticode signatures. It then requires the
operator to type the release-specific confirmation phrase.

Protected evidence is stored outside the checkout under
`C:\ProgramData\MTO\updates\<release-and-timestamp>`. It includes the release
manifest, pre-update financial/backup baseline, supply-chain report, audit
integrity report, post-update comparison, exact previous and target commits,
and a retained Git rollback reference. The updater stops on every failed gate.
The candidate dependencies are installed into a separate hash-locked virtual
environment. The active runtime is switched only after that environment passes
`pip check`, while the exact previous environment is retained with the rollback
evidence. A failure before migrations automatically restores both the prior
code revision and its runtime. Once migration execution starts, the updater
fails closed and requires explicit incident review rather than assuming that a
code-only rollback is schema-safe.

An explicitly approved code rollback uses the evidence record ID:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File C:\mto\scripts\apply_immutable_release.ps1 `
  -Rollback `
  -RollbackId <approved-record-id> `
  -ProjectRoot C:\mto
```

Rollback preserves the failed commit, captures immediate before/after
financial evidence, reinstalls the previous hash-locked runtime, restarts the
managed API, and requires authenticated readiness. It does not reverse database
schema changes and must never be run without separate incident approval.
