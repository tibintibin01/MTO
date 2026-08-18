# -*- coding: utf-8 -*-
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from scripts import configure_r2_backup as r2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("A" * 32, "a" * 32),
        ("0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef"),
    ],
)
def test_validate_account_id(value, expected):
    assert r2.validate_account_id(value) == expected


@pytest.mark.parametrize("value", ["", "123", "g" * 32, "a" * 33])
def test_validate_account_id_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="32 hexadecimal"):
        r2.validate_account_id(value)


@pytest.mark.parametrize("value", ["mto-treasury-backups", "mto-123"])
def test_validate_bucket_name(value):
    assert r2.validate_bucket_name(value) == value


@pytest.mark.parametrize("value", ["ab", "MTO-BACKUPS", "-mto", "mto_", "mto-"])
def test_validate_bucket_name_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="3-63"):
        r2.validate_bucket_name(value)


def test_recovery_key_path_must_be_outside_project(tmp_path):
    project_root = tmp_path / "MTO"
    outside = tmp_path / "offline" / "mto_backup_recovery_key.txt"
    inside = project_root / "mto_backup_recovery_key.txt"

    assert r2.validate_recovery_path(str(outside), project_root) == outside.resolve()
    with pytest.raises(ValueError, match="outside the MTO project"):
        r2.validate_recovery_path(str(inside), project_root)


def test_atomic_vault_write_preserves_json_and_hardens_files(tmp_path, monkeypatch):
    hardened = []
    monkeypatch.setattr(r2, "_harden_file", lambda path: hardened.append(path))
    vault_path = tmp_path / ".mto" / "secrets.json"

    r2._atomic_write_vault({"secret": "value"}, vault_path)

    assert json.loads(vault_path.read_text(encoding="utf-8")) == {"secret": "value"}
    assert hardened[-1] == vault_path
    assert len(hardened) == 2
    assert not list(vault_path.parent.glob("secrets-*.tmp"))


def test_recovery_key_refuses_overwrite(tmp_path, monkeypatch):
    recovery_path = tmp_path / "mto_backup_recovery_key.txt"
    recovery_path.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(r2, "_harden_file", lambda path: None)

    with pytest.raises(RuntimeError, match="will not be overwritten"):
        r2._write_recovery_key(recovery_path, "secret-key")

    assert recovery_path.read_text(encoding="utf-8") == "existing"


def test_recovery_key_is_removed_if_permissions_cannot_be_hardened(
    tmp_path, monkeypatch
):
    recovery_path = tmp_path / "mto_backup_recovery_key.txt"

    def fail_hardening(path):
        raise RuntimeError("permission failure")

    monkeypatch.setattr(r2, "_harden_file", fail_hardening)
    with pytest.raises(RuntimeError, match="permission failure"):
        r2._write_recovery_key(recovery_path, "secret-key")

    assert not recovery_path.exists()


def _valid_settings():
    return {
        "MTO_BACKUP_S3_ENDPOINT_URL": "https://abc.r2.cloudflarestorage.com",
        "MTO_BACKUP_S3_ACCESS_KEY": "access",
        "MTO_BACKUP_S3_SECRET_KEY": "secret",
        "MTO_BACKUP_S3_BUCKET_NAME": "mto-treasury-backups",
        "MTO_BACKUP_S3_REGION_NAME": "auto",
    }


def test_r2_probe_uses_random_non_taxpayer_bytes_and_cleans_up(monkeypatch):
    client = MagicMock()
    body = io.BytesIO(b"P" * 64)
    client.head_object.return_value = {"ContentLength": 64}
    client.get_object.return_value = {"Body": body}
    client.list_objects_v2.side_effect = [
        {"Contents": []},
        {"Contents": [{"Key": "phase2-probe/probe-id.bin"}]},
    ]
    boto_client = MagicMock(return_value=client)
    monkeypatch.setattr(r2.boto3, "client", boto_client)
    monkeypatch.setattr(r2.py_secrets, "token_bytes", lambda size: b"P" * size)
    monkeypatch.setattr(r2.uuid, "uuid4", lambda: SimpleNamespace(hex="probe-id"))

    r2.test_r2_access(_valid_settings())

    boto_client.assert_called_once()
    assert boto_client.call_args.kwargs["region_name"] == "auto"
    client.head_bucket.assert_not_called()
    assert client.list_objects_v2.call_args_list[0].kwargs == {
        "Bucket": "mto-treasury-backups",
        "Prefix": "phase2-probe/",
        "MaxKeys": 1,
    }
    client.put_object.assert_called_once_with(
        Bucket="mto-treasury-backups",
        Key="phase2-probe/probe-id.bin",
        Body=b"P" * 64,
        ContentType="application/octet-stream",
    )
    client.delete_object.assert_called_once_with(
        Bucket="mto-treasury-backups", Key="phase2-probe/probe-id.bin"
    )


def test_r2_probe_reports_actionable_redacted_client_error(monkeypatch):
    client = MagicMock()
    client.list_objects_v2.side_effect = ClientError(
        {
            "Error": {"Code": "400", "Message": "Bad Request"},
            "ResponseMetadata": {
                "HTTPStatusCode": 400,
                "RequestId": "request-123",
            },
        },
        "ListObjectsV2",
    )
    monkeypatch.setattr(r2.boto3, "client", MagicMock(return_value=client))

    with pytest.raises(RuntimeError) as error:
        r2.test_r2_access(_valid_settings())

    message = str(error.value)
    assert "R2 list check failed" in message
    assert "HTTP 400" in message
    assert "request-123" in message
    assert "Synchronize Windows" in message
    assert "secret" not in message.lower()


def test_r2_probe_deletes_uploaded_object_after_verification_failure(monkeypatch):
    client = MagicMock()
    client.head_object.return_value = {"ContentLength": 64}
    client.get_object.return_value = {"Body": io.BytesIO(b"wrong")}
    boto_client = MagicMock(return_value=client)
    monkeypatch.setattr(r2.boto3, "client", boto_client)
    monkeypatch.setattr(r2.py_secrets, "token_bytes", lambda size: b"P" * size)
    monkeypatch.setattr(r2.uuid, "uuid4", lambda: SimpleNamespace(hex="probe-id"))

    with pytest.raises(RuntimeError, match="did not match"):
        r2.test_r2_access(_valid_settings())

    client.delete_object.assert_called_once_with(
        Bucket="mto-treasury-backups", Key="phase2-probe/probe-id.bin"
    )


def test_cloud_backup_enable_guard_checks_process_and_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("MTO_ENABLE_CLOUD_BACKUP", raising=False)
    (tmp_path / ".env").write_text("MTO_ENABLE_CLOUD_BACKUP=0\n", encoding="utf-8")
    assert r2._cloud_backup_is_enabled(tmp_path) is False

    (tmp_path / ".env").write_text("MTO_ENABLE_CLOUD_BACKUP=true\n", encoding="utf-8")
    assert r2._cloud_backup_is_enabled(tmp_path) is True

    (tmp_path / ".env").write_text("MTO_ENABLE_CLOUD_BACKUP=0\n", encoding="utf-8")
    monkeypatch.setenv("MTO_ENABLE_CLOUD_BACKUP", "1")
    assert r2._cloud_backup_is_enabled(tmp_path) is True

    monkeypatch.delenv("MTO_ENABLE_CLOUD_BACKUP", raising=False)
    vault_path = tmp_path / "secrets.json"
    vault_path.write_text(
        '{"MTO_ENABLE_CLOUD_BACKUP": "true"}\n', encoding="utf-8"
    )
    assert r2._cloud_backup_is_enabled(tmp_path, vault_path) is True
