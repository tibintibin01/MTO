"""Securely configure and validate the dedicated Cloudflare R2 backup bucket.

This script intentionally does not enable live cloud backups. It validates a
private, bucket-scoped R2 credential using a random probe object, then stores
credentials in ~/.mto/secrets.json without printing them.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import secrets as py_secrets
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from dotenv import dotenv_values


ACCOUNT_ID_PATTERN = re.compile(r"^[a-fA-F0-9]{32}$")
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
TRUE_VALUES = {"1", "true", "yes", "on"}
VAULT_PATH = Path.home() / ".mto" / "secrets.json"
BACKUP_PREFIX = "backups/"


def validate_account_id(value: str) -> str:
    value = value.strip()
    if not ACCOUNT_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "Cloudflare Account ID must contain exactly 32 hexadecimal characters."
        )
    return value.lower()


def validate_bucket_name(value: str) -> str:
    value = value.strip()
    if not BUCKET_PATTERN.fullmatch(value):
        raise ValueError(
            "Bucket name must be 3-63 characters using lowercase letters, numbers, and hyphens."
        )
    return value


def validate_recovery_path(value: str, project_root: Path) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(project_root.resolve())
    except ValueError:
        return path
    raise ValueError(
        "The recovery key must be stored outside the MTO project directory; "
        "use a protected removable USB drive whenever possible."
    )


def key_fingerprint(encoded_key: str) -> str:
    return hashlib.sha256(encoded_key.encode("ascii")).hexdigest()[:16]


def _read_vault(path: Path = VAULT_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read the existing secrets vault: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("The existing secrets vault must contain a JSON object.")
    return data


def _harden_file(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
        return

    identity_result = subprocess.run(
        ["whoami"], capture_output=True, text=True, check=True, timeout=15
    )
    identity = identity_result.stdout.strip()
    if not identity:
        raise RuntimeError(
            "Could not determine the Windows account for vault permissions."
        )
    result = subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{identity}:(F)",
            "*S-1-5-18:(F)",
            "*S-1-5-32-544:(F)",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Windows could not restrict the secrets file permissions: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def _atomic_write_vault(data: dict[str, Any], path: Path = VAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix="secrets-",
            suffix=".tmp",
            delete=False,
        ) as target:
            temporary_path = Path(target.name)
            json.dump(data, target, sort_keys=True, indent=2)
            target.write("\n")
        _harden_file(temporary_path)
        os.replace(temporary_path, path)
        _harden_file(path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _write_recovery_key(path: Path, encoded_key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "MTO CLOUD BACKUP RECOVERY KEY\n"
        "================================\n"
        f"Key fingerprint: {key_fingerprint(encoded_key)}\n"
        f"MTO_BACKUP_ENCRYPTION_KEY={encoded_key}\n\n"
        "Keep this file offline and protected. Anyone with this key and the encrypted "
        "backup can decrypt municipal data. Losing this key makes cloud backups unrecoverable.\n"
    )
    try:
        with path.open("x", encoding="utf-8", newline="\n") as target:
            target.write(content)
    except FileExistsError as exc:
        raise RuntimeError(
            f"Recovery key file already exists and will not be overwritten: {path}"
        ) from exc
    try:
        _harden_file(path)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _cloud_backup_is_enabled(
    project_root: Path, vault_path: Path | None = None
) -> bool:
    environment_value = os.getenv("MTO_ENABLE_CLOUD_BACKUP", "").strip().lower()
    env_file_value = (
        str(
            dotenv_values(project_root / ".env").get("MTO_ENABLE_CLOUD_BACKUP", "")
            or ""
        )
        .strip()
        .lower()
    )
    vault_value = ""
    if vault_path is not None:
        vault_value = str(
            _read_vault(vault_path).get("MTO_ENABLE_CLOUD_BACKUP", "") or ""
        ).strip().lower()
    return any(
        value in TRUE_VALUES
        for value in (environment_value, env_file_value, vault_value)
    )


def _run_r2_operation(label: str, operation):
    """Run one R2 operation and return a useful error without exposing secrets."""
    try:
        return operation()
    except ClientError as exc:
        response = exc.response or {}
        error = response.get("Error", {})
        metadata = response.get("ResponseMetadata", {})
        status = metadata.get("HTTPStatusCode", "unknown")
        code = str(error.get("Code", "unknown"))
        request_id = (
            metadata.get("RequestId") or error.get("RequestId") or "unavailable"
        )

        if str(status) == "400" or code in {
            "400",
            "InvalidRequest",
            "RequestExpired",
        }:
            hint = (
                "Synchronize Windows date, time, and time zone, then verify that "
                "the values entered are the two R2 credential values, not the "
                "Cloudflare API token value."
            )
        elif str(status) in {"401", "403"} or code in {
            "AccessDenied",
            "InvalidAccessKeyId",
            "SignatureDoesNotMatch",
        }:
            hint = (
                "Verify the R2 credentials and confirm the token has Object Read & "
                "Write permission for this exact bucket."
            )
        elif str(status) == "404" or code in {"404", "NoSuchBucket"}:
            hint = (
                "Verify the bucket name and confirm it belongs to this Cloudflare account."
            )
        else:
            hint = "Review the R2 token scope, bucket name, endpoint, and network connection."

        raise RuntimeError(
            f"R2 {label} failed (HTTP {status}, code {code}, request {request_id}). "
            f"{hint}"
        ) from exc


def test_r2_access(settings: dict[str, str]) -> None:
    """Runs bounded create/read/list/delete checks using a non-taxpayer probe."""
    client = boto3.client(
        "s3",
        endpoint_url=settings["MTO_BACKUP_S3_ENDPOINT_URL"],
        aws_access_key_id=settings["MTO_BACKUP_S3_ACCESS_KEY"],
        aws_secret_access_key=settings["MTO_BACKUP_S3_SECRET_KEY"],
        region_name=settings.get("MTO_BACKUP_S3_REGION_NAME", "auto"),
        use_ssl=True,
        config=Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=20,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )
    bucket = settings["MTO_BACKUP_S3_BUCKET_NAME"]
    probe_key = f"phase2-probe/{uuid.uuid4().hex}.bin"
    probe_data = py_secrets.token_bytes(64)
    uploaded = False
    try:
        # Bucket-scoped Object Read & Write tokens need object operations, not
        # bucket-management access. HeadBucket can hide the real failure behind
        # a generic 400 response, so check the isolated probe prefix instead.
        _run_r2_operation(
            "list check",
            lambda: client.list_objects_v2(
                Bucket=bucket, Prefix="phase2-probe/", MaxKeys=1
            ),
        )
        _run_r2_operation(
            "probe upload",
            lambda: client.put_object(
                Bucket=bucket,
                Key=probe_key,
                Body=probe_data,
                ContentType="application/octet-stream",
            ),
        )
        uploaded = True
        metadata = _run_r2_operation(
            "probe metadata check",
            lambda: client.head_object(Bucket=bucket, Key=probe_key),
        )
        if int(metadata.get("ContentLength", -1)) != len(probe_data):
            raise RuntimeError("R2 returned an unexpected probe-object size.")
        response = _run_r2_operation(
            "probe download",
            lambda: client.get_object(Bucket=bucket, Key=probe_key),
        )
        try:
            downloaded = response["Body"].read(len(probe_data) + 1)
        finally:
            response["Body"].close()
        if downloaded != probe_data:
            raise RuntimeError("R2 probe download did not match the uploaded bytes.")
        listed = _run_r2_operation(
            "uploaded-object list check",
            lambda: client.list_objects_v2(
                Bucket=bucket, Prefix=probe_key, MaxKeys=1
            ),
        )
        if not any(item.get("Key") == probe_key for item in listed.get("Contents", [])):
            raise RuntimeError("R2 token cannot list the uploaded probe object.")
    finally:
        if uploaded:
            _run_r2_operation(
                "probe cleanup",
                lambda: client.delete_object(Bucket=bucket, Key=probe_key),
            )


def _settings_from_vault(vault: dict[str, Any]) -> dict[str, str]:
    keys = (
        "MTO_BACKUP_S3_ENDPOINT_URL",
        "MTO_BACKUP_S3_ACCESS_KEY",
        "MTO_BACKUP_S3_SECRET_KEY",
        "MTO_BACKUP_S3_BUCKET_NAME",
        "MTO_BACKUP_S3_REGION_NAME",
    )
    missing = [key for key in keys if not str(vault.get(key, "")).strip()]
    if missing:
        raise RuntimeError(
            f"Backup vault configuration is incomplete: {', '.join(missing)}"
        )
    return {key: str(vault[key]).strip() for key in keys}


def _configure(project_root: Path, vault_path: Path) -> None:
    if _cloud_backup_is_enabled(project_root, vault_path):
        raise RuntimeError(
            "Live cloud backup is already enabled. Set MTO_ENABLE_CLOUD_BACKUP=0 and "
            "restart the API before running Phase 2 configuration."
        )

    vault = _read_vault(vault_path)
    print("\nMTO Cloudflare R2 Backup - Phase 2")
    print("Cloud backup will remain DISABLED after this configuration.\n")
    account_id = validate_account_id(input("Cloudflare Account ID: "))
    bucket = validate_bucket_name(
        input("Private R2 bucket name [mto-treasury-backups]: ").strip()
        or "mto-treasury-backups"
    )
    access_key = getpass.getpass("R2 Access Key ID (hidden): ").strip()
    secret_key = getpass.getpass("R2 Secret Access Key (hidden): ").strip()
    if not access_key or not secret_key:
        raise RuntimeError("Both R2 credential values are required.")

    encryption_key = str(vault.get("MTO_BACKUP_ENCRYPTION_KEY", "")).strip()
    recovery_path = None
    if encryption_key:
        print(
            f"Existing backup encryption key retained ({key_fingerprint(encryption_key)})."
        )
    else:
        encryption_key = base64.urlsafe_b64encode(py_secrets.token_bytes(32)).decode(
            "ascii"
        )
        recovery_text = (
            input("Offline recovery-key file path (USB drive strongly recommended): ")
            .strip()
            .strip('"')
        )
        if not recovery_text:
            raise RuntimeError(
                "An offline recovery-key path is required for a new key."
            )
        recovery_path = validate_recovery_path(recovery_text, project_root)

    settings = {
        "MTO_BACKUP_S3_STORAGE_ENABLED": "true",
        "MTO_BACKUP_S3_ENDPOINT_URL": f"https://{account_id}.r2.cloudflarestorage.com",
        "MTO_BACKUP_S3_ACCESS_KEY": access_key,
        "MTO_BACKUP_S3_SECRET_KEY": secret_key,
        "MTO_BACKUP_S3_BUCKET_NAME": bucket,
        "MTO_BACKUP_S3_REGION_NAME": "auto",
        "MTO_BACKUP_S3_SECURE": "true",
    }

    confirmation = input(
        f"Test bucket '{bucket}' and save this configuration? Type CONFIGURE: "
    ).strip()
    if confirmation != "CONFIGURE":
        raise RuntimeError("Configuration cancelled; no credentials were saved.")

    print("Testing private bucket access without taxpayer data...")
    test_r2_access(settings)
    if recovery_path:
        _write_recovery_key(recovery_path, encryption_key)
    vault.update(settings)
    vault["MTO_BACKUP_ENCRYPTION_KEY"] = encryption_key
    _atomic_write_vault(vault, vault_path)
    print("R2 create/read/list/delete probe passed.")
    print(f"Encryption key fingerprint: {key_fingerprint(encryption_key)}")
    print(f"Credentials saved securely to: {vault_path}")
    if recovery_path:
        print(f"Offline recovery key saved to: {recovery_path}")
    print("Live cloud backup remains disabled pending Phase 3 restore verification.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Re-run the safe R2 access probe using the existing secrets vault.",
    )
    parser.add_argument(
        "--vault", type=Path, default=VAULT_PATH, help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent.parent
    try:
        if args.check:
            settings = _settings_from_vault(_read_vault(args.vault))
            test_r2_access(settings)
            print(
                "R2 backup bucket readiness check passed; live backup state was unchanged."
            )
        else:
            _configure(project_root, args.vault)
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nConfiguration cancelled; no changes were made.", file=sys.stderr)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
