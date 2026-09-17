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
