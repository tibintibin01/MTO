"""Rotate server database and JWT credentials without displaying secret values.

This is a server-only Phase 1 closure utility. It deliberately stages randomly
generated replacement credentials in the protected machine vault before it
changes MariaDB. If the process is interrupted, rerunning ``--apply`` resumes
the same rotation instead of generating a second, unknown password.

Run from an Administrator Command Prompt on the API server only::

    python -m scripts.rotate_server_credentials --preflight
    python -m scripts.rotate_server_credentials --apply

The API recovery task must be stopped first. The desktop application must
never import or package this module.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import secrets as py_secrets
import socket
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import pymysql
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.configure_r2_backup import (  # noqa: E402
    _atomic_write_vault,
    _harden_file,
    _read_vault,
)
from utils.secrets_vault import resolve_secrets_vault_path  # noqa: E402


CONFIRMATION = "ROTATE PHASE 1 SERVER CREDENTIALS"
ROTATION_STATE_KEY = "MTO_CREDENTIAL_ROTATION_STATE"
ROTATION_ID_KEY = "MTO_CREDENTIAL_ROTATION_ID"
PENDING_KEYS = {
    "MTO_DB_PASSWORD": "MTO_PENDING_DB_PASSWORD",
    "DB_ROOT_PASSWORD": "MTO_PENDING_ROOT_PASSWORD",
    "MTO_JWT_SECRET": "MTO_PENDING_JWT_SECRET",
}
ACTIVE_SECRET_KEYS = tuple(PENDING_KEYS)
LEGACY_SECRET_ALIASES = {
    "API_SECRET_KEY",
    "DB_PASSWORD",
    "JWT_SECRET",
    "MTO_API_SECRET_KEY",
    "SECRET_KEY",
}
ENV_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


class RotationError(RuntimeError):
    """A redacted, operator-actionable credential rotation failure."""


@dataclass(frozen=True)
class ServerDatabaseSettings:
    host: str
    port: int
    user: str
    database: str


@dataclass(frozen=True)
class RotationSecrets:
    rotation_id: str
    app_password: str
    root_password: str
    jwt_secret: str


@dataclass(frozen=True)
class RotationResult:
    rotation_id: str
    completed_at_utc: str
    app_accounts_rotated: int
    root_accounts_rotated: int
    sessions_revoked: int
    resumed: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_administrator() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:  # pragma: no cover - Windows API failure
        raise RotationError("Could not verify Windows Administrator access.") from exc
    if not is_admin:
        raise RotationError("Run this command from Command Prompt as Administrator.")


def _api_is_listening(host: str = "127.0.0.1", port: int = 8001) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _require_api_stopped() -> None:
    if _api_is_listening():
        raise RotationError(
            "The MTO API is still listening on port 8001. Run "
            "scripts\\stop_mto_runtime.ps1 before credential rotation."
        )


def _read_server_env(path: Path) -> tuple[dict[str, str], str]:
    if not path.is_file():
        raise RotationError(f"Server configuration file was not found: {path}")
    try:
        content = path.read_text(encoding="utf-8")
        values = {
            str(key): str(value)
            for key, value in dotenv_values(dotenv_path=path).items()
            if value is not None
        }
    except (OSError, UnicodeError) as exc:
        raise RotationError("The server .env file could not be read.") from exc
    return values, content


def _setting(
    vault: Mapping[str, Any],
    environment: Mapping[str, str],
    key: str,
    *,
    required: bool = True,
) -> str:
    value = str(vault.get(key) or environment.get(key) or "").strip()
    if required and not value:
        raise RotationError(f"Required server setting is missing: {key}")
    return value


def _load_database_settings(
    vault: Mapping[str, Any], environment: Mapping[str, str]
) -> ServerDatabaseSettings:
    host = _setting(vault, environment, "MTO_DB_HOST")
    user = _setting(vault, environment, "MTO_DB_USER")
    database = _setting(vault, environment, "MTO_DB_NAME")
    if user.lower() == "root":
        raise RotationError("The API database account must not be root.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", user):
        raise RotationError("MTO_DB_USER contains unsupported characters.")
    try:
        port = int(_setting(vault, environment, "MTO_DB_PORT"))
    except ValueError as exc:
        raise RotationError("MTO_DB_PORT must be numeric.") from exc
    if not 1 <= port <= 65535:
        raise RotationError("MTO_DB_PORT is outside the valid range.")
    return ServerDatabaseSettings(host=host, port=port, user=user, database=database)


def _current_secrets(
    vault: Mapping[str, Any], environment: Mapping[str, str]
) -> dict[str, str]:
    # Existing credentials may be weak; that is a reason to rotate them, not a
    # reason to make the rotation utility unusable. ``_setting`` still rejects
    # missing values, while replacement credentials are validated separately.
    return {key: _setting(vault, environment, key) for key in ACTIVE_SECRET_KEYS}


def _validate_rotation_secrets(rotation: RotationSecrets) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", rotation.rotation_id):
        raise RotationError("The prepared credential rotation identifier is invalid.")
    if len(rotation.app_password) < 32 or len(rotation.root_password) < 32:
        raise RotationError("Replacement database credentials do not meet policy.")
    if len(rotation.jwt_secret) < 64:
        raise RotationError("The replacement JWT signing secret does not meet policy.")
    if len({rotation.app_password, rotation.root_password, rotation.jwt_secret}) != 3:
        raise RotationError("Replacement credentials must be distinct.")


def _load_pending_rotation(vault: Mapping[str, Any]) -> RotationSecrets | None:
    state = str(vault.get(ROTATION_STATE_KEY, "") or "").strip()
    pending_metadata = (ROTATION_ID_KEY, *PENDING_KEYS.values())
    if not state:
        if any(str(vault.get(key, "") or "").strip() for key in pending_metadata):
            raise RotationError(
                "The protected vault contains incomplete credential rotation metadata."
            )
        return None
    if state != "prepared":
        raise RotationError("The protected vault contains an unknown rotation state.")

    pending = {
        active: str(vault.get(pending_key, "") or "").strip()
        for active, pending_key in PENDING_KEYS.items()
    }
    rotation = RotationSecrets(
        rotation_id=str(vault.get(ROTATION_ID_KEY, "") or "").strip(),
        app_password=pending["MTO_DB_PASSWORD"],
        root_password=pending["DB_ROOT_PASSWORD"],
        jwt_secret=pending["MTO_JWT_SECRET"],
    )
    if not rotation.rotation_id or any(not value for value in pending.values()):
        raise RotationError("The prepared credential rotation is incomplete.")
    _validate_rotation_secrets(rotation)
    return rotation


def _prepare_rotation(
    vault: Mapping[str, Any],
    *,
    token_hex: Callable[[int], str] = py_secrets.token_hex,
) -> tuple[dict[str, Any], RotationSecrets, bool]:
    pending = _load_pending_rotation(vault)
    if pending is not None:
        return dict(vault), pending, True

    rotation = RotationSecrets(
        rotation_id=uuid.uuid4().hex,
        app_password=token_hex(32),
        root_password=token_hex(32),
        jwt_secret=token_hex(64),
    )
    _validate_rotation_secrets(rotation)

    staged = dict(vault)
    staged[ROTATION_STATE_KEY] = "prepared"
    staged[ROTATION_ID_KEY] = rotation.rotation_id
    staged[PENDING_KEYS["MTO_DB_PASSWORD"]] = rotation.app_password
    staged[PENDING_KEYS["DB_ROOT_PASSWORD"]] = rotation.root_password
    staged[PENDING_KEYS["MTO_JWT_SECRET"]] = rotation.jwt_secret
    return staged, rotation, False


def _finalize_vault(
    vault: Mapping[str, Any], rotation: RotationSecrets, completed_at: datetime
) -> dict[str, Any]:
    final = dict(vault)
    final["MTO_DB_PASSWORD"] = rotation.app_password
    final["DB_ROOT_PASSWORD"] = rotation.root_password
    final["MTO_JWT_SECRET"] = rotation.jwt_secret
    final["MTO_LAST_CREDENTIAL_ROTATION_ID"] = rotation.rotation_id
    final["MTO_LAST_CREDENTIAL_ROTATION_AT"] = completed_at.isoformat()
    for key in (*PENDING_KEYS.values(), ROTATION_STATE_KEY, ROTATION_ID_KEY):
        final.pop(key, None)
    for key in LEGACY_SECRET_ALIASES:
        final.pop(key, None)
    return final


def _render_rotated_env(content: str, rotation: RotationSecrets) -> str:
    replacements = {
        "MTO_DB_PASSWORD": rotation.app_password,
        "DB_ROOT_PASSWORD": rotation.root_password,
        "MTO_JWT_SECRET": rotation.jwt_secret,
    }
    rendered: list[str] = []
    written: set[str] = set()
    for line in content.splitlines():
        match = ENV_ASSIGNMENT.match(line)
        if not match:
            rendered.append(line)
            continue
        key = match.group(1)
        if key in LEGACY_SECRET_ALIASES or key in PENDING_KEYS.values():
            continue
        if key in replacements:
            if key not in written:
                rendered.append(f"{key}={replacements[key]}")
                written.add(key)
            continue
        rendered.append(line)
    if rendered and rendered[-1] != "":
        rendered.append("")
    for key, value in replacements.items():
        if key not in written:
            rendered.append(f"{key}={value}")
    return "\n".join(rendered).rstrip("\n") + "\n"


def _atomic_write_server_env(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix="mto-env-",
            suffix=".tmp",
            delete=False,
        ) as target:
            target.write(content)
            temporary = Path(target.name)
        _harden_file(temporary)
        os.replace(temporary, path)
        _harden_file(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def _connect(
    settings: ServerDatabaseSettings,
    *,
    user: str,
    password: str,
    database: str,
):
    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
        autocommit=True,
    )


def _connect_with_candidates(
    settings: ServerDatabaseSettings,
    *,
    user: str,
    passwords: list[str],
    database: str,
):
    attempted: set[str] = set()
    for password in passwords:
        if not password or password in attempted:
            continue
        attempted.add(password)
        try:
            return _connect(settings, user=user, password=password, database=database)
        except pymysql.MySQLError:
            continue
    raise RotationError(
        f"Database authentication failed for the configured {user!r} account."
    )


def _account_hosts(connection, user: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT Host FROM mysql.user WHERE User=%s ORDER BY Host", (user,)
        )
        return [str(row[0]) for row in cursor.fetchall()]


def _alter_account_passwords(
    connection, user: str, hosts: list[str], password: str
) -> None:
    if not hosts:
        raise RotationError(f"No MariaDB accounts were found for {user!r}.")
    with connection.cursor() as cursor:
        for host in hosts:
            cursor.execute("ALTER USER %s@%s IDENTIFIED BY %s", (user, host, password))


def _validate_database_login(
    settings: ServerDatabaseSettings, *, user: str, password: str, database: str
) -> None:
    connection = _connect(settings, user=user, password=password, database=database)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone()[0] != 1:
                raise RotationError("Database validation returned an invalid result.")
    finally:
        connection.close()


def _revoke_sessions_and_audit(
    settings: ServerDatabaseSettings, rotation: RotationSecrets
) -> int:
    connection = _connect(
        settings,
        user=settings.user,
        password=rotation.app_password,
        database=settings.database,
    )
    try:
        connection.begin()
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE refresh_tokens SET is_revoked=TRUE, revoked_at=NOW() "
                "WHERE is_revoked=FALSE"
            )
            revoked = int(cursor.rowcount)
            cursor.execute(
                "INSERT INTO audit_logs "
                "(user_id, username, action, table_name, record_id, old_values, "
                "new_values, ip_address, timestamp) "
                "VALUES (NULL, %s, %s, %s, NULL, NULL, %s, %s, NOW())",
                (
                    "SYSTEM",
                    "PHASE1_SERVER_CREDENTIAL_ROTATION",
                    "system_security",
                    json.dumps(
                        {
                            "rotation_id": rotation.rotation_id,
                            "sessions_revoked": revoked,
                        },
                        sort_keys=True,
                    ),
                    "127.0.0.1",
                ),
            )
        connection.commit()
        return revoked
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _require_backup_ready() -> None:
    from scripts.capture_remediation_baseline import (
        assess_database_readiness,
        capture_configured_database,
    )

    snapshot = capture_configured_database()
    issues = assess_database_readiness(snapshot)
    if issues:
        raise RotationError("Hybrid Backup readiness failed: " + "; ".join(issues))


def _database_preflight(
    settings: ServerDatabaseSettings,
    current: Mapping[str, str],
    pending: RotationSecrets | None,
) -> tuple[int, int]:
    root_candidates = [current["DB_ROOT_PASSWORD"]]
    app_candidates = [current["MTO_DB_PASSWORD"]]
    if pending:
        root_candidates.insert(0, pending.root_password)
        app_candidates.insert(0, pending.app_password)

    root = _connect_with_candidates(
        settings,
        user="root",
        passwords=root_candidates,
        database="mysql",
    )
    try:
        root_hosts = _account_hosts(root, "root")
        app_hosts = _account_hosts(root, settings.user)
    finally:
        root.close()
    if not root_hosts:
        raise RotationError("No MariaDB root accounts were found.")
    if not app_hosts:
        raise RotationError(f"No MariaDB accounts were found for {settings.user!r}.")

    app = _connect_with_candidates(
        settings,
        user=settings.user,
        passwords=app_candidates,
        database=settings.database,
    )
    app.close()
    return len(app_hosts), len(root_hosts)


def preflight(
    *,
    project_root: Path = PROJECT_ROOT,
    vault_path: Path | None = None,
    require_administrator: bool = True,
    require_backup: bool = True,
) -> tuple[int, int, bool]:
    if require_administrator:
        _require_administrator()
    _require_api_stopped()
    resolved_vault = vault_path or resolve_secrets_vault_path()
    vault = _read_vault(resolved_vault)
    environment, _ = _read_server_env(project_root / ".env")
    settings = _load_database_settings(vault, environment)
    current = _current_secrets(vault, environment)
    pending = _load_pending_rotation(vault)
    resumed = pending is not None
    if require_backup:
        _require_backup_ready()
    app_hosts, root_hosts = _database_preflight(settings, current, pending)
    return app_hosts, root_hosts, resumed


def rotate_credentials(
    *,
    project_root: Path = PROJECT_ROOT,
    vault_path: Path | None = None,
    require_administrator: bool = True,
    require_backup: bool = True,
) -> RotationResult:
    if require_administrator:
        _require_administrator()
    _require_api_stopped()
    resolved_vault = vault_path or resolve_secrets_vault_path()
    vault = _read_vault(resolved_vault)
    environment, env_content = _read_server_env(project_root / ".env")
    settings = _load_database_settings(vault, environment)
    current = _current_secrets(vault, environment)
    staged_vault, rotation, resumed = _prepare_rotation(vault)

    if require_backup:
        _require_backup_ready()
    _database_preflight(settings, current, rotation if resumed else None)

    if not resumed:
        _atomic_write_vault(staged_vault, resolved_vault)
    # Refuse a race with the API supervisor after staging recoverable secrets.
    _require_api_stopped()

    root = _connect_with_candidates(
        settings,
        user="root",
        passwords=[rotation.root_password, current["DB_ROOT_PASSWORD"]],
        database="mysql",
    )
    try:
        app_hosts = _account_hosts(root, settings.user)
        root_hosts = _account_hosts(root, "root")
        _alter_account_passwords(root, settings.user, app_hosts, rotation.app_password)
        _alter_account_passwords(root, "root", root_hosts, rotation.root_password)
    except Exception as exc:
        raise RotationError(
            "MariaDB credential rotation did not complete. The prepared "
            "replacement credentials remain in the protected vault; keep the "
            "API stopped and rerun --apply to resume."
        ) from exc
    finally:
        root.close()

    try:
        _validate_database_login(
            settings,
            user=settings.user,
            password=rotation.app_password,
            database=settings.database,
        )
        _validate_database_login(
            settings,
            user="root",
            password=rotation.root_password,
            database="mysql",
        )
        sessions_revoked = _revoke_sessions_and_audit(settings, rotation)
        _atomic_write_server_env(
            project_root / ".env", _render_rotated_env(env_content, rotation)
        )
        completed_at = _utc_now()
        final_vault = _finalize_vault(staged_vault, rotation, completed_at)
        _atomic_write_vault(final_vault, resolved_vault)
    except Exception as exc:
        raise RotationError(
            "Credential verification or finalization failed. Prepared credentials "
            "remain recoverable in the protected vault; keep the API stopped and "
            "rerun --apply."
        ) from exc

    return RotationResult(
        rotation_id=rotation.rotation_id,
        completed_at_utc=completed_at.isoformat(),
        app_accounts_rotated=len(app_hosts),
        root_accounts_rotated=len(root_hosts),
        sessions_revoked=sessions_revoked,
        resumed=resumed,
    )


def _write_report(path: Path, result: RotationResult) -> None:
    payload = {
        "format_version": 1,
        "operation": "phase_1_server_credential_rotation",
        "secret_values_recorded": False,
        **asdict(result),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "logs" / "remediation-phase-1-credential-rotation.json",
        help="Privacy-safe rotation report path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.preflight:
            app_hosts, root_hosts, resumed = preflight()
            print("PHASE 1 SERVER CREDENTIAL ROTATION PREFLIGHT: PASS")
            print("- Hybrid Backup readiness: PASS")
            print("- MTO API stopped: PASS")
            print(f"- Application database accounts: {app_hosts}")
            print(f"- Database root accounts: {root_hosts}")
            print(f"- Interrupted rotation to resume: {'YES' if resumed else 'NO'}")
            print("No credentials were changed or displayed.")
            return 0

        print("This operation changes the server database and signing credentials.")
        print("All active sessions will be revoked and the API must remain stopped.")
        typed = input(f"Type {CONFIRMATION} to continue: ").strip()
        if not hmac.compare_digest(typed, CONFIRMATION):
            print("Credential rotation cancelled; no new rotation was started.")
            return 2
        result = rotate_credentials()
        try:
            _write_report(args.output, result)
        except Exception as exc:
            # At this point the database, server .env, and vault are already
            # finalized. A report I/O failure must never lead the operator to
            # run a second rotation under the false impression that it failed.
            print(
                "ERROR: Credentials were rotated successfully, but the "
                f"privacy-safe report could not be written ({type(exc).__name__}).",
                file=sys.stderr,
            )
            print("Do not rerun --apply. Restart the API and complete validation.")
            return 3
        print("PHASE 1 SERVER CREDENTIAL ROTATION: PASS")
        print(f"- Rotation ID: {result.rotation_id}")
        print(f"- Application database accounts rotated: {result.app_accounts_rotated}")
        print(f"- Database root accounts rotated: {result.root_accounts_rotated}")
        print(f"- Active sessions revoked: {result.sessions_revoked}")
        print(f"- Privacy-safe report: {args.output.resolve()}")
        print("Secret values were not displayed.")
        print("Restart the MTO API and run the Phase 1 post-rotation checks.")
        return 0
    except RotationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Do not render third-party exception messages; they can contain
        # connection details. The exception type is enough for server logs.
        print(
            f"ERROR: Credential rotation stopped safely ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
