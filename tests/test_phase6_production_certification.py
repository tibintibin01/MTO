import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import phase6_production_certification as certification


def _pass_component():
    return {"status": "PASS", "findings": []}


def _patch_pass_components(monkeypatch):
    monkeypatch.setattr(certification, "capture_source_control", _pass_component)
    monkeypatch.setattr(certification, "capture_database_assurance", _pass_component)
    monkeypatch.setattr(certification, "capture_dependency_policy", _pass_component)
    monkeypatch.setattr(
        certification,
        "capture_desktop_boundary",
        lambda _distribution: {
            **_pass_component(),
            "public_ca_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        certification,
        "capture_tls",
        lambda _minimum_days: {
            **_pass_component(),
            "ca_certificate_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        certification,
        "capture_api_latency",
        lambda _samples, _maximum: _pass_component(),
    )
    monkeypatch.setattr(
        certification,
        "capture_critical_query_latency",
        lambda _samples, _maximum: _pass_component(),
    )
    monkeypatch.setattr(certification, "capture_runtime_supervisor", _pass_component)


def _capture(monkeypatch, *, final=False, confirmed=False):
    _patch_pass_components(monkeypatch)
    return certification.capture_certification(
        distribution=Path("dist"),
        final=final,
        desktop_smoke_confirmed=confirmed,
        api_samples=3,
        query_samples=2,
        maximum_api_seconds=3.0,
        maximum_query_seconds=5.0,
        minimum_certificate_days=30,
    )


def test_preflight_passes_automated_gates_and_leaves_manual_acceptance_pending(
    monkeypatch,
):
    report = _capture(monkeypatch)

    assert report["status"] == "READY_FOR_MANUAL_ACCEPTANCE"
    assert report["automated_gates_pass"] is True
    assert report["manual_acceptance"]["desktop_smoke_confirmed"] is False
    assert report["finding_count"] == 0


def test_final_certification_requires_manual_desktop_smoke(monkeypatch):
    report = _capture(monkeypatch, final=True, confirmed=False)

    assert report["status"] == "FAIL"
    assert report["automated_gates_pass"] is True
    assert report["findings"] == [
        {
            "component": "manual_acceptance",
            "code": "DESKTOP_SMOKE_NOT_CONFIRMED",
            "detail": "Final certification requires the documented desktop smoke test.",
            "severity": "HIGH",
        }
    ]


def test_final_certification_passes_after_manual_desktop_smoke(monkeypatch):
    report = _capture(monkeypatch, final=True, confirmed=True)

    assert report["status"] == "PASS"
    assert report["finding_count"] == 0


def test_certification_rejects_desktop_ca_that_does_not_match_server(monkeypatch):
    _patch_pass_components(monkeypatch)
    monkeypatch.setattr(
        certification,
        "capture_tls",
        lambda _minimum_days: {
            **_pass_component(),
            "ca_certificate_sha256": "b" * 64,
        },
    )

    report = certification.capture_certification(
        distribution=Path("dist"),
        final=False,
        desktop_smoke_confirmed=False,
        api_samples=1,
        query_samples=1,
        maximum_api_seconds=3.0,
        maximum_query_seconds=5.0,
        minimum_certificate_days=30,
    )

    assert report["status"] == "FAIL"
    assert report["components"]["desktop"]["public_ca_matches_server"] is False
    assert "DESKTOP_PUBLIC_CA_MISMATCH" in json.dumps(report)


def test_component_exception_fails_closed_without_exposing_exception_text(monkeypatch):
    _patch_pass_components(monkeypatch)

    def fail_source():
        raise RuntimeError("secret=value")

    monkeypatch.setattr(certification, "capture_source_control", fail_source)
    report = certification.capture_certification(
        distribution=Path("dist"),
        final=False,
        desktop_smoke_confirmed=False,
        api_samples=1,
        query_samples=1,
        maximum_api_seconds=3.0,
        maximum_query_seconds=5.0,
        minimum_certificate_days=30,
    )

    rendered = json.dumps(report)
    assert report["status"] == "FAIL"
    assert "COMPONENT_CHECK_FAILED" in rendered
    assert "secret=value" not in rendered


def test_dirty_source_blocks_certification(monkeypatch):
    from scripts import capture_remediation_baseline as baseline

    monkeypatch.setattr(
        baseline,
        "collect_source_snapshot",
        lambda: {
            "commit": "a" * 40,
            "branch": "master",
            "dirty": True,
            "changed_file_count": 4,
            "python": "3.11.9",
            "platform": "Windows",
            "dependency_manifest_sha256": {},
        },
    )

    report = certification.capture_source_control()

    assert report["status"] == "FAIL"
    assert report["changed_file_count"] == 4
    assert report["findings"][0]["code"] == "SOURCE_WORKTREE_DIRTY"


def test_database_assurance_blocks_missing_migration(monkeypatch):
    from scripts import phase3_financial_preflight as phase3
    from scripts import phase5_audit_observability_preflight as phase5

    monkeypatch.setattr(
        phase3,
        "capture_preflight",
        lambda: {
            "financial_invariants": {"cross_property_allocations": 0},
            "financial_invariants_pass": True,
            "schema": {"active": True},
        },
    )
    monkeypatch.setattr(
        phase5,
        "capture_preflight",
        lambda: {
            "schema": {
                "active": True,
                "timestamp_precision": 6,
                "required_timestamp_precision": 6,
            },
            "audit": {
                "status": "verified",
                "event_count": 10,
                "legacy_event_count": 8,
                "live_event_count": 2,
                "failure_count": 0,
            },
            "backup": {"restore_verification_current": True},
            "readiness_issues": [],
        },
    )
    monkeypatch.setattr(
        certification,
        "_capture_migrations",
        lambda: {
            "required_count": 20,
            "applied_required_count": 19,
            "missing": ["required_migration"],
        },
    )

    report = certification.capture_database_assurance()

    assert report["status"] == "FAIL"
    assert report["findings"][0]["code"] == "MIGRATIONS_MISSING"


def _write_certification_package(path: Path) -> bytes:
    executable = b"phase-6-desktop-binary"
    (path / "Treasury.exe").write_bytes(executable)
    certificates = path / "certificates"
    certificates.mkdir()
    (certificates / "mto-lan-ca.pem").write_text("public CA", encoding="utf-8")
    (path / "server_config.json").write_text(
        '{"server_url":"https://127.0.0.1:8001",'
        '"ca_certificate":"certificates/mto-lan-ca.pem"}',
        encoding="utf-8",
    )
    return executable


def test_desktop_certification_fingerprints_clean_executable(tmp_path):
    executable = _write_certification_package(tmp_path)

    report = certification.capture_desktop_boundary(tmp_path)

    assert report["status"] == "PASS"
    assert report["executable_present"] is True
    assert report["executable_size_bytes"] == len(executable)
    assert report["executable_sha256"] == hashlib.sha256(executable).hexdigest()
    assert report["public_ca_configured"] is True
    assert len(report["public_ca_sha256"]) == 64
    assert report["unexpected_item_count"] == 0


def test_desktop_certification_rejects_missing_executable(tmp_path):
    _write_certification_package(tmp_path)
    (tmp_path / "Treasury.exe").unlink()

    report = certification.capture_desktop_boundary(tmp_path)

    assert report["status"] == "FAIL"
    assert report["executable_present"] is False
    assert any(
        item["code"] == "DESKTOP_EXECUTABLE_MISSING" for item in report["findings"]
    )


def test_desktop_certification_rejects_runtime_artifacts_without_naming_them(
    tmp_path,
):
    _write_certification_package(tmp_path)
    private_runtime_name = "PRIVATE-TAXPAYER-local.db"
    (tmp_path / private_runtime_name).write_bytes(b"runtime data")

    report = certification.capture_desktop_boundary(tmp_path)
    rendered = json.dumps(report)

    assert report["status"] == "FAIL"
    assert report["unexpected_item_count"] == 1
    assert "DESKTOP_CERTIFICATION_PACKAGE_NOT_CLEAN" in rendered
    assert private_runtime_name not in rendered


def test_api_latency_report_omits_credentials_and_query(monkeypatch):
    from scripts import tls_health

    response = MagicMock()
    response.status = 200
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    monkeypatch.setattr(
        tls_health,
        "health_url",
        lambda: "https://user:secret@server.local:8001/readyz?token=hidden",
    )
    monkeypatch.setattr(
        tls_health, "ssl_context_for_health_url", lambda _target: object()
    )
    monkeypatch.setattr(certification, "urlopen", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(
        certification.time,
        "perf_counter",
        MagicMock(side_effect=[1.0, 1.1, 2.0, 2.2]),
    )

    report = certification.capture_api_latency(2, 0.25)
    rendered = json.dumps(report)

    assert report["status"] == "PASS"
    assert report["endpoint"] == {
        "scheme": "https",
        "host": "server.local",
        "port": 8001,
        "path": "/readyz",
    }
    assert "secret" not in rendered
    assert "token" not in rendered


def test_api_latency_rejects_plaintext_endpoint(monkeypatch):
    from scripts import tls_health

    monkeypatch.setattr(
        tls_health,
        "health_url",
        lambda: "http://127.0.0.1:8001/readyz",
    )
    report = certification.capture_api_latency(1, 3.0)

    assert report["status"] == "FAIL"
    assert report["findings"][0]["code"] == "API_READINESS_FAILED"


def test_critical_query_latency_report_contains_no_taxpayer_data(monkeypatch):
    from backend import database
    from backend.services import billing_service
    from scripts import capture_remediation_baseline as baseline
    from utils.config import config

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    monkeypatch.setattr(baseline, "_begin_read_only_transaction", lambda _session: None)
    monkeypatch.setattr(config, "ENABLE_COMPLIANCE_V2", True)
    private_row = {"owner_name": "PRIVATE TAXPAYER", "td_number": "06-0001-00001"}
    monkeypatch.setattr(
        billing_service,
        "get_delinquent_accounts",
        lambda **_kwargs: {"count": 1, "items": [private_row]},
    )
    monkeypatch.setattr(
        billing_service,
        "get_compliant_accounts_v2",
        lambda **_kwargs: {"count": 1, "items": [private_row]},
    )
    monkeypatch.setattr(
        billing_service,
        "get_compliant_summary_by_barangay_v2",
        lambda **_kwargs: [{"barangay": "PRIVATE"}],
    )

    report = certification.capture_critical_query_latency(1, 5.0)
    rendered = json.dumps(report)

    assert report["status"] == "PASS"
    assert report["classification_version"] == "v2_per_year"
    assert "PRIVATE TAXPAYER" not in rendered
    assert "06-0001-00001" not in rendered
    session.rollback.assert_called_once()


@pytest.mark.skipif(certification.os.name != "nt", reason="Windows task check")
def test_runtime_supervisor_requires_running_system_task(monkeypatch):
    payload = {
        "State": "Running",
        "UserId": "SYSTEM",
        "Execute": "C:\\mto\\venv\\Scripts\\python.exe",
        "Arguments": "-m scripts.run_api_supervisor",
        "WorkingDirectory": str(certification.PROJECT_ROOT),
        "LastTaskResult": 267009,
    }
    monkeypatch.setattr(certification.shutil, "which", lambda _name: "powershell.exe")
    monkeypatch.setattr(
        certification.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(payload), stderr=""
        ),
    )

    report = certification.capture_runtime_supervisor()

    assert report["status"] == "PASS"
    assert report["runs_as_system"] is True
    assert report["supervisor_module"] is True


def test_preflight_rejects_manual_confirmation_flag():
    with pytest.raises(SystemExit) as caught:
        certification.main(
            [
                "--preflight",
                "--distribution",
                "dist",
                "--confirm-desktop-smoke",
            ]
        )

    assert caught.value.code == 2


def test_production_launchers_use_only_managed_supervisor():
    project_root = Path(__file__).resolve().parents[1]
    start = (project_root / "start_mto.bat").read_text(encoding="utf-8").lower()
    restart = (project_root / "restart_mto.bat").read_text(encoding="utf-8").lower()

    for launcher in (start, restart):
        assert 'schtasks /run /tn "mto treasury api"' in launcher
        assert "wait_for_mto_api.ps1" in launcher
        assert "uvicorn" not in launcher
        assert "npm start" not in launcher
        assert "--host 0.0.0.0" not in launcher

    assert "stop_mto_runtime.ps1" in restart
