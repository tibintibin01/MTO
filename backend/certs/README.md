# MTO LAN TLS Certificate Management

The legacy self-signed `backend/certs/cert.pem` workflow is retired. Production
uses an internal MTO LAN certificate authority and fails closed if TLS material
is missing, expired, untrusted, mismatched, or missing an approved server
identity.

Canonical procedure: [Phase 2 authenticated TLS runbook](../../docs/REMEDIATION_PHASE_2_RUNBOOK.md).

Managed server files live under `C:\ProgramData\MTO\tls`:

- `mto-lan-ca-key.pem` — CA private key; server only.
- `server-key.pem` — API private key; server only.
- `server-cert.pem` — CA-signed API certificate.
- `mto-lan-ca.pem` — public CA certificate; the only TLS file copied to clients.

Never place private keys in this repository, `dist`, an installer, a client PC,
email, chat, or cloud backup intended for ordinary application files. The
provisioning tool applies an ACL restricted to the provisioning administrator,
Administrators, and SYSTEM.

Use the controlled server-only tool:

```bat
python -m scripts.provision_server_tls --preflight --server-name <STATIC_SERVER_IP> --server-name localhost --server-name 127.0.0.1
```

Certificate creation, replacement, configuration, API restart, and client
deployment require the separate live-activation approval described in the
runbook.
