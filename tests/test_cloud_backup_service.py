# -*- coding: utf-8 -*-
import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.services import cloud_backup_service as cloud


SQL_BYTES = (
    b"-- MySQL dump\n"
    b"INSERT INTO properties VALUES (1, 'CONFIDENTIAL OWNER RECORD');\n"
    + (b"x" * 256)
    + b"\n-- Dump completed on 2026-08-18\n"
)


class MemoryStorage:
    def __init__(self):
        self.enabled = True
        self.objects = {}
        self.modified = {}
        self.uploaded = []
        self.deleted = []

    def upload_file(self, local_path, key, content_type="application/pdf"):
        self.objects[key] = Path(local_path).read_bytes()
        self.modified[key] = datetime.now(timezone.utc)
        self.uploaded.append((local_path, key, content_type))
        return key

    def head_object(self, key):
        data = self.objects.get(key)
        return None if data is None else {"key": key, "size": len(data)}

    def get_object_bytes(self, key, max_bytes=1024 * 1024):
        data = self.objects.get(key)
        return data if data is not None and len(data) <= max_bytes else None

    def list_objects(self, prefix=""):
        return [
            {
                "key": key,
                "size": len(data),
                "last_modified": self.modified[key],
            }
            for key, data in self.objects.items()
            if key.startswith(prefix)
        ]

    def delete_objects(self, keys):
        self.deleted.append(list(keys))
        for key in keys:
            self.objects.pop(key, None)
            self.modified.pop(key, None)
        return True

    def download_file(self, key, target_path):
        data = self.objects.get(key)
        if data is None:
            return False
        Path(target_path).write_bytes(data)
        return True


@pytest.fixture
def master_key():
    return bytes(range(32))


@pytest.fixture
def sql_file(tmp_path):
    path = tmp_path / "revenue_backup_2026-08-18_12-00-00.sql"
    path.write_bytes(SQL_BYTES)
    return path


def _configure_enabled(monkeypatch, master_key, *, keep=14, max_bytes=8 * 1024**3):
    encoded = base64.urlsafe_b64encode(master_key).decode("ascii")
    monkeypatch.setattr(cloud.mto_config, "ENABLE_CLOUD_BACKUP", True)
    monkeypatch.setattr(cloud, "cloud_backup_enabled", lambda: True)
    monkeypatch.setattr(cloud, "cloud_backup_activation_ready", lambda: (True, "ready"))
    monkeypatch.setattr(cloud.mto_config, "CLOUD_BACKUP_PREFIX", "backups/")
    monkeypatch.setattr(cloud.mto_config, "CLOUD_BACKUP_KEEP", keep)
    monkeypatch.setattr(cloud.mto_config, "CLOUD_BACKUP_MAX_BYTES", max_bytes)
    monkeypatch.setattr(
        cloud.secrets,
        "get",
        lambda key, default=None: encoded if key == "MTO_BACKUP_ENCRYPTION_KEY" else default,
    )


def _add_set(storage, name, size, modified):
    artifact_key = f"backups/{name}.sql.gz.enc"
    manifest_key = f"{artifact_key}.manifest.json"
    storage.objects[artifact_key] = b"a" * size
    storage.objects[manifest_key] = b"{}"
    storage.modified[artifact_key] = modified
    storage.modified[manifest_key] = modified
    return artifact_key, manifest_key


