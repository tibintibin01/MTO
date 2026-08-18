import json

import pytest

from scripts import migrate_r2_vault as migration
from utils.secrets_vault import resolve_secrets_vault_path


def _phase3_vault():
    return {
        "MTO_BACKUP_S3_STORAGE_ENABLED": "true",
        "MTO_BACKUP_S3_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
        "MTO_BACKUP_S3_ACCESS_KEY": "access",
        "MTO_BACKUP_S3_SECRET_KEY": "secret",
        "MTO_BACKUP_S3_BUCKET_NAME": "mto-treasury-backups",
        "MTO_BACKUP_S3_REGION_NAME": "auto",
        "MTO_BACKUP_ENCRYPTION_KEY": "encrypted-key",
        "MTO_CLOUD_BACKUP_PHASE3_VERIFIED": "true",
        "MTO_CLOUD_BACKUP_PHASE3_CONFIG_FINGERPRINT": "fingerprint",
        "MTO_ENABLE_CLOUD_BACKUP": "true",
    }


def test_windows_vault_path_is_independent_of_process_home(tmp_path):
    environment = {"PROGRAMDATA": str(tmp_path / "ProgramData")}
    first = resolve_secrets_vault_path(
        environment=environment, platform_name="nt", home=tmp_path / "Administrator"
    )
    second = resolve_secrets_vault_path(
        environment=environment, platform_name="nt", home=tmp_path / "systemprofile"
    )

    assert first == second
    assert first == tmp_path / "ProgramData" / "MTO" / "secrets.json"


def test_explicit_vault_path_override_wins(tmp_path):
    override = tmp_path / "custom" / "vault.json"
    assert resolve_secrets_vault_path(
        environment={"MTO_SECRETS_VAULT_PATH": str(override)},
        platform_name="nt",
    ) == override


def test_migration_preserves_complete_phase3_vault(tmp_path):
    source = tmp_path / "Administrator" / ".mto" / "secrets.json"
    destination = tmp_path / "ProgramData" / "MTO" / "secrets.json"
    source.parent.mkdir(parents=True)
    expected = _phase3_vault()
    source.write_text(json.dumps(expected), encoding="utf-8")

    count = migration.migrate_vault(
        source, destination, require_administrator=False
    )

    assert count == len(expected)
    assert json.loads(destination.read_text(encoding="utf-8")) == expected


def test_migration_refuses_conflicting_machine_vault(tmp_path):
    source = tmp_path / "legacy.json"
    destination = tmp_path / "machine.json"
    source.write_text(json.dumps(_phase3_vault()), encoding="utf-8")
    destination.write_text(
        json.dumps({"MTO_BACKUP_S3_BUCKET_NAME": "different-bucket"}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="different values"):
        migration.migrate_vault(
            source, destination, require_administrator=False
        )

    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "MTO_BACKUP_S3_BUCKET_NAME": "different-bucket"
    }


def test_migration_rejects_incomplete_phase3_vault(tmp_path):
    source = tmp_path / "legacy.json"
    destination = tmp_path / "machine.json"
    source.write_text('{"MTO_ENABLE_CLOUD_BACKUP": "true"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="complete Phase 3"):
        migration.migrate_vault(
            source, destination, require_administrator=False
        )

    assert not destination.exists()
