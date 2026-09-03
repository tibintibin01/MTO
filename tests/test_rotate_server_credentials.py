import json
from datetime import datetime, timezone

import pytest

from scripts import rotate_server_credentials as rotation
from scripts import rotate_jwt_secret


def _vault():
    return {
        "MTO_DB_PASSWORD": "a" * 32,
        "DB_ROOT_PASSWORD": "b" * 32,
        "MTO_JWT_SECRET": "c" * 64,
        "MTO_BACKUP_S3_SECRET_KEY": "preserve-backup-secret",
        "SECRET_KEY": "obsolete-alias",
    }


def _rotation():
    return rotation.RotationSecrets(
        rotation_id="rotation-id",
        app_password="d" * 64,
        root_password="e" * 64,
        jwt_secret="f" * 128,
    )


def test_prepare_rotation_stages_secrets_without_replacing_active_values():
    generated = iter(("d" * 64, "e" * 64, "f" * 128))
    staged, prepared, resumed = rotation._prepare_rotation(
        _vault(), token_hex=lambda _size: next(generated)
    )

    assert resumed is False
    assert staged["MTO_DB_PASSWORD"] == "a" * 32
    assert staged["DB_ROOT_PASSWORD"] == "b" * 32
    assert staged["MTO_JWT_SECRET"] == "c" * 64
    assert staged[rotation.ROTATION_STATE_KEY] == "prepared"
    assert staged[rotation.PENDING_KEYS["MTO_DB_PASSWORD"]] == prepared.app_password
    assert staged[rotation.PENDING_KEYS["DB_ROOT_PASSWORD"]] == prepared.root_password
    assert staged[rotation.PENDING_KEYS["MTO_JWT_SECRET"]] == prepared.jwt_secret


def test_prepare_rotation_resumes_the_same_pending_credentials():
    staged = _vault()
    staged.update(
        {
            rotation.ROTATION_STATE_KEY: "prepared",
            rotation.ROTATION_ID_KEY: "1" * 32,
            rotation.PENDING_KEYS["MTO_DB_PASSWORD"]: "d" * 64,
            rotation.PENDING_KEYS["DB_ROOT_PASSWORD"]: "e" * 64,
            rotation.PENDING_KEYS["MTO_JWT_SECRET"]: "f" * 128,
        }
    )

    unchanged, prepared, resumed = rotation._prepare_rotation(
        staged, token_hex=lambda _size: pytest.fail("must not generate new secrets")
    )

    assert resumed is True
    assert unchanged == staged
    assert prepared.rotation_id == "1" * 32
    assert prepared.app_password == "d" * 64
    assert prepared.root_password == "e" * 64
    assert prepared.jwt_secret == "f" * 128


def test_current_weak_credentials_are_accepted_for_rotation():
    current = rotation._current_secrets(
        {
            "MTO_DB_PASSWORD": "weak-app",
            "DB_ROOT_PASSWORD": "weak-root",
            "MTO_JWT_SECRET": "weak-jwt",
        },
        {},
    )

    assert current["MTO_DB_PASSWORD"] == "weak-app"
    assert current["DB_ROOT_PASSWORD"] == "weak-root"
    assert current["MTO_JWT_SECRET"] == "weak-jwt"


@pytest.mark.parametrize(
    "changes",
    (
        {rotation.PENDING_KEYS["MTO_DB_PASSWORD"]: "short"},
        {rotation.PENDING_KEYS["DB_ROOT_PASSWORD"]: "short"},
        {rotation.PENDING_KEYS["MTO_JWT_SECRET"]: "short"},
        {
            rotation.PENDING_KEYS["MTO_DB_PASSWORD"]: "d" * 64,
            rotation.PENDING_KEYS["DB_ROOT_PASSWORD"]: "d" * 64,
        },
    ),
)
def test_prepare_rotation_rejects_damaged_pending_credentials(changes):
    staged = _vault()
    staged.update(
        {
            rotation.ROTATION_STATE_KEY: "prepared",
            rotation.ROTATION_ID_KEY: "1" * 32,
            rotation.PENDING_KEYS["MTO_DB_PASSWORD"]: "d" * 64,
            rotation.PENDING_KEYS["DB_ROOT_PASSWORD"]: "e" * 64,
            rotation.PENDING_KEYS["MTO_JWT_SECRET"]: "f" * 128,
            **changes,
        }
    )

    with pytest.raises(rotation.RotationError):
        rotation._prepare_rotation(staged)


