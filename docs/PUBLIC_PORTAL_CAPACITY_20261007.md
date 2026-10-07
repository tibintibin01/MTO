# Portal capacity and deployment status

Status: **implementation/local validation; NOT DEPLOYED**. No GitHub push, live
upload, Windows task upgrade, financial write, secret rotation or API restart has
been performed by this change. The working R2 publisher remains in place.

## Implemented transport

The website adds authenticated prepare/commit endpoints for `private-direct-v1`.
The original single-upload endpoint remains compatible with the installed R2
publisher. Prepare/commit JSON bodies are limited to 16 KiB. The full gzip goes
directly to the existing private Vercel Blob store using a signed URL scoped to
one immutable staging pathname, PUT only, gzip only, exact upload size and a
20-minute lifetime. No Blob read-write token or signing key is sent to the office.

Prepare captures the current Blob ETag in a server-authenticated ticket. Commit
verifies gzip and expanded-body SHA256, exact lengths, bounded decompression,
record count, schema, account isolation and masked owner/PIN/receipt fields. A
conditional `ifMatch` write prevents an older upload from replacing a newer one.
The previous current snapshot keeps serving until verification succeeds. A retry
after a lost response checks the actual stored bytes rather than writing again.
Only the exact helper staging object is deleted after successful promotion.

The new transport cap is **32 MiB compressed**, with the existing **60 MiB expanded**
cap retained. No accounts, histories or monetary fields are removed. Exact original
Python JSON bytes are preserved during storage; health reports their computed hash
for independent readback. Preview/development Vercel deployments cannot issue write
credentials or commit data through the new endpoints.

The signed upload path and conditional writes use the installed @vercel/blob 2.4.0
API documented at:

- <https://vercel.com/docs/vercel-blob/vercel-signed-urls>
- <https://vercel.com/docs/vercel-blob>

The Windows R3 helper is a **draft** and is not approved for transfer or execution.
It must retain the original source pin, read-only SQL transaction, protected
evidence, masking, old-snapshot preservation and named-task ownership controls.
Its packaging, task upgrade and end-to-end server checks must finish after the
website's deployment gate is resolved. Do not distribute a draft tools directory.

## Local checks

- Production build and TypeScript checks passed.
- Synthetic private-publication tests passed, including a >4.5 MB gzip, integrity
  rejection, incomplete uploads, conditional-update conflict and idempotent retry.
  The latest run passed 100 checks, including refusal to write from Vercel preview.
- 80 synthetic production-server browser/API checks passed at 320, 390 and 1440 px.
  Search remains within the initial viewport; history failure is not shown as zero
  payments or an empty history; publication controls reject unauthenticated callers.
- Mobile and history-error screenshots were visually inspected; no real taxpayers
  or municipal database were used in these tests.
- Lint has zero errors and six pre-existing warnings in redirected legacy admin pages.
  The existing Next.js middleware-convention deprecation warning remains.

## Approved, scoped build-only security exception

A fresh audit found patched advisories for sharp and postcss-selector-parser.
Targeted overrides install **sharp 0.35.5** and **postcss-selector-parser 7.1.6**
without a forced Tailwind/framework upgrade. The production-only npm audit now
reports zero known vulnerabilities.

The complete dependency audit still reports seven high-severity package findings
that trace to **one unpatched advisory**, GHSA-vfj7-8cjw-p6xm (braces <=3.0.3), in
development-only Tailwind/lint/glob tooling. `npm ls braces --omit=dev` shows no
production dependency instance. That fact is not a claim of formal security
certification or proof that every possible use is unreachable.

Primary advisory references:

- <https://github.com/advisories/GHSA-vfj7-8cjw-p6xm> (no patched version published)
- <https://github.com/advisories/GHSA-rj75-hqrm-r3gf> (patched in 7.1.6)
- <https://github.com/advisories/GHSA-wq5f-xc86-pv6w> (patched in 0.35.5)

The human operator explicitly replied **approve** on 2026-10-07. The approval is
recorded separately in `governance/accepted-risks/public-portal-build-only-braces-20261007.json`.
The audit policy checks both complete and production reports, the dependency lock,
trusted same-repository source and the expiring approval. Only this advisory's
development-only graph is accepted. Every production finding and unrelated
moderate/high/critical development finding remains blocking. Fork and
pull_request_target contexts cannot use the exception; it cannot renew itself.
The review date remains **2026-10-14**. This does not claim the advisory was fixed.

Existing unsigned-desktop risk acceptance is not authorization for this separate
website build dependency exception and has not been changed.
