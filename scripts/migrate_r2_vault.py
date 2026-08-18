"""Migrate the legacy per-user R2 vault to the protected machine vault.

Run this once as Administrator after upgrading a server that configured R2
before the machine-wide vault fix. Secret values are never printed.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.configure_r2_backup import (  # noqa: E402
    _atomic_write_vault,
    _harden_directory,
    _harden_file,
    _read_vault,
)
from utils.secrets_vault import (  # noqa: E402
    resolve_legacy_user_vault_path,
    resolve_secrets_vault_path,
)


TRUE_VALUES = {"1", "true", "yes", "on"}
REQUIRED_PHASE3_KEYS = (
    "MTO_BACKUP_S3_STORAGE_ENABLED",
    "MTO_BACKUP_S3_ENDPOINT_URL",
    "MTO_BACKUP_S3_ACCESS_KEY",
    "MTO_BACKUP_S3_SECRET_KEY",
    "MTO_BACKUP_S3_BUCKET_NAME",
    "MTO_BACKUP_S3_REGION_NAME",
    "MTO_BACKUP_ENCRYPTION_KEY",
    "MTO_CLOUD_BACKUP_PHASE3_VERIFIED",
    "MTO_CLOUD_BACKUP_PHASE3_CONFIG_FINGERPRINT",
    "MTO_ENABLE_CLOUD_BACKUP",
)


def _require_administrator() -> None:
    if os.name != "nt":
        return
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:  # pragma: no cover - Windows API failure
        raise RuntimeError("Could not verify Windows Administrator access.") from exc
    if not is_admin:
        raise RuntimeError("Run this migration from Command Prompt as Administrator.")


def _validate_phase3_vault(vault: dict[str, Any]) -> None:
    missing = [
        key for key in REQUIRED_PHASE3_KEYS if not str(vault.get(key, "") or "").strip()
    ]
    if missing:
        raise RuntimeError(
            "The source vault does not contain a complete Phase 3 configuration. "
            f"Missing keys: {', '.join(missing)}"
        )
    for key in (
        "MTO_BACKUP_S3_STORAGE_ENABLED",
        "MTO_CLOUD_BACKUP_PHASE3_VERIFIED",
        "MTO_ENABLE_CLOUD_BACKUP",
    ):
        if str(vault.get(key, "") or "").strip().lower() not in TRUE_VALUES:
            raise RuntimeError(
                f"The source vault has not activated the required setting: {key}"
            )


def _merge_without_overwrite(
    source: dict[str, Any], destination: dict[str, Any]
) -> dict[str, Any]:
    conflicts = sorted(
        key
        for key, value in source.items()
        if key in destination and destination[key] != value
    )
    if conflicts:
        raise RuntimeError(
            "The machine vault already contains different values for: "
            f"{', '.join(conflicts)}. No files were changed."
        )
    merged = dict(destination)
    merged.update(source)
    return merged


def migrate_vault(
    source_path: Path,
    destination_path: Path,
    *,
    require_administrator: bool = True,
) -> int:
    if require_administrator:
        _require_administrator()

    source_path = Path(source_path)
    destination_path = Path(destination_path)
    if source_path.resolve() == destination_path.resolve():
        raise RuntimeError("The legacy and machine vault paths unexpectedly match.")
    if not source_path.is_file():
        raise RuntimeError(f"Legacy Administrator vault was not found: {source_path}")

    source = _read_vault(source_path)
    _validate_phase3_vault(source)
    destination = _read_vault(destination_path)
    merged = _merge_without_overwrite(source, destination)

    _atomic_write_vault(merged, destination_path)
    persisted = _read_vault(destination_path)
    if persisted != merged:
        raise RuntimeError("Machine vault verification failed after the atomic write.")
    _validate_phase3_vault(persisted)
    _harden_directory(destination_path.parent)
    _harden_file(destination_path)
    return len(merged)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=resolve_legacy_user_vault_path(),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=resolve_secrets_vault_path(),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    try:
        count = migrate_vault(args.source, args.destination)
        print("Protected R2 vault migration PASSED.")
        print(f"Machine vault: {args.destination}")
        print(f"Validated settings migrated: {count}")
        print("Secret values were not displayed.")
        print("Restart the MTO API before running the next Hybrid Backup.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
