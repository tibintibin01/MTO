import json
from pathlib import Path

import pytest

from scripts import phase9_production_readiness_certification as certification


def _pass_component(**extra):
    return {"status": "PASS", "findings": [], **extra}


def _release_component(*, accepted=True):
    acceptance = {
        "status": "PASS",
        "active": accepted,
        "risk_id": (
            "MTO-ORIGINAL-PHASE-5-UNSIGNED-INTERNAL-ONLY" if accepted else None
        ),
        "effective_date": "2026-09-21" if accepted else None,
        "review_due_date": "2027-03-20" if accepted else None,
        "waived_findings": ["AUTHENTICODE_SIGNATURE_INVALID"] if accepted else [],
        "required_control_count": 8 if accepted else 0,
        "findings": [],
    }
    return _pass_component(
        distribution_scope="internal-municipal" if accepted else "signed-production",
        components={"risk_acceptance": acceptance},
    )


def _automated_components(*, accepted=True):
    return {
        "release": _release_component(accepted=accepted),
        "reliability": _pass_component(),
        "financial_reconciliation": _pass_component(),
        "performance": _pass_component(),
        "accessibility": _pass_component(),
        "operations_monitoring": _pass_component(),
    }


def _all_confirmed():
    return {name: True for name in certification.MANUAL_ACCEPTANCE_REQUIREMENTS}


def test_preflight_builds_ready_scorecard_and_risk_register(monkeypatch, tmp_path):
    monkeypatch.setattr(
        certification,
        "_capture_automated_components",
        lambda **_kwargs: _automated_components(),
    )
    report = certification.capture_certification(
        distribution=tmp_path,
        distribution_scope="internal-municipal",
        risk_acceptance=tmp_path / "risk.json",
        final=False,
        confirmations={},
    )
    assert report["status"] == "READY_FOR_MANUAL_ACCEPTANCE"
    assert report["manual_acceptance"]["status"] == "PENDING"
    assert report["scorecard"]["automated_controls_passed"] == 6
    assert report["scorecard"]["manual_controls_confirmed"] == 0
    assert report["scorecard"]["accepted_residual_risk_count"] == 1
    assert report["accepted_residual_risks"][0]["review_due_date"] == "2027-03-20"
    assert len(report["maintenance_schedule"]) == 5


def test_final_requires_every_manual_acceptance(monkeypatch, tmp_path):
    monkeypatch.setattr(
        certification,
        "_capture_automated_components",
        lambda **_kwargs: _automated_components(),
    )
    report = certification.capture_certification(
        distribution=tmp_path,
        distribution_scope="internal-municipal",
        risk_acceptance=tmp_path / "risk.json",
        final=True,
        confirmations={"desktop_workflows": True},
    )
    assert report["status"] == "FAIL"
    assert report["manual_acceptance"]["status"] == "FAIL"
    assert report["scorecard"]["manual_controls_confirmed"] == 1
    assert report["scorecard"]["blocking_finding_count"] == 3


def test_final_passes_with_active_accepted_risk(monkeypatch, tmp_path):
    monkeypatch.setattr(
        certification,
        "_capture_automated_components",
        lambda **_kwargs: _automated_components(),
    )
    report = certification.capture_certification(
        distribution=tmp_path,
        distribution_scope="internal-municipal",
        risk_acceptance=tmp_path / "risk.json",
        final=True,
        confirmations=_all_confirmed(),
    )
    assert report["status"] == "PASS_WITH_ACCEPTED_RISK"
    assert report["decision"] == "CERTIFIED_FOR_CONTROLLED_INTERNAL_MUNICIPAL_USE"
    assert report["finding_count"] == 0
    assert report["scorecard"] == {
        "automated_controls_passed": 6,
        "automated_controls_total": 6,
        "manual_controls_confirmed": 4,
        "manual_controls_total": 4,
        "accepted_residual_risk_count": 1,
        "blocking_finding_count": 0,
    }


def test_signed_final_passes_without_residual_risk(monkeypatch, tmp_path):
    monkeypatch.setattr(
        certification,
        "_capture_automated_components",
        lambda **_kwargs: _automated_components(accepted=False),
    )
    report = certification.capture_certification(
        distribution=tmp_path,
        distribution_scope="signed-production",
        risk_acceptance=None,
        final=True,
        confirmations=_all_confirmed(),
    )
    assert report["status"] == "PASS"
    assert report["accepted_residual_risks"] == []


def test_automated_failure_blocks_preflight(monkeypatch, tmp_path):
    components = _automated_components()
    components["financial_reconciliation"] = {
        "status": "FAIL",
        "findings": [
            {
                "component": "financial_reconciliation",
                "code": "FINANCIAL_TEST_FAILURE",
                "detail": "Financial test failed.",
                "severity": "CRITICAL",
            }
        ],
    }
    monkeypatch.setattr(
        certification,
        "_capture_automated_components",
        lambda **_kwargs: components,
    )
    report = certification.capture_certification(
        distribution=tmp_path,
        distribution_scope="internal-municipal",
        risk_acceptance=tmp_path / "risk.json",
        final=False,
        confirmations={},
    )
    assert report["status"] == "FAIL"
    assert report["findings"][0]["code"] == "FINANCIAL_TEST_FAILURE"


