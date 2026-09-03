"""Recover the lost MariaDB 10.6 root credential for Phase 1 rotation.

This server-only utility is deliberately specific to the reviewed production
installation. It uses MariaDB's ``init-file`` startup option to change only
``root@localhost`` to the already-staged Phase 1 replacement password. It does
not use ``--skip-grant-tables`` and never displays a secret.

The normal credential rotation must still be resumed after recovery::

    python -m scripts.recover_mariadb_root --preflight
    python -m scripts.recover_mariadb_root --apply
    python -m scripts.rotate_server_credentials --preflight
    python -m scripts.rotate_server_credentials --apply

Do not run this utility on a workstation or package it in ``Treasury.exe``.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pymysql


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.configure_r2_backup import (  # noqa: E402
    _atomic_write_vault,
    _harden_file,
    _read_vault,
)
from scripts.rotate_server_credentials import (  # noqa: E402
    RotationSecrets,
    RotationError,
    ServerDatabaseSettings,
    _account_hosts,
    _api_is_listening,
    _connect,
    _current_secrets,
    _load_database_settings,
    _load_pending_rotation,
    _prepare_rotation,
    _read_server_env,
    _require_administrator,
    _require_backup_ready,
    _validate_database_login,
)
from utils.secrets_vault import resolve_secrets_vault_path  # noqa: E402


CONFIRMATION = "RECOVER MARIADB ROOT FOR PHASE 1"
SERVICE_NAME = "MariaDB"
EXPECTED_EXECUTABLE = Path(r"C:\Program Files\MariaDB 10.6\bin\mysqld.exe")
EXPECTED_DEFAULTS_FILE = Path(r"C:\Program Files\MariaDB 10.6\data\my.ini")
SERVICE_COMMAND_PATTERN = re.compile(
    r'^\s*"(?P<executable>[^"]+)"\s+'
    r'"--defaults-file=(?P<defaults_file>[^"]+)"'
    r'(?:\s+"?MariaDB"?)?\s*$',
    re.IGNORECASE,
)
EXPECTED_SHUTDOWN_ERRORS = {2006, 2013}


class RootRecoveryError(RuntimeError):
    """A redacted, operator-actionable root recovery failure."""


@dataclass(frozen=True)
class MariaDBService:
    name: str
    state: str
    start_mode: str
    executable: Path
    defaults_file: Path
    version: str


@dataclass(frozen=True)
class RecoveryPreflight:
    service_name: str
    service_state: str
    server_version: str
    recovery_required: bool
    pending_rotation: bool


@dataclass(frozen=True)
class RecoveryResult:
    rotation_id: str
    completed_at_utc: str
    root_accounts_discovered: int
    service_restored: bool
    init_file_removed: bool
    resumed: bool


def _require_windows() -> None:
    if os.name != "nt":
        raise RootRecoveryError("MariaDB root recovery is supported on Windows only.")


def _path_key(path: Path | str) -> str:
    return str(path).replace("/", "\\").rstrip("\\").casefold()


def _parse_service_command(command: str) -> tuple[Path, Path]:
    match = SERVICE_COMMAND_PATTERN.fullmatch(str(command or ""))
    if not match:
        raise RootRecoveryError(
            "The MariaDB Windows service command does not match the reviewed layout."
        )
    return Path(match.group("executable")), Path(match.group("defaults_file"))


def _query_service() -> dict[str, str]:
    script = (
        "$service=Get-CimInstance Win32_Service -Filter \"Name='MariaDB'\";"
        "if($null -eq $service){exit 3};"
        "$service | Select-Object Name,State,StartMode,PathName | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RootRecoveryError(
            "Could not inspect the MariaDB Windows service."
        ) from exc
    if result.returncode != 0:
        raise RootRecoveryError("The MariaDB Windows service was not found.")
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RootRecoveryError("The MariaDB service description was invalid.") from exc
    if not isinstance(payload, dict):
        raise RootRecoveryError("The MariaDB service description was invalid.")
    return {str(key): str(value) for key, value in payload.items()}


def _server_version(executable: Path) -> str:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RootRecoveryError("Could not verify the MariaDB server version.") from exc
    version = " ".join((result.stdout or result.stderr or "").split())
    if result.returncode != 0 or "mariadb" not in version.casefold():
        raise RootRecoveryError("The configured database binary is not MariaDB.")
    if not re.search(r"\b10\.6(?:\.|\b)", version):
        raise RootRecoveryError(
            "Only the reviewed MariaDB 10.6 installation is allowed."
        )
    return version


def _validated_service() -> MariaDBService:
    payload = _query_service()
    executable, defaults_file = _parse_service_command(payload.get("PathName", ""))
    if payload.get("Name", "").casefold() != SERVICE_NAME.casefold():
        raise RootRecoveryError("The database service name is not MariaDB.")
    if payload.get("StartMode", "").casefold() != "auto":
        raise RootRecoveryError("The MariaDB service start mode must be Automatic.")
    if _path_key(executable) != _path_key(EXPECTED_EXECUTABLE):
        raise RootRecoveryError("The MariaDB executable path requires manual review.")
    if _path_key(defaults_file) != _path_key(EXPECTED_DEFAULTS_FILE):
        raise RootRecoveryError(
            "The MariaDB defaults-file path requires manual review."
        )
    if not executable.is_file() or not defaults_file.is_file():
        raise RootRecoveryError("A reviewed MariaDB service file is missing.")
    return MariaDBService(
        name=payload["Name"],
        state=payload.get("State", "Unknown"),
        start_mode=payload["StartMode"],
        executable=executable,
        defaults_file=defaults_file,
        version=_server_version(executable),
    )


def _service_state() -> str:
    try:
        result = subprocess.run(
            ["sc.exe", "query", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RootRecoveryError("Could not query the MariaDB service state.") from exc
    if result.returncode != 0:
        raise RootRecoveryError("Could not query the MariaDB service state.")
    match = re.search(
        r"\b(STOPPED|START_PENDING|STOP_PENDING|RUNNING)\b",
        result.stdout,
        re.IGNORECASE,
    )
    if not match:
        raise RootRecoveryError("MariaDB returned an unknown service state.")
    return match.group(1).upper()


def _wait_for_service_state(expected: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _service_state() == expected.upper():
            return
        time.sleep(1)
    raise RootRecoveryError(
        f"MariaDB did not reach the required {expected.upper()} state."
    )


def _control_service(action: str) -> None:
    if action not in {"start", "stop"}:
        raise ValueError("Unsupported service action")
    try:
        result = subprocess.run(
            ["sc.exe", action, SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RootRecoveryError(f"Could not {action} the MariaDB service.") from exc
    if result.returncode not in {0, 1056, 1062}:
        raise RootRecoveryError(f"Could not {action} the MariaDB service.")
    _wait_for_service_state("RUNNING" if action == "start" else "STOPPED")


def _port_is_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _root_authenticates(settings: ServerDatabaseSettings, passwords: list[str]) -> bool:
    attempted: set[str] = set()
    for password in passwords:
        if password in attempted:
            continue
        attempted.add(password)
        try:
            connection = _connect(
                settings,
                user="root",
                password=password,
                database="mysql",
            )
        except pymysql.err.OperationalError as exc:
            error_code = exc.args[0] if exc.args else None
            if error_code == 1045:
                continue
            raise RootRecoveryError(
                "MariaDB root authentication could not be tested safely."
            ) from exc
        except pymysql.MySQLError as exc:
            raise RootRecoveryError(
                "MariaDB root authentication could not be tested safely."
            ) from exc
        connection.close()
        return True
    return False


def _validate_app_login(
    settings: ServerDatabaseSettings, current: Mapping[str, str]
) -> None:
    try:
        _validate_database_login(
            settings,
            user=settings.user,
            password=current["MTO_DB_PASSWORD"],
            database=settings.database,
        )
    except Exception as exc:
        raise RootRecoveryError(
            "The application database account failed validation; recovery stopped."
        ) from exc


def _load_context(project_root: Path, vault_path: Path) -> tuple[
    dict[str, Any],
    dict[str, str],
    ServerDatabaseSettings,
    dict[str, str],
    RotationSecrets | None,
]:
    vault = _read_vault(vault_path)
    environment, _ = _read_server_env(project_root / ".env")
    settings = _load_database_settings(vault, environment)
    current = _current_secrets(vault, environment)
    pending = _load_pending_rotation(vault)
    return vault, environment, settings, current, pending


def _recovery_candidates(
    current: Mapping[str, str], pending: RotationSecrets | None
) -> list[str]:
    candidates = [current["DB_ROOT_PASSWORD"]]
    if pending is not None:
        candidates.insert(0, pending.root_password)
    return candidates


def preflight(
    *,
    project_root: Path = PROJECT_ROOT,
    vault_path: Path | None = None,
    require_administrator: bool = True,
    require_backup: bool = True,
) -> RecoveryPreflight:
    _require_windows()
    if require_administrator:
        _require_administrator()
    service = _validated_service()
    if service.state.casefold() != "running" or _service_state() != "RUNNING":
        raise RootRecoveryError("MariaDB must be running for recovery preflight.")

    resolved_vault = vault_path or resolve_secrets_vault_path()
    _vault, _environment, settings, current, pending = _load_context(
        project_root, resolved_vault
    )
    if require_backup:
        _require_backup_ready()
    _validate_app_login(settings, current)
    recovery_required = not _root_authenticates(
        settings, _recovery_candidates(current, pending)
    )
    return RecoveryPreflight(
        service_name=service.name,
        service_state=service.state,
        server_version=service.version,
        recovery_required=recovery_required,
        pending_rotation=pending is not None,
    )


def _render_init_sql(rotation: RotationSecrets) -> str:
    # Rotation secrets are generated as lowercase hexadecimal by the existing
    # Phase 1 utility, so no SQL quoting ambiguity is possible here.
    if not re.fullmatch(r"[0-9a-f]{64}", rotation.root_password):
        raise RootRecoveryError("The staged root credential failed validation.")
    return (
        "ALTER USER IF EXISTS 'root'@'localhost' "
        f"IDENTIFIED BY '{rotation.root_password}';\n"
    )


def _write_init_file(path: Path, rotation: RotationSecrets) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix="mariadb-root-recovery-",
            suffix=".tmp",
            delete=False,
        ) as target:
            target.write(_render_init_sql(rotation))
            temporary = Path(target.name)
        _harden_file(temporary)
        os.replace(temporary, path)
        _harden_file(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _remove_init_file(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return not path.exists()


def _start_recovery_server(
    service: MariaDBService,
    settings: ServerDatabaseSettings,
    init_file: Path,
):
    command = [
        str(service.executable),
        f"--defaults-file={service.defaults_file}",
        f"--init-file={init_file}",
        "--console",
        "--bind-address=127.0.0.1",
        f"--port={settings.port}",
        "--event-scheduler=OFF",
        "--skip-slave-start",
    ]
    try:
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise RootRecoveryError(
            "Could not start the temporary MariaDB server."
        ) from exc


def _wait_for_recovered_root(
    process,
    settings: ServerDatabaseSettings,
    rotation: RotationSecrets,
    timeout: float = 60.0,
):
    local_settings = ServerDatabaseSettings(
        host="127.0.0.1",
        port=settings.port,
        user=settings.user,
        database=settings.database,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RootRecoveryError(
                "The temporary MariaDB server exited before root recovery completed."
            )
        try:
            connection = _connect(
                local_settings,
                user="root",
                password=rotation.root_password,
                database="mysql",
            )
            with connection.cursor() as cursor:
                cursor.execute("SELECT CURRENT_USER()")
                account = str(cursor.fetchone()[0]).casefold()
            if account != "root@localhost":
                connection.close()
                raise RootRecoveryError(
                    "Recovery authenticated an unexpected MariaDB account."
                )
            return connection
        except RootRecoveryError:
            raise
        except pymysql.MySQLError:
            time.sleep(1)
    raise RootRecoveryError("Timed out waiting for recovered root authentication.")


def _shutdown_recovery_server(connection, process) -> None:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHUTDOWN")
    except pymysql.MySQLError as exc:
        code = int(exc.args[0]) if exc.args and str(exc.args[0]).isdigit() else None
        if code not in EXPECTED_SHUTDOWN_ERRORS:
            raise RootRecoveryError(
                "The temporary MariaDB server did not accept a clean shutdown."
            ) from exc
    finally:
        try:
            connection.close()
        except Exception:
            pass
    try:
        process.wait(timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise RootRecoveryError(
            "The temporary MariaDB server did not stop cleanly."
        ) from exc


def _stop_process_after_failure(process) -> bool:
    if process is None or process.poll() is not None:
        return True
    try:
        process.terminate()
        process.wait(timeout=30)
        return True
    except Exception:
        return False


def _restore_normal_service() -> bool:
    try:
        if _service_state() != "RUNNING":
            _control_service("start")
        return _service_state() == "RUNNING"
    except Exception:
        return False


def recover_root(
    *,
    project_root: Path = PROJECT_ROOT,
    vault_path: Path | None = None,
    require_administrator: bool = True,
    require_backup: bool = True,
) -> RecoveryResult:
    _require_windows()
    if require_administrator:
        _require_administrator()
    if _api_is_listening():
        raise RootRecoveryError(
            "The MTO API is still listening on port 8001. Stop the runtime first."
        )

    service = _validated_service()
    if service.state.casefold() != "running" or _service_state() != "RUNNING":
        raise RootRecoveryError("MariaDB must be running before recovery starts.")
    resolved_vault = vault_path or resolve_secrets_vault_path()
    vault, _environment, settings, current, pending = _load_context(
        project_root, resolved_vault
    )
    if require_backup:
        _require_backup_ready()
    _validate_app_login(settings, current)
    if _root_authenticates(settings, _recovery_candidates(current, pending)):
        raise RootRecoveryError(
            "A configured or staged root credential already works; recovery is not required."
        )

    staged_vault, rotation, resumed = _prepare_rotation(vault)
    if not resumed:
        _atomic_write_vault(staged_vault, resolved_vault)
    if _api_is_listening():
        raise RootRecoveryError(
            "The API restarted after credential staging. Keep it stopped and rerun --apply."
        )

    init_file = resolved_vault.parent / f"mariadb-root-{rotation.rotation_id}.sql"
    process = None
    root_connection = None
    root_hosts: list[str] = []
    service_stopped = False
    init_removed = False
    try:
        _write_init_file(init_file, rotation)
        _control_service("stop")
        service_stopped = True
        if _port_is_listening(settings.port):
            raise RootRecoveryError(
                "The MariaDB port remained occupied after the service stopped."
            )

        process = _start_recovery_server(service, settings, init_file)
        root_connection = _wait_for_recovered_root(process, settings, rotation)
        init_removed = _remove_init_file(init_file)
        if not init_removed:
            raise RootRecoveryError(
                "The protected MariaDB initialization file could not be removed."
            )
        root_hosts = _account_hosts(root_connection, "root")
        if "localhost" not in {host.casefold() for host in root_hosts}:
            raise RootRecoveryError(
                "The expected root@localhost account was not found."
            )
        _shutdown_recovery_server(root_connection, process)
        root_connection = None
        process = None

        _control_service("start")
        service_stopped = False
        _validate_database_login(
            settings,
            user="root",
            password=rotation.root_password,
            database="mysql",
        )
        _validate_app_login(settings, current)
    except Exception as exc:
        stopped_cleanly = False
        if root_connection is not None and process is not None:
            try:
                _shutdown_recovery_server(root_connection, process)
                root_connection = None
                process = None
                stopped_cleanly = True
            except Exception:
                root_connection = None
        elif root_connection is not None:
            try:
                root_connection.close()
            except Exception:
                pass
            root_connection = None
        process_stopped = stopped_cleanly or _stop_process_after_failure(process)
        service_restored = process_stopped and _restore_normal_service()
        init_removed = _remove_init_file(init_file)
        if not service_restored:
            raise RootRecoveryError(
                "Root recovery failed and the normal MariaDB service could not be "
                "restored automatically. Keep the API stopped and start the MariaDB "
                "Windows service before any further action."
            ) from exc
        raise RootRecoveryError(
            "Root recovery stopped safely. The normal MariaDB service was restored "
            "and the staged credential remains protected. Run recovery preflight; "
            "if recovery is no longer required, continue credential rotation."
        ) from exc
    finally:
        if not init_removed:
            _remove_init_file(init_file)

    if service_stopped or _service_state() != "RUNNING":
        raise RootRecoveryError("MariaDB service validation failed after recovery.")
    return RecoveryResult(
        rotation_id=rotation.rotation_id,
        completed_at_utc=datetime.now(timezone.utc).isoformat(),
        root_accounts_discovered=len(root_hosts),
        service_restored=True,
        init_file_removed=True,
        resumed=resumed,
    )


def _write_report(path: Path, result: RecoveryResult) -> None:
    payload = {
        "format_version": 1,
        "operation": "phase_1_mariadb_root_recovery",
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
        default=PROJECT_ROOT / "logs" / "remediation-phase-1-root-recovery.json",
        help="Privacy-safe recovery report path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.preflight:
            result = preflight()
            print("PHASE 1 MARIADB ROOT RECOVERY PREFLIGHT: PASS")
            print("- Hybrid Backup readiness: PASS")
            print(f"- Service: {result.service_name} ({result.service_state})")
            print(f"- MariaDB version: {result.server_version}")
            print(
                "- Root recovery required: "
                f"{'YES' if result.recovery_required else 'NO'}"
            )
            print(
                "- Existing staged rotation: "
                f"{'YES' if result.pending_rotation else 'NO'}"
            )
            print("No service, account, configuration, or credential was changed.")
            return 0

        print("This operation performs controlled MariaDB root-account recovery.")
        print("The MTO API must remain stopped until Phase 1 rotation is complete.")
        typed = input(f"Type {CONFIRMATION} to continue: ").strip()
        if not hmac.compare_digest(typed, CONFIRMATION):
            print("Root recovery cancelled; no new recovery was started.")
            return 2
        result = recover_root()
        try:
            _write_report(args.output, result)
        except Exception as exc:
            print(
                "ERROR: MariaDB root recovery completed, but the privacy-safe "
                f"report could not be written ({type(exc).__name__}).",
                file=sys.stderr,
            )
            print("Do not rerun root recovery. Run the credential-rotation preflight.")
            return 3
        print("PHASE 1 MARIADB ROOT RECOVERY: PASS")
        print(f"- Rotation ID: {result.rotation_id}")
        print(f"- Root accounts discovered: {result.root_accounts_discovered}")
        print("- Normal MariaDB service restored: YES")
        print("- Protected initialization file removed: YES")
        print(f"- Privacy-safe report: {args.output.resolve()}")
        print("Secret values were not displayed.")
        print("Keep the API stopped and run rotate_server_credentials --preflight.")
        return 0
    except (RootRecoveryError, RotationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"ERROR: Root recovery stopped safely ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
