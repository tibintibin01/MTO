import json
from pathlib import Path

import pytest

from api_clients.client_config import ClientConfigurationError, load_client_config


def _write(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_client_config_accepts_endpoint_metadata_only(tmp_path):
    config_path = _write(
        tmp_path / "server_config.json",
        {
            "server_url": "http://192.0.2.10:8001/",
            "ca_certificate": "certificates/municipal-ca.pem",
            "client_version": "2.1.0",
        },
    )

    config = load_client_config(config_path)

    assert config.server_url == "http://192.0.2.10:8001"
    assert (
        config.ca_certificate
        == (tmp_path / "certificates" / "municipal-ca.pem").resolve()
    )
    assert config.client_version == "2.1.0"
    assert config.source_path == config_path.resolve()


@pytest.mark.parametrize(
    "field",
    ["MTO_DB_PASSWORD", "jwt_secret", "api_token", "database_url", "api_key"],
)
def test_client_config_rejects_sensitive_fields(tmp_path, field):
    config_path = _write(
        tmp_path / "server_config.json",
        {"server_url": "http://127.0.0.1:8001", field: "do-not-package"},
    )

    with pytest.raises(ClientConfigurationError, match="prohibited sensitive"):
        load_client_config(config_path)


def test_client_config_rejects_unknown_fields(tmp_path):
    config_path = _write(
        tmp_path / "server_config.json",
        {"server_url": "http://127.0.0.1:8001", "note": "legacy metadata"},
    )

    with pytest.raises(ClientConfigurationError, match="unsupported field"):
        load_client_config(config_path)


@pytest.mark.parametrize(
    "url",
    [
        "mysql://db.internal/revenue",
        "http://user:password@127.0.0.1:8001",
        "http://127.0.0.1:8001?token=secret",
    ],
)
def test_client_config_rejects_non_api_or_credentialed_urls(tmp_path, url):
    config_path = _write(tmp_path / "server_config.json", {"server_url": url})

    with pytest.raises(ClientConfigurationError):
        load_client_config(config_path)
