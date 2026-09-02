"""Strict, non-secret configuration for the desktop API client."""

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Optional
from urllib.parse import urlparse


DEFAULT_SERVER_URL = "http://localhost:8001"
_ALLOWED_KEYS = frozenset({"server_url", "ca_certificate", "client_version"})
_SENSITIVE_KEY_MARKERS = (
    "secret",
    "password",
    "token",
    "database",
    "db_",
    "jwt",
    "private_key",
    "api_key",
)


class ClientConfigurationError(ValueError):
    """Raised when desktop configuration contains unsafe or invalid values."""


@dataclass(frozen=True)
class ClientConfig:
    server_url: str = DEFAULT_SERVER_URL
    ca_certificate: Optional[Path] = None
    client_version: Optional[str] = None
    source_path: Optional[Path] = None


def _candidate_paths() -> list[Path]:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        bundled_dir = Path(getattr(sys, "_MEIPASS", executable_dir)).resolve()
        candidates = [
            executable_dir / "server_config.json",
            bundled_dir / "server_config.json",
        ]
    else:
        project_root = Path(__file__).resolve().parent.parent
        candidates = [
            Path.cwd() / "server_config.json",
            project_root / "server_config.json",
        ]

    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def find_client_config_path() -> Optional[Path]:
    return next((path for path in _candidate_paths() if path.is_file()), None)


def _validate_keys(data: dict[str, Any], source: Path) -> None:
    sensitive = sorted(
        key
        for key in data
        if any(marker in key.lower() for marker in _SENSITIVE_KEY_MARKERS)
    )
    if sensitive:
        raise ClientConfigurationError(
            f"{source.name} contains prohibited sensitive field(s): "
            + ", ".join(sensitive)
        )

    unknown = sorted(set(data) - _ALLOWED_KEYS)
    if unknown:
        raise ClientConfigurationError(
            f"{source.name} contains unsupported field(s): " + ", ".join(unknown)
        )


def _validate_server_url(value: Any, source: Path) -> str:
    server_url = str(value or DEFAULT_SERVER_URL).strip().rstrip("/")
    parsed = urlparse(server_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ClientConfigurationError(
            f"{source.name} server_url must be an http(s) URL with a hostname"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ClientConfigurationError(
            f"{source.name} server_url must not contain credentials, query values, or fragments"
        )
    return server_url


def _certificate_path(value: Any, source: Path) -> Optional[Path]:
    if value is None or not str(value).strip():
        return None
    path = Path(str(value).strip())
    if not path.is_absolute():
        path = source.parent / path
    return path.resolve()


def load_client_config(path: Optional[Path] = None) -> ClientConfig:
    source = Path(path).resolve() if path is not None else find_client_config_path()
    if source is None:
        return ClientConfig()

    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClientConfigurationError(f"Unable to read {source.name}: {exc}") from exc

    if not isinstance(data, dict):
        raise ClientConfigurationError(f"{source.name} must contain a JSON object")

    _validate_keys(data, source)
    version = data.get("client_version")
    if version is not None:
        version = str(version).strip() or None

    return ClientConfig(
        server_url=_validate_server_url(data.get("server_url"), source),
        ca_certificate=_certificate_path(data.get("ca_certificate"), source),
        client_version=version,
        source_path=source,
    )
