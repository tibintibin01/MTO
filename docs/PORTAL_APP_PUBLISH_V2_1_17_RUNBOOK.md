# v2.1.17 guarded in-app portal publication

This release connects the desktop Publish button to the same installed, hash-pinned R4 publisher used for automatic publication. The legacy full-body website upload is retired, not enlarged or bypassed. No financial calculations, billing history, receipts, tax policy, credentials or backup/restore behavior are changed.

## Behavior

- Admin-only publish queues a background `portal_publish` job and returns promptly. The desktop polls that job without offline queuing or resubmitting on status failures. Navigating back resumes the same job.
- The API worker executes the publisher in an isolated child, preventing R4's cwd/environment/output handling from changing the running API process.
- The installed R4 helper remains immutable and SHA256-pinned. It retains read-only/repeatable-read export, shared publisher lock, masking, account isolation, private signed PUT, expiry, atomic conditional commit, bounded metadata retries and checksum/exact-byte readback.
- An explicitly approved source commit, product version and bridge revision in the protected publisher state must match the immutable Git tag. HTTP requests cannot approve source, paths, code or secrets. Any missing approval blocks; there is no legacy fallback.
- Publication status requires admin access. Acknowledged uploads without cryptographic readback show warning, not success. Failures use an error indicator, not OK. Long messages scroll; DONE remains visible.

## Coordinated deployment

Use the release-specific immutable six-file installer package and separately hash-verified deployment tools. Close client apps and pause financial entry for the maintenance window. Keep all original workflow/baseline/publisher evidence and old R4 files.

The deployment launcher uses the existing backup/preflight/baseline gates and immutable updater. For v2.1.17, its post-update workflow then invokes `scripts/install_guarded_portal_task.ps1` in a separate native PowerShell process, preserving real exit status.

The migration requires an exact approved commit matching `v2.1.17`, clean production source, owned R4 schedule/state, intact protected R4 helper and no pending publication. Type `APPROVE APP PORTAL BRIDGE v2.1.17` only during this coordinated upgrade. It preserves original control files and task XML, writes only explicit source-approval metadata, tests a demand-only SYSTEM CLI, changes only the owned daily publisher action, and tests that actual daily task under SYSTEM. The four triggers, principal/settings, original tools/evidence and other API/backup/operations tasks remain untouched. No automatic rollback or candidate deletion occurs.

If a step blocks, stop and return its safe result, workflow ID and evidence path. Do not rerun Deploy, replace the baseline, delete genuine collections, rotate secrets, change tasks manually or suppress the failing gate. Unresolved candidates require read-only inspection before resuming.

## Client pilot and finalization

Install the matching v2.1.17 client after automated server gates and migration pass. Existing v2.1.16 clients should not use the publishing button during this transition; their old UI cannot monitor the new background response properly.

As administrator, click PUBLISH PORTAL once. Confirm queued/progress states and a final Website Publication Verified result with current publication date, record count and checksum. Confirm the full DONE button and error/warning semantics using synthetic tests, not a live destructive action. Navigate away/back while a job is pending and confirm the same job is monitored. Check property/assessment/ledger/export workflows and duplicate-account isolation.

Only finalize Phase 9 after the actual client pilot, update/reconnection, isolated restore evidence and named operations ownership are truthfully accepted. Automated checks and local visual previews are not production certification. Keep payment entry paused through strict baseline comparison; legitimate collections after activation must be reviewed, not deleted to force equality.