def test_prepare_encrypts_round_trip_and_cleans_temporary_files(sql_file, tmp_path, master_key):
    with cloud.prepare_cloud_backup(
        str(sql_file), prefix="backups/", encryption_key=master_key
    ) as prepared:
        artifact_path = prepared.artifact_path
        manifest_path = prepared.manifest_path
        encrypted = Path(artifact_path).read_bytes()
        assert SQL_BYTES not in encrypted
        assert b"CONFIDENTIAL OWNER RECORD" not in encrypted
        assert prepared.artifact_key.endswith(".sql.gz.enc")
        assert prepared.manifest_key.endswith(".sql.gz.enc.manifest.json")

        aes_key, signing_key = cloud._derive_keys(master_key)
        cloud._validate_manifest(prepared.manifest, signing_key)
        compressed = tmp_path / "roundtrip.sql.gz"
        restored = tmp_path / "roundtrip.sql"
        cloud._decrypt_file(artifact_path, str(compressed), aes_key)
        cloud._decompress_gzip(str(compressed), str(restored))
        assert restored.read_bytes() == SQL_BYTES

    assert not Path(artifact_path).exists()
    assert not Path(manifest_path).exists()


def test_manifest_tampering_is_rejected(sql_file, master_key):
    with cloud.prepare_cloud_backup(
        str(sql_file), prefix="backups/", encryption_key=master_key
    ) as prepared:
        tampered = dict(prepared.manifest)
        tampered["plaintext_size"] += 1
        _, signing_key = cloud._derive_keys(master_key)
        with pytest.raises(cloud.CloudBackupIntegrityError, match="signature"):
            cloud._validate_manifest(tampered, signing_key)


def test_invalid_master_key_configuration_is_rejected(monkeypatch):
    monkeypatch.setattr(cloud.secrets, "get", lambda *args, **kwargs: "not-base64***")
    with pytest.raises(cloud.CloudBackupConfigurationError):
        cloud.load_backup_encryption_key()


def test_retention_deletes_oldest_complete_set(monkeypatch, master_key):
    _configure_enabled(monkeypatch, master_key, keep=2, max_bytes=10_000)
    storage = MemoryStorage()
    now = datetime.now(timezone.utc)
    oldest = _add_set(storage, "backup-old", 100, now - timedelta(days=2))
    newest = _add_set(storage, "backup-new", 100, now - timedelta(days=1))

    cloud.enforce_cloud_limits(storage, incoming_bytes=200)

    assert storage.deleted == [list(oldest)]
    assert all(key not in storage.objects for key in oldest)
    assert all(key in storage.objects for key in newest)


def test_unknown_objects_block_quota_without_deletion(monkeypatch, master_key):
    _configure_enabled(monkeypatch, master_key, keep=14, max_bytes=100)
    storage = MemoryStorage()
    key = "backups/manual-file.bin"
    storage.objects[key] = b"x" * 60
    storage.modified[key] = datetime.now(timezone.utc)

    with pytest.raises(cloud.CloudBackupQuotaError, match="manual review"):
        cloud.enforce_cloud_limits(storage, incoming_bytes=50)
    assert storage.deleted == []


def test_sync_uploads_only_encrypted_artifact_and_manifest(
    monkeypatch, sql_file, master_key
):
    _configure_enabled(monkeypatch, master_key)
    storage = MemoryStorage()

    result = cloud.sync_encrypted_backup(
        str(sql_file), cloud._sha256(str(sql_file)), storage=storage
    )

    assert result.success is True
    assert result.code == "UPLOADED"
    assert len(storage.uploaded) == 2
    assert all(key != sql_file.name for _, key, _ in storage.uploaded)
    assert not any(key.endswith(".sql") for _, key, _ in storage.uploaded)
    assert storage.uploaded[0][2] == "application/octet-stream"
    assert storage.uploaded[1][2] == "application/json"
    assert b"CONFIDENTIAL OWNER RECORD" not in storage.objects[result.artifact_key]


def test_cloud_verification_decrypts_and_checks_sql(
    monkeypatch, sql_file, master_key
):
    _configure_enabled(monkeypatch, master_key)
    storage = MemoryStorage()
    result = cloud.sync_encrypted_backup(str(sql_file), storage=storage)
    verified = {}

    def fake_verify(
        path, db_session=None, expected_checksum=None, *, require_restore_test=False
    ):
        verified["data"] = Path(path).read_bytes()
        verified["restore_required"] = require_restore_test
        verified["checksum"] = expected_checksum
        return True, "Restore verification passed."

    monkeypatch.setattr(cloud, "verify_sql_dump", fake_verify)
    success, message = cloud.verify_cloud_backup(
        result.manifest_key, storage=storage, db_session=object()
    )

    assert success is True
    assert message == "Restore verification passed."
    assert verified["data"] == SQL_BYTES
    assert verified["checksum"] == cloud._sha256(str(sql_file))
    assert verified["restore_required"] is True


