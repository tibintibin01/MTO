import asyncio
import inspect
import os
import tomllib
from pathlib import Path

os.environ.setdefault(
    "MTO_JWT_SECRET",
    "release_identity_test_only_0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ",
)

from api_clients import system_service
from backend.app_factory import app
from backend.routes.health import api_version
from mto_version import (
    API_VERSION,
    MIN_CLIENT_VERSION,
    PRODUCT_NAME,
    PRODUCT_VERSION,
)
from scripts.check_dependency_policy import validate_repository

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_project_metadata_uses_authoritative_product_version_module():
    project = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert "version" not in project["project"]
    assert "version" in project["project"]["dynamic"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "mto_version.PRODUCT_VERSION"
    }
    assert "mto_version" in project["tool"]["setuptools"]["py-modules"]


def test_dependency_policy_accepts_authoritative_dynamic_version():
    findings, _counts = validate_repository(PROJECT_ROOT)

    assert findings == []


def test_api_metadata_uses_authoritative_product_version():
    assert app.version == PRODUCT_VERSION

    payload = asyncio.run(api_version())

    assert payload == {
        "api_version": API_VERSION,
        "min_client_version": MIN_CLIENT_VERSION,
        "app_name": PRODUCT_NAME,
        "app_version": PRODUCT_VERSION,
        "status": "online",
    }


def test_desktop_compatibility_default_uses_api_contract(monkeypatch):
    monkeypatch.setattr(
        system_service,
        "get_api_version",
        lambda: {
            "api_version": API_VERSION,
            "min_client_version": MIN_CLIENT_VERSION,
        },
    )

    default = (
        inspect.signature(system_service.check_version_compatibility)
        .parameters["client_version"]
        .default
    )
    result = system_service.check_version_compatibility()

    assert default == API_VERSION
    assert result["compatible"] is True
    assert result["server_version"] == API_VERSION
    assert result["min_client_version"] == MIN_CLIENT_VERSION
