import json
from pathlib import Path

import pymysql
import pytest

from scripts import recover_mariadb_root as recovery


def _settings():
    return recovery.ServerDatabaseSettings(
        host="127.0.0.1",
        port=3306,
        user="mto_app",
        database="property_system",
    )


def _service():
    return recovery.MariaDBService(
        name="MariaDB",
        state="Running",
        start_mode="Auto",
        executable=recovery.EXPECTED_EXECUTABLE,
        defaults_file=recovery.EXPECTED_DEFAULTS_FILE,
        version="mysqld.exe Ver 15.1 Distrib 10.6.20-MariaDB",
    )


def _rotation():
    return recovery.RotationSecrets(
        rotation_id="1" * 32,
        app_password="a" * 64,
        root_password="b" * 64,
        jwt_secret="c" * 128,
    )


def _current():
    return {
        "MTO_DB_PASSWORD": "old-app-password",
        "DB_ROOT_PASSWORD": "unknown-root-password",
        "MTO_JWT_SECRET": "old-jwt-secret",
    }


class _Connection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Process:
    def poll(self):
        return None


def test_parse_service_command_accepts_only_reviewed_shape():
    executable, defaults_file = recovery._parse_service_command(
        '"C:\\Program Files\\MariaDB 10.6\\bin\\mysqld.exe" '
        '"--defaults-file=C:\\Program Files\\MariaDB 10.6\\data\\my.ini" '
        '"MariaDB"'
    )

    assert recovery._path_key(executable) == recovery._path_key(
        recovery.EXPECTED_EXECUTABLE
    )
    assert recovery._path_key(defaults_file) == recovery._path_key(
        recovery.EXPECTED_DEFAULTS_FILE
    )

    with pytest.raises(recovery.RootRecoveryError):
        recovery._parse_service_command(
            '"C:\\Program Files\\MariaDB 10.6\\bin\\mysqld.exe" '
            '"--defaults-file=C:\\Program Files\\MariaDB 10.6\\data\\my.ini" '
            '"MariaDB" --skip-grant-tables'
        )


def test_init_sql_is_single_account_and_rejects_unexpected_secret():
    statement = recovery._render_init_sql(_rotation())

    assert statement == (
        "ALTER USER IF EXISTS 'root'@'localhost' "
        f"IDENTIFIED BY '{_rotation().root_password}';\n"
    )
    assert statement.count(";") == 1
    assert "skip-grant" not in statement.casefold()

    invalid = recovery.RotationSecrets(
        rotation_id="1" * 32,
        app_password="a" * 64,
        root_password="not-sql-safe",
        jwt_secret="c" * 128,
    )
    with pytest.raises(recovery.RootRecoveryError):
        recovery._render_init_sql(invalid)


def test_root_authentication_only_treats_access_denied_as_bad_password(monkeypatch):
    attempts = []

    def reject(_settings, *, user, password, database):
        attempts.append((user, password, database))
        raise pymysql.err.OperationalError(1045, "Access denied")

    monkeypatch.setattr(recovery, "_connect", reject)

    assert recovery._root_authenticates(_settings(), ["wrong", "wrong"]) is False
    assert attempts == [("root", "wrong", "mysql")]


