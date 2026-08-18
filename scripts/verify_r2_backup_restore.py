"""Run the one-time Phase 3 encrypted R2 recovery test.

The command keeps live cloud backup disabled while it uploads one encrypted
SQL dump, downloads it into a temporary directory, authenticates and decrypts
it, and restores it into an isolated verification database. Only a complete
restore records the Phase 3 attestation. The operator must separately confirm
activation after the test passes.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.configure_r2_backup import (  # noqa: E402
    VAULT_PATH,
    _atomic_write_vault,
    _read_vault,
    _settings_from_vault,
    test_r2_access,
)


CHECKSUM_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_source(explicit_source: str | None, backup_dir: str) -> Path:
    if explicit_source:
        source = Path(explicit_source).expanduser().resolve()
    else:
        local_dir = Path(backup_dir).expanduser().resolve() / "local"
        candidates = [path for path in local_dir.glob("*.sql") if path.is_file()]
        if not candidates:
            raise RuntimeError(
                f"No local SQL backup was found in {local_dir}. Run one local Hybrid "
                "Backup while cloud backup is disabled, then run Phase 3 again."
            )
        source = max(candidates, key=lambda path: path.stat().st_mtime)

    if not source.is_file() or source.suffix.lower() != ".sql":
        raise RuntimeError(f"Phase 3 requires an existing .sql backup file: {source}")
    return source


def _validated_checksum(source: Path) -> str:
    actual = _sha256(source)
    checksum_path = Path(f"{source}.sha256")
    if not checksum_path.exists():
        return actual

    recorded = checksum_path.read_text(encoding="utf-8").strip().split()[0]
    if not CHECKSUM_PATTERN.fullmatch(recorded):
        raise RuntimeError(f"The checksum file is invalid: {checksum_path}")
    if recorded.lower() != actual.lower():
        raise RuntimeError(
            "The local SQL backup no longer matches its recorded SHA-256 checksum."
        )
    return actual


def _load_verification_credentials(vault: dict) -> tuple[str, str, bool]:
    user = str(vault.get("MTO_BACKUP_VERIFY_DB_USER", "") or "").strip()
    password = str(vault.get("MTO_BACKUP_VERIFY_DB_PASSWORD", "") or "")
    if user:
        return user, password, False

    print(
        "Phase 3 requires a MariaDB/MySQL verification account that can create "
        "and drop an isolated temporary database. This is not an MTO application "
        "login. The credentials are hidden and are saved only after the full test passes."
    )
    user = input("Verification DB username: ").strip()
    password = getpass.getpass("Verification DB password (hidden): ")
    if not user or not password:
        raise RuntimeError(
            "A dedicated verification DB username and password are required."
        )
    return user, password, True


def _create_phase3_storage():
    from backend.services.storage_service import StorageService

    storage = StorageService(
        settings_prefix="MTO_BACKUP_S3",
        allow_bucket_create=False,
        enable_versioning=False,
        activation_setting=None,
        object_prefix_access_check="backups/",
    )
    if not storage.enabled:
        raise RuntimeError(
            "The dedicated R2 backup storage could not be initialized. Re-run "
            "python scripts/configure_r2_backup.py --check and review the server log."
        )
    return storage


def _record_success(
    vault: dict,
    *,
    verification_user: str,
    verification_password: str,
    persist_verification_credentials: bool,
    config_fingerprint: str,
    manifest_key: str,
    checksum: str,
    activate: bool,
) -> None:
    if persist_verification_credentials:
        vault["MTO_BACKUP_VERIFY_DB_USER"] = verification_user
        vault["MTO_BACKUP_VERIFY_DB_PASSWORD"] = verification_password
    vault["MTO_CLOUD_BACKUP_PHASE3_VERIFIED"] = "true"
    vault["MTO_CLOUD_BACKUP_PHASE3_VERIFIED_AT"] = datetime.now(
        timezone.utc
    ).isoformat()
    vault["MTO_CLOUD_BACKUP_PHASE3_CONFIG_FINGERPRINT"] = config_fingerprint
    vault["MTO_CLOUD_BACKUP_PHASE3_MANIFEST_KEY"] = manifest_key
    vault["MTO_CLOUD_BACKUP_PHASE3_SOURCE_SHA256"] = checksum
    vault["MTO_ENABLE_CLOUD_BACKUP"] = "true" if activate else "false"
    _atomic_write_vault(vault, VAULT_PATH)


def run_phase3(source_arg: str | None = None) -> int:
    vault = _read_vault(VAULT_PATH)
    settings = _settings_from_vault(vault)
    verification_user, verification_password, persist_credentials = (
        _load_verification_credentials(vault)
    )

    # Make newly supplied credentials available before the singleton secrets
    # manager and database modules are imported in this process.
    os.environ["MTO_BACKUP_VERIFY_DB_USER"] = verification_user
    os.environ["MTO_BACKUP_VERIFY_DB_PASSWORD"] = verification_password

    from backend.services.cloud_backup_service import (
        cloud_backup_configuration_fingerprint,
        cloud_backup_enabled,
        sync_encrypted_backup_for_restore_test,
        verify_cloud_backup,
    )
    from utils.config import config as mto_config

    if cloud_backup_enabled():
        raise RuntimeError(
            "Live cloud backup is already enabled. Set MTO_ENABLE_CLOUD_BACKUP to "
            "false in the protected vault, restart the API, and rerun Phase 3."
        )

    source = _resolve_source(source_arg, mto_config.BACKUP_DIR)
    checksum = _validated_checksum(source)
    print("\nMTO Cloudflare R2 Backup - Phase 3")
    print("Live cloud backup remains DISABLED during this test.")
    print(f"Source backup: {source.name}")
    print(f"Source checksum: {checksum[:16]}...{checksum[-8:]}")
    confirmation = input(
        "Upload this backup encrypted and perform an isolated restore? "
        "Type RESTORE TEST: "
    ).strip()
    if confirmation != "RESTORE TEST":
        raise RuntimeError("Phase 3 cancelled; cloud backup remains disabled.")

    print("Checking private R2 access without taxpayer data...")
    test_r2_access(settings)
    storage = _create_phase3_storage()

    print("Encrypting and uploading one backup...")
    upload = sync_encrypted_backup_for_restore_test(
        str(source), checksum, storage=storage
    )
    if not upload.success or not upload.manifest_key:
        raise RuntimeError(f"Encrypted upload failed: {upload.message}")

    print("Downloading, authenticating, decrypting, and restore-testing...")
    verified, message = verify_cloud_backup(upload.manifest_key, storage=storage)
    if not verified or "skipped" in str(message).lower():
        raise RuntimeError(
            "Phase 3 did not complete a real database restore. Live cloud backup "
            f"remains disabled. Details: {message}"
        )

    print(f"Restore verification passed: {message}")
    activation = input(
        "Type ACTIVATE CLOUD BACKUP to enable cloud copies for future Hybrid "
        "Backups, or press Enter to keep it disabled: "
    ).strip()
    activate = activation == "ACTIVATE CLOUD BACKUP"
    _record_success(
        vault,
        verification_user=verification_user,
        verification_password=verification_password,
        persist_verification_credentials=persist_credentials,
        config_fingerprint=cloud_backup_configuration_fingerprint(),
        manifest_key=upload.manifest_key,
        checksum=checksum,
        activate=activate,
    )

    print("Phase 3 encrypted cloud restore verification PASSED.")
    if activate:
        print(
            "Cloud backup is activated. Restart the MTO API, then run one Hybrid "
            "Backup and confirm the dashboard reports cloud protection."
        )
    else:
        print("Cloud backup remains disabled by operator choice.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        help="Optional explicit local .sql backup; defaults to the newest local backup.",
    )
    args = parser.parse_args()
    try:
        return run_phase3(args.source)
    except (EOFError, KeyboardInterrupt):
        print("\nPhase 3 cancelled; cloud backup remains disabled.", file=sys.stderr)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