def test_cloud_verification_rejects_tampered_manifest(
    monkeypatch, sql_file, master_key
):
    _configure_enabled(monkeypatch, master_key)
    storage = MemoryStorage()
    result = cloud.sync_encrypted_backup(str(sql_file), storage=storage)
    manifest = json.loads(storage.objects[result.manifest_key].decode("utf-8"))
    manifest["plaintext_size"] += 10
    storage.objects[result.manifest_key] = json.dumps(manifest).encode("utf-8")

    success, message = cloud.verify_cloud_backup(result.manifest_key, storage=storage)

    assert success is False
    assert "signature" in message.lower()


def test_disabled_cloud_backup_does_not_touch_storage(monkeypatch):
    monkeypatch.setattr(cloud, "cloud_backup_enabled", lambda: False)
    storage = MemoryStorage()
    result = cloud.sync_encrypted_backup("missing.sql", storage=storage)
    assert result.code == "DISABLED"
    assert storage.uploaded == []


def test_live_upload_is_blocked_without_phase3_attestation(monkeypatch):
    monkeypatch.setattr(cloud, "cloud_backup_enabled", lambda: True)
    monkeypatch.setattr(
        cloud,
        "cloud_backup_activation_ready",
        lambda: (False, "Phase 3 has not passed."),
    )
    storage = MemoryStorage()

    result = cloud.sync_encrypted_backup("missing.sql", storage=storage)

    assert result.code == "CLOUD_CONFIG_ERROR"
    assert "Phase 3" in result.message
    assert storage.uploaded == []


def test_phase3_upload_can_run_while_live_cloud_is_disabled(
    monkeypatch, sql_file, master_key
):
    _configure_enabled(monkeypatch, master_key)
    monkeypatch.setattr(cloud, "cloud_backup_enabled", lambda: False)
    storage = MemoryStorage()

    result = cloud.sync_encrypted_backup_for_restore_test(
        str(sql_file), storage=storage
    )

    assert result.success is True
    assert len(storage.uploaded) == 2


def test_phase3_attestation_is_bound_to_bucket_prefix_and_key(
    monkeypatch, master_key
):
    encoded = base64.urlsafe_b64encode(master_key).decode("ascii")
    values = {
        "MTO_BACKUP_ENCRYPTION_KEY": encoded,
        "MTO_BACKUP_S3_BUCKET_NAME": "mto-treasury-backups",
        "MTO_BACKUP_S3_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
        "MTO_CLOUD_BACKUP_PHASE3_VERIFIED": "false",
        "MTO_CLOUD_BACKUP_PHASE3_CONFIG_FINGERPRINT": "",
    }
    monkeypatch.setattr(cloud.mto_config, "CLOUD_BACKUP_PREFIX", "backups/")
    monkeypatch.setattr(
        cloud.secrets,
        "get",
        lambda key, default=None: values.get(key, default),
    )

    fingerprint = cloud.cloud_backup_configuration_fingerprint()
    values["MTO_CLOUD_BACKUP_PHASE3_VERIFIED"] = "true"
    values["MTO_CLOUD_BACKUP_PHASE3_CONFIG_FINGERPRINT"] = fingerprint

    ready, _ = cloud.cloud_backup_activation_ready()
    assert ready is True

    values["MTO_BACKUP_S3_BUCKET_NAME"] = "different-backup-bucket"
    ready, message = cloud.cloud_backup_activation_ready()

    assert ready is False
    assert "changed after Phase 3" in message
