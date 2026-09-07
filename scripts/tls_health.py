"""Authenticated HTTPS health-check helpers for server operations."""

from __future__ import annotations

import os
from pathlib import Path
import ssl
from typing import Mapping
from urllib.parse import urlparse

from backend.tls_config import TLSConfigurationError, load_server_tls_config


def health_url(environment: Mapping[str, str] | None = None) -> str:
    env = environment if environment is not None else os.environ
    configured = env.get("MTO_SUPERVISOR_HEALTH_URL", "").strip()
    if configured:
        url = configured
    else:
        tls = load_server_tls_config(env)
        scheme = "https" if tls.enabled else "http"
        port = int(env.get("PORT", "8001"))
        url = f"{scheme}://127.0.0.1:{port}/readyz"

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise TLSConfigurationError("MTO_SUPERVISOR_HEALTH_URL must be an HTTP(S) URL.")
    tls = load_server_tls_config(env)
    if tls.required and parsed.scheme != "https":
        raise TLSConfigurationError(
            "The API health endpoint must use HTTPS when authenticated TLS is required."
        )
    return url


def ssl_context_for_health_url(
    url: str,
    environment: Mapping[str, str] | None = None,
    ca_certificate: Path | None = None,
) -> ssl.SSLContext | None:
    if urlparse(url).scheme != "https":
        return None
    env = environment if environment is not None else os.environ
    tls = load_server_tls_config(env)
    ca_file = (ca_certificate or tls.ca_certificate_file).expanduser().resolve()
    if not ca_file.is_file():
        raise TLSConfigurationError(
            f"Trusted MTO LAN CA certificate was not found: {ca_file}"
        )
    context = ssl.create_default_context(cafile=str(ca_file))
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context
