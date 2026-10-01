# Assessment Roll consolidation and simpler deployment

## Scope and safety boundary

Combine the visible Property Records and Assessment Roll destinations into one
Assessment Roll workspace. This is a desktop navigation/workflow change, not
a property-data migration. Keep the existing property model, financial rules,
history snapshots, API permissions, optimistic concurrency, validation,
audit events, duplicate-TD authorization, and Recycle Bin operations.

Production remains on the last certified release until a separate immutable
release is built, verified, transferred, and approved. Do not copy development
Python files directly into `C:\mto` or replace a client executable by hand.

## Implementation phases

1. Inventory the existing screens, entry points, permissions, and exports.
   Establish the certified production source and preserve the old page class
   as a development fallback and source of the shared editor/cleanup dialogs.
2. Introduce **Current Records** and **As-of-Year View**. Clearly distinguish
   live registry management from historical assessment reporting. Preserve
   search-first loading, paging, empty states, and duplicate-account identity.
3. Integrate Add Property, Edit, Delete, Data Cleanup, and both existing import
   formats. Replace the sidebar destination and redirect portfolio/command
   palette entry points. Keep the existing editor's fresh ID-based load and
   version checks. Delete means moving one account to the Recycle Bin, never
   permanent purge.
4. Test role permissions, read-only history, duplicate IDs, stale responses,
   selection changes, year filters, export scope, real Windows widget layout,
   existing financial/audit/security behavior, and release-helper failure paths.
5. Build and hand off an approved immutable release. Run server activation and
   automated checks, install the verified client, complete the pilot, and then
   perform explicit final acceptance. Preserve rollback and all evidence.

## Workspace behavior

- Current Records supports the existing PIN/TD/former-TD/owner search,
  barangay filter, and effectivity-year range. Account modification is gated
  by the existing role permissions. Admin can import/delete; encoder can
  add/edit/clean up; cashier and viewer cannot modify property records.
- As-of-Year View requires an explicit valid year. Management and current
  dossier controls are disabled, including direct keyboard/callback paths.
  The existing snapshot logic supplies historical assessment value,
  classification, and effectivity; other identifiers describe the property
  account, not a new complete historical owner registry.
- Import offers Property Records and Assessment Roll templates. These are
  existing, different import modes; neither is described as a harmless
  history-only upload. Preserve their validation preview and commit controls.
- Selecting a duplicate TD account retains its immutable internal ID. Do not
  merge accounts or choose one by TD number. The delete confirmation shows
  the selected account ID and owner. Editing fetches the current server record.
- Changing mode, filters, page, or starting a refresh invalidates the old
  selection. A delayed response cannot re-enable actions for stale rows.
- PDF/Excel exports retain their existing report scope: complete barangay
  roll and the selected historical year, not the search result or page. The
  screen makes this scope explicit.
- The visible redundant Property Records sidebar button is removed. The
  legacy implementation and shared dialogs remain in source; the underlying
  records and management services are not removed.

## Reducing server command copying

`scripts/run_release_workflow.ps1` orchestrates the approved checks. It does
not weaken or replace `update_mto.bat`'s PowerShell implementation. The
existing immutable updater still validates artifacts, approved source,
signatures or bounded risk acceptance, dependencies, migrations, readiness,
audit integrity, and financial invariants. Its interactive unsigned-release
approval and protected rollback evidence remain intact.

`scripts/create_release_workflow_handoff.py` generates a **release-specific**
tools kit from the final release manifest and approved previous production
commit. It contains a menu launcher, a release-pinned PowerShell launcher,
and the workflow helper. Both script hashes are checked before execution.
The tools ZIP is separate from the six-file application ZIP, and its SHA256
must be verified independently before anything in it is executed. The
generator only creates files; it never deploys, fetches source, or approves a
pilot. Do not generate a kit from an unpublished development manifest.

For the operator, the intended handoff is:

1. Transfer and verify the release/application and deployment-tools packages
   using the provided staging helper. Keep Windows Security active.
