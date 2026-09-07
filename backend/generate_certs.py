"""Retired compatibility entry point for the unsafe legacy certificate tool."""

from __future__ import annotations


def main() -> int:
    print(
        "backend.generate_certs has been retired because it created an "
        "untrusted, localhost-only certificate in a hard-coded user path."
    )
    print(
        "Use: python -m scripts.provision_server_tls --preflight "
        "--server-name <STATIC_SERVER_IP> --server-name localhost "
        "--server-name 127.0.0.1"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
