"""Fail closed when server-only code or secrets enter the desktop package."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
ENTRYPOINT = PROJECT_ROOT / "clients" / "desktop" / "main.py"
SPEC_PATH = PROJECT_ROOT / "Treasury.spec"
CLIENT_SOURCE_DIRS = (
    PROJECT_ROOT / "clients" / "desktop",
    PROJECT_ROOT / "api_clients",
    PROJECT_ROOT / "ui",
)
SHARED_CLIENT_FILES = (
    PROJECT_ROOT / "utils" / "__init__.py",
    PROJECT_ROOT / "utils" / "metrics.py",
)
FORBIDDEN_IMPORTS = frozenset(
    {
        "alembic",
        "backend",
        "boto3",
        "botocore",
        "database_hardening_tool",
        "dotenv",
        "migration_manager",
        "pymysql",
        "scripts.recover_mariadb_root",
        "scripts.rotate_server_credentials",
        "sqlalchemy",
        "utils.config",
        "utils.db_compat",
        "utils.logger",
        "utils.secrets_manager",
    }
)
REQUIRED_SPEC_EXCLUDES = FORBIDDEN_IMPORTS | {"pytest"}
FORBIDDEN_DATA_SOURCES = frozenset({".env", "api_clients", "backend", "ui", "utils"})
FORBIDDEN_ENTRYPOINT_TEXT = (
    ".env",
    "load_dotenv",
    "migration_manager",
    "SECRET_KEY",
    "MTO_DB_",
    "DATABASE_URL",
    "JWT_SECRET",
)
FORBIDDEN_DISTRIBUTION_NAMES = frozenset({".env", "secrets.json", "credentials.json"})


def _python_sources() -> Iterable[Path]:
    for directory in CLIENT_SOURCE_DIRS:
        yield from directory.rglob("*.py")
    yield from SHARED_CLIENT_FILES


def _module_is_forbidden(module: str) -> bool:
    return any(
        module == item or module.startswith(f"{item}.") for item in FORBIDDEN_IMPORTS
    )


def _imports(path: Path) -> Iterable[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module


def verify_source_boundary() -> list[str]:
    errors: list[str] = []
    for source in _python_sources():
        for line, module in _imports(source):
            if _module_is_forbidden(module):
                relative = source.relative_to(PROJECT_ROOT)
                errors.append(f"{relative}:{line} imports forbidden module {module}")

    entrypoint_text = ENTRYPOINT.read_text(encoding="utf-8-sig")
    for marker in FORBIDDEN_ENTRYPOINT_TEXT:
        if marker in entrypoint_text:
            errors.append(f"desktop entrypoint contains forbidden marker {marker!r}")
    return errors


def _analysis_keyword(tree: ast.AST, name: str):
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    ]
    if len(calls) != 1:
        raise ValueError("Treasury.spec must contain exactly one Analysis call")
    keyword = next((item for item in calls[0].keywords if item.arg == name), None)
    if keyword is None:
        raise ValueError(f"Treasury.spec Analysis is missing {name}")
    return ast.literal_eval(keyword.value)


def verify_spec_boundary() -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(
            SPEC_PATH.read_text(encoding="utf-8-sig"), filename=str(SPEC_PATH)
        )
        datas = _analysis_keyword(tree, "datas")
        hiddenimports = set(_analysis_keyword(tree, "hiddenimports"))
        excludes = set(_analysis_keyword(tree, "excludes"))
    except (OSError, SyntaxError, ValueError) as exc:
        return [f"unable to validate Treasury.spec: {exc}"]

    for source, _destination in datas:
        normalized = str(source).replace("\\", "/").rstrip("/")
        basename = normalized.rsplit("/", 1)[-1]
        if normalized in FORBIDDEN_DATA_SOURCES or basename in FORBIDDEN_DATA_SOURCES:
            errors.append(f"Treasury.spec copies forbidden data source {source!r}")
        if normalized.startswith("backend/") or normalized.endswith(".key"):
            errors.append(
                f"Treasury.spec copies server/private-key material {source!r}"
            )

    for module in sorted(hiddenimports):
        if _module_is_forbidden(module):
            errors.append(f"Treasury.spec hidden-imports forbidden module {module}")

    missing = sorted(REQUIRED_SPEC_EXCLUDES - excludes)
    if missing:
        errors.append(
            "Treasury.spec is missing required excludes: " + ", ".join(missing)
        )
    return errors


def verify_client_config(require_config: bool = False) -> list[str]:
    from api_clients.client_config import find_client_config_path, load_client_config

    path = find_client_config_path()
    if path is None:
        return (
            ["server_config.json is required but was not found"]
            if require_config
            else []
        )
    try:
        load_client_config(path)
    except ValueError as exc:
        return [f"unsafe desktop configuration: {exc}"]
    return []


def verify_pyz_manifest(path: Path) -> list[str]:
    """Inspect the actual PyInstaller PYZ manifest after a build."""
    try:
        manifest = ast.literal_eval(path.read_text(encoding="utf-8-sig"))
        entries = manifest[1]
        modules = {str(entry[0]) for entry in entries}
    except (OSError, SyntaxError, ValueError, IndexError, TypeError) as exc:
        return [f"unable to validate PyInstaller manifest {path}: {exc}"]

    prohibited = sorted(
        module
        for module in modules
        if _module_is_forbidden(module)
        or module == "pytest"
        or module.startswith("pytest.")
    )
    if prohibited:
        return ["built PYZ contains prohibited module(s): " + ", ".join(prohibited)]
    return []


def verify_distribution(path: Path) -> list[str]:
    if not path.exists():
        return [f"distribution directory does not exist: {path}"]
    errors: list[str] = []
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        lowered = item.name.lower()
        if (
            lowered in FORBIDDEN_DISTRIBUTION_NAMES
            or lowered.endswith(".key")
            or "private_key" in lowered
        ):
            errors.append(f"forbidden sensitive build companion: {item}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-config", action="store_true")
    parser.add_argument("--distribution", type=Path)
    parser.add_argument("--pyz-manifest", type=Path)
    args = parser.parse_args()

    errors = verify_source_boundary()
    errors.extend(verify_spec_boundary())
    errors.extend(verify_client_config(require_config=args.require_config))
    if args.distribution is not None:
        errors.extend(verify_distribution(args.distribution.resolve()))
    if args.pyz_manifest is not None:
        errors.extend(verify_pyz_manifest(args.pyz_manifest.resolve()))

    if errors:
        print("DESKTOP TRUST BOUNDARY: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("DESKTOP TRUST BOUNDARY: PASS")
    print(
        "- No server database, migration, or secret modules are imported by client sources."
    )
    print("- Treasury.spec excludes server-only modules and sensitive build inputs.")
    print("- Desktop configuration contains endpoint metadata only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