def _valid_task_payload():
    return {
        "Present": True,
        "State": "Ready",
        "Execute": str(certification.PROJECT_ROOT / "venv" / "Scripts" / "python.exe"),
        "Arguments": certification.OPERATIONS_TASK_ARGUMENTS,
        "WorkingDirectory": str(certification.PROJECT_ROOT),
        "UserId": "SYSTEM",
        "LogonType": "ServiceAccount",
        "RunLevel": "Highest",
        "TriggerClass": "MSFT_TaskDailyTrigger",
        "StartBoundary": "2026-09-23T06:30:00+08:00",
        "MultipleInstances": "IgnoreNew",
        "StartWhenAvailable": True,
        "ExecutionLimitSeconds": 1800,
        "LastRunTime": "2026-09-22T22:30:00Z",
        "LastTaskResult": 0,
    }


def test_operations_task_requires_approved_configuration_and_smoke(monkeypatch):
    monkeypatch.setattr(
        certification, "_read_operations_task_payload", _valid_task_payload
    )
    report = certification.capture_operations_task()
    assert report["status"] == "PASS"
    assert report["last_task_result"] == 0
    assert report["retention_days"] == 400


def test_operations_task_missing_blocks_certification(monkeypatch):
    monkeypatch.setattr(
        certification,
        "_read_operations_task_payload",
        lambda: {"Present": False},
    )
    report = certification.capture_operations_task()
    assert report["status"] == "FAIL"
    assert report["findings"][0]["code"] == "OPERATIONS_TASK_MISSING"


def test_operations_task_rejects_unsuccessful_smoke(monkeypatch):
    payload = _valid_task_payload()
    payload["LastTaskResult"] = 2
    monkeypatch.setattr(certification, "_read_operations_task_payload", lambda: payload)
    report = certification.capture_operations_task()
    assert report["status"] == "FAIL"
    assert any(
        item["code"] == "OPERATIONS_TASK_SMOKE_MISSING" for item in report["findings"]
    )


def test_operations_monitoring_requires_initialized_alert_state(monkeypatch):
    monkeypatch.setattr(
        certification.operations_health_check,
        "capture_health",
        lambda: _pass_component(),
    )
    monkeypatch.setattr(
        certification, "capture_operations_task", lambda: _pass_component()
    )
    monkeypatch.setattr(
        certification.operations_alerting,
        "capture_preflight",
        lambda: _pass_component(state="ABSENT", active=False),
    )
    report = certification.capture_operations_monitoring()
    assert report["status"] == "FAIL"
    assert report["components"]["alerting"]["findings"][0]["code"] == (
        "OPERATIONS_ALERT_STATE_NOT_INITIALIZED"
    )


def test_operations_monitoring_passes_with_local_alerting(monkeypatch):
    monkeypatch.setattr(
        certification.operations_health_check,
        "capture_health",
        lambda: _pass_component(),
    )
    monkeypatch.setattr(
        certification, "capture_operations_task", lambda: _pass_component()
    )
    monkeypatch.setattr(
        certification.operations_alerting,
        "capture_preflight",
        lambda: _pass_component(state="VALID", active=False),
    )
    report = certification.capture_operations_monitoring()
    assert report["status"] == "PASS"
    assert report["external_notifications"] == ("DISABLED_LOCAL_ESCALATION_ACTIVE")


def test_component_exception_is_privacy_safe():
    def fail():
        raise RuntimeError("secret database details")

    report = certification._capture_component("database", fail)
    assert report["status"] == "FAIL"
    assert report["findings"][0]["detail"] == ("database failed with RuntimeError.")


def test_report_write_is_atomic_json(tmp_path):
    destination = tmp_path / "phase9.json"
    written = certification.write_report({"status": "PASS"}, destination)
    assert written == destination.resolve()
    assert json.loads(destination.read_text(encoding="utf-8")) == {"status": "PASS"}
    assert list(tmp_path.glob("*.tmp")) == []


def test_preflight_rejects_manual_confirmation_switch(tmp_path):
    with pytest.raises(SystemExit) as exc:
        certification.main(
            [
                "--preflight",
                "--distribution",
                str(tmp_path),
                "--confirm-desktop-workflows",
            ]
        )
    assert exc.value.code == 2


def test_project_root_environment_override(tmp_path):
    resolved = certification._resolve_project_root(
        environment={"MTO_PROJECT_ROOT": str(tmp_path)}
    )
    assert resolved == tmp_path.resolve()