2. Run the verified `Upgrade-MTO-<release>.cmd` as Administrator. Choose
   **Deploy**. Approve the maintenance window and existing unsigned-release
   prompt if applicable. Backup, pre-checks, update, operations smoke test,
   Phase 9 preflight, financial comparison, and dependency checks run for you.
3. Install the independently verified installer on a pilot client and test
   the new workflow. This cannot be established by a server script alone.
4. Run the launcher again, choose **Finalize**, and enter the WorkflowId
   printed by Deploy. Fresh server checks run again. Read and explicitly
   accept each of the four manual controls before final certification.

This removes the repeated long command chains. It does not mean unattended
remote access, skipped checks, automatically accepted restore evidence, or
daily updates. Normal daily startup is unchanged.

## Evidence, failure, and recovery

- Evidence is stored outside the checkout under
  `C:\ProgramData\MTO\release-workflows\<WorkflowId>`. Restrict each new run
  folder to Administrators and SYSTEM. Keep the original pre-update baseline,
  its hash, package-manifest hash, risk-document hash, and pinned commits.
- Every verification attempt has a separate checks directory. Previous
  failed reports/logs are retained. The original baseline is never recreated
  after activation or silently replaced during resume.
- The helper stops on a nonzero native command or a failed gate. It does not
  delete unexpected files, install optional updates, disable antivirus,
  change notification policy, perform a restore, or invent a risk exception.
- **Recheck** runs only after confirmed complete activation, and only for
  the same workflow/release/package/baseline/risk identity. It does not apply
  the update again. An incomplete or ambiguous activation requires inspection
  of the existing updater's protected evidence before recovery.
- A passed preflight means **READY_FOR_PILOT**, not final certification.
  Four explicit human confirmations are still required. Unsigned internal
  distribution remains bounded by its existing governance record; do not
  distribute publicly or extend the acceptance period through this helper.
- Rollback remains the existing controlled immutable-update procedure. No
  database restore is justified solely by a UI problem. Preserve evidence
  and review any migration/financial finding before authorizing recovery.

## Pilot checklist

- Confirm the installed client version matches the new release and reconnects.
- One Assessment Roll sidebar entry; no redundant Property Records entry.
- Current search by PIN, TD, former TD, and owner; barangay/year range;
  previous/next pages; clear guidance when no results are found.
- Duplicate-TD rows remain separate. Open each account's details and editor
  to check the displayed identity, then cancel if no real change is needed.
- As-of-Year View requires a year and has no enabled management actions.
  Switching back clears stale selection. Historical/current exports show
  the intended report scope and correct PDF/Excel file types.
- Check permitted controls with admin, encoder, cashier, and viewer roles.
  Validate actual create/edit/delete/import behavior in an isolated test
  database. Do not create dummy taxpayers/payments or purge accounts in the
  production database merely to prove that a button works.
- Review current restore evidence and named operations ownership. Accept
  only evidence actually reviewed; final acceptance is not an automatic step.

Release readiness requires development checks, the immutable release checks,
and this client pilot. Local unit tests do not certify the production server.

## Development verification (2026-10-01)

Development phases 1–4 are implemented on `codex/assessment-management`.
The complete local Windows regression suite, excluding load tests, passed:
888 tests and 4 subtests. Changed-file formatting/lint checks, diff whitespace
checks, the desktop/server trust boundary, Python syntax, existing UI contracts,
and contrast-policy checks also passed. Real Windows Tk layout and isolated
Windows PowerShell parsing, SHA256, manual-acceptance, resume, and operations
failure-path checks are included in the suite.

The release target is **v2.1.16**. The v2.1.15 candidate was not handed off:
Linux CI exposed Windows-only path and log-encoding assumptions in two test
fixtures. Those fixtures now exercise native absolute paths and both PowerShell
log encodings, including explicit failure-reason assertions. No production
operation was run; the old candidate tag is preserved and must not be deployed.
Phase 5 uses the clean, approved release tag
to build the installer, provenance manifest, SBOM, six-file application archive,
and separate hash-pinned deployment kit. Building or transferring those files
does not activate production or establish client acceptance. Server activation,
the client pilot, and final certification remain operator-controlled steps.
The last user-confirmed production release remains v2.1.14 until that handoff
is completed and its evidence is reviewed.
