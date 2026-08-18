"""Resolve the single protected secrets vault used by every MTO process."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


VAULT_PATH_ENV = "MTO_SECRETS_VAULT_PATH"


def resolve_secrets_vault_path(
    *,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: Path | None = None,
) -> Path:
    """Return a stable machine vault path instead of a process-user path.

    The production API runs as Windows SYSTEM while setup commands are run by
    an Administrator. A ``~/.mto`` default therefore creates two unrelated
    vaults. ProgramData is machine-scoped and is readable by both identities
    after the setup utility applies its restrictive ACL.
    """

    env = os.environ if environment is None else environment
    override = str(env.get(VAULT_PATH_ENV, "") or "").strip()
    if override:
        return Path(override).expanduser()

    platform = os.name if platform_name is None else platform_name
    if platform == "nt":
        program_data = str(env.get("PROGRAMDATA", "") or "").strip()
        base = Path(program_data) if program_data else Path("C:/ProgramData")
        return base / "MTO" / "secrets.json"

    user_home = Path.home() if home is None else Path(home)
    return user_home / ".mto" / "secrets.json"


def resolve_legacy_user_vault_path(*, home: Path | None = None) -> Path:
    """Return the pre-migration per-user vault location."""

    user_home = Path.home() if home is None else Path(home)
    return user_home / ".mto" / "secrets.json"
