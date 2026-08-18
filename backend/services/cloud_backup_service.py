"""Encrypted, quota-bounded cloud backup artifacts.

Cloud backup remains opt-in. This module never uploads a readable SQL dump:
the dump is compressed, encrypted with AES-256-GCM, and paired with a signed
manifest before it is handed to S3-compatible object storage.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.services.verification_service import verify_sql_dump
from utils.config import config as mto_config
from utils.logger import mto_logger
from utils.secrets_manager import secrets


FORMAT_NAME = "mto-cloud-backup"
FORMAT_VERSION = 1
MAGIC = b"MTOBKP1\x00"
NONCE_SIZE = 12
TAG_SIZE = 16
CHUNK_SIZE = 1024 * 1024


class CloudBackupError(RuntimeError):
    """Base exception for cloud backup safety failures."""


class CloudBackupConfigurationError(CloudBackupError):
    """Raised when cloud backup is enabled without safe configuration."""


class CloudBackupQuotaError(CloudBackupError):
    """Raised when the configured application quota cannot be respected."""


class CloudBackupIntegrityError(CloudBackupError):
    """Raised when an encrypted artifact or manifest fails verification."""


@dataclass(frozen=True)
class CloudSyncResult:
    success: bool
    code: str
    message: str
    artifact_key: str | None = None
    manifest_key: str | None = None

    def __bool__(self) -> bool:
        return self.success


@dataclass(frozen=True)
class PreparedCloudBackup:
    artifact_path: str
    manifest_path: str
    artifact_key: str
    manifest_key: str
    manifest: dict[str, Any]


TRUE_VALUES = {"1", "true", "yes", "on"}


def cloud_backup_enabled() -> bool:
    """Returns the live activation flag, preferring the protected secrets vault."""
    fallback = "true" if mto_config.ENABLE_CLOUD_BACKUP else "false"
    value = secrets.get("MTO_ENABLE_CLOUD_BACKUP", default=fallback)
    return str(value or "").strip().lower() in TRUE_VALUES


def cloud_backup_configuration_fingerprint() -> str:
    """Binds Phase 3 approval to the bucket, endpoint, prefix, and encryption key."""
    values = {
        "bucket": str(
            secrets.get("MTO_BACKUP_S3_BUCKET_NAME", default="") or ""
        ).strip(),
        "endpoint": str(
            secrets.get("MTO_BACKUP_S3_ENDPOINT_URL", default="") or ""
        ).strip().rstrip("/"),
        "prefix": _normalized_prefix(mto_config.CLOUD_BACKUP_PREFIX),
        "key_sha256": hashlib.sha256(load_backup_encryption_key()).hexdigest(),
    }
    if not values["bucket"] or not values["endpoint"]:
        raise CloudBackupConfigurationError(
            "The dedicated cloud backup bucket and endpoint are required."
        )
    payload = json.dumps(values, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def cloud_backup_activation_ready() -> tuple[bool, str]:
    """Requires a successful Phase 3 restore test for the current configuration."""
    verified = str(
        secrets.get("MTO_CLOUD_BACKUP_PHASE3_VERIFIED", default="false") or ""
    ).strip().lower()
    if verified not in TRUE_VALUES:
        return False, "Phase 3 cloud restore verification has not passed."
    expected = str(
        secrets.get(
            "MTO_CLOUD_BACKUP_PHASE3_CONFIG_FINGERPRINT", default=""
        )
        or ""
    ).strip()
    try:
        current = cloud_backup_configuration_fingerprint()
    except CloudBackupConfigurationError as exc:
        return False, str(exc)
    if not expected or not hmac.compare_digest(expected, current):
        return False, (
            "The cloud backup destination or encryption key changed after Phase 3; "
            "run restore verification again."
        )
    return True, "Phase 3 cloud restore verification is current."



def _sha256(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_prefix(prefix: str) -> str:
    cleaned = str(prefix or "").strip().replace("\\", "/").strip("/")
    if not cleaned:
        raise CloudBackupConfigurationError("MTO_CLOUD_BACKUP_PREFIX cannot be empty.")
    if any(part in ("", ".", "..") for part in cleaned.split("/")):
        raise CloudBackupConfigurationError("MTO_CLOUD_BACKUP_PREFIX contains an unsafe path segment.")
    return f"{cleaned}/"


def load_backup_encryption_key() -> bytes:
    """Loads a strict URL-safe base64-encoded 256-bit key from the secret store."""
    encoded = secrets.get("MTO_BACKUP_ENCRYPTION_KEY", default=None)
    if not encoded:
        raise CloudBackupConfigurationError("MTO_BACKUP_ENCRYPTION_KEY is required when cloud backup is enabled.")
    try:
        raw = base64.b64decode(encoded.strip().encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise CloudBackupConfigurationError("MTO_BACKUP_ENCRYPTION_KEY must be URL-safe base64.") from exc
    if len(raw) != 32:
        raise CloudBackupConfigurationError("MTO_BACKUP_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256).")
    return raw


def _derive_keys(master_key: bytes) -> tuple[bytes, bytes]:
    """Derives separate AES and HMAC keys from the protected master secret."""
    material = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=None,
        info=b"mto-cloud-backup-v1",
    ).derive(master_key)
    return material[:32], material[32:]


def _copy_stream(source, target) -> None:
    for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
        target.write(chunk)


def _compress_sql(sql_path: str, compressed_path: str) -> None:
    with open(sql_path, "rb") as source, open(compressed_path, "wb") as raw_target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_target, compresslevel=6, mtime=0) as target:
            _copy_stream(source, target)


def _encrypt_file(source_path: str, encrypted_path: str, key: bytes) -> None:
    nonce = os.urandom(NONCE_SIZE)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    with open(source_path, "rb") as source, open(encrypted_path, "wb") as target:
        target.write(MAGIC)
        target.write(nonce)
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            target.write(encryptor.update(chunk))
        encryptor.finalize()
        target.write(encryptor.tag)


def _decrypt_file(encrypted_path: str, decrypted_path: str, key: bytes) -> None:
    minimum_size = len(MAGIC) + NONCE_SIZE + TAG_SIZE
    file_size = os.path.getsize(encrypted_path)
    if file_size <= minimum_size:
        raise CloudBackupIntegrityError("Encrypted backup is truncated.")

    with open(encrypted_path, "rb") as source:
        if source.read(len(MAGIC)) != MAGIC:
            raise CloudBackupIntegrityError("Encrypted backup has an unknown file format.")
        nonce = source.read(NONCE_SIZE)
        source.seek(-TAG_SIZE, os.SEEK_END)
        tag = source.read(TAG_SIZE)
        source.seek(len(MAGIC) + NONCE_SIZE)
        remaining = file_size - minimum_size
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        try:
            with open(decrypted_path, "wb") as target:
                while remaining:
                    chunk = source.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise CloudBackupIntegrityError("Encrypted backup ended unexpectedly.")
                    remaining -= len(chunk)
                    target.write(decryptor.update(chunk))
                decryptor.finalize()
        except InvalidTag as exc:
            try:
                os.remove(decrypted_path)
            except OSError:
                pass
            raise CloudBackupIntegrityError("Encrypted backup authentication failed; the file or key is incorrect.") from exc


def _decompress_gzip(compressed_path: str, sql_path: str) -> None:
    try:
        with gzip.open(compressed_path, "rb") as source, open(sql_path, "wb") as target:
            _copy_stream(source, target)
    except (OSError, EOFError) as exc:
        try:
            os.remove(sql_path)
        except OSError:
            pass
        raise CloudBackupIntegrityError("Compressed backup content is invalid.") from exc


def _canonical_manifest(manifest: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_hmac_sha256"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sign_manifest(manifest: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, _canonical_manifest(manifest), hashlib.sha256).hexdigest()


def _validate_manifest(manifest: dict[str, Any], key: bytes) -> None:
    required = {
        "format",
        "version",
        "created_at",
        "key_derivation",
        "artifact_key",
        "compression",
        "encryption",
        "plaintext_sha256",
        "plaintext_size",
        "encrypted_sha256",
        "encrypted_size",
        "manifest_hmac_sha256",
    }
    if not required.issubset(manifest):
        raise CloudBackupIntegrityError("Cloud backup manifest is incomplete.")
    if manifest["format"] != FORMAT_NAME or manifest["version"] != FORMAT_VERSION:
        raise CloudBackupIntegrityError("Cloud backup manifest format is unsupported.")
    if manifest["compression"] != "gzip" or manifest["encryption"] != "AES-256-GCM" or manifest["key_derivation"] != "HKDF-SHA256":
        raise CloudBackupIntegrityError("Cloud backup algorithms are unsupported.")
    signature = str(manifest.get("manifest_hmac_sha256", ""))
    if not hmac.compare_digest(signature, _sign_manifest(manifest, key)):
        raise CloudBackupIntegrityError("Cloud backup manifest signature is invalid.")


@contextmanager
def prepare_cloud_backup(
    sql_path: str,
    plaintext_checksum: str | None = None,
    *,
    prefix: str | None = None,
    encryption_key: bytes | None = None,
) -> Iterator[PreparedCloudBackup]:
    """Builds temporary encrypted cloud files and deletes them after use."""
    source = Path(sql_path)
    if not source.is_file():
        raise CloudBackupError(f"SQL backup file was not found: {sql_path}")

    master_key = encryption_key or load_backup_encryption_key()
    if len(master_key) != 32:
        raise CloudBackupConfigurationError("Cloud backup encryption key must be 32 bytes.")
    aes_key, manifest_key_material = _derive_keys(master_key)
    object_prefix = _normalized_prefix(prefix or mto_config.CLOUD_BACKUP_PREFIX)
    plain_digest = _sha256(str(source))
    if plaintext_checksum and not hmac.compare_digest(plain_digest.lower(), plaintext_checksum.lower()):
        raise CloudBackupIntegrityError("Local SQL checksum changed before cloud encryption began.")

    stem = source.name[:-4] if source.name.lower().endswith(".sql") else source.name
    artifact_name = f"{stem}.sql.gz.enc"
    manifest_name = f"{artifact_name}.manifest.json"
    artifact_key = f"{object_prefix}{artifact_name}"
    manifest_key = f"{object_prefix}{manifest_name}"

    with tempfile.TemporaryDirectory(prefix="mto-cloud-backup-") as temp_dir:
        compressed_path = os.path.join(temp_dir, f"{stem}.sql.gz")
        artifact_path = os.path.join(temp_dir, artifact_name)
        manifest_path = os.path.join(temp_dir, manifest_name)
        _compress_sql(str(source), compressed_path)
        _encrypt_file(compressed_path, artifact_path, aes_key)

        manifest: dict[str, Any] = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "artifact_key": artifact_key,
            "compression": "gzip",
            "encryption": "AES-256-GCM",
            "plaintext_sha256": plain_digest,
            "key_derivation": "HKDF-SHA256",
            "plaintext_size": source.stat().st_size,
            "encrypted_sha256": _sha256(artifact_path),
            "encrypted_size": os.path.getsize(artifact_path),
        }
        manifest["manifest_hmac_sha256"] = _sign_manifest(manifest, manifest_key_material)
        with open(manifest_path, "w", encoding="utf-8", newline="\n") as target:
            json.dump(manifest, target, sort_keys=True, indent=2)
            target.write("\n")

        yield PreparedCloudBackup(
            artifact_path=artifact_path,
            manifest_path=manifest_path,
            artifact_key=artifact_key,
            manifest_key=manifest_key,
            manifest=manifest,
        )


def _backup_sets(objects: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Groups recognized artifact/manifest pairs; returns (sets, unknown objects)."""
    grouped: dict[str, dict[str, Any]] = {}
    unknown: list[dict[str, Any]] = []
    for obj in objects:
        key = str(obj.get("key", ""))
        if key.endswith(".sql.gz.enc.manifest.json"):
            base = key[: -len(".manifest.json")]
            grouped.setdefault(base, {"keys": [], "objects": [], "size": 0, "last_modified": None})
        elif key.endswith(".sql.gz.enc"):
            base = key
            grouped.setdefault(base, {"keys": [], "objects": [], "size": 0, "last_modified": None})
        else:
            unknown.append(obj)
            continue
        entry = grouped[base]
        entry["keys"].append(key)
        entry["objects"].append(obj)
        entry["size"] += int(obj.get("size", 0) or 0)
        modified = obj.get("last_modified")
        if entry["last_modified"] is None or (modified and modified > entry["last_modified"]):
            entry["last_modified"] = modified

    recognized: list[dict[str, Any]] = []
    for base, entry in grouped.items():
        expected = {base, f"{base}.manifest.json"}
        if set(entry["keys"]) == expected:
            recognized.append(entry)
        else:
            unknown.extend(entry["objects"])
    recognized.sort(key=lambda item: item.get("last_modified") or datetime.min.replace(tzinfo=timezone.utc))
    return recognized, unknown


