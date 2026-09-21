# Original Phase 5 — Public Code-Signing Certificate Procurement Package

## Document control

- **Purpose:** procure one publicly trusted organization-validation code-signing
  identity for the MTO Treasury desktop release process.
- **Status:** request-for-quotation and approval package; no vendor selected.
- **Evaluation date:** 2026-09-21.
- **Technical owner:** MTO Treasury system owner.
- **Business owner:** to be assigned by the municipality.
- **Procurement owner:** to be assigned through the municipality's approved
  procurement process.

This package does not authorize a purchase, payment, certificate request,
identity-validation submission, token shipment, certificate installation, or
artifact signing. Each of those actions remains subject to the municipality's
normal authority and a separate technical activation approval.

## Executive decision

The required product class is:

- a publicly trusted **Organization Validation (OV) code-signing
  certificate**;
- issued to the municipality's exact legally validated name;
- delivered on a certificate-authority-provided hardware token, or an
  equivalently compliant managed HSM service if separately approved;
- valid for Microsoft Authenticode signing of Windows PE executables and Inno
  Setup installer/uninstaller artifacts;
- supported on the approved Windows build workstation;
- accompanied by an RFC 3161 SHA-256 timestamp service; and
- backed by documented revocation, replacement, renewal, and incident support.

EV code signing is not required for the present scope because MTO does not
build Windows kernel drivers. A vendor may quote EV as a clearly separated
alternative, but it must not silently replace the requested OV option or be
selected without a documented business justification.

An ad-hoc self-signed certificate, an employee-owned certificate, a certificate
issued to a contractor, or a private key stored as an exportable PFX file is not
acceptable for production.

## Why Microsoft Artifact Signing is not the current selection

As of the evaluation date, Microsoft documents Public Trust onboarding for a
limited list of organization locations that does not include the Philippines.
Private Trust does not provide public Windows trust by default and would require
separate controlled trust deployment to every relying client. The municipality
therefore needs a conventional publicly trusted organizational code-signing
certificate unless Microsoft's eligibility rules change before procurement.

Procurement must re-check the current Microsoft eligibility page before award:

<https://learn.microsoft.com/azure/artifact-signing/quickstart>

If Philippine Public Trust eligibility becomes available, return to technical
and procurement review rather than changing the solution during checkout.

## Organizational information to confirm outside Git

The procurement and legal offices must confirm the following from authoritative
municipal records. Do not fill personal information into this repository.

- exact legal name that the certificate authority must validate;
- government entity type and legal basis or registration evidence;
- official physical and postal address;
- official website and municipality-controlled email domain;
- authorized requesting officer and certificate custodian;
- official telephone verification channel;
- token shipping recipient and controlled delivery address;
- tax, customs, foreign-currency, and payment requirements; and
- authority to accept the certificate authority's subscriber agreement.

The validated name will appear to Windows users as the software publisher. It
must be approved by the municipality before the certificate request is filed.

## Intended technical use

The vendor must evaluate the certificate for this exact scope:

- Windows 10 and Windows 11 desktop clients;
- `Treasury.exe`, built with PyInstaller;
- `MTO_Treasury_Setup.exe`, built with Inno Setup;
- the Inno Setup-generated uninstaller;
- Microsoft Authenticode with SHA-256 file and timestamp digests;
- low-volume release signing on one controlled Windows x64 build workstation;
- no Windows kernel drivers;
- no TLS server authentication; and
- no document, email, user-authentication, or unrelated certificate use.

## Mandatory vendor requirements

A response is technically compliant only when every mandatory item below is
answered **Yes** with supporting detail.

### Public trust and identity

- The vendor is a publicly trusted certificate authority for Microsoft
  Authenticode code signing.
- The vendor can validate and issue to a Philippine local government unit or
  equivalent government entity.
- The certificate subject will contain the municipality's exact validated legal
  identity, not an employee, reseller, developer, or contractor identity.
- The issued certificate includes the Code Signing EKU
  `1.3.6.1.5.5.7.3.3`.
- The vendor identifies all validation documents, verification calls, language
  or translation requirements, and expected validation time before award.

### Private-key protection

- The private key is generated and retained on a CA-provided hardware token or
  separately approved compliant HSM.
- The key is non-exportable and cannot be delivered as a PFX, PEM, or other
  copyable private-key file.
- The token or HSM protection meets current CA/Browser Forum code-signing
  requirements and the vendor identifies the applicable certification.
- Signing requires an authorized custodian action and protected PIN, MFA, or
  equivalent activation control.
- The vendor documents PIN reset, lockout, token failure, replacement,
  revocation, and compromise procedures.

### Windows build compatibility

- The certificate and token middleware support the approved 64-bit Windows
  build workstation.
- The certificate is available to Microsoft SignTool through a supported
  Windows certificate-provider interface.
- Signing supports `/fd SHA256`, RFC 3161 `/tr`, and `/td SHA256`.
- The vendor supplies signed middleware and installation documentation without
  requiring private-key export.
- The vendor confirms compatibility with non-interactive build tooling while
  retaining an authorized human or managed-HSM approval control.

### Timestamp, lifecycle, and support

- An HTTPS RFC 3161 timestamp endpoint is supplied and supported for
  Authenticode.
