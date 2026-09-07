# Phase 2 — Authenticated TLS and LAN Boundary

## Purpose

Phase 2 encrypts and authenticates every connection between `Treasury.exe` and
the MTO API. It removes the former HTTP fallback and the desktop client's
certificate-verification bypass. Production startup now fails closed if the
certificate, key, CA, validity period, server identity, or configuration is
wrong.

This phase does not modify MariaDB records or financial data. The public Vercel
inquiry portal remains a separate HTTPS service and must not receive the LAN CA
private key.

## Trust model

- `mto-lan-ca-key.pem` is the CA private key. It stays only on the server in
  `C:\ProgramData\MTO\tls` and is restricted to the provisioning administrator,
  Administrators, and SYSTEM.
- `server-key.pem` is the API private key. It also stays only in the protected
  server TLS directory.
- `server-cert.pem` is the CA-signed API identity.
- `mto-lan-ca.pem` is public trust material. This is the only TLS file copied to
  client PCs, normally as `certificates\mto-lan-ca.pem` beside `Treasury.exe`.
- `server_config.json` remains external to `Treasury.exe` and contains only the
  HTTPS endpoint, public CA path, and optional client version.

The address in `server_url` must exactly match an IP address or DNS name in the
certificate Subject Alternative Name list. Do not use `localhost` from a client
PC; that name means the client PC itself.

## Required production settings

Replace `<SERVER_IP>` with the server's reserved/static LAN address and add the
approved server hostname only if clients actually use it.

```dotenv
MTO_ENVIRONMENT=production
MTO_REQUIRE_TLS=1
MTO_TLS_DIR=C:/ProgramData/MTO/tls
MTO_TLS_CERT_FILE=C:/ProgramData/MTO/tls/server-cert.pem
MTO_TLS_KEY_FILE=C:/ProgramData/MTO/tls/server-key.pem
MTO_TLS_CA_FILE=C:/ProgramData/MTO/tls/mto-lan-ca.pem
MTO_TLS_SERVER_NAMES=<SERVER_IP>,localhost,127.0.0.1
MTO_TRUSTED_HOSTS=<SERVER_IP>,localhost,127.0.0.1
MTO_SUPERVISOR_HEALTH_URL=https://127.0.0.1:8001/readyz
```

Client configuration:

```json
{
  "server_url": "https://<SERVER_IP>:8001",
  "ca_certificate": "certificates/mto-lan-ca.pem",
  "client_version": "2.1.0"
}
```

## Implementation verification — no live cutover

Run from the isolated implementation worktree:

```bat
python -m pytest tests\test_client_config.py tests\test_tls_config.py tests\test_tls_health.py tests\test_notification_tls.py tests\test_desktop_trust_boundary.py tests\test_api_supervisor.py -q
python -m pytest -q
python scripts\verify_desktop_trust_boundary.py
git diff --check
```

Do not commit, push, provision certificates, change `.env`, build the live EXE,
or restart the API until the Phase 2 implementation review is approved.

## Controlled activation procedure

Activation requires a separate approval and a maintenance window. Keep the
current HTTP client package and server `.env` backup available for rollback.

1. Confirm the server has a reserved/static LAN address. Record `ipconfig` and
   the exact address clients use.
2. Run Hybrid Backup. Require a new cloud timestamp, restore verification
   `SUCCESS`, and protected server/cloud storage.
3. Stop the MTO API and confirm port 8001 is free.
4. Run the read-only TLS preflight:

   ```bat
   python -m scripts.provision_server_tls --preflight --server-name <SERVER_IP> --server-name localhost --server-name 127.0.0.1
   ```

5. After explicit live-provisioning approval, create the CA and server identity:

   ```bat
   python -m scripts.provision_server_tls --apply --server-name <SERVER_IP> --server-name localhost --server-name 127.0.0.1
   ```

6. Record the displayed SHA-256 fingerprint and expiry. Never display or copy a
   private key. Copy only `C:\ProgramData\MTO\tls\mto-lan-ca.pem` to the
   controlled build/staging folder as `certificates\mto-lan-ca.pem`.
7. Update the server `.env` with the required production settings above. Create
   the external client `server_config.json` using the same `<SERVER_IP>`.
8. Build and verify the desktop package. The build must fail if the URL is HTTP,
   the public CA is missing, or private TLS material is found in `dist`.
9. Start the scheduled API task and require authenticated readiness:

   ```bat
   powershell -NoProfile -ExecutionPolicy Bypass -File C:\MTO\scripts\wait_for_mto_api.ps1 -TimeoutSeconds 90
   ```

10. On one pilot client, place `Treasury.exe`, `server_config.json`, and the
    `certificates` directory together. Verify login, Property Records, Payment
    Ledger, duplicate TD separation, one PDF, notifications, logout, and reopen.
11. Verify an intentionally wrong server IP or untrusted CA is rejected with a
    secure-connection error and never queues an offline write.
12. Expand to the remaining clients only after the pilot is accepted.

## Rollback

If the API or pilot fails:

1. Stop the API and do not deploy to more clients.
2. Restore the pre-cutover server `.env` and prior client package/config.
3. Restart the prior API runtime and run its readiness check.
4. Confirm login and one read-only property lookup.
5. Preserve the TLS provisioning report and logs for diagnosis. Do not delete or
   expose private keys. Leaving protected unused TLS files on the server is safer
   than copying them during troubleshooting.

Rollback does not require database restore because Phase 2 makes no database
schema or record changes.

## Renewal and rotation

The server certificate is issued for 397 days and the internal CA for five
years. Schedule renewal review at least 60 days before expiry. A CA rotation
requires all clients to receive the new public CA as one coordinated rollout;
`--replace` must therefore be used only under a separately approved maintenance
procedure.
