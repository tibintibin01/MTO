# -*- coding: utf-8 -*-
import os
import logging
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from botocore.client import Config
from utils.secrets_manager import secrets

logger = logging.getLogger("MTO_SYSTEM")


class StorageService:
    """
    Resilient S3-compatible storage with optional activation and versioning.
    """

    def __init__(
        self,
        settings_prefix: str = "S3",
        *,
        allow_bucket_create: bool = True,
        enable_versioning: bool = True,
        activation_setting: str | None = None,
    ):
        self.settings_prefix = settings_prefix.strip().upper()
        self.allow_bucket_create = allow_bucket_create
        self.enable_versioning = enable_versioning
        self.activation_setting = activation_setting

        def setting(name: str, default: str = "") -> str:
            return str(secrets.get(f"{self.settings_prefix}_{name}", default=default) or "")

        is_document_storage = self.settings_prefix == "S3"
        self.configured = setting("STORAGE_ENABLED", "false").lower() == "true"
        self.enabled = self.configured
        self.bucket_name = setting("BUCKET_NAME", "mto-ledgers" if is_document_storage else "")
        self.endpoint_url = setting("ENDPOINT_URL", "http://localhost:9000" if is_document_storage else "")
        self.access_key = setting("ACCESS_KEY", "minioadmin" if is_document_storage else "")
        self.secret_key = setting("SECRET_KEY", "minioadmin" if is_document_storage else "")
        self.region_name = setting("REGION_NAME", "us-east-1" if is_document_storage else "auto")
        self.secure = setting("SECURE", "false" if is_document_storage else "true").lower() == "true"

        self.s3_client = None
        if self.enabled and self.activation_setting:
            activation_value = secrets.get(self.activation_setting, default="false")
            if str(activation_value or "").strip().lower() not in {
                "1",
                "true",
                "yes",
                "on",
            }:
                self.enabled = False

        if self.enabled:
            missing = [
                label
                for label, value in (
                    ("bucket name", self.bucket_name),
                    ("endpoint URL", self.endpoint_url),
                    ("access key", self.access_key),
                    ("secret key", self.secret_key),
                )
                if not value
            ]
            if missing:
                logger.error(f"StorageService[{self.settings_prefix}]: disabled because " f"{', '.join(missing)} is missing.")
                self.enabled = False
                return
            try:
                # Use signature_version='s3v4' for MinIO compatibility
                self.s3_client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.region_name,
                    use_ssl=self.secure,
                    config=Config(signature_version="s3v4"),
                )
                self._ensure_bucket_and_versioning()
                logger.info(f"StorageService: Connected to S3-compatible host at {self.endpoint_url}")
            except Exception as e:
                logger.error(f"StorageService: Failed to connect to S3-compatible host: {e}. Falling back to local disk.")
                self.enabled = False

    def _ensure_bucket_and_versioning(self):
        """Ensures the configured S3 bucket exists and has versioning enabled."""
        if not self.s3_client:
            return

        try:
            # Check if bucket exists
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            # If bucket doesn't exist, create it
            if error_code in ["404", "NoSuchBucket"]:
                if not self.allow_bucket_create:
                    raise RuntimeError(f"Required bucket '{self.bucket_name}' does not exist or is not " "accessible. Create it manually and use a bucket-scoped token.") from e
                try:
                    logger.info(f"StorageService: Bucket '{self.bucket_name}' not found. Creating it...")
                    # AWS S3 requires LocationConstraint if not in us-east-1, but MinIO does not
                    if self.region_name == "us-east-1":
                        self.s3_client.create_bucket(Bucket=self.bucket_name)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=self.bucket_name,
                            CreateBucketConfiguration={"LocationConstraint": self.region_name},
                        )
                except Exception as create_err:
                    logger.error(f"StorageService: Failed to create bucket '{self.bucket_name}': {create_err}")
                    raise
            else:
                logger.error(f"StorageService: Unexpected head_bucket error: {e}")
                raise

        if not self.enable_versioning:
            return

        # Enable versioning on the bucket
        try:
            self.s3_client.put_bucket_versioning(Bucket=self.bucket_name, VersioningConfiguration={"Status": "Enabled"})
            logger.info(f"StorageService: Bucket '{self.bucket_name}' versioning is verified/enabled.")
        except Exception as ver_err:
            logger.warning(f"StorageService: Failed to enable versioning on bucket '{self.bucket_name}': {ver_err}")

    def upload_file(self, local_path: str, s3_key: str, content_type: str = "application/pdf") -> Optional[str]:
        """
        Uploads a local file to the configured S3 bucket.
        Returns the s3_key if upload succeeds, otherwise None.
        """
        if not self.enabled or not self.s3_client:
            logger.debug("StorageService: Upload skipped (disabled or uninitialized).")
            return None

        if not os.path.exists(local_path):
            logger.error(f"StorageService: Local file not found: {local_path}")
            return None

        try:
            self.s3_client.upload_file(
                Filename=local_path,
                Bucket=self.bucket_name,
                Key=s3_key,
                ExtraArgs={"ContentType": content_type},
            )
            logger.info(f"StorageService: Successfully uploaded '{local_path}' to S3 as '{s3_key}'")
            return s3_key
        except Exception as e:
            logger.error(f"StorageService: Failed to upload file '{local_path}' to '{s3_key}': {e}")
            return None

    def generate_presigned_url(self, s3_key: str, expiration: int = 3600) -> Optional[str]:
        """
        Generates a secure, temporary GET presigned URL for viewing/downloading the file.
        Returns the presigned URL if successful, otherwise None.
        """
        if not self.enabled or not self.s3_client:
            return None

        try:
            url = self.s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=expiration,
            )
            return url
        except Exception as e:
            logger.error(f"StorageService: Failed to generate presigned URL for key '{s3_key}': {e}")
            return None

    def download_file(self, s3_key: str, target_local_path: str) -> bool:
        """
        Downloads a file from S3 to a local file path.
        Returns True if successful, otherwise False.
        """
        if not self.enabled or not self.s3_client:
            return False

        try:
            self.s3_client.download_file(Bucket=self.bucket_name, Key=s3_key, Filename=target_local_path)
            logger.info(f"StorageService: Downloaded '{s3_key}' to '{target_local_path}'")
            return True
        except Exception as e:
            logger.error(f"StorageService: Failed to download '{s3_key}' to '{target_local_path}': {e}")
            return False

    def head_object(self, s3_key: str) -> Optional[dict]:
        """Returns trusted object metadata used for post-upload verification."""
        if not self.enabled or not self.s3_client:
            return None
        try:
            response = self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return {
                "key": s3_key,
                "size": int(response.get("ContentLength", 0)),
                "etag": str(response.get("ETag", "")).strip('"'),
                "last_modified": response.get("LastModified"),
            }
        except Exception as e:
            logger.error(f"StorageService: Failed to inspect object '{s3_key}': {e}")
            return None

    def get_object_bytes(self, s3_key: str, max_bytes: int = 1024 * 1024) -> Optional[bytes]:
        """Downloads a small object into memory with a strict size ceiling."""
        if not self.enabled or not self.s3_client or max_bytes <= 0:
            return None
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            content_length = int(response.get("ContentLength", 0))
            if content_length > max_bytes:
                logger.error(f"StorageService: Refused oversized object '{s3_key}' ({content_length} bytes).")
                response["Body"].close()
                return None
            body = response["Body"]
            try:
                data = body.read(max_bytes + 1)
            finally:
                body.close()
            if len(data) > max_bytes:
                logger.error(f"StorageService: Object '{s3_key}' exceeded its read limit.")
                return None
            return data
        except Exception as e:
            logger.error(f"StorageService: Failed to read object '{s3_key}': {e}")
            return None

    def list_objects(self, prefix: str = "") -> list[dict]:
        """Lists every object under a prefix, raising on incomplete/failed listings."""
        if not self.enabled or not self.s3_client:
            raise RuntimeError("S3-compatible storage is disabled or unavailable.")

        objects = []
        continuation_token = None
        try:
            while True:
                params = {"Bucket": self.bucket_name, "Prefix": prefix}
                if continuation_token:
                    params["ContinuationToken"] = continuation_token
                response = self.s3_client.list_objects_v2(**params)
                for item in response.get("Contents", []):
                    objects.append(
                        {
                            "key": item["Key"],
                            "size": int(item.get("Size", 0)),
                            "last_modified": item.get("LastModified"),
                        }
                    )
                if not response.get("IsTruncated"):
                    break
                continuation_token = response.get("NextContinuationToken")
                if not continuation_token:
                    raise RuntimeError("S3 listing was truncated without a continuation token.")
            return objects
        except Exception as e:
            logger.error(f"StorageService: Failed to list objects under '{prefix}': {e}")
            raise RuntimeError("Could not enumerate cloud backup objects safely.") from e

    def delete_objects(self, s3_keys: list[str]) -> bool:
        """Deletes explicitly named objects in S3 API-sized batches."""
        if not self.enabled or not self.s3_client:
            return False
        keys = [key for key in dict.fromkeys(s3_keys) if key]
        if not keys:
            return True
        try:
            for start in range(0, len(keys), 1000):
                batch = keys[start : start + 1000]
                response = self.s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={
                        "Objects": [{"Key": key} for key in batch],
                        "Quiet": True,
                    },
                )
                errors = response.get("Errors", [])
                if errors:
                    logger.error(f"StorageService: Cloud object deletion errors: {errors}")
                    return False
            logger.info(f"StorageService: Deleted {len(keys)} cloud object(s).")
            return True
        except Exception as e:
            logger.error(f"StorageService: Failed to delete cloud objects: {e}")
            return False


# Global singleton instance
storage_service = StorageService()

# Database backups use separate credentials and a dedicated private bucket.
# This prevents enabling cloud backup from also uploading receipts and billing
# PDFs handled by the legacy/document storage singleton above.
backup_storage_service = StorageService(
    settings_prefix="MTO_BACKUP_S3",
    allow_bucket_create=False,
    enable_versioning=False,
    activation_setting="MTO_ENABLE_CLOUD_BACKUP",
)
