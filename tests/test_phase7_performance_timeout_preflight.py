import json
from types import SimpleNamespace

import pytest

from scripts import phase7_performance_timeout_preflight as preflight


class FakePool:
    def __init__(
        self,
        *,
        size=20,
        checked_out=2,
        max_overflow=5,
        timeout=30,
        recycle=1800,
        pre_ping=True,
    ):
        self._size = size
        self._checked_out = checked_out
        self._max_overflow = max_overflow
        self._timeout = timeout
        self._recycle = recycle
        self._pre_ping = pre_ping

    def size(self):
        return self._size

    def checkedout(self):
        return self._checked_out


def _client_policy(**overrides):
    policy = {
        "connect_seconds": 4,
        "ordinary_read_seconds": 120,
        "download_read_seconds": 120,
        "soa_job_seconds": 120,
        "connection_failure_threshold": 3,
    }
    policy.update(overrides)
    return policy


def _pass_component():
    return {"status": "PASS", "findings": []}


def test_project_root_defaults_to_script_parent(tmp_path):
    script = tmp_path / "scripts" / "phase7_gate.py"

    assert preflight._resolve_project_root(script, {}) == tmp_path.resolve()


def test_project_root_supports_exported_assessment_tool(tmp_path):
    configured = tmp_path / "production-checkout"

    assert (
        preflight._resolve_project_root(
            tmp_path / "release-tools" / "phase7_gate.py",
            {"MTO_PROJECT_ROOT": str(configured)},
        )
        == configured.resolve()
    )


def test_timeout_policy_accepts_bounded_client_and_pool_settings():
    report = preflight.capture_timeout_policy(
        engine=SimpleNamespace(pool=FakePool()),
        client_policy=_client_policy(),
    )

    assert report["status"] == "PASS"
    assert report["desktop"]["connect_seconds"] == 4
    assert report["database_pool"] == {
        "pool_size": 20,
        "max_overflow": 5,
        "capacity": 25,
        "checked_out": 2,
        "utilization_percent": 8.0,
        "checkout_timeout_seconds": 30.0,
        "recycle_seconds": 1800.0,
        "pre_ping": True,
    }


def test_timeout_policy_rejects_unbounded_client_wait_and_exhausted_pool():
    report = preflight.capture_timeout_policy(
        engine=SimpleNamespace(pool=FakePool(checked_out=25)),
        client_policy=_client_policy(connect_seconds=60),
    )

    assert report["status"] == "FAIL"
    assert {item["code"] for item in report["findings"]} == {
        "CLIENT_CONNECT_TIMEOUT_UNBOUNDED",
        "DATABASE_POOL_EXHAUSTED",
    }


def test_timeout_policy_marks_high_pool_pressure_for_review():
    report = preflight.capture_timeout_policy(
        engine=SimpleNamespace(pool=FakePool(checked_out=20)),
        client_policy=_client_policy(),
    )

    assert report["status"] == "REVIEW"
    assert report["findings"][0]["code"] == "DATABASE_POOL_PRESSURE_HIGH"


def test_measured_query_report_omits_returned_taxpayer_data():
    ticks = iter([1.0, 1.1, 2.0, 2.2])
    private_result = {
        "count": 1,
        "items": [
            {
                "owner_name": "PRIVATE TAXPAYER",
                "td_number": "06-PRIVATE",
            }
        ],
    }

    report = preflight.measure_operations(
        {"property_search": lambda: private_result},
        samples=2,
        thresholds={"property_search": 0.5},
        clock=lambda: next(ticks),
    )
    rendered = json.dumps(report)

    assert report["status"] == "PASS"
    assert report["operations"]["property_search"]["result_count"] == 1
    assert report["operations"]["property_search"]["maximum_seconds"] == 0.2
    assert "PRIVATE TAXPAYER" not in rendered
    assert "06-PRIVATE" not in rendered


def test_measured_query_threshold_is_blocking():
    ticks = iter([1.0, 2.25])

    report = preflight.measure_operations(
        {"delinquent_page": lambda: {"count": 0, "items": []}},
        samples=1,
        thresholds={"delinquent_page": 1.0},
        clock=lambda: next(ticks),
    )

    assert report["status"] == "FAIL"
    assert report["findings"][0]["code"] == ("CRITICAL_SCREEN_QUERY_LATENCY_EXCEEDED")


def test_measured_query_requires_one_threshold_per_operation():
    with pytest.raises(ValueError, match="exactly one threshold"):
        preflight.measure_operations(
            {"property_search": lambda: []},
            samples=1,
            thresholds={},
        )


def test_phase7_assessment_combines_only_privacy_safe_components(monkeypatch):
    monkeypatch.setattr(
        preflight.certification, "capture_source_control", _pass_component
    )
    monkeypatch.setattr(
        preflight.certification, "capture_runtime_supervisor", _pass_component
    )
    monkeypatch.setattr(
        preflight.certification,
        "capture_api_latency",
        lambda _samples, _maximum: _pass_component(),
    )
    monkeypatch.setattr(preflight, "capture_timeout_policy", _pass_component)
    monkeypatch.setattr(
        preflight,
        "capture_critical_query_latency",
        lambda **_kwargs: _pass_component(),
    )

    report = preflight.capture_phase7_assessment()

    assert report["status"] == "PASS"
    assert report["mode"] == "READ_ONLY"
    assert report["finding_count"] == 0
    assert set(report["components"]) == {
        "source",
        "timeout_policy",
        "critical_queries",
        "api",
        "runtime",
    }


def test_phase7_assessment_preserves_blocking_finding(monkeypatch):
    monkeypatch.setattr(
        preflight.certification, "capture_source_control", _pass_component
    )
    monkeypatch.setattr(
        preflight.certification, "capture_runtime_supervisor", _pass_component
    )
    monkeypatch.setattr(
        preflight.certification,
        "capture_api_latency",
        lambda _samples, _maximum: _pass_component(),
    )
    monkeypatch.setattr(preflight, "capture_timeout_policy", _pass_component)
    monkeypatch.setattr(
        preflight,
        "capture_critical_query_latency",
        lambda **_kwargs: {
            "status": "FAIL",
            "findings": [
                preflight._finding(
                    "critical_queries",
                    "CRITICAL_SCREEN_QUERY_LATENCY_EXCEEDED",
                    "delinquent_page exceeded its threshold.",
                    "HIGH",
                )
            ],
        },
    )

    report = preflight.capture_phase7_assessment()

    assert report["status"] == "FAIL"
    assert report["finding_count"] == 1
    assert report["findings"][0]["code"] == ("CRITICAL_SCREEN_QUERY_LATENCY_EXCEEDED")


def test_report_write_is_json_and_ends_with_newline(tmp_path):
    destination = preflight.write_report(
        {"status": "PASS", "findings": []}, tmp_path / "nested" / "report.json"
    )

    payload = destination.read_text(encoding="utf-8")
    assert payload.endswith("\n")
    assert json.loads(payload)["status"] == "PASS"
