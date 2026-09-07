# -*- coding: utf-8 -*-
"""
MTO Treasury System API Server Entry Point.
Wait for the database, configure SSL certificates, and launch uvicorn.
"""
import os
import ssl

import uvicorn
from dotenv import load_dotenv

# Load environment variables before doing anything else.
load_dotenv()

# Import the configured FastAPI application instance.
from backend.app_factory import app
from backend.database import wait_for_db
from backend.tls_config import load_server_tls_config, validate_server_tls_config


if __name__ == "__main__":
    # Wait for MariaDB to be ready before accepting traffic.
    tls = load_server_tls_config()
    identity = validate_server_tls_config(tls)

    # On Windows with XAMPP, the DB takes 5-15s to start after boot.
    wait_for_db(max_attempts=10, base_delay=2.0)

    port = int(os.getenv("PORT", "8001"))
    # The office server intentionally accepts LAN clients by default. Deployments
    # may set MTO_API_HOST=127.0.0.1 when a local reverse proxy is used.
    bind_host = os.getenv("MTO_API_HOST", "0.0.0.0")  # nosec B104

    if tls.enabled:
        assert identity is not None
        print(
            f"Starting authenticated MTO API (HTTPS) on port {port}; "
            f"certificate SHA-256 {identity.fingerprint_sha256[:16]}..."
        )
        uvicorn.run(
            app,
            host=bind_host,
            port=port,
            ssl_keyfile=str(tls.private_key_file),
            ssl_certfile=str(tls.certificate_file),
            ssl_version=ssl.PROTOCOL_TLS_SERVER,
        )
    else:
        print(
            "WARNING: Starting development-only HTTP API. Production refuses "
            "to start without authenticated TLS."
        )
        uvicorn.run(app, host=bind_host, port=port)
