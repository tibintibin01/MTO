# -*- coding: utf-8 -*-
import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from backend.services.storage_service import StorageService


@pytest.fixture
def backup_env(monkeypatch):
    keys = (
        "S3_STORAGE_ENABLED",
        "S3_BUCKET_NAME",
        "MTO_BACKUP_S3_STORAGE_ENABLED",
        "MTO_BACKUP_S3_BUCKET_NAME",
        "MTO_BACKUP_S3_ENDPOINT_URL",
        "MTO_BACKUP_S3_ACCESS_KEY",
        "MTO_BACKUP_S3_SECRET_KEY",
        "MTO_BACKUP_S3_REGION_NAME",
        "MTO_BACKUP_S3_SECURE",
        "MTO_ENABLE_CLOUD_BACKUP",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "backend.services.storage_service.secrets.get",
        lambda key, default=None: os.environ.get(key, default),
    )


@patch("backend.services.storage_service.boto3.client")
def test_backup_storage_uses_only_dedicated_settings(mock_boto_client, backup_env):
    os.environ.update(
        {
            "S3_STORAGE_ENABLED": "true",
            "S3_BUCKET_NAME": "document-bucket",
            "MTO_BACKUP_S3_STORAGE_ENABLED": "true",
            "MTO_BACKUP_S3_BUCKET_NAME": "backup-bucket",
            "MTO_BACKUP_S3_ENDPOINT_URL": "https://abc.r2.cloudflarestorage.com",
            "MTO_BACKUP_S3_ACCESS_KEY": "backup-access",
            "MTO_BACKUP_S3_SECRET_KEY": "backup-secret",
            "MTO_BACKUP_S3_REGION_NAME": "auto",
            "MTO_BACKUP_S3_SECURE": "true",
            "MTO_ENABLE_CLOUD_BACKUP": "true",
        }
    )
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.head_bucket.return_value = {}

    service = StorageService(
        settings_prefix="MTO_BACKUP_S3",
        allow_bucket_create=False,
        enable_versioning=False,
        activation_setting="MTO_ENABLE_CLOUD_BACKUP",
    )

    assert service.enabled is True
    assert service.bucket_name == "backup-bucket"
    client_kwargs = mock_boto_client.call_args.kwargs
    assert client_kwargs["endpoint_url"] == "https://abc.r2.cloudflarestorage.com"
    assert client_kwargs["aws_access_key_id"] == "backup-access"
    assert client_kwargs["aws_secret_access_key"] == "backup-secret"
    assert client_kwargs["region_name"] == "auto"
    assert client_kwargs["use_ssl"] is True
    mock_s3.head_bucket.assert_called_once_with(Bucket="backup-bucket")
    mock_s3.create_bucket.assert_not_called()
    mock_s3.put_bucket_versioning.assert_not_called()


@patch("backend.services.storage_service.boto3.client")
def test_backup_storage_never_creates_a_missing_bucket(mock_boto_client, backup_env):
    os.environ.update(
        {
            "MTO_BACKUP_S3_STORAGE_ENABLED": "true",
            "MTO_BACKUP_S3_BUCKET_NAME": "missing-backup-bucket",
            "MTO_BACKUP_S3_ENDPOINT_URL": "https://abc.r2.cloudflarestorage.com",
            "MTO_BACKUP_S3_ACCESS_KEY": "backup-access",
            "MTO_BACKUP_S3_SECRET_KEY": "backup-secret",
            "MTO_ENABLE_CLOUD_BACKUP": "true",
        }
    )
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket"
    )

    service = StorageService(
        settings_prefix="MTO_BACKUP_S3",
        allow_bucket_create=False,
        enable_versioning=False,
        activation_setting="MTO_ENABLE_CLOUD_BACKUP",
    )

    assert service.enabled is False
    mock_s3.create_bucket.assert_not_called()
    mock_s3.put_bucket_versioning.assert_not_called()


@patch("backend.services.storage_service.boto3.client")
def test_backup_storage_fails_closed_when_configuration_is_incomplete(
    mock_boto_client, backup_env
):
    os.environ["MTO_BACKUP_S3_STORAGE_ENABLED"] = "true"
    os.environ["MTO_BACKUP_S3_BUCKET_NAME"] = "backup-bucket"
    os.environ["MTO_ENABLE_CLOUD_BACKUP"] = "true"

    service = StorageService(
        settings_prefix="MTO_BACKUP_S3",
        allow_bucket_create=False,
        enable_versioning=False,
        activation_setting="MTO_ENABLE_CLOUD_BACKUP",
    )

    assert service.enabled is False
    assert service.s3_client is None
    mock_boto_client.assert_not_called()


@patch("backend.services.storage_service.boto3.client")
def test_backup_storage_does_not_contact_r2_before_live_activation(
    mock_boto_client, backup_env
):
    os.environ.update(
        {
            "MTO_BACKUP_S3_STORAGE_ENABLED": "true",
            "MTO_BACKUP_S3_BUCKET_NAME": "backup-bucket",
            "MTO_BACKUP_S3_ENDPOINT_URL": "https://abc.r2.cloudflarestorage.com",
            "MTO_BACKUP_S3_ACCESS_KEY": "backup-access",
            "MTO_BACKUP_S3_SECRET_KEY": "backup-secret",
            "MTO_ENABLE_CLOUD_BACKUP": "false",
        }
    )

    service = StorageService(
        settings_prefix="MTO_BACKUP_S3",
        allow_bucket_create=False,
        enable_versioning=False,
        activation_setting="MTO_ENABLE_CLOUD_BACKUP",
    )

    assert service.configured is True
    assert service.enabled is False
    assert service.s3_client is None
    mock_boto_client.assert_not_called()