def test_preflight_does_not_generate_or_stage_credentials(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MTO_DB_HOST=127.0.0.1\n"
        "MTO_DB_PORT=3306\n"
        "MTO_DB_USER=mto_app\n"
        "MTO_DB_NAME=property_system\n"
        "MTO_DB_PASSWORD=weak-app\n"
        "DB_ROOT_PASSWORD=weak-root\n"
        "MTO_JWT_SECRET=weak-jwt\n",
        encoding="utf-8",
    )
    vault = {
        "MTO_DB_PASSWORD": "weak-app",
        "DB_ROOT_PASSWORD": "weak-root",
        "MTO_JWT_SECRET": "weak-jwt",
    }

    monkeypatch.setattr(rotation, "_require_api_stopped", lambda: None)
    monkeypatch.setattr(rotation, "_read_vault", lambda _path: dict(vault))
    monkeypatch.setattr(
        rotation,
        "_database_preflight",
        lambda _settings, _current, pending: (
            (2, 2) if pending is None else pytest.fail("unexpected pending rotation")
        ),
    )
    monkeypatch.setattr(
        rotation,
        "_prepare_rotation",
        lambda *_args, **_kwargs: pytest.fail("preflight must not prepare secrets"),
    )

    assert rotation.preflight(
        project_root=tmp_path,
        vault_path=tmp_path / "secrets.json",
        require_administrator=False,
        require_backup=False,
    ) == (2, 2, False)


def test_finalize_promotes_pending_values_and_removes_legacy_aliases():
    staged = _vault()
    staged.update(
        {
            rotation.ROTATION_STATE_KEY: "prepared",
            rotation.ROTATION_ID_KEY: "rotation-id",
            rotation.PENDING_KEYS["MTO_DB_PASSWORD"]: "d" * 64,
            rotation.PENDING_KEYS["DB_ROOT_PASSWORD"]: "e" * 64,
            rotation.PENDING_KEYS["MTO_JWT_SECRET"]: "f" * 128,
            "MTO_API_SECRET_KEY": "obsolete",
        }
    )
    completed = datetime(2026, 9, 3, tzinfo=timezone.utc)

    final = rotation._finalize_vault(staged, _rotation(), completed)

    assert final["MTO_DB_PASSWORD"] == "d" * 64
    assert final["DB_ROOT_PASSWORD"] == "e" * 64
    assert final["MTO_JWT_SECRET"] == "f" * 128
    assert final["MTO_BACKUP_S3_SECRET_KEY"] == "preserve-backup-secret"
    assert final["MTO_LAST_CREDENTIAL_ROTATION_ID"] == "rotation-id"
    assert final["MTO_LAST_CREDENTIAL_ROTATION_AT"] == completed.isoformat()
    for key in (
        rotation.ROTATION_STATE_KEY,
        rotation.ROTATION_ID_KEY,
        *rotation.PENDING_KEYS.values(),
        *rotation.LEGACY_SECRET_ALIASES,
    ):
        assert key not in final


def test_render_rotated_env_preserves_nonsecrets_and_removes_aliases():
    content = (
        "MTO_DB_HOST=127.0.0.1\n"
        "MTO_DB_PASSWORD=old-app\n"
        "DB_ROOT_PASSWORD=old-root\n"
        "MTO_JWT_SECRET=old-jwt\n"
        "SECRET_KEY=old-alias\n"
        "MTO_API_SECRET_KEY=old-alias\n"
        "MTO_ENABLE_CLOUD_BACKUP=true\n"
    )

    rendered = rotation._render_rotated_env(content, _rotation())

    assert "MTO_DB_HOST=127.0.0.1" in rendered
    assert "MTO_ENABLE_CLOUD_BACKUP=true" in rendered
    assert "MTO_DB_PASSWORD=" + "d" * 64 in rendered
    assert "DB_ROOT_PASSWORD=" + "e" * 64 in rendered
    assert "MTO_JWT_SECRET=" + "f" * 128 in rendered
    assert "old-app" not in rendered
    assert "old-root" not in rendered
    assert "old-jwt" not in rendered
    assert "SECRET_KEY=" not in rendered
    assert "MTO_API_SECRET_KEY=" not in rendered


