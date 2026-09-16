import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import operations_health_check as health
from scripts import run_operations_health_check as runner


class _Lock:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _base_report(status="PASS"):
    return {
        "format_version": 1,
        "report_type": "MTO_OPERATIONS_HEALTH",
        "timestamp_utc": "2026-09-16T00:00:00+00:00",
        "status": status,
        "thresholds": {},
        "summary": {
            "component_counts": {"PASS": 1, "WARN": 0, "FAIL": 0},
            "finding_count": 0,
            "highest_severity": None,
        },
        "components": {"source": {"status": status, "findings": []}},
        "findings": [],
    }


def test_retention_removes_only_expired_managed_reports(tmp_path):
    expired = tmp_path / "operations-health-20240101T000000Z.json"
    current = tmp_path / "operations-health-20260915T000000Z.json"
    unrelated = tmp_path / "remediation-phase-6-final.json"
    lock_file = tmp_path / ".operations-health.lock"
    for item in (expired, current, unrelated, lock_file):
        item.write_text("{}", encoding="utf-8")

    result = runner.prune_expired_reports(
        tmp_path,
        400,
        now=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )

    assert result["status"] == "PASS"
    assert result["expired_reports_removed"] == 1
    assert not expired.exists()
    assert current.exists()
    assert unrelated.exists()
    assert lock_file.exists()


def test_retention_rejects_unapproved_age(tmp_path):
    with pytest.raises(ValueError):
        runner.prune_expired_reports(tmp_path, 29)


def test_retention_failure_is_privacy_safe_warning(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        raise OSError("C:/sensitive/location")

    monkeypatch.setattr(runner, "prune_expired_reports", fail)

    result = runner.capture_report_retention(400, report_directory=tmp_path)
    rendered = json.dumps(result)

    assert result["status"] == "WARN"
    assert result["findings"][0]["code"] == "OPERATIONS_REPORT_RETENTION_FAILED"
    assert "sensitive" not in rendered
    assert "location" not in rendered


def test_duplicate_run_is_skipped_without_running_health_check(monkeypatch):
    monkeypatch.setattr(runner, "acquire_single_instance_lock", lambda: None)
    monkeypatch.setattr(
        health,
        "capture_health",
        lambda: pytest.fail("health check must not run without the lock"),
    )

    assert runner.run_once() == 0


def test_single_instance_lock_rejects_a_second_holder(tmp_path):
    lock_path = tmp_path / "operations-health.lock"
    first = runner.acquire_single_instance_lock(lock_path)
    assert first is not None
    try:
        assert runner.acquire_single_instance_lock(lock_path) is None
    finally:
        first.close()

    after_release = runner.acquire_single_instance_lock(lock_path)
    assert after_release is not None
    after_release.close()


def test_scheduled_run_writes_retention_component(monkeypatch, tmp_path):
    lock = _Lock()
    destination = tmp_path / "operations-health-20260916T000000Z.json"
    monkeypatch.setattr(runner, "acquire_single_instance_lock", lambda: lock)
    monkeypatch.setattr(health, "capture_health", _base_report)
    monkeypatch.setattr(
        runner,
        "capture_report_retention",
        lambda *_args, **_kwargs: {
            "status": "PASS",
            "retention_days": 400,
            "expired_reports_removed": 2,
            "findings": [],
        },
    )
    monkeypatch.setattr(health, "_default_report_path", lambda _now: destination)

    result = runner.run_once(400)
    report = json.loads(destination.read_text(encoding="utf-8"))

    assert result == 0
    assert lock.closed is True
    assert report["status"] == "PASS"
    assert report["components"]["report_retention"]["expired_reports_removed"] == 2
    assert report["summary"]["component_counts"]["PASS"] == 2
    assert report["scheduled_runner"]["single_instance"] is True


def test_retention_warning_sets_task_warning_exit(monkeypatch, tmp_path):
    lock = _Lock()
    destination = tmp_path / "operations-health-20260916T000000Z.json"
    monkeypatch.setattr(runner, "acquire_single_instance_lock", lambda: lock)
    monkeypatch.setattr(health, "capture_health", _base_report)
    monkeypatch.setattr(
        runner,
        "capture_report_retention",
        lambda *_args, **_kwargs: {
            "status": "WARN",
            "retention_days": 400,
            "expired_reports_removed": 0,
            "findings": [
                {
                    "component": "report_retention",
                    "code": "OPERATIONS_REPORT_RETENTION_FAILED",
                    "detail": "Operator review is required.",
                    "severity": "MEDIUM",
                }
            ],
        },
    )
    monkeypatch.setattr(health, "_default_report_path", lambda _now: destination)

    assert runner.run_once(400) == 1
    assert lock.closed is True
    assert json.loads(destination.read_text(encoding="utf-8"))["status"] == "WARN"


def test_installer_is_daily_single_instance_and_does_not_start_task():
    project_root = Path(__file__).resolve().parent.parent
    content = (
        project_root / "scripts" / "install_operations_health_task.ps1"
    ).read_text(encoding="utf-8")

    assert 'TaskName = "MTO Operations Health Check"' in content
    assert "New-ScheduledTaskTrigger -Daily" in content
    assert "-MultipleInstances IgnoreNew" in content
    assert '-UserId "SYSTEM"' in content
    assert "-ExecutionTimeLimit (New-TimeSpan -Minutes 30)" in content
    assert "Test-ApprovedTaskConfiguration" in content
    assert 'triggerClass -eq "MSFT_TaskDailyTrigger"' in content
    assert 'Task.Settings.MultipleInstances -eq "IgnoreNew"' in content
    assert "Task.Settings.StartWhenAvailable" in content
    assert "-m scripts.run_operations_health_check" in content
    assert "INSTALL MTO OPERATIONS HEALTH TASK" in content
    assert "Start-ScheduledTask" not in content