def enforce_cloud_limits(storage, incoming_bytes: int) -> None:
    """Deletes oldest complete backup sets while enforcing retention and quota."""
    prefix = _normalized_prefix(mto_config.CLOUD_BACKUP_PREFIX)
    max_bytes = int(mto_config.CLOUD_BACKUP_MAX_BYTES)
    keep = int(mto_config.CLOUD_BACKUP_KEEP)
    if incoming_bytes <= 0 or incoming_bytes > max_bytes:
        raise CloudBackupQuotaError("Encrypted backup is larger than the configured cloud backup quota.")

    objects = storage.list_objects(prefix=prefix)
    backup_sets, unknown = _backup_sets(objects)
    unknown_bytes = sum(int(item.get("size", 0) or 0) for item in unknown)
    total_bytes = sum(int(item.get("size", 0) or 0) for item in objects)

    # Unknown/incomplete objects are never auto-deleted because they may be unrelated.
    # They still count against the application quota, so the operation fails closed.
    if unknown_bytes + incoming_bytes > max_bytes:
        raise CloudBackupQuotaError("Cloud backup quota is occupied by unknown or incomplete objects; " "manual review is required.")

    while backup_sets and (len(backup_sets) >= keep or total_bytes + incoming_bytes > max_bytes):
        oldest = backup_sets.pop(0)
        if not storage.delete_objects(oldest["keys"]):
            raise CloudBackupQuotaError("Old cloud backups could not be removed safely; upload was stopped.")
        total_bytes -= int(oldest["size"])

    if total_bytes + incoming_bytes > max_bytes:
        raise CloudBackupQuotaError("Cloud backup quota would be exceeded.")


