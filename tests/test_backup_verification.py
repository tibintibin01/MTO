import hashlib
import shutil
from unittest.mock import MagicMock

from utils import log_critical_event
from utils import logger
from backend.services import verification_service


def _write_valid_dump(path):
    path.write_text(
        "-- MySQL dump\n"
        "CREATE TABLE properties (id INT);\n"
        "INSERT INTO properties VALUES (1);\n" + ("-" * 200) + "\n-- Dump completed\n",
        encoding="utf-8",
    )


def test_verify_sql_dump_rejects_checksum_mismatch(tmp_path, monkeypatch):
    dump_path = tmp_path / "backup.sql"
    _write_valid_dump(dump_path)

    called_restore = False

    def fake_restore(*args, **kwargs):
        nonlocal called_restore
        called_restore = True
        return True, "restore ok"

    monkeypatch.setattr(verification_service, "perform_restore_test", fake_restore)

    success, message = verification_service.verify_sql_dump(
        str(dump_path),
        expected_checksum="0" * 64,
    )

    assert success is False
    assert "Checksum mismatch" in message
    assert called_restore is False


def test_verify_sql_dump_accepts_matching_checksum(tmp_path, monkeypatch):
    dump_path = tmp_path / "backup.sql"
    _write_valid_dump(dump_path)
    expected = hashlib.sha256(dump_path.read_bytes()).hexdigest()

    monkeypatch.setattr(
        verification_service,
        "perform_restore_test",
        lambda *args, **kwargs: (True, "restore ok"),
    )

    success, message = verification_service.verify_sql_dump(
        str(dump_path),
        expected_checksum=expected,
    )

    assert success is True
    assert message == "restore ok"


def test_log_critical_event_does_not_raise():
    log_critical_event("BACKUP_FAILURE", "test failure", user="SYSTEM")


def test_logger_module_critical_compatibility_does_not_raise():
    logger.critical("test critical compatibility")


def test_restore_invokes_mysql_without_a_command_shell(tmp_path, monkeypatch):
    dump_path = tmp_path / "verified-backup.sql"
    dump_path.write_text("SELECT 1;", encoding="utf-8")

    required_tables = (
        "users",
        "properties",
        "payments",
        "property_billings",
        "backup_history",
    )
    cursor = MagicMock()
    cursor.fetchall.return_value = [(table,) for table in required_tables]
    cursor.fetchone.side_effect = [(1,), (0,)]
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    connection = MagicMock()
    connection.cursor.return_value = cursor_context

    monkeypatch.setattr(shutil, "which", lambda _name: "mysql")
    monkeypatch.setattr(
        verification_service,
        "_connect_for_restore_verification",
        lambda: (connection, "verify_user", "verify_password", "test account"),
    )
    run_mock = MagicMock()
    monkeypatch.setattr(verification_service.subprocess, "run", run_mock)

    success, message = verification_service.perform_restore_test(str(dump_path))

    assert success is True
    assert "restore test passed" in message.lower()
    run_mock.assert_called_once()
    assert run_mock.call_args.kwargs.get("shell", False) is False


def test_logger_positional_args_compatibility_does_not_raise():
    logger.warning("backup warning: %s", "locked")
    logger.error("backup error: %s", "locked")
    logger.critical("backup critical: %s", "locked")