- Correctly timestamped signatures remain verifiable after certificate expiry,
  subject to revocation and applicable platform policy.
- The quote states certificate validity, renewal lead time, revalidation needs,
  replacement charges, and shipping charges.
- The vendor provides a 24-hour certificate revocation channel and a documented
  compromise response.
- Support coverage and escalation contacts are stated for validation, token,
  middleware, signing, timestamping, and renewal incidents.

## Required commercial response

Each quote must separately identify:

- certificate product and assurance level;
- initial certificate charge;
- hardware-token or HSM charge;
- shipping, customs, taxes, foreign-exchange, and handling costs;
- annual renewal cost and whether renewal is automatic;
- included signature quota and overage charges, if any;
- validation and delivery lead times;
- reissue, replacement, and revocation costs;
- support tier and response targets;
- quote validity date; and
- complete terms, subscriber agreement, privacy terms, and refund/cancellation
  conditions.

Prices copied from public web pages are planning estimates only. The signed
vendor quotation and municipal procurement record are authoritative.

## Vendor evaluation matrix

Procurement should obtain comparable responses using
`templates/ORIGINAL_PHASE_5_CODE_SIGNING_VENDOR_RESPONSE.md` and score only
offers that pass every mandatory technical control.

| Category | Weight | Mandatory fail condition |
| --- | ---: | --- |
| Public trust and Philippine government eligibility | 25% | Not publicly trusted or cannot validate the municipality |
| Non-exportable key custody | 25% | Exportable/private-key file or uncontrolled signing |
| Windows and SignTool compatibility | 20% | Cannot sign and timestamp all required artifacts |
| Incident, revocation, replacement, and support | 15% | No timely revocation or token replacement process |
| Total evaluated lifecycle cost | 10% | Hidden mandatory charges or unaffordable renewal |
| Delivery and validation schedule | 5% | Cannot meet the approved release schedule |

Lowest price alone must not override a mandatory trust or key-custody control.
No vendor is preferred or selected by this document.

## Separation of duties

At minimum, assign these named roles in the protected procurement record:

- **Requesting officer:** confirms business need and legal publisher name.
- **Procurement officer:** conducts quotation, award, and payment processes.
- **Identity-validation contact:** supplies approved organizational evidence.
- **Certificate custodian:** controls the token and activation secret.
- **Release approver:** authorizes each production release signing event.
- **Build operator:** prepares the reproducible release but does not approve it.
- **Security reviewer:** verifies readiness, signature evidence, and custody.

One person may hold more than one role only when municipal policy permits it,
but the release approver and build operator should remain separate whenever
staffing allows.

## Token custody minimum controls

- Record the token as a controlled municipal asset without recording its PIN.
- Keep it in locked storage when not used and record custody transfers.
- Never leave the token continuously attached to the build workstation.
- Store the activation secret only in an approved secrets-management process,
  separate from the token and source repository.
- Do not transmit the PIN through chat, email, issue trackers, screenshots, or
  the procurement response template.
- Permit signing only for an approved immutable release commit and manifest.
- Retain a signing log containing release version, artifact hashes, approver,
  operator, UTC time, and signature-verification results—but no PIN or private
  material.
- Revoke immediately after confirmed loss, compromise, unauthorized signing,
  or unrecoverable custody failure.

## Procurement approval evidence

Before placing an order, the protected municipal record must contain:

- completed comparable vendor responses;
- technical compliance review;
- legal-name and publisher-name approval;
- budget and procurement approval;
- authorized subscriber-agreement approval;
- named certificate custodian and backup incident contact;
- selected delivery method and controlled shipping address;
- renewal owner and renewal reminder date; and
- explicit approval to place the order.

Do not store identity documents, personal contact details, quotations containing
personal data, payment information, or signed agreements in Git.

## Delivery acceptance boundary

Delivery does not authorize production signing. When the token and certificate
arrive, use
`templates/ORIGINAL_PHASE_5_CODE_SIGNING_DELIVERY_ACCEPTANCE.md` under a
separately approved acceptance activity.

Acceptance must verify the package and chain of custody, Microsoft-signed token
middleware, certificate identity, Code Signing EKU, public trust, validity,
non-exportable private-key access, revocation contacts, and a privacy-safe
readiness-gate PASS. A disposable test-signing exercise and the first production
release each require separate explicit approvals.

## Current readiness state

The designated build workstation currently has:

- 64-bit Python 3.11: ready;
- Microsoft Windows SDK x64 SignTool: ready;
- Inno Setup 6: ready;
- HTTPS timestamp configuration: ready; and
- approved managed code-signing certificate: not yet procured.

No certificate purchase, installation, or signing should occur until the
procurement evidence above is approved.

## Reference material

- Microsoft Artifact Signing onboarding:
  <https://learn.microsoft.com/azure/artifact-signing/quickstart>
- Microsoft SignTool:
  <https://learn.microsoft.com/windows/win32/seccrypto/signtool>
- CA/Browser Forum Code Signing requirements:
  <https://cabforum.org/working-groups/code-signing/requirements/>
- DigiCert code-signing comparison:
  <https://www.digicert.com/signing/compare-code-signing-certificates>
- GlobalSign code-signing procurement:
  <https://shop.globalsign.com/en/code-signing>

Vendor links are reference candidates, not endorsements or award decisions.
