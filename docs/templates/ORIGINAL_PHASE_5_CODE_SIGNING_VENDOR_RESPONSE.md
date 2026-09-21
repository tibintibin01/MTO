# Original Phase 5 — Code-Signing Vendor Response Template

## Handling instructions

Complete this form for technical and commercial comparison. Store the completed
response in the municipality's protected procurement record, not in Git.

Do not include identity-document images, personal addresses, payment details,
certificate PINs, passwords, private keys, PFX/PEM files, recovery codes, or
other secrets in this form.

## Vendor and offer

- Vendor legal name:
- Certificate authority:
- Product name:
- Assurance level: OV / EV
- Key-delivery model: CA token / managed HSM / other
- Quote reference and validity date:
- Sales contact through official vendor channel:
- Proposed certificate validity:

## Mandatory eligibility response

For every item, answer **Yes** or **No** and cite the product document or
contract section.

| Requirement | Yes/No | Evidence or explanation |
| --- | --- | --- |
| Publicly trusted for Microsoft Authenticode |  |  |
| Can validate a Philippine local government entity |  |  |
| Certificate subject uses the municipality's exact validated legal name |  |  |
| Code Signing EKU `1.3.6.1.5.5.7.3.3` |  |  |
| CA-provided non-exportable hardware token or approved HSM |  |  |
| Current CA/Browser Forum key-protection compliance |  |  |
| Windows 10/11 x64 token middleware |  |  |
| Microsoft SignTool certificate-provider compatibility |  |  |
| SHA-256 file and RFC 3161 timestamp signing |  |  |
| HTTPS RFC 3161 timestamp endpoint |  |  |
| Documented 24-hour revocation channel |  |  |
| Documented token replacement and compromise response |  |  |
| Certificate can be issued without exporting a PFX/private key |  |  |

Any **No** answer to a mandatory item makes the offer technically
non-compliant unless the MTO security reviewer explicitly changes the
requirement before award.

## Identity-validation requirements

- Required government-entity documents:
- Authorized-representative evidence:
- Official-domain email requirement:
- Telephone or independent verification process:
- Translation or notarization requirements:
- Expected validation duration:
- Reasons validation may be rejected or delayed:
- Revalidation requirements at renewal:

List document types only. Do not attach personal or organizational evidence to
the Git copy of this template.

## Key custody and middleware

- Token/HSM manufacturer and model:
- Security certification and level:
- Private key generated on device/service: Yes / No
- Private key export possible: Yes / No
- User-presence, PIN, or MFA control:
- PIN attempt limit and lockout behavior:
- PIN reset and recovery process:
- Token middleware name and supported Windows versions:
- Middleware Authenticode signer:
- Supported unattended-build approval model:
- Replacement process and target time after failure:
- Revocation process and target time after compromise:

## Signing and timestamp compatibility

- Supported SignTool command model:
- Supported file digest algorithms:
- Supported RFC 3161 timestamp digest algorithms:
- Production timestamp URL:
- Timestamp service availability commitment:
- Expected verification behavior after certificate expiry:
- Windows publisher name that will be displayed:

## Commercial response

- Certificate charge:
- Token/HSM charge:
- Shipping and handling:
- Estimated customs and taxes, if vendor can provide them:
- Included signature volume:
- Overage charge:
- Reissue charge:
- Lost/damaged-token replacement charge:
- Revocation charge:
- Renewal charge and renewal terms:
- Support tier and response targets:
- Estimated validation completion:
- Estimated token delivery to the approved Philippine address:
- Refund/cancellation conditions:
- Automatic renewal enabled by default: Yes / No

## Vendor declarations

- The offer does not require an exportable private-key file: Yes / No
- All mandatory charges are disclosed: Yes / No
- All cited product documents and terms are attached to the protected
  procurement record: Yes / No
- The response remains valid until:
- Authorized vendor representative and date:

The municipality will perform its own legal, procurement, technical, and
security review. Completion of this form is not an award or purchase order.
