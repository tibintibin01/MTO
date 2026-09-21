# Original Phase 5 — Code-Signing Delivery Acceptance Checklist

## Approval boundary

Use this checklist only after procurement and delivery are complete and a
separate certificate-delivery acceptance activity has been approved. Delivery
acceptance does not authorize production artifact signing.

Store the completed checklist and sensitive evidence in the municipality's
protected records system. Do not place personal information, token PINs,
private keys, identity documents, recovery codes, or unredacted certificate
records in Git.

## Before opening or activating the token

- [ ] Purchase order, vendor, product, and delivery match the approved award.
- [ ] Package was received through the approved controlled delivery address.
- [ ] Tamper evidence and package condition were inspected and recorded.
- [ ] Token serial or asset identifier was recorded in controlled inventory.
- [ ] Certificate custodian accepted custody in writing.
- [ ] Backup incident and revocation contacts were confirmed.
- [ ] PIN/activation material is physically or logically separate from token
      custody and is not copied into this checklist.

Stop and escalate any mismatch, tamper indication, unexpected sender, or
unapproved substitution. Do not connect the token in that state.

## Middleware acceptance

- [ ] Middleware came from the certificate authority's official channel.
- [ ] Installer hash or vendor-published integrity evidence was recorded.
- [ ] Windows reports a valid Authenticode signature from the expected vendor.
- [ ] Installation scope and requested privileges were reviewed.
- [ ] No browser extension, remote-support tool, or unrelated component was
      installed without separate approval.
- [ ] Build workstation recovery point and configuration evidence were
      captured before middleware installation.

## Certificate and key checks

- [ ] Certificate subject exactly matches the approved municipal publisher
      name.
- [ ] Issuer matches the awarded public certificate authority.
- [ ] Certificate chain is trusted by Windows.
- [ ] Code Signing EKU `1.3.6.1.5.5.7.3.3` is present.
- [ ] Certificate is currently valid and has at least 90 days remaining.
- [ ] Windows reports access to the corresponding private key while the token
      is present.
- [ ] Vendor evidence confirms the private key is non-exportable.
- [ ] Certificate cannot be exported with its private key from Windows.
- [ ] Default activation secret was changed if the vendor requires that step.
- [ ] Token lockout, reset, replacement, and revocation procedures were tested
      or reviewed without disclosing secrets.

## Custody controls

- [ ] Primary and backup custodians are named in protected records.
- [ ] Locked storage location is assigned.
- [ ] Custody-transfer log is available.
- [ ] Release approver is separate from build operator where staffing permits.
- [ ] Token is removed from the workstation outside approved signing sessions.
- [ ] Activation secret is stored in the approved secrets-management process,
      separate from the token and source code.
- [ ] Lost-token and unauthorized-signing response contacts are available to
      staff.

## Read-only technical readiness verification

Set the certificate thumbprint only in the current controlled shell. Do not add
it to source, a `.env` file, a batch file, screenshots, or chat.

```bat
cd /d C:\mto
call venv\Scripts\activate
set MTO_CODE_SIGNING_CERT_THUMBPRINT=<approved-certificate-thumbprint>
python -m scripts.phase5_signing_readiness --require-ready --confirm-managed-key-custody --output logs\remediation-original-phase-5-signing-delivery-readiness.json
echo Exit code: %ERRORLEVEL%
set MTO_CODE_SIGNING_CERT_THUMBPRINT=
```

- [ ] Readiness command exited `0`.
- [ ] Python 3.11, SignTool, Inno Setup, certificate, and timestamp components
      all reported `PASS`.
- [ ] Privacy-safe report contains only a shortened thumbprint.
- [ ] Full thumbprint was cleared from the shell after verification.
- [ ] No artifact was signed during this read-only check.

## Subsequent separately approved tests

Do not perform these steps under delivery acceptance alone:

- disposable test-artifact signing and timestamp verification;
- secure-client rebuild;
- installer or uninstaller signing;
- creation of a production release tag;
- deployment to a pilot or production client; or
- first production release signing.

Each action requires an explicit approval, before/after evidence, signature
verification, audit-chain verification, and financial invariant checks where
production services or data are involved.

## Acceptance result

- Result: PASS / BLOCKED
- Non-sensitive finding references:
- Protected evidence record identifier:
- Certificate custodian approval:
- Security reviewer approval:
- Date and time:

A blocked result requires incident or vendor resolution. It must not be waived
by exporting the key, generating a self-signed replacement, disabling signature
verification, or changing the trusted publisher identity.
