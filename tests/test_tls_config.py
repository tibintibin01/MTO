from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.tls_config import (
    ServerTLSConfig,
    TLSConfigurationError,
    load_server_tls_config,
    validate_server_tls_config,
)
from scripts.provision_server_tls import create_certificate_bundle


NAMES = ("192.0.2.10", "localhost", "127.0.0.1")


@pytest.fixture
def tls_material(tmp_path):
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    bundle = create_certificate_bundle(
        NAMES,
        ca_key_size=2048,
        server_key_size=2048,
    )
    (tls_dir / "mto-lan-ca.pem").write_bytes(bundle.ca_certificate)
    (tls_dir / "server-cert.pem").write_bytes(bundle.server_certificate)
    (tls_dir / "server-key.pem").write_bytes(bundle.server_private_key)
    config = ServerTLSConfig(
        enabled=True,
        required=True,
        directory=tls_dir,
        certificate_file=tls_dir / "server-cert.pem",
        private_key_file=tls_dir / "server-key.pem",
        ca_certificate_file=tls_dir / "mto-lan-ca.pem",
        server_names=NAMES,
    )
    return config, bundle


def test_valid_ca_signed_server_identity_passes(tls_material):
    config, _bundle = tls_material

    identity = validate_server_tls_config(config)

    assert identity is not None
    assert set(NAMES).issubset(identity.server_names)
    assert len(identity.fingerprint_sha256) == 64


def test_missing_required_server_identity_fails(tls_material):
    config, _bundle = tls_material

    with pytest.raises(TLSConfigurationError, match="missing required identity"):
        validate_server_tls_config(
            replace(config, server_names=NAMES + ("mto-server.example",))
        )


def test_mismatched_private_key_fails(tls_material):
    config, _bundle = tls_material
    different = create_certificate_bundle(
        NAMES,
        ca_key_size=2048,
        server_key_size=2048,
    )
    config.private_key_file.write_bytes(different.server_private_key)

    with pytest.raises(TLSConfigurationError, match="do not match"):
        validate_server_tls_config(config)


def test_untrusted_ca_fails(tls_material):
    config, _bundle = tls_material
    different = create_certificate_bundle(
        NAMES,
        ca_key_size=2048,
        server_key_size=2048,
    )
    config.ca_certificate_file.write_bytes(different.ca_certificate)

    with pytest.raises(TLSConfigurationError, match="not signed"):
        validate_server_tls_config(config)


def test_expired_server_certificate_fails(tls_material):
    config, _bundle = tls_material

    with pytest.raises(TLSConfigurationError, match="not currently valid"):
        validate_server_tls_config(
            config,
            now=datetime.now(timezone.utc) + timedelta(days=398),
        )


def test_production_cannot_disable_tls(tmp_path):
    tls_dir = tmp_path / "ProgramData" / "MTO" / "tls"
    env = {
        "MTO_ENVIRONMENT": "production",
        "MTO_REQUIRE_TLS": "0",
        "PROGRAMDATA": str(tmp_path / "ProgramData"),
        "MTO_TLS_DIR": str(tls_dir),
        "MTO_TLS_SERVER_NAMES": ",".join(NAMES),
    }

    config = load_server_tls_config(env)

    assert config.required is True
    assert config.enabled is True
    with pytest.raises(TLSConfigurationError, match="was not found"):
        validate_server_tls_config(config)


def test_required_tls_rejects_private_key_outside_protected_directory(tmp_path):
    tls_dir = tmp_path / "ProgramData" / "MTO" / "tls"
    env = {
        "MTO_ENVIRONMENT": "production",
        "PROGRAMDATA": str(tmp_path / "ProgramData"),
        "MTO_TLS_DIR": str(tls_dir),
        "MTO_TLS_KEY_FILE": str(tmp_path / "outside" / "server-key.pem"),
        "MTO_TLS_SERVER_NAMES": ",".join(NAMES),
    }

    with pytest.raises(TLSConfigurationError, match="protected MTO_TLS_DIR"):
        load_server_tls_config(env)


def test_required_tls_rejects_unspecified_identity(tmp_path):
    with pytest.raises(TLSConfigurationError, match="MTO_TLS_SERVER_NAMES"):
        load_server_tls_config(
            {
                "MTO_ENVIRONMENT": "production",
                "MTO_TLS_DIR": str(tmp_path),
            }
        )


def test_production_rejects_tls_directory_outside_program_data(tmp_path):
    env = {
        "MTO_ENVIRONMENT": "production",
        "PROGRAMDATA": str(tmp_path / "ProgramData"),
        "MTO_TLS_DIR": str(tmp_path / "Desktop" / "tls"),
        "MTO_TLS_SERVER_NAMES": ",".join(NAMES),
    }

    with pytest.raises(TLSConfigurationError, match="protected server path"):
        load_server_tls_config(env)
