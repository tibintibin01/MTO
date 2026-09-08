import pytest
from pydantic import ValidationError

from utils.config import MTOSettings


def _production_settings(monkeypatch, **overrides):
    monkeypatch.setenv("MTO_ENVIRONMENT", "production")
    values = {
        "MTO_DB_USER": "mto_app",
        "MTO_DB_NAME": "property_system",
        "MTO_DB_PASSWORD": "production-database-password-123456789",
    }
    values.update(overrides)
    return MTOSettings(_env_file=None, **values)


def test_production_accepts_password_resolved_by_base_settings(monkeypatch):
    monkeypatch.delenv("MTO_DB_PASSWORD", raising=False)

    settings = _production_settings(monkeypatch)

    assert settings.DB_PASSWORD == "production-database-password-123456789"


@pytest.mark.parametrize(
    "password",
    [
        "",
        "CHANGE_ME",
        "your_secure_db_password",
        "your_secure_db_password_min_16_chars",
    ],
)
def test_production_rejects_blank_or_placeholder_resolved_password(
    monkeypatch, password
):
    monkeypatch.delenv("MTO_DB_PASSWORD", raising=False)

    with pytest.raises(ValidationError, match="cannot be empty or a placeholder"):
        _production_settings(monkeypatch, MTO_DB_PASSWORD=password)


def test_production_rejects_root_database_user(monkeypatch):
    with pytest.raises(ValidationError, match="MTO_DB_USER=root is not allowed"):
        _production_settings(monkeypatch, MTO_DB_USER="root")
