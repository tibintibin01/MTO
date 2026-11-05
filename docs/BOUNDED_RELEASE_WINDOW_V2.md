# v2.1.26: prepare first, bound the release window, accept later

## Scope and predecessor

This opt-in workflow is for the reviewed v2.1.26 account-routing hotfix. It is a
financial workflow change, not a read-only-report change. It preserves financial
formulae, schema, official history, runtime requirements and the API/minimum-client
contract. Unsupported changes require a different reviewed release profile.

The source fix resolves a proven same-year predecessor/successor chain without
deleting old TDs or changing their years. See SAME_YEAR_TD_PAYMENT_RESOLUTION.md.

The exact v2.1.25 predecessor was accepted by a separate controlled continuation;
the original strict workflow intentionally stayed blocked. Preparation validates
the pinned completion and all required hashed original/checkpoint/manual/gate
evidence using the already-validated read-only functions. It must never fabricate
original Finalize success, replace a baseline or erase an aborted attempt.

## Delivery

The application archive remains the immutable six-artifact internal package.
The separate tools kit contains the new workflow/launcher and three hash-pinned
legacy helper files. Their main bodies are NEVER executed. Only allowlisted
validation/capture functions are imported after exact byte-hash verification.
The launcher's checks cover every executable helper before any workflow starts.

`scripts.create_bounded_release_handoff` generates this reviewed v2.1.26 kit.
It requires the original checkpoint and r2 acceptance helpers as explicit local
inputs and refuses changed bytes or an existing destination. It does not publish,
Stage, deploy, start tasks or set manual controls. Original toolkits are untouched.

The existing `run_release_workflow.ps1` and immutable updater are unchanged.
Do not use the old generic launcher to deploy this new workflow profile.

## Operator sequence

| Stage | Office financial entry | Actions and evidence |
| --- | --- | --- |
| Transfer/staging | Continues | Verify source/tag, packages, Defender, risk, predecessor acceptance and publisher ownership before maintenance. |
| Prepare | Continues | Read-only existing readiness/audit/financial gates; validate unchanged runtime/schema/protocol; download all hash-locked runtime wheels and verify an offline install plan. Print a new WorkflowId. |
| Activate prepared ID | Paused on all clients | Require explicit maintenance approval; create/verify a fresh normal backup; capture the immutable before baseline; run the existing updater and owned publisher approval; run strict immediate after checks. |
| Essential pilot | Still paused | On a matching verified client, inspect account/ledger, target resolution and required exports without saving dummy production data. |
| Resume prepared ID | Paused until PASS, then may resume | Confirm essential read-only pilot; repeat current controls and strict comparison to the ORIGINAL before baseline; write immutable resume evidence and print explicit authorization. |
| Verify/Finalize after Resume | Continues unless a failing control requires incident action | Verify the original release-window proof; run current readiness/reconciliation/audit controls; collect genuine full-pilot/restore/ownership acceptance. Do not demand unchanged business totals since deployment. |

Preparation is not a maintenance-window approval. A successful source build or
simulated rehearsal is not a measured production outage duration. Agree the
actual window and escalation plan before Activate; do not promise zero downtime
or a particular number of minutes without a server rehearsal.

The essential pilot must include the affected same-year TD pattern and correct
account selection. Do not enter fictitious ORs or save test payments to force a
successful pilot. After explicit Resume, normal genuine business payments can
be used in the authorized office workflow; later acceptance does not mislabel
their new totals as a deployment mutation.

## Runtime preparation

Only the target's Git lock bytes are used for the wheel download. Prepare uses
hash checking and binary-only wheels, then resolves an offline, ignore-installed,
hash-checked install plan. The completed wheel set and lock are hashed and later
rechecked before activation. Unexpected files/subdirectories or changed hashes
block activation. Runtime/schema differences or a changed API/minimum-client
contract block this profile.

The existing updater still constructs Windows virtual environments at their final
path, retains the old runtime for its bounded rollback rules, runs migrations/
compatibility checks, restarts the supervisor, and compares financial invariants.
Only its child process receives temporary PIP_NO_INDEX, PIP_FIND_LINKS,
PIP_NO_INPUT and disabled version-check settings. All are restored afterward.
There is no pip configuration change and no unapproved runtime dependency update.
Git/source and owned portal verification still have their existing controls.

## Evidence and acceptance meaning

The before baseline is created once and pinned. Each check attempt has a fresh
directory. Successful activation proof binds the exact source, original baseline
and all required gate files. Resume proof binds activation proof, its own passing
comparison, essential-pilot attestation and an explicit UTC resume time.

Before Resume, a financial change blocks the strict comparison. It is never
"explained away" by replacing the baseline. After Resume, Verify/Finalize capture
current financial readiness without comparing business totals to the pre-update
totals. The comparison scope is explicitly UNCHANGED_DURING_RELEASE_WINDOW_ONLY;
post-resume activity is not attributed or individually certified by this helper.

Final acceptance requires all four genuine controls: desktop workflows/exports,
matching installed client and reconnection, reviewed isolated restore evidence,
and named operations responsibilities. Confirmation whitespace is trimmed, but
missing, wrong-version or duplicated phrases are rejected. No confirmations are
pre-filled in the generated launcher.

An immutable completion record binds the accepted gate/manual/resume/activation
evidence. A later Verify does not downgrade completed acceptance to pending. An
attempt to repeat Finalize must not overwrite the existing completion. Current
health failure is a new operational event, not permission to erase acceptance
history or assume the system remains healthy.

## Failure behavior

- Prepare failure: keep the current version in service where its current health
  permits; investigate before scheduling activation. No freeze was requested.
- Updater outcome uncertain: preserve protected updater evidence. Never rerun
  Activate blindly or infer success from current Git HEAD alone.
- Updater completed but publisher/postchecks failed: Verify the SAME WorkflowId
  while entry remains paused. Recheck owned publisher/gates, not source activation.
- Failed financial comparison inside the freeze: do not Resume, repair financial
  records, reset the checkpoint or delete genuine payments to obtain PASS.
- Failure after entry resumed: record BLOCKED_POST_RESUME and review the failed
  current control under incident procedures. Financial/audit-integrity failures
  may require pausing entry; a later acceptance prompt alone must not cause a
  day-long operational freeze. Never automatically restore over later payments.

The wrapper performs no automatic cleanup, new code rollback, data repair,
retention change, secret rotation or original-evidence rewrite. The existing
immutable updater retains its separately reviewed failure/rollback behavior.
Unsigned binaries remain internal-only under the existing bounded risk; this
workflow neither extends that acceptance nor certifies legal/COA correctness.
