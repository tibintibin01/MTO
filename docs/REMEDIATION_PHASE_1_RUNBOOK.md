# Remediation Phase 1 — Desktop/server trust boundary

This runbook belongs to the security and production-readiness remediation. It
is separate from the Verified Duplicate TD rollout.

Phase 1 removes server authority from the desktop application. `Treasury.exe`
may know the API address, an optional public CA certificate path, and its client
version. It must not receive database credentials, JWT signing keys, private
keys, server secret files, migration code, or direct access to the revenue
database.

## Implemented boundary

- Desktop startup no longer loads `.env`, validates a server signing secret, or
  imports/runs `migration_manager`.
- Desktop API helpers use a strict `server_config.json` allowlist:
  `server_url`, `ca_certificate`, and `client_version` only.
- Client technical logging is isolated from the server logger and secret vault.
- `Treasury.spec` packages client modules as code instead of copying entire
  source directories, and explicitly excludes backend, migration, ORM, database
  driver, dotenv, and server-secret modules.
- Both desktop build scripts run the trust-boundary verifier. The installer no
  longer requires or installs `.env`.
- CI runs the same verifier on every change.
- The server updater applies migrations after stopping the API and before
  restarting it. A migration failure stops the update; it cannot report a
  healthy API after a partial or failed migration.

The local SQLite cache/queue remains client state; it is not a connection to the
municipal revenue database. Removal or encryption of offline client state is a
separate reviewed change.

## Desktop configuration

Create `server_config.json` beside the source checkout for building, and beside
`Treasury.exe` for deployment. Start from `server_config.example.json`. Do not
add comments or extra fields. Never place `.env`, database credentials, API
keys, bearer tokens, JWT secrets, cloud credentials, or private keys beside the
EXE.

`ca_certificate` is a path to a public CA certificate, not a private key. Phase
2 will make authenticated TLS mandatory; Phase 1 preserves the current HTTP/LAN
compatibility so this trust-boundary change can be reviewed independently.

## Review checks before commit

From the development worktree:

```bat
call venv\Scripts\activate
python scripts\verify_desktop_trust_boundary.py --require-config
python -m pytest tests\test_client_config.py tests\test_desktop_trust_boundary.py tests\test_server_migration_entrypoint.py
python -m pytest tests
```

Review `git diff` and confirm no `.env`, `server_config.json`, certificate,
private key, generated EXE, taxpayer data, or Phase 0 baseline report is staged.

## Approved deployment sequence after review and commit

Do not perform this sequence until the Phase 1 implementation commit and push
are separately approved.

1. On the server, run **Start Hybrid Backup** and require a current cloud sync,
   restore test `SUCCESS`, and protected server/cloud storage.
2. Preserve `logs\remediation-phase-0-server.json`.
3. Run `update_mto.bat` on the server. Its migration step must complete before
   the API restarts and `/readyz` passes.
4. Capture a post-phase server baseline and compare it to Phase 0:

   ```bat
   python -m scripts.capture_remediation_baseline --database --require-ready --compare-to logs\remediation-phase-0-server.json --output logs\remediation-phase-1-server.json
   ```

5. Build the desktop in the reviewed source checkout with
   `powershell -ExecutionPolicy Bypass -File build_pyinstaller.ps1`.
6. Pilot the new EXE on one client. The production replacement target remains
   `C:\MTO\dist\Treasury.exe`; preserve its external `server_config.json` and
   do not copy `.env` from the server.
7. Verify login, property search, payment ledger, duplicate-TD separation,
   document generation, and logout before expanding to other clients.
8. Deploy the same reviewed executable to every client and record each
   workstation's completion.
9. Rotate database credentials and JWT signing keys only after every old client
   build has been removed. Rotation is a separately approved operational step.

## Rollback

If the server migration fails, leave the API stopped, preserve the error, and do
not retry blindly. Compare the database to the current verified backup and
restore only through the approved recovery procedure.

If a pilot desktop fails but the server is healthy, restore only the previous
client executable and its endpoint config. Do not restore server secrets to the
client. After credential rotation, an old secret-bearing client build must not
be returned to service.

## Phase 1 completion gate

Phase 1 is ready for review only when:

1. The source/spec/config verifier passes.
2. Focused and full automated tests pass.
3. The diff contains no sensitive or generated artifacts.
4. The server update path is fail-closed on migration error.
5. No commit, push, live server update, client deployment, or credential
   rotation occurred without its separate approval.