def test_rotate_credentials_stages_before_database_change_and_finalizes(
    tmp_path, monkeypatch
):
    project_root = tmp_path / "MTO"
    project_root.mkdir()
    env_path = project_root / ".env"
    env_path.write_text(
        "MTO_DB_HOST=127.0.0.1\n"
        "MTO_DB_PORT=3306\n"
        "MTO_DB_USER=mto_app\n"
        "MTO_DB_NAME=property_system\n"
        "MTO_DB_PASSWORD="
        + "a" * 32
        + "\nDB_ROOT_PASSWORD="
        + "b" * 32
        + "\nMTO_JWT_SECRET="
        + "c" * 64
        + "\n",
        encoding="utf-8",
    )
    vault_path = tmp_path / "secrets.json"
    vault = _vault()
    writes = []
    database_events = []

    monkeypatch.setattr(rotation, "_require_api_stopped", lambda: None)
    monkeypatch.setattr(rotation, "_require_backup_ready", lambda: None)
    monkeypatch.setattr(rotation, "_read_vault", lambda _path: dict(vault))
    monkeypatch.setattr(
        rotation,
        "_prepare_rotation",
        lambda data: (
            {
                **data,
                rotation.ROTATION_STATE_KEY: "prepared",
                rotation.ROTATION_ID_KEY: "rotation-id",
                rotation.PENDING_KEYS["MTO_DB_PASSWORD"]: "d" * 64,
                rotation.PENDING_KEYS["DB_ROOT_PASSWORD"]: "e" * 64,
                rotation.PENDING_KEYS["MTO_JWT_SECRET"]: "f" * 128,
            },
            _rotation(),
            False,
        ),
    )
    monkeypatch.setattr(
        rotation,
        "_atomic_write_vault",
        lambda data, _path: writes.append(dict(data)),
    )
    monkeypatch.setattr(
        rotation,
        "_database_preflight",
        lambda *_args: (database_events.append("preflight") or (2, 2)),
    )

    class FakeRoot:
        def close(self):
            database_events.append("root-close")

    monkeypatch.setattr(
        rotation,
        "_connect_with_candidates",
        lambda *_args, **_kwargs: FakeRoot(),
    )
    monkeypatch.setattr(
        rotation,
        "_account_hosts",
        lambda _connection, user: (
            ["localhost", "%"] if user == "root" else ["localhost"]
        ),
    )

    def alter(_connection, user, _hosts, _password):
        assert writes and writes[0][rotation.ROTATION_STATE_KEY] == "prepared"
        database_events.append("alter-" + user)

    monkeypatch.setattr(rotation, "_alter_account_passwords", alter)
    monkeypatch.setattr(
        rotation,
        "_validate_database_login",
        lambda *_args, **kwargs: database_events.append("validate-" + kwargs["user"]),
    )
    monkeypatch.setattr(rotation, "_revoke_sessions_and_audit", lambda *_args: 7)
    monkeypatch.setattr(
        rotation,
        "_atomic_write_server_env",
        lambda path, content: path.write_text(content, encoding="utf-8"),
    )
    monkeypatch.setattr(
        rotation,
        "_utc_now",
        lambda: datetime(2026, 9, 3, tzinfo=timezone.utc),
    )

    result = rotation.rotate_credentials(
        project_root=project_root,
        vault_path=vault_path,
        require_administrator=False,
        require_backup=False,
    )

    assert result.sessions_revoked == 7
    assert result.app_accounts_rotated == 1
    assert result.root_accounts_rotated == 2
    assert len(writes) == 2
    assert writes[0][rotation.ROTATION_STATE_KEY] == "prepared"
    assert rotation.ROTATION_STATE_KEY not in writes[1]
    assert writes[1]["MTO_DB_PASSWORD"] == "d" * 64
    assert database_events.index("alter-mto_app") > database_events.index("preflight")
    assert "MTO_DB_PASSWORD=" + "d" * 64 in env_path.read_text(encoding="utf-8")


def test_rotation_report_never_contains_secret_values(tmp_path):
    report = tmp_path / "rotation.json"
    result = rotation.RotationResult(
        rotation_id="safe-id",
        completed_at_utc="2026-09-03T00:00:00+00:00",
        app_accounts_rotated=2,
        root_accounts_rotated=2,
        sessions_revoked=4,
        resumed=False,
    )

    rotation._write_report(report, result)
    payload = json.loads(report.read_text(encoding="utf-8"))

    assert payload["secret_values_recorded"] is False
    assert "password" not in report.read_text(encoding="utf-8").lower()
    assert "jwt" not in report.read_text(encoding="utf-8").lower()


def test_legacy_jwt_helper_is_disabled_and_never_displays_a_secret(capsys):
    result = rotate_jwt_secret.main()
    output = capsys.readouterr().out

    assert result == 1
    assert "disabled" in output.lower()
    assert "MTO_JWT_SECRET=" not in output
    assert "token_" not in output
    assert "rotate_server_credentials --preflight" in output


def test_report_failure_does_not_misreport_completed_rotation(
    monkeypatch, capsys, tmp_path
):
    result = rotation.RotationResult(
        rotation_id="1" * 32,
        completed_at_utc="2026-09-03T00:00:00+00:00",
        app_accounts_rotated=1,
        root_accounts_rotated=1,
        sessions_revoked=2,
        resumed=False,
    )

    monkeypatch.setattr("builtins.input", lambda _prompt: rotation.CONFIRMATION)
    monkeypatch.setattr(rotation, "rotate_credentials", lambda: result)

    def fail_report(_path, _result):
        raise OSError("sensitive filesystem details")

    monkeypatch.setattr(rotation, "_write_report", fail_report)

    exit_code = rotation.main(["--apply", "--output", str(tmp_path / "report.json")])
    captured = capsys.readouterr()

    assert exit_code == 3
    assert "rotated successfully" in captured.err
    assert "sensitive filesystem details" not in captured.err
    assert "Do not rerun --apply" in captured.out