def _best_effort_delete(storage, keys: list[str]) -> None:
    try:
        storage.delete_objects(keys)
    except Exception as exc:
        mto_logger.warning(f"Could not clean incomplete cloud backup objects: {exc}")


def sync_encrypted_backup(
    sql_path: str,
    plaintext_checksum: str | None = None,
    *,
    storage=None,
) -> CloudSyncResult:
    """Encrypts, uploads, and verifies a cloud backup without exposing raw SQL."""
    if not cloud_backup_enabled():
        return CloudSyncResult(False, "DISABLED", "Cloud backup is disabled.")

    activation_ready, activation_message = cloud_backup_activation_ready()
    if not activation_ready:
        return CloudSyncResult(False, "CLOUD_CONFIG_ERROR", activation_message)

    return _sync_encrypted_backup(sql_path, plaintext_checksum, storage=storage)


def sync_encrypted_backup_for_restore_test(
    sql_path: str,
    plaintext_checksum: str | None = None,
    *,
    storage=None,
) -> CloudSyncResult:
    """Uploads one encrypted artifact for the explicit Phase 3 recovery test."""
    if cloud_backup_enabled():
        return CloudSyncResult(
            False,
            "CLOUD_CONFIG_ERROR",
            "Disable live cloud backup before running the Phase 3 restore test.",
        )
    return _sync_encrypted_backup(sql_path, plaintext_checksum, storage=storage)


