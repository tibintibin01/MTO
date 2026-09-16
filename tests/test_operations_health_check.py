import json
from collections import namedtuple

import pytest

from scripts import operations_health_check as health


def _pass_component(**extra):
    return {"status": "PASS", "findings": [], **extra}


def _patch_all_pass(monkeypatch):
    monkeypatch.setattr(
        health.certification, "capture_source_control", lambda: _pass_component()
    )
    monkeypatch.setattr(
        health.certification, "capture_database_assurance", lambda: _pass_component()
    )
    monkeypatch.setattr(
        health.certification, "capture_dependency_policy", lambda: _pass_component()
    )
    monkeypatch.setattr(
        health.certification,
        "capture_tls",
        lambda _minimum_days: _pass_component(certificate_days_remaining=365),
    )
    monkeypatch.setattr(
        health.certification,
        "capture_api_latency",
        lambda _samples, _maximum: _pass_component(),
    )
    monkeypatch.setattr(
        health.certification,
        "capture_critical_query_latency",
        lambda _samples, _maximum: _pass_component(),
    )
    monkeypatch.setattr(
        health.certification, "capture_runtime_supervisor", lambda: _pass_component()
    )
    monkeypatch.setattr(
        health,
        "capture_backup_schedule",
        lambda: _pass_component(schedule="daily", meets_daily_target=True),
    )
    monkeypatch.setattr(
        health,
        "capture_disk_capacity",
        lambda _percent, _gb: _pass_component(),
    )


def test_health_report_passes_when_every_component_passes(monkeypatch):
    _patch_all_pass(monkeypatch)

    report = health.capture_health()

    assert report["status"] == "PASS"
    assert report["report_type"] == "MTO_OPERATIONS_HEALTH"
    assert report["summary"] == {
        "component_counts": {"PASS": 9, "WARN": 0, "FAIL": 0},
        "finding_count": 0,
        "highest_severity": None,
    }


def test_disabled_backup_schedule_is_warning(monkeypatch):
    from utils.config import config

    monkeypatch.setattr(config, "BACKUP_SCHEDULE", "disabled")

    result = health.capture_backup_schedule()

    assert result["status"] == "WARN"
    assert result["enabled"] is False
    assert result["findings"][0]["code"] == "AUTOMATIC_BACKUP_DISABLED"


def test_daily_backup_schedule_meets_target(monkeypatch):
    from utils.config import config

    monkeypatch.setattr(config, "BACKUP_SCHEDULE", "daily")
    monkeypatch.setattr(config, "BACKUP_SCHEDULE_HOUR", 16)
    monkeypatch.setattr(config, "BACKUP_SCHEDULE_MINUTE", 30)

    result = health.capture_backup_schedule()

    assert result["status"] == "PASS"
    assert result["meets_daily_target"] is True
    assert result["scheduled_hour"] == 16
    assert result["scheduled_minute"] == 30


def test_component_exception_fails_closed_without_exposing_message(monkeypatch):
    _patch_all_pass(monkeypatch)

    def fail_tls(_minimum_days):
        raise RuntimeError("MTO_DB_PASSWORD=secret")

    monkeypatch.setattr(health.certification, "capture_tls", fail_tls)

    report = health.capture_health()
    rendered = json.dumps(report)

    assert report["status"] == "FAIL"
    assert "OPERATIONS_COMPONENT_CHECK_FAILED" in rendered
    assert "MTO_DB_PASSWORD" not in rendered
    assert "secret" not in rendered


def test_low_disk_capacity_fails_without_exposing_paths(monkeypatch, tmp_path):
    application = tmp_path / "application"
    backup = tmp_path / "backup"
    application.mkdir()
    backup.mkdir()
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        health.shutil,
        "disk_usage",
        lambda _path: usage(100 * 1024**3, 95 * 1024**3, 5 * 1024**3),
    )

    report = health.capture_disk_capacity(
        15.0,
        10.0,
        application_path=application,
        backup_path=backup,
    )
    rendered = json.dumps(report)

    assert report["status"] == "FAIL"
    assert len(report["findings"]) == 2
    assert "DISK_CAPACITY_BELOW_THRESHOLD" in rendered
    assert str(tmp_path) not in rendered


def test_missing_backup_directory_fails_privacy_safely(monkeypatch, tmp_path):
    application = tmp_path / "application"
    application.mkdir()
    missing_backup = tmp_path / "missing" / "backup"
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        health.shutil,
        "disk_usage",
        lambda _path: usage(100 * 1024**3, 20 * 1024**3, 80 * 1024**3),
    )

    report = health.capture_disk_capacity(
        15.0,
        10.0,
        application_path=application,
        backup_path=missing_backup,
    )

    assert report["status"] == "FAIL"
    assert report["volumes"]["backup"]["configured_path_present"] is False
    assert report["findings"][0]["code"] == "BACKUP_DIRECTORY_MISSING"


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [("PASS", 0), ("WARN", 1), ("FAIL", 2)],
)
def test_main_writes_atomic_json_and_returns_operational_exit_code(
    monkeypatch, tmp_path, status, expected_exit
):
    report = {
        "status": status,
        "components": {"example": {"status": status}},
        "summary": {"finding_count": 0},
        "findings": [],
    }
    monkeypatch.setattr(health, "capture_health", lambda **_kwargs: report)
    destination = tmp_path / "operations-health.json"

    result = health.main(["--output", str(destination)])

    assert result == expected_exit
    assert json.loads(destination.read_text(encoding="utf-8")) == report
    assert not list(tmp_path.glob("*.tmp"))


def test_invalid_component_status_fails_closed():
    result = health._capture_component(
        "example", lambda: {"status": "UNKNOWN", "findings": []}
    )

    assert result["status"] == "FAIL"
    assert result["findings"][0]["code"] == "OPERATIONS_COMPONENT_STATUS_INVALID"
