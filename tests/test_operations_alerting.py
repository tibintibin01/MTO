import json
from datetime import datetime, timedelta, timezone

from scripts import operations_alerting as alerting


NOW = datetime(2026, 9, 16, 2, 30, tzinfo=timezone.utc)


def _report(status, code="EXAMPLE"):
    findings = []
    if status != "PASS":
        findings.append(
            {
                "component": "example",
                "code": code,
                "detail": "Details must not be copied to alert state.",
                "severity": "MEDIUM" if status == "WARN" else "HIGH",
            }
        )
    return {"status": status, "findings": findings}


def _events(directory):
    return sorted(directory.glob("operations-alert-*.json"))


def test_warning_opens_privacy_safe_local_alert(tmp_path):
    result = alerting.process_health_report(
        _report("WARN"),
        tmp_path / "operations-health-20260916T023000Z.json",
        alert_directory=tmp_path,
        now=NOW,
    )
    state = alerting.load_alert_state(tmp_path / alerting.STATE_FILE_NAME)
    rendered = json.dumps(state)

    assert result["event_action"] == "OPENED"
    assert result["escalation"] == "SAME_BUSINESS_DAY"
    assert state["active"] is True
    assert state["status"] == "WARN"
    assert state["occurrence_count"] == 1
    assert len(_events(tmp_path)) == 1
    assert "Details must not be copied" not in rendered
    assert state["external_notifications"] == "DISABLED"


def test_duplicate_alert_is_suppressed_and_occurrence_increments(tmp_path):
    report_path = tmp_path / "operations-health-20260916T023000Z.json"
    alerting.process_health_report(
        _report("FAIL"),
        report_path,
        alert_directory=tmp_path,
        now=NOW,
    )

    result = alerting.process_health_report(
        _report("FAIL"),
        report_path,
        alert_directory=tmp_path,
        now=NOW + timedelta(hours=1),
    )
    state = alerting.load_alert_state(tmp_path / alerting.STATE_FILE_NAME)

    assert result["event_action"] == "SUPPRESSED"
    assert result["escalation"] == "IMMEDIATE"
    assert state["occurrence_count"] == 2
    assert len(_events(tmp_path)) == 1


def test_active_alert_emits_reminder_after_twenty_four_hours(tmp_path):
    report_path = tmp_path / "operations-health-20260916T023000Z.json"
    alerting.process_health_report(
        _report("FAIL"),
        report_path,
        alert_directory=tmp_path,
        now=NOW,
    )

    result = alerting.process_health_report(
        _report("FAIL"),
        report_path,
        alert_directory=tmp_path,
        now=NOW + timedelta(hours=25),
    )

    assert result["event_action"] == "REMINDER"
    assert result["occurrence_count"] == 2
    assert len(_events(tmp_path)) == 2


def test_pass_resolves_active_alert(tmp_path):
    report_path = tmp_path / "operations-health-20260916T023000Z.json"
    alerting.process_health_report(
        _report("WARN"),
        report_path,
        alert_directory=tmp_path,
        now=NOW,
    )

    result = alerting.process_health_report(
        _report("PASS"),
        report_path,
        alert_directory=tmp_path,
        now=NOW + timedelta(hours=2),
    )
    state = alerting.load_alert_state(tmp_path / alerting.STATE_FILE_NAME)
    event = json.loads(_events(tmp_path)[-1].read_text(encoding="utf-8"))

    assert result["event_action"] == "RESOLVED"
    assert state["active"] is False
    assert state["status"] == "PASS"
    assert state["fingerprint"] is None
    assert event["event_type"] == "RESOLVED"
    assert event["previous_status"] == "WARN"


def test_changed_finding_creates_new_alert_transition(tmp_path):
    report_path = tmp_path / "operations-health-20260916T023000Z.json"
    alerting.process_health_report(
        _report("FAIL", "FIRST"),
        report_path,
        alert_directory=tmp_path,
        now=NOW,
    )

    result = alerting.process_health_report(
        _report("FAIL", "SECOND"),
        report_path,
        alert_directory=tmp_path,
        now=NOW + timedelta(minutes=5),
    )

    assert result["event_action"] == "CHANGED"
    assert result["occurrence_count"] == 1
    assert len(_events(tmp_path)) == 2


def test_invalid_existing_state_fails_closed_without_exposing_contents(tmp_path):
    state = tmp_path / alerting.STATE_FILE_NAME
    state.write_text('{"password": "secret"', encoding="utf-8")

    result = alerting.capture_alerting(
        _report("WARN"),
        tmp_path / "operations-health-20260916T023000Z.json",
        400,
        alert_directory=tmp_path,
        now=NOW,
    )
    rendered = json.dumps(result)

    assert result["status"] == "FAIL"
    assert result["findings"][0]["code"] == "OPERATIONS_ALERT_EVIDENCE_FAILED"
    assert "password" not in rendered
    assert "secret" not in rendered
    assert state.read_text(encoding="utf-8") == '{"password": "secret"'


def test_alert_retention_deletes_only_expired_managed_events(tmp_path):
    expired = tmp_path / "operations-alert-20240101T000000000000Z.json"
    current = tmp_path / "operations-alert-20260915T000000000000Z.json"
    unrelated = tmp_path / "remediation-phase-6-final.json"
    for item in (expired, current, unrelated):
        item.write_text("{}", encoding="utf-8")

    removed = alerting.prune_alert_events(tmp_path, 400, now=NOW)

    assert removed == 1
    assert not expired.exists()
    assert current.exists()
    assert unrelated.exists()


def test_read_only_preflight_accepts_absent_and_valid_state(tmp_path):
    absent = alerting.capture_preflight(tmp_path)
    assert absent["status"] == "PASS"
    assert absent["state"] == "ABSENT"

    alerting.process_health_report(
        _report("PASS"),
        tmp_path / "operations-health-20260916T023000Z.json",
        alert_directory=tmp_path,
        now=NOW,
    )
    valid = alerting.capture_preflight(tmp_path)

    assert valid["status"] == "PASS"
    assert valid["state"] == "VALID"
    assert valid["active"] is False
    assert valid["external_notifications"] == "DISABLED"