def _sync_encrypted_backup(
    sql_path: str,
    plaintext_checksum: str | None = None,
    *,
    storage=None,
) -> CloudSyncResult:
    """Shared upload implementation after the caller's activation guard passes."""

    try:
        if storage is None:
            from backend.services.storage_service import backup_storage_service

            storage = backup_storage_service
        if not storage.enabled:
            raise CloudBackupConfigurationError("S3-compatible object storage is not configured.")

        with prepare_cloud_backup(sql_path, plaintext_checksum) as prepared:
            manifest_size = os.path.getsize(prepared.manifest_path)
            incoming_bytes = os.path.getsize(prepared.artifact_path) + manifest_size
            enforce_cloud_limits(storage, incoming_bytes)

            artifact_uploaded = storage.upload_file(
                prepared.artifact_path,
                prepared.artifact_key,
                content_type="application/octet-stream",
            )
            if not artifact_uploaded:
                raise CloudBackupError("Encrypted backup artifact upload failed.")
            manifest_uploaded = storage.upload_file(
                prepared.manifest_path,
                prepared.manifest_key,
                content_type="application/json",
            )
            if not manifest_uploaded:
                _best_effort_delete(storage, [prepared.artifact_key])
                raise CloudBackupError("Cloud backup manifest upload failed.")

            artifact_head = storage.head_object(prepared.artifact_key)
            remote_manifest = storage.get_object_bytes(prepared.manifest_key, max_bytes=1024 * 1024)
            expected_manifest = Path(prepared.manifest_path).read_bytes()
            if not artifact_head or int(artifact_head.get("size", -1)) != prepared.manifest["encrypted_size"] or remote_manifest != expected_manifest:
                _best_effort_delete(storage, [prepared.artifact_key, prepared.manifest_key])
                raise CloudBackupIntegrityError("Cloud upload verification failed; uploaded size or manifest changed.")

            mto_logger.info(f"Encrypted cloud backup uploaded and verified: {prepared.artifact_key}")
            return CloudSyncResult(
                True,
                "UPLOADED",
                "Encrypted cloud backup uploaded and verified.",
                prepared.artifact_key,
                prepared.manifest_key,
            )
    except CloudBackupQuotaError as exc:
        mto_logger.error(f"Cloud backup blocked by quota/retention safeguards: {exc}")
        return CloudSyncResult(False, "CLOUD_QUOTA_BLOCKED", str(exc))
    except CloudBackupConfigurationError as exc:
        mto_logger.error(f"Cloud backup configuration error: {exc}")
        return CloudSyncResult(False, "CLOUD_CONFIG_ERROR", str(exc))
    except Exception as exc:
        mto_logger.error(f"Encrypted cloud backup failed: {exc}")
        return CloudSyncResult(False, "CLOUD_UPLOAD_FAILED", str(exc))


