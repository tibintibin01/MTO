import os

import pytest


os.environ.setdefault(
    "MTO_JWT_SECRET",
    "phase2-network-boundary-test-secret-that-is-long-enough-123456789",
)

from backend.app_factory import configured_cors_origins, configured_trusted_hosts


def test_production_rejects_wildcard_cors():
    with pytest.raises(RuntimeError, match="Unsafe CORS origin"):
        configured_cors_origins(
            {"MTO_ENVIRONMENT": "production", "MTO_CORS_ORIGINS": "*"}
        )


def test_production_rejects_plaintext_lan_cors():
    with pytest.raises(RuntimeError, match="Plaintext CORS origin"):
        configured_cors_origins(
            {
                "MTO_ENVIRONMENT": "production",
                "MTO_CORS_ORIGINS": "http://192.0.2.20:3000",
            }
        )


def test_development_permits_only_plaintext_loopback_cors():
    origins = configured_cors_origins(
        {
            "MTO_ENVIRONMENT": "development",
            "MTO_CORS_ORIGINS": "http://localhost:3000",
        }
    )

    assert "http://localhost:3000" in origins


def test_production_default_cors_excludes_loopback_origins():
    origins = configured_cors_origins({"MTO_ENVIRONMENT": "production"})

    assert origins == ["https://mto-portal-dipaculao.vercel.app"]
    assert all("localhost" not in origin for origin in origins)
    assert all("127.0.0.1" not in origin for origin in origins)


def test_production_requires_explicit_trusted_host():
    with pytest.raises(RuntimeError, match="Production requires"):
        configured_trusted_hosts({"MTO_ENVIRONMENT": "production"})


def test_tls_identities_become_trusted_hosts():
    hosts = configured_trusted_hosts(
        {
            "MTO_ENVIRONMENT": "production",
            "MTO_TLS_SERVER_NAMES": "192.0.2.10,localhost,127.0.0.1",
        }
    )

    assert hosts == ["192.0.2.10", "localhost", "127.0.0.1"]


def test_vercel_runtime_hostname_is_allowed_without_wildcard():
    hosts = configured_trusted_hosts(
        {
            "MTO_ENVIRONMENT": "production",
            "VERCEL_PROJECT_PRODUCTION_URL": "https://mto.example.gov.ph",
        }
    )

    assert hosts == ["mto.example.gov.ph"]


def test_wildcard_trusted_host_is_rejected():
    with pytest.raises(RuntimeError, match="Unsafe trusted host"):
        configured_trusted_hosts(
            {"MTO_ENVIRONMENT": "production", "MTO_TRUSTED_HOSTS": "*"}
        )


@pytest.mark.parametrize(
    "unsafe_host",
    [
        "https://mto.example.gov.ph/admin",
        "https://user:password@mto.example.gov.ph",
        "http://mto.example.gov.ph",
        "mto.example.gov.ph:invalid",
    ],
)
def test_malformed_or_plaintext_production_trusted_host_is_rejected(unsafe_host):
    with pytest.raises(RuntimeError, match="Unsafe trusted host"):
        configured_trusted_hosts(
            {"MTO_ENVIRONMENT": "production", "MTO_TRUSTED_HOSTS": unsafe_host}
        )
