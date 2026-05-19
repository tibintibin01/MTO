# -*- coding: utf-8 -*-
import os
import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError
from backend.services.storage_service import StorageService

@pytest.fixture
def clean_env():
    """Backup and restore S3-related env variables."""
    old_env = {k: os.environ.get(k) for k in [
        "S3_STORAGE_ENABLED", "S3_BUCKET_NAME", "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_REGION_NAME", "S3_SECURE"
    ]}
    yield
    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

def test_storage_disabled_by_default(clean_env):
    """Verifies that storage is disabled if env says so."""
    os.environ["S3_STORAGE_ENABLED"] = "false"
    service = StorageService()
    assert service.enabled is False
    assert service.s3_client is None

    # Operations should handle being disabled gracefully
    assert service.upload_file("dummy_path.pdf", "dummy_key.pdf") is None
    assert service.generate_presigned_url("dummy_key.pdf") is None
    assert service.download_file("dummy_key.pdf", "dummy_path.pdf") is False

@patch("boto3.client")
def test_storage_initialization_bucket_exists(mock_boto_client, clean_env):
    """Verifies standard initialization when the bucket already exists."""
    os.environ["S3_STORAGE_ENABLED"] = "true"
    os.environ["S3_BUCKET_NAME"] = "test-bucket"
    os.environ["S3_REGION_NAME"] = "us-east-1"

    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3

    # head_bucket succeeds, meaning bucket exists
    mock_s3.head_bucket.return_value = {}

    service = StorageService()

    assert service.enabled is True
    mock_s3.head_bucket.assert_called_once_with(Bucket="test-bucket")
    mock_s3.create_bucket.assert_not_called()
    mock_s3.put_bucket_versioning.assert_called_once_with(
        Bucket="test-bucket",
        VersioningConfiguration={"Status": "Enabled"}
    )

@patch("boto3.client")
def test_storage_initialization_bucket_missing(mock_boto_client, clean_env):
    """Verifies bucket creation and versioning setup when head_bucket throws 404."""
    os.environ["S3_STORAGE_ENABLED"] = "true"
    os.environ["S3_BUCKET_NAME"] = "missing-bucket"
    os.environ["S3_REGION_NAME"] = "us-east-1"

    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3

    # head_bucket throws 404
    mock_s3.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket"
    )

    service = StorageService()

    assert service.enabled is True
    mock_s3.create_bucket.assert_called_once_with(Bucket="missing-bucket")
    mock_s3.put_bucket_versioning.assert_called_once_with(
        Bucket="missing-bucket",
        VersioningConfiguration={"Status": "Enabled"}
    )

@patch("boto3.client")
def test_storage_upload_success(mock_boto_client, clean_env, tmp_path):
    """Verifies upload_file behaves correctly under S3-enabled mode."""
    os.environ["S3_STORAGE_ENABLED"] = "true"
    os.environ["S3_BUCKET_NAME"] = "test-bucket"

    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.head_bucket.return_value = {}

    # Create dummy local file
    temp_file = tmp_path / "test.pdf"
    temp_file.write_text("dummy PDF content")

    service = StorageService()
    res = service.upload_file(str(temp_file), "receipts/test.pdf")

    assert res == "receipts/test.pdf"
    mock_s3.upload_file.assert_called_once_with(
        Filename=str(temp_file),
        Bucket="test-bucket",
        Key="receipts/test.pdf",
        ExtraArgs={"ContentType": "application/pdf"}
    )

@patch("boto3.client")
def test_storage_generate_presigned_url(mock_boto_client, clean_env):
    """Verifies presigned url generation logic."""
    os.environ["S3_STORAGE_ENABLED"] = "true"
    os.environ["S3_BUCKET_NAME"] = "test-bucket"

    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.head_bucket.return_value = {}
    mock_s3.generate_presigned_url.return_value = "https://s3.mock/test-bucket/receipts/test.pdf?signature=123"

    service = StorageService()
    url = service.generate_presigned_url("receipts/test.pdf", expiration=1800)

    assert url == "https://s3.mock/test-bucket/receipts/test.pdf?signature=123"
    mock_s3.generate_presigned_url.assert_called_once_with(
        ClientMethod="get_object",
        Params={"Bucket": "test-bucket", "Key": "receipts/test.pdf"},
        ExpiresIn=1800
    )