def verify_cloud_backup(
    manifest_key: str,
    *,
    storage=None,
    db_session=None,
) -> tuple[bool, str]:
    """Downloads, authenticates, decrypts, and restore-tests one cloud backup."""
    try:
        if storage is None:
            from backend.services.storage_service import backup_storage_service

            storage = backup_storage_service
        if not storage.enabled:
            raise CloudBackupConfigurationError("Cloud storage is not configured.")

        master_key = load_backup_encryption_key()
        aes_key, manifest_key_material = _derive_keys(master_key)
        manifest_bytes = storage.get_object_bytes(manifest_key, max_bytes=1024 * 1024)
        if not manifest_bytes:
            raise CloudBackupIntegrityError("Cloud backup manifest could not be downloaded.")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloudBackupIntegrityError("Cloud backup manifest is invalid JSON.") from exc
        if not isinstance(manifest, dict):
            raise CloudBackupIntegrityError("Cloud backup manifest has an invalid structure.")
        _validate_manifest(manifest, manifest_key_material)

        prefix = _normalized_prefix(mto_config.CLOUD_BACKUP_PREFIX)
        artifact_key = str(manifest["artifact_key"])
        if not manifest_key.startswith(prefix) or not artifact_key.startswith(prefix):
            raise CloudBackupIntegrityError("Cloud backup object is outside the approved prefix.")
        if manifest_key != f"{artifact_key}.manifest.json":
            raise CloudBackupIntegrityError("Cloud backup manifest and artifact do not match.")

        with tempfile.TemporaryDirectory(prefix="mto-cloud-verify-") as temp_dir:
            encrypted_path = os.path.join(temp_dir, "backup.sql.gz.enc")
            compressed_path = os.path.join(temp_dir, "backup.sql.gz")
            sql_path = os.path.join(temp_dir, "backup.sql")
            if not storage.download_file(artifact_key, encrypted_path):
                raise CloudBackupIntegrityError("Encrypted cloud backup could not be downloaded.")
            if os.path.getsize(encrypted_path) != int(manifest["encrypted_size"]):
                raise CloudBackupIntegrityError("Encrypted cloud backup size does not match.")
            if not hmac.compare_digest(_sha256(encrypted_path), manifest["encrypted_sha256"]):
                raise CloudBackupIntegrityError("Encrypted cloud backup checksum does not match.")

            _decrypt_file(encrypted_path, compressed_path, aes_key)
            _decompress_gzip(compressed_path, sql_path)
            if os.path.getsize(sql_path) != int(manifest["plaintext_size"]):
                raise CloudBackupIntegrityError("Decrypted SQL backup size does not match.")
            if not hmac.compare_digest(_sha256(sql_path), manifest["plaintext_sha256"]):
                raise CloudBackupIntegrityError("Decrypted SQL backup checksum does not match.")
            return verify_sql_dump(
                sql_path,
                db_session=db_session,
                expected_checksum=manifest["plaintext_sha256"],
                require_restore_test=True,
            )
    except Exception as exc:
        mto_logger.error(f"Cloud restore verification failed: {exc}")
        return False, str(exc)
