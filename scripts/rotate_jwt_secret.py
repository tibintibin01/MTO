#!/usr/bin/env python3
"""Disabled legacy helper that previously displayed a JWT secret.

Production rotation must use the resumable server-only utility so database and
JWT credentials change together, active sessions are revoked, and no secret is
written to the terminal or audit report.
"""


def main() -> int:
    print("This legacy JWT-only helper is disabled for security.")
    print("Use the server-only preflight instead:")
    print("  python -m scripts.rotate_server_credentials --preflight")
    print(
        "Credential changes require a current Hybrid Backup and separate live "
        "rotation approval."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
