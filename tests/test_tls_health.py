import ssl

import pytest

from backend.tls_config import TLSConfigurationError
from scripts.provision_server_tls import (
    create_certificate_bundle,
    normalize_server_names,
    validate_tls_directory,
)
from scripts.tls_health import health_url, ssl_context_for_health_url


def _production_env(tmp_path):
    program_data = tmp_path / "ProgramData"
    tls_dir = program_data / "MTO" / "tls"
    tls_dir.mkdir(parents=True)
    bundle = create_certificate_bundle(
        ("192.0.2.10", "localhost", "127.0.0.1"),
        ca_key_size=2048,
        server_key_size=2048,
    )
    ca_path = tls_dir / "mto-lan-ca.pem"
    ca_path.write_bytes(bundle.ca_certificate)
    return {
        "MTO_ENVIRONMENT": "production",
        "PROGRAMDATA": str(program_data),
        "MTO_TLS_DIR": str(tls_dir),
        "MTO_TLS_CA_FILE": str(ca_path),
        "MTO_TLS_SERVER_NAMES": "192.0.2.10,localhost,127.0.0.1",
    }


def test_production_health_defaults_to_authenticated_https(tmp_path):
    env = _production_env(tmp_path)

    target = health_url(env)
    context = ssl_context_for_health_url(target, env)

    assert target == "https://127.0.0.1:8001/readyz"
    assert context is not None
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2


def test_production_rejects_plaintext_health_override(tmp_path):
    env = _production_env(tmp_path)
    env["MTO_SUPERVISOR_HEALTH_URL"] = "http://127.0.0.1:8001/readyz"

    with pytest.raises(TLSConfigurationError, match="must use HTTPS"):
        health_url(env)


def test_https_health_requires_public_ca(tmp_path):
    env = _production_env(tmp_path)
    env["MTO_TLS_CA_FILE"] = str(
        tmp_path / "ProgramData" / "MTO" / "tls" / "missing.pem"
    )

    with pytest.raises(TLSConfigurationError, match="was not found"):
        ssl_context_for_health_url("https://127.0.0.1:8001/readyz", env)


def test_provisioning_requires_lan_identity():
    with pytest.raises(ValueError, match="LAN-reachable"):
        normalize_server_names(["localhost", "127.0.0.1"])


def test_provisioning_rejects_wildcard_identity():
    with pytest.raises(ValueError, match="Invalid server identity"):
        normalize_server_names(["*.example.test"])


def test_provisioning_rejects_unprotected_key_directory(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.provision_server_tls.os.name", "nt")
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))

    with pytest.raises(ValueError, match="protected server path"):
        validate_tls_directory(tmp_path / "Desktop" / "tls")
