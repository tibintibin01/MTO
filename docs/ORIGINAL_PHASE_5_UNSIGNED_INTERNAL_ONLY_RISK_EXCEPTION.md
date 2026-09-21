# Original Phase 5 unsigned internal-only risk exception

## Decision

The MTO system owner accepts the temporary residual risk of distributing an
unsigned Windows desktop executable and installer only inside the controlled
municipal environment. This is not an assertion that the artifacts are signed,
trusted by Windows, suitable for public distribution, or equivalent to a public
code-signing certificate.

The machine-readable approval record is
`governance/accepted-risks/original-phase-5-unsigned-internal-only.json`. It is
effective on 2026-09-21 and expires after 2027-03-20 unless it is explicitly
reviewed and replaced. Editing the date or record does not extend approval by
itself; an updated exception requires a new approval and normal code review.

## Scope and residual risk

This exception waives only `AUTHENTICODE_SIGNATURE_INVALID` for
`Treasury.exe` and `installer/MTO_Treasury_Setup.exe`. Windows may display an
Unknown Publisher or SmartScreen warning. The exception provides no public
publisher identity and cannot prove artifact origin by signature.

It does not waive any of the following:

- missing or mutable release tags;
- dirty or unapproved source;
- missing artifacts, release manifest, or CycloneDX SBOM;
- SHA-256 mismatches or altered build material;
- private keys or secret material in the package;
- an unavailable signature-verification mechanism;
- TLS, dependency, backup, database, audit, or runtime failures.

Any non-signature finding continues to block the release.

## Mandatory compensating controls

Every accepted unsigned release must use a reviewed immutable `vX.Y.Z` tag,
hash-locked dependencies, the generated release manifest and SBOM, and SHA-256
verification immediately before installation. Distribution is limited to
managed municipal computers through a controlled operator. The artifacts must
be malware-scanned before installation, their unsigned status must be disclosed
to operators, and Windows Security, SmartScreen, or antivirus protection must
not be disabled or bypassed.

The normal signed-production gate remains the default. The exception must be
selected explicitly:

```bat
call update_mto.bat vX.Y.Z C:\ProgramData\MTO\releases\vX.Y.Z --internal-only C:\mto\governance\accepted-risks\original-phase-5-unsigned-internal-only.json
```

The updater copies the acceptance record into protected update evidence and
records its SHA-256. The supply-chain report must state
`PASS_WITH_ACCEPTED_RISK`; a plain signature PASS must never be claimed for an
unsigned package.

## Exit condition

Procure and protect a public code-signing identity when resources become
available, rebuild both executable and installer, verify valid Authenticode
signatures, and retire this exception. It must also be suspended immediately if
distribution expands outside the controlled municipal environment or if an
artifact hash, source identity, malware scan, or endpoint control is uncertain.