def test_root_authentication_fails_closed_on_operational_error(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise pymysql.err.OperationalError(2003, "Connection refused")

    monkeypatch.setattr(recovery, "_connect", unavailable)

    with pytest.raises(
        recovery.RootRecoveryError,
        match="could not be tested safely",
    ):
        recovery._root_authenticates(_settings(), ["candidate"])


def test_preflight_is_read_only(monkeypatch, tmp_path):
    events = []
    vault_path = tmp_path / "secrets.json"
    monkeypatch.setattr(recovery, "_require_windows", lambda: None)
    monkeypatch.setattr(recovery, "_validated_service", _service)
    monkeypatch.setattr(recovery, "_service_state", lambda: "RUNNING")
    monkeypatch.setattr(
        recovery,
        "_load_context",
        lambda *_args: ({}, {}, _settings(), _current(), None),
    )
    monkeypatch.setattr(
        recovery, "_require_backup_ready", lambda: events.append("backup")
    )
    monkeypatch.setattr(
        recovery,
        "_validate_app_login",
        lambda *_args: events.append("app-login"),
    )
    monkeypatch.setattr(recovery, "_root_authenticates", lambda *_args: False)

    def forbidden(*_args, **_kwargs):
        pytest.fail("preflight attempted a mutation")

    monkeypatch.setattr(recovery, "_atomic_write_vault", forbidden)
    monkeypatch.setattr(recovery, "_control_service", forbidden)
    monkeypatch.setattr(recovery, "_prepare_rotation", forbidden)

    result = recovery.preflight(
        project_root=tmp_path,
        vault_path=vault_path,
        require_administrator=False,
    )

    assert result.recovery_required is True
    assert result.pending_rotation is False
    assert events == ["backup", "app-login"]


def test_temporary_server_uses_defaults_first_and_never_skips_grants(monkeypatch):
    captured = {}
    marker = object()

    def popen(command, **options):
        captured["command"] = command
        captured["options"] = options
        return marker

    monkeypatch.setattr(recovery.subprocess, "Popen", popen)

    result = recovery._start_recovery_server(
        _service(), _settings(), Path(r"C:\ProgramData\MTO\root-init.sql")
    )

    assert result is marker
    command = captured["command"]
    assert command[0] == str(recovery.EXPECTED_EXECUTABLE)
    assert command[1] == f"--defaults-file={recovery.EXPECTED_DEFAULTS_FILE}"
    assert any(item.startswith("--init-file=") for item in command)
    assert all("skip-grant" not in item.casefold() for item in command)
    assert captured["options"]["stdin"] is recovery.subprocess.DEVNULL


def test_recovery_stages_before_service_stop_and_restores_normal_service(
    monkeypatch, tmp_path
):
    events = []
    rotation = _rotation()
    staged_vault = {"pending": "protected"}
    process = _Process()
    connection = _Connection()

    monkeypatch.setattr(recovery, "_require_windows", lambda: None)
    monkeypatch.setattr(recovery, "_api_is_listening", lambda: False)
    monkeypatch.setattr(recovery, "_validated_service", _service)
    monkeypatch.setattr(recovery, "_service_state", lambda: "RUNNING")
    monkeypatch.setattr(
        recovery,
        "_load_context",
        lambda *_args: ({}, {}, _settings(), _current(), None),
    )
    monkeypatch.setattr(
        recovery, "_require_backup_ready", lambda: events.append("backup")
    )
    monkeypatch.setattr(
        recovery,
        "_validate_app_login",
        lambda *_args: events.append("app-login"),
    )
    monkeypatch.setattr(recovery, "_root_authenticates", lambda *_args: False)
    monkeypatch.setattr(
        recovery,
        "_prepare_rotation",
        lambda _vault: (staged_vault, rotation, False),
    )
    monkeypatch.setattr(
        recovery,
        "_atomic_write_vault",
        lambda data, path: events.append(("stage", data, path)),
    )
    monkeypatch.setattr(
        recovery,
        "_write_init_file",
        lambda *_args: events.append("write-init"),
    )
    monkeypatch.setattr(
        recovery, "_control_service", lambda action: events.append(action)
    )
    monkeypatch.setattr(recovery, "_port_is_listening", lambda _port: False)
    monkeypatch.setattr(
        recovery,
        "_start_recovery_server",
        lambda *_args: events.append("start-temporary") or process,
    )
    monkeypatch.setattr(
        recovery,
        "_wait_for_recovered_root",
        lambda *_args: events.append("validate-recovered-root") or connection,
    )
    monkeypatch.setattr(
        recovery,
        "_remove_init_file",
        lambda _path: events.append("remove-init") or True,
    )
    monkeypatch.setattr(recovery, "_account_hosts", lambda *_args: ["localhost", "%"])
    monkeypatch.setattr(
        recovery,
        "_shutdown_recovery_server",
        lambda *_args: events.append("shutdown-temporary"),
    )
    monkeypatch.setattr(
        recovery,
        "_validate_database_login",
        lambda *_args, **_kwargs: events.append("validate-normal-root"),
    )

    vault_path = tmp_path / "secrets.json"
    result = recovery.recover_root(
        project_root=tmp_path,
        vault_path=vault_path,
        require_administrator=False,
    )

    stage_event = next(item for item in events if isinstance(item, tuple))
    assert stage_event == ("stage", staged_vault, vault_path)
    assert events.index(stage_event) < events.index("stop")
    assert events.index("stop") < events.index("start-temporary")
    assert events.index("remove-init") < events.index("shutdown-temporary")
    assert events.index("shutdown-temporary") < events.index("start")
    assert events.index("start") < events.index("validate-normal-root")
    assert result.root_accounts_discovered == 2
    assert result.service_restored is True
    assert result.init_file_removed is True


def test_recovery_failure_restores_service_and_keeps_staged_rotation(
    monkeypatch, tmp_path
):
    events = []
    secret = "b" * 64
    rotation = recovery.RotationSecrets(
        rotation_id="1" * 32,
        app_password="a" * 64,
        root_password=secret,
        jwt_secret="c" * 128,
    )

    monkeypatch.setattr(recovery, "_require_windows", lambda: None)
    monkeypatch.setattr(recovery, "_api_is_listening", lambda: False)
    monkeypatch.setattr(recovery, "_validated_service", _service)
    monkeypatch.setattr(recovery, "_service_state", lambda: "RUNNING")
    monkeypatch.setattr(
        recovery,
        "_load_context",
        lambda *_args: ({}, {}, _settings(), _current(), None),
    )
    monkeypatch.setattr(recovery, "_require_backup_ready", lambda: None)
    monkeypatch.setattr(recovery, "_validate_app_login", lambda *_args: None)
    monkeypatch.setattr(recovery, "_root_authenticates", lambda *_args: False)
    monkeypatch.setattr(
        recovery,
        "_prepare_rotation",
        lambda _vault: ({"pending": secret}, rotation, False),
    )
    monkeypatch.setattr(
        recovery,
        "_atomic_write_vault",
        lambda *_args: events.append("stage"),
    )
    monkeypatch.setattr(recovery, "_write_init_file", lambda *_args: None)
    monkeypatch.setattr(
        recovery, "_control_service", lambda action: events.append(action)
    )
    monkeypatch.setattr(recovery, "_port_is_listening", lambda _port: False)

    def fail_start(*_args):
        raise recovery.RootRecoveryError("temporary startup failed")

    monkeypatch.setattr(recovery, "_start_recovery_server", fail_start)
    monkeypatch.setattr(
        recovery,
        "_restore_normal_service",
        lambda: events.append("restore-normal") or True,
    )
    monkeypatch.setattr(recovery, "_remove_init_file", lambda _path: True)

    with pytest.raises(recovery.RootRecoveryError) as caught:
        recovery.recover_root(
            project_root=tmp_path,
            vault_path=tmp_path / "secrets.json",
            require_administrator=False,
        )

    assert events == ["stage", "stop", "restore-normal"]
    assert "normal MariaDB service was restored" in str(caught.value)
    assert secret not in str(caught.value)


def test_privacy_safe_report_contains_no_secret_values(tmp_path):
    result = recovery.RecoveryResult(
        rotation_id="1" * 32,
        completed_at_utc="2026-09-03T00:00:00+00:00",
        root_accounts_discovered=2,
        service_restored=True,
        init_file_removed=True,
        resumed=False,
    )
    output = tmp_path / "recovery.json"

    recovery._write_report(output, result)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["secret_values_recorded"] is False
    assert set(payload) == {
        "format_version",
        "operation",
        "secret_values_recorded",
        "rotation_id",
        "completed_at_utc",
        "root_accounts_discovered",
        "service_restored",
        "init_file_removed",
        "resumed",
    }


def test_main_does_not_repeat_recovery_when_only_report_write_fails(
    monkeypatch, capsys, tmp_path
):
    result = recovery.RecoveryResult(
        rotation_id="1" * 32,
        completed_at_utc="2026-09-03T00:00:00+00:00",
        root_accounts_discovered=2,
        service_restored=True,
        init_file_removed=True,
        resumed=False,
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: recovery.CONFIRMATION)
    monkeypatch.setattr(recovery, "recover_root", lambda: result)
    monkeypatch.setattr(
        recovery,
        "_write_report",
        lambda *_args: (_ for _ in ()).throw(OSError("private path")),
    )

    exit_code = recovery.main(["--apply", "--output", str(tmp_path / "recovery.json")])
    output = capsys.readouterr()

    assert exit_code == 3
    assert "Do not rerun root recovery" in output.out
    assert "private path" not in output.out
    assert "private path" not in output.err


def test_failure_after_root_login_prefers_clean_shutdown(monkeypatch, tmp_path):
    events = []
    process = _Process()
    connection = _Connection()

    monkeypatch.setattr(recovery, "_require_windows", lambda: None)
    monkeypatch.setattr(recovery, "_api_is_listening", lambda: False)
    monkeypatch.setattr(recovery, "_validated_service", _service)
    monkeypatch.setattr(recovery, "_service_state", lambda: "RUNNING")
    monkeypatch.setattr(
        recovery,
        "_load_context",
        lambda *_args: ({}, {}, _settings(), _current(), None),
    )
    monkeypatch.setattr(recovery, "_require_backup_ready", lambda: None)
    monkeypatch.setattr(recovery, "_validate_app_login", lambda *_args: None)
    monkeypatch.setattr(recovery, "_root_authenticates", lambda *_args: False)
    monkeypatch.setattr(
        recovery,
        "_prepare_rotation",
        lambda _vault: ({"pending": "protected"}, _rotation(), False),
    )
    monkeypatch.setattr(recovery, "_atomic_write_vault", lambda *_args: None)
    monkeypatch.setattr(recovery, "_write_init_file", lambda *_args: None)
    monkeypatch.setattr(
        recovery, "_control_service", lambda action: events.append(action)
    )
    monkeypatch.setattr(recovery, "_port_is_listening", lambda _port: False)
    monkeypatch.setattr(recovery, "_start_recovery_server", lambda *_args: process)
    monkeypatch.setattr(recovery, "_wait_for_recovered_root", lambda *_args: connection)

    removals = iter((False, True))
    monkeypatch.setattr(
        recovery,
        "_remove_init_file",
        lambda _path: next(removals),
    )
    monkeypatch.setattr(
        recovery,
        "_shutdown_recovery_server",
        lambda *_args: events.append("shutdown-cleanly"),
    )
    monkeypatch.setattr(
        recovery,
        "_stop_process_after_failure",
        lambda *_args: pytest.fail("clean shutdown should avoid termination"),
    )
    monkeypatch.setattr(
        recovery,
        "_restore_normal_service",
        lambda: events.append("restore-normal") or True,
    )

    with pytest.raises(recovery.RootRecoveryError) as caught:
        recovery.recover_root(
            project_root=tmp_path,
            vault_path=tmp_path / "secrets.json",
            require_administrator=False,
        )

    assert events.index("shutdown-cleanly") < events.index("restore-normal")
    assert "if recovery is no longer required" in str(caught.value)
