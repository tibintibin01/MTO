"""Read-only performance and timeout gate for original remediation Phase 7.

The gate measures representative critical-screen database operations, HTTPS
readiness latency, desktop timeout policy, database-pool resilience, source
identity, and the managed API supervisor.  It never submits a job, mutates
business data, runs a migration, restarts a service, or performs load testing.

The JSON report is deliberately privacy-safe: it contains operation names,
aggregate row counts, timings, thresholds, and finding codes only.  Search
terms, taxpayer identities, receipt numbers, and credentials are never emitted.
"""

from __future__ import annotations

import argparse
import inspect as python_inspect
import json
import math
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy import text


def _resolve_project_root(
    script_file: str | os.PathLike[str] = __file__,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the checkout assessed by an in-tree or exported gate."""
    environment = os.environ if environment is None else environment
    configured_root = str(environment.get("MTO_PROJECT_ROOT") or "").strip()
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    return Path(script_file).resolve().parents[1]


PROJECT_ROOT = _resolve_project_root()
project_root_text = str(PROJECT_ROOT)
if project_root_text in sys.path:
    sys.path.remove(project_root_text)
sys.path.insert(0, project_root_text)

from scripts import phase6_production_certification as certification  # noqa: E402
from scripts.capture_remediation_baseline import (  # noqa: E402
    _begin_read_only_transaction,
)

FORMAT_VERSION = 1
REPORT_TYPE = "MTO_ORIGINAL_PHASE_7_PERFORMANCE_TIMEOUT"
DEFAULT_REPORT = PROJECT_ROOT / "logs" / "remediation-original-phase-7-assessment.json"
DEFAULT_API_SAMPLES = 5
DEFAULT_QUERY_SAMPLES = 3
DEFAULT_MAX_API_SECONDS = 2.0

# These are server-side query ceilings, not full desktop response-time targets.
# They include conservative Windows/MariaDB headroom while still detecting the
# multi-second regressions that previously made critical screens time out.
CRITICAL_QUERY_THRESHOLDS_SECONDS = {
    "property_search": 1.0,
    "recent_payments": 0.75,
    "assessment_roll": 0.75,
    "payment_ledger": 1.0,
    "delinquent_page": 2.0,
    "compliant_page": 2.5,
    "compliant_summary": 2.5,
    "operational_analytics": 3.0,
}

SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _finding(component: str, code: str, detail: str, severity: str) -> dict:
    return {
        "component": component,
        "code": code,
        "detail": detail,
        "severity": severity,
    }


def _status_for_findings(findings: list[dict]) -> str:
    highest = max(
        (
            SEVERITY_ORDER.get(str(item.get("severity") or "").upper(), 3)
            for item in findings
        ),
        default=0,
    )
    if highest >= SEVERITY_ORDER["HIGH"]:
        return "FAIL"
    if highest >= SEVERITY_ORDER["MEDIUM"]:
        return "REVIEW"
    return "PASS"


def _capture_component(name: str, operation: Callable[[], dict]) -> dict:
    try:
        result = operation()
    except Exception as exc:
        return {
            "status": "FAIL",
            "findings": [
                _finding(
                    name,
                    "PHASE7_COMPONENT_CHECK_FAILED",
                    f"{name} check failed with {type(exc).__name__}.",
                    "HIGH",
                )
            ],
        }
    status = str(result.get("status") or "").upper()
    if status not in {"PASS", "REVIEW", "FAIL"}:
        return {
            "status": "FAIL",
            "findings": [
                _finding(
                    name,
                    "PHASE7_COMPONENT_STATUS_INVALID",
                    f"{name} returned an invalid status.",
                    "HIGH",
                )
            ],
        }
    return result


def _numeric_default(callable_object: Callable[..., Any], parameter: str) -> float:
    value = python_inspect.signature(callable_object).parameters[parameter].default
    if value is python_inspect.Parameter.empty or isinstance(value, bool):
        raise ValueError(f"{parameter} has no numeric default")
    return float(value)


def _runtime_client_policy() -> dict[str, float | int]:
    from api_clients import api_helper, billing_service

    timeout_pair = api_helper._requests_timeout(37)
    if not isinstance(timeout_pair, tuple) or len(timeout_pair) != 2:
        raise ValueError("desktop timeout adapter must return connect/read pair")
    return {
        "connect_seconds": float(timeout_pair[0]),
        "ordinary_read_seconds": _numeric_default(api_helper.api_request, "timeout"),
        "download_read_seconds": _numeric_default(
            api_helper.api_download_file, "timeout"
        ),
        "soa_job_seconds": _numeric_default(
            billing_service.download_statement_pdf, "timeout_seconds"
        ),
        "connection_failure_threshold": int(api_helper.CONNECTION_FAILURE_THRESHOLD),
    }


def capture_timeout_policy(
    *, engine=None, client_policy: Mapping | None = None
) -> dict:
    """Inspect bounded client timeouts and live SQLAlchemy pool policy."""
    if engine is None:
        from backend.database import engine as runtime_engine

        engine = runtime_engine
    policy = dict(client_policy or _runtime_client_policy())
    pool = engine.pool
    pool_size = int(pool.size())
    checked_out = int(pool.checkedout())
    max_overflow = int(getattr(pool, "_max_overflow", 0))
    capacity = pool_size + max(0, max_overflow)
    pool_timeout = float(getattr(pool, "_timeout", 0))
    pool_recycle = float(getattr(pool, "_recycle", -1))
    pre_ping = bool(getattr(pool, "_pre_ping", False))

    findings: list[dict] = []
    checks = (
        (
            0 < float(policy.get("connect_seconds", 0)) <= 5,
            "CLIENT_CONNECT_TIMEOUT_UNBOUNDED",
            "Desktop connection attempts must fail within five seconds.",
        ),
        (
            0 < float(policy.get("ordinary_read_seconds", 0)) <= 120,
            "CLIENT_READ_TIMEOUT_UNBOUNDED",
            "Ordinary desktop API requests must have a bounded read timeout.",
        ),
        (
            0 < float(policy.get("download_read_seconds", 0)) <= 180,
            "CLIENT_DOWNLOAD_TIMEOUT_UNBOUNDED",
            "Desktop downloads must have a bounded read timeout.",
        ),
        (
            0 < float(policy.get("soa_job_seconds", 0)) <= 180,
            "SOA_JOB_TIMEOUT_UNBOUNDED",
            "Queued SOA polling must have a bounded completion timeout.",
        ),
        (
            2 <= int(policy.get("connection_failure_threshold", 0)) <= 5,
            "CLIENT_FAILURE_THRESHOLD_INVALID",
            "Desktop connectivity must tolerate transient failure without hiding outages.",
        ),
        (
            pool_size >= 10 and capacity >= 20,
            "DATABASE_POOL_CAPACITY_LOW",
            "Database pool capacity is below the approved municipal workload floor.",
        ),
        (
            0 < pool_timeout <= 30,
            "DATABASE_POOL_WAIT_UNBOUNDED",
            "Database pool checkout waits must be bounded to thirty seconds.",
        ),
        (
            0 < pool_recycle <= 1800,
            "DATABASE_POOL_RECYCLE_INVALID",
            "Database connections must be recycled within thirty minutes.",
        ),
        (
            pre_ping,
            "DATABASE_POOL_PRE_PING_DISABLED",
            "Database connections must be validated before reuse.",
        ),
    )
    for condition, code, detail in checks:
        if not condition:
            findings.append(_finding("timeout_policy", code, detail, "HIGH"))

    utilization = (checked_out / capacity) if capacity else 1.0
    if utilization >= 1.0:
        findings.append(
            _finding(
                "timeout_policy",
                "DATABASE_POOL_EXHAUSTED",
                "Every configured database connection is currently checked out.",
                "HIGH",
            )
        )
    elif utilization >= 0.8:
        findings.append(
            _finding(
                "timeout_policy",
                "DATABASE_POOL_PRESSURE_HIGH",
                "Database pool utilization is at or above eighty percent.",
                "MEDIUM",
            )
        )

    return {
        "status": _status_for_findings(findings),
        "desktop": {
            "connect_seconds": float(policy["connect_seconds"]),
            "ordinary_read_seconds": float(policy["ordinary_read_seconds"]),
            "download_read_seconds": float(policy["download_read_seconds"]),
            "soa_job_seconds": float(policy["soa_job_seconds"]),
            "connection_failure_threshold": int(policy["connection_failure_threshold"]),
        },
        "database_pool": {
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "capacity": capacity,
            "checked_out": checked_out,
            "utilization_percent": round(utilization * 100, 1),
            "checkout_timeout_seconds": pool_timeout,
            "recycle_seconds": pool_recycle,
            "pre_ping": pre_ping,
        },
        "findings": findings,
    }


def _result_count(result: Any) -> int:
    if isinstance(result, dict):
        if "count" in result:
            return int(result.get("count") or 0)
        if isinstance(result.get("items"), list):
            return len(result["items"])
        if isinstance(result.get("recent_payments"), list):
            return len(result["recent_payments"])
        return len(result)
    if isinstance(result, (list, tuple)):
        return len(result)
    return 0


def _percentile_nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("at least one timing is required")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def measure_operations(
    operations: Mapping[str, Callable[[], Any]],
    *,
    samples: int,
    thresholds: Mapping[str, float],
    clock: Callable[[], float] = time.perf_counter,
) -> dict:
    """Measure operations without serializing any returned business data."""
    if samples < 1:
        raise ValueError("query sample count must be positive")
    if set(operations) != set(thresholds):
        raise ValueError("every measured operation must have exactly one threshold")

    findings: list[dict] = []
    measured: dict[str, dict] = {}
    for name, operation in operations.items():
        timings: list[float] = []
        result_count = 0
        try:
            for _index in range(samples):
                started = clock()
                result = operation()
                elapsed = clock() - started
                if elapsed < 0:
                    raise RuntimeError("monotonic clock moved backwards")
                timings.append(elapsed)
                result_count = _result_count(result)
            maximum = max(timings)
            threshold = float(thresholds[name])
            status = "PASS" if maximum <= threshold else "FAIL"
            if status == "FAIL":
                findings.append(
                    _finding(
                        "critical_queries",
                        "CRITICAL_SCREEN_QUERY_LATENCY_EXCEEDED",
                        f"{name} exceeded its approved server-side latency threshold.",
                        "HIGH",
                    )
                )
            measured[name] = {
                "status": status,
                "sample_count": len(timings),
                "result_count": result_count,
                "threshold_seconds": threshold,
                "samples_seconds": [round(value, 4) for value in timings],
                "median_seconds": round(statistics.median(timings), 4),
                "p95_seconds": round(_percentile_nearest_rank(timings, 0.95), 4),
                "maximum_seconds": round(maximum, 4),
            }
        except Exception as exc:
            findings.append(
                _finding(
                    "critical_queries",
                    "CRITICAL_SCREEN_QUERY_FAILED",
                    f"{name} failed with {type(exc).__name__}.",
                    "HIGH",
                )
            )
            measured[name] = {
                "status": "FAIL",
                "sample_count": len(timings),
                "result_count": 0,
                "threshold_seconds": float(thresholds[name]),
                "samples_seconds": [round(value, 4) for value in timings],
            }

    return {
        "status": _status_for_findings(findings),
        "sample_count_per_operation": samples,
        "operations": measured,
        "findings": findings,
    }


def capture_critical_query_latency(
    *,
    samples: int = DEFAULT_QUERY_SAMPLES,
    thresholds: Mapping[str, float] | None = None,
    session_factory=None,
) -> dict:
    """Time representative critical-screen queries in one read-only snapshot."""
    from backend.services import (
        billing_service,
        payment_service,
        property_service,
    )
    from utils.config import config

    if session_factory is None:
        from backend.database import SessionLocal

        session_factory = SessionLocal
    selected_thresholds = dict(thresholds or CRITICAL_QUERY_THRESHOLDS_SECONDS)
    session = session_factory()
    coverage_findings: list[dict] = []
    try:
        _begin_read_only_transaction(session)
        sample_td = session.execute(
            text(
                "SELECT td_number FROM properties "
                "WHERE deleted_at IS NULL AND td_number IS NOT NULL "
                "AND TRIM(td_number) <> '' ORDER BY id DESC LIMIT 1"
            )
        ).scalar()
        sample_payment_property = session.execute(
            text(
                "SELECT property_id FROM payments WHERE property_id IS NOT NULL "
                "ORDER BY id DESC LIMIT 1"
            )
        ).scalar()
        if not sample_td:
            coverage_findings.append(
                _finding(
                    "critical_queries",
                    "PROPERTY_SEARCH_SAMPLE_UNAVAILABLE",
                    "No active TD number is available for representative search timing.",
                    "MEDIUM",
                )
            )
        if sample_payment_property is None:
            coverage_findings.append(
                _finding(
                    "critical_queries",
                    "PAYMENT_LEDGER_SAMPLE_UNAVAILABLE",
                    "No linked payment is available for representative ledger timing.",
                    "MEDIUM",
                )
            )

        compliance_page = (
            billing_service.get_compliant_accounts_v2
            if config.ENABLE_COMPLIANCE_V2
            else billing_service.get_compliant_accounts
        )
        compliance_summary = (
            billing_service.get_compliant_summary_by_barangay_v2
            if config.ENABLE_COMPLIANCE_V2
            else billing_service.get_compliant_summary_by_barangay
        )
        operations: dict[str, Callable[[], Any]] = {
            "property_search": lambda: property_service.search_properties(
                sample_td, limit=10, db_session=session
            ),
            "recent_payments": lambda: payment_service.get_recent_payments(
                limit=8, db_session=session
            ),
            "assessment_roll": lambda: property_service.get_assessment_roll(
                limit=100, db_session=session
            ),
            "payment_ledger": lambda: payment_service.get_payment_ledger(
                sample_payment_property, db_session=session
            ),
            "delinquent_page": lambda: billing_service.get_delinquent_accounts(
                limit=50, db_session=session
            ),
            "compliant_page": lambda: compliance_page(limit=50, db_session=session),
            "compliant_summary": lambda: compliance_summary(db_session=session),
            "operational_analytics": lambda: payment_service.get_operational_analytics(
                db_session=session
            ),
        }
        measured = measure_operations(
            operations,
            samples=samples,
            thresholds=selected_thresholds,
        )
        measured["classification_version"] = (
            "v2_per_year" if config.ENABLE_COMPLIANCE_V2 else "legacy_currency_safe"
        )
        measured["representative_samples"] = {
            "property_search_available": bool(sample_td),
            "payment_ledger_available": sample_payment_property is not None,
        }
        measured["findings"] = coverage_findings + measured["findings"]
        measured["status"] = _status_for_findings(measured["findings"])
        return measured
    finally:
        try:
            session.rollback()
        finally:
            session.close()


def _normalized_findings(components: Mapping[str, dict]) -> list[dict]:
    findings: list[dict] = []
    for component_name, component in components.items():
        component_findings = component.get("findings") or []
        for item in component_findings:
            findings.append(
                {
                    "component": str(item.get("component") or component_name),
                    "code": str(item.get("code") or "PHASE7_FINDING"),
                    "detail": str(item.get("detail") or "Phase 7 review is required."),
                    "severity": str(item.get("severity") or "HIGH").upper(),
                }
            )
        if (
            str(component.get("status") or "").upper() == "FAIL"
            and not component_findings
        ):
            findings.append(
                _finding(
                    component_name,
                    "PHASE7_COMPONENT_FAILED",
                    f"{component_name} failed without a diagnostic finding.",
                    "HIGH",
                )
            )
    return findings


def capture_phase7_assessment(
    *,
    api_samples: int = DEFAULT_API_SAMPLES,
    query_samples: int = DEFAULT_QUERY_SAMPLES,
    maximum_api_seconds: float = DEFAULT_MAX_API_SECONDS,
) -> dict:
    components = {
        "source": _capture_component("source", certification.capture_source_control),
        "timeout_policy": _capture_component("timeout_policy", capture_timeout_policy),
        "critical_queries": _capture_component(
            "critical_queries",
            lambda: capture_critical_query_latency(samples=query_samples),
        ),
        "api": _capture_component(
            "api",
            lambda: certification.capture_api_latency(api_samples, maximum_api_seconds),
        ),
        "runtime": _capture_component(
            "runtime", certification.capture_runtime_supervisor
        ),
    }
    findings = _normalized_findings(components)
    status = _status_for_findings(findings)
    statuses = {
        str(component.get("status") or "FAIL").upper()
        for component in components.values()
    }
    if "FAIL" in statuses:
        status = "FAIL"
    elif status == "PASS" and "REVIEW" in statuses:
        status = "REVIEW"
    return {
        "format_version": FORMAT_VERSION,
        "report_type": REPORT_TYPE,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY",
        "status": status,
        "thresholds": {
            "api_samples": api_samples,
            "query_samples": query_samples,
            "maximum_api_seconds": maximum_api_seconds,
            "critical_queries_seconds": dict(CRITICAL_QUERY_THRESHOLDS_SECONDS),
        },
        "components": components,
        "finding_count": len(findings),
        "findings": findings,
    }


def write_report(report: dict, destination: Path) -> Path:
    resolved = destination.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, resolved)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return resolved


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only original Phase 7 performance/timeout gate."
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Require every Phase 7 component to pass.",
    )
    parser.add_argument(
        "--api-samples", type=_positive_int, default=DEFAULT_API_SAMPLES
    )
    parser.add_argument(
        "--query-samples", type=_positive_int, default=DEFAULT_QUERY_SAMPLES
    )
    parser.add_argument(
        "--max-api-seconds",
        type=_positive_float,
        default=DEFAULT_MAX_API_SECONDS,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    report = capture_phase7_assessment(
        api_samples=args.api_samples,
        query_samples=args.query_samples,
        maximum_api_seconds=args.max_api_seconds,
    )
    report["require_ready"] = bool(args.require_ready)
    destination = write_report(report, args.output)

    print("ORIGINAL PHASE 7 PERFORMANCE AND TIMEOUT PREFLIGHT")
    print("- Mode: READ ONLY")
    for name, component in report["components"].items():
        print(f"- {name}: {component['status']}")
    print(f"- Gate status: {report['status']}")
    print(f"- Findings: {report['finding_count']}")
    print(f"- Privacy-safe report: {destination}")
    for item in report["findings"]:
        print(
            f"  - [{item['severity']}] {item['component']}/{item['code']}: "
            f"{item['detail']}"
        )

    if report["status"] == "PASS":
        print("  ORIGINAL PHASE 7 PERFORMANCE AND TIMEOUT PREFLIGHT PASSED")
        return 0
    if report["status"] == "REVIEW":
        print("  ORIGINAL PHASE 7 PREFLIGHT REQUIRES REVIEW")
        return 2 if args.require_ready else 4
    print("  ORIGINAL PHASE 7 PERFORMANCE AND TIMEOUT PREFLIGHT BLOCKED")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
