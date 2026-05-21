# -*- coding: utf-8 -*-
import os
import logging
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from botocore.client import Config

logger = logging.getLogger("MTO_SYSTEM")

class StorageService:
    """
    Resilient S3-compatible Object Storage Service with local fallback and automatic bucket versioning setup.
    """
    def __init__(self):
        self.enabled = os.getenv("S3_STORAGE_ENABLED", "false").lower() == "true"
        self.bucket_name = os.getenv("S3_BUCKET_NAME", "mto-ledgers")
        self.endpoint_url = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
        self.access_key = os.getenv("S3_ACCESS_KEY", "minioadmin")
        self.secret_key = os.getenv("S3_SECRET_KEY", "minioadmin")
        self.region_name = os.getenv("S3_REGION_NAME", "us-east-1")
        self.secure = os.getenv("S3_SECURE", "false").lower() == "true"

        self.s3_client = None

        if self.enabled:
            try:
                # Use signature_version='s3v4' for MinIO compatibility
                self.s3_client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.region_name,
                    use_ssl=self.secure,
                    config=Config(signature_version="s3v4")
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
                try:
                    logger.info(f"StorageService: Bucket '{self.bucket_name}' not found. Creating it...")
                    # AWS S3 requires LocationConstraint if not in us-east-1, but MinIO does not
                    if self.region_name == "us-east-1":
                        self.s3_client.create_bucket(Bucket=self.bucket_name)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=self.bucket_name,
                            CreateBucketConfiguration={"LocationConstraint": self.region_name}
                        )
                except Exception as create_err:
                    logger.error(f"StorageService: Failed to create bucket '{self.bucket_name}': {create_err}")
                    raise
            else:
                logger.error(f"StorageService: Unexpected head_bucket error: {e}")
                raise

        # Enable versioning on the bucket
        try:
            self.s3_client.put_bucket_versioning(
                Bucket=self.bucket_name,
                VersioningConfiguration={
                    "Status": "Enabled"
                }
            )
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
                ExtraArgs={"ContentType": content_type}
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
                Params={
                    "Bucket": self.bucket_name,
                    "Key": s3_key
                },
                ExpiresIn=expiration
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
            self.s3_client.download_file(
                Bucket=self.bucket_name,
                Key=s3_key,
                Filename=target_local_path
            )
            logger.info(f"StorageService: Downloaded '{s3_key}' to '{target_local_path}'")
            return True
        except Exception as e:
            logger.error(f"StorageService: Failed to download '{s3_key}' to '{target_local_path}': {e}")
            return False

# Global singleton instance
storage_service = StorageService()
