"""Read-only certification gate for the original remediation Phase 4.

This command inspects source, database assurance, the persistent job queue,
authenticated API readiness, and the managed supervisor.  It never submits a
job, runs a migration, starts or stops a service, or commits a database change.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import func, inspect, or_

from backend.models import Job
from backend.services import job_service
from scripts import phase6_production_certification as certification
from scripts.capture_remediation_baseline import _begin_read_only_transaction


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = PROJECT_ROOT / "logs" / "remediation-phase-4-reliability.json"
FORMAT_VERSION = 1
REPORT_TYPE = "MTO_ORIGINAL_PHASE_4_RELIABILITY"
VALID_JOB_STATUSES = frozenset({"PENDING", "RUNNING", "COMPLETED", "FAILED"})
REQUIRED_JOB_COLUMNS = frozenset(
    {
        "id",
        "job_type",
        "status",
        "submitted_by",
        "payload",
        "result",
        "error",
        "progress",
        "progress_message",
        "created_at",
        "started_at",
        "completed_at",
    }
)
REQUIRED_JOB_INDEXES = frozenset(
    {"ix_jobs_status_type_created", "ix_jobs_status_started"}
)
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
                    "PHASE4_COMPONENT_CHECK_FAILED",
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
                    "PHASE4_COMPONENT_STATUS_INVALID",
                    f"{name} returned an invalid reliability status.",
                    "HIGH",
                )
            ],
        }
    return result


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _counts(rows) -> dict[str, int]:
    return {
        str(name): int(count)
        for name, count in rows
        if name is not None
    }


def capture_job_queue(
    *,
    session_factory=None,
    now: datetime | None = None,
    stale_minutes: int = job_service.STALE_THRESHOLD_MINUTES,
    recent_failure_hours: int = 24,
) -> dict:
    """Inspect job schema and state without exposing payloads or row identity."""
    if stale_minutes < 1 or recent_failure_hours < 1:
        raise ValueError("Reliability time windows must be positive.")

    if session_factory is None:
        from backend.database import SessionLocal

        session_factory = SessionLocal

    findings: list[dict] = []
    captured_at = _naive_utc(now or datetime.now(timezone.utc))
    stale_cutoff = captured_at - timedelta(minutes=stale_minutes)
    failure_cutoff = captured_at - timedelta(hours=recent_failure_hours)
    session = session_factory()
    try:
        _begin_read_only_transaction(session)
        inspector = inspect(session.get_bind())
        if not inspector.has_table("jobs"):
            return {
                "status": "FAIL",
                "schema": {"table_present": False},
                "findings": [
                    _finding(
                        "job_queue",
                        "JOB_TABLE_MISSING",
                        "The persistent jobs table is missing.",
                        "CRITICAL",
                    )
                ],
            }

        columns = {str(item["name"]) for item in inspector.get_columns("jobs")}
        indexes = {str(item["name"]) for item in inspector.get_indexes("jobs")}
        missing_columns = sorted(REQUIRED_JOB_COLUMNS - columns)
        missing_indexes = sorted(REQUIRED_JOB_INDEXES - indexes)
        if missing_columns:
            findings.append(
                _finding(
                    "job_queue",
                    "JOB_COLUMNS_MISSING",
                    "The persistent job schema is missing required columns.",
                    "CRITICAL",
                )
            )
        if missing_indexes:
            findings.append(
                _finding(
                    "job_queue",
                    "JOB_INDEXES_MISSING",
                    "The persistent job queue is missing required indexes.",
                    "HIGH",
                )
            )

        status_counts = _counts(
            session.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
        )
        type_counts = _counts(
            session.query(Job.job_type, func.count(Job.id))
            .group_by(Job.job_type)
            .all()
        )
        invalid_status_count = int(
            session.query(func.count(Job.id))
            .filter(~Job.status.in_(tuple(VALID_JOB_STATUSES)))
            .scalar()
            or 0
        )
        invalid_type_count = int(
            session.query(func.count(Job.id))
            .filter(~Job.job_type.in_(tuple(job_service.ALL_JOB_TYPES)))
            .scalar()
            or 0
        )
        stale_running_count = int(
            session.query(func.count(Job.id))
            .filter(
                Job.status == "RUNNING",
                or_(Job.started_at.is_(None), Job.started_at < stale_cutoff),
            )
            .scalar()
            or 0
        )
        stale_pending_count = int(
            session.query(func.count(Job.id))
            .filter(Job.status == "PENDING", Job.created_at < stale_cutoff)
            .scalar()
            or 0
        )
        invalid_progress_count = int(
            session.query(func.count(Job.id))
            .filter(or_(Job.progress < 0, Job.progress > 100))
            .scalar()
            or 0
        )
        inconsistent_completed_count = int(
            session.query(func.count(Job.id))
            .filter(
                Job.status == "COMPLETED",
                or_(
                    Job.completed_at.is_(None),
                    Job.progress != 100,
                    Job.result.is_(None),
                ),
            )
            .scalar()
            or 0
        )
        inconsistent_failed_count = int(
            session.query(func.count(Job.id))
            .filter(
                Job.status == "FAILED",
                or_(Job.completed_at.is_(None), Job.error.is_(None)),
            )
            .scalar()
            or 0
        )
        inconsistent_nonterminal_count = int(
            session.query(func.count(Job.id))
            .filter(
                Job.status.in_(("PENDING", "RUNNING")),
                Job.completed_at.is_not(None),
            )
            .scalar()
            or 0
        )
        recent_failure_counts = _counts(
            session.query(Job.job_type, func.count(Job.id))
            .filter(Job.status == "FAILED", Job.completed_at >= failure_cutoff)
            .group_by(Job.job_type)
            .all()
        )
        session.rollback()

        if invalid_status_count:
            findings.append(
                _finding(
                    "job_queue",
                    "JOB_STATUS_INVALID",
                    "One or more jobs use an unsupported status.",
                    "HIGH",
                )
            )
        if invalid_type_count:
            findings.append(
                _finding(
                    "job_queue",
                    "JOB_TYPE_INVALID",
                    "One or more jobs use an unsupported type.",
                    "HIGH",
                )
            )
        if stale_running_count:
            findings.append(
                _finding(
                    "job_queue",
                    "STALE_RUNNING_JOBS",
                    "One or more running jobs exceeded the approved stale threshold.",
                    "HIGH",
                )
            )
        if stale_pending_count:
            findings.append(
                _finding(
                    "job_queue",
                    "STALE_PENDING_JOBS",
                    "One or more pending jobs remained unclaimed beyond the approved threshold.",
                    "HIGH",
                )
            )
        inconsistent_terminal_count = (
            inconsistent_completed_count
            + inconsistent_failed_count
            + inconsistent_nonterminal_count
            + invalid_progress_count
        )
        if inconsistent_terminal_count:
            findings.append(
                _finding(
                    "job_queue",
                    "JOB_STATE_INCONSISTENT",
                    "One or more jobs have inconsistent progress or terminal timestamps.",
                    "HIGH",
                )
            )
        if recent_failure_counts:
            findings.append(
                _finding(
                    "job_queue",
                    "RECENT_JOB_FAILURE_REVIEW_REQUIRED",
                    "Recent failed jobs require documented operational review.",
                    "MEDIUM",
                )
            )

        return {
            "status": _status_for_findings(findings),
            "schema": {
                "table_present": True,
                "missing_column_count": len(missing_columns),
                "missing_index_count": len(missing_indexes),
            },
            "thresholds": {
                "stale_minutes": stale_minutes,
                "recent_failure_hours": recent_failure_hours,
            },
            "counts": {
                "by_status": status_counts,
                "by_type": type_counts,
                "invalid_status": invalid_status_count,
                "invalid_type": invalid_type_count,
                "stale_running": stale_running_count,
                "stale_pending": stale_pending_count,
                "inconsistent_state": inconsistent_terminal_count,
                "recent_failures_by_type": recent_failure_counts,
            },
            "expected_workers": {
                "fast": job_service.FAST_POOL_SIZE,
                "slow": job_service.SLOW_POOL_SIZE,
            },
            "findings": findings,
        }
    finally:
        try:
            session.rollback()
        finally:
            session.close()


def _normalized_findings(components: dict[str, dict]) -> list[dict]:
    normalized: list[dict] = []
    for component_name, component in components.items():
        findings = component.get("findings") or []
        for item in findings:
            normalized.append(
                {
                    "component": str(item.get("component") or component_name),
                    "code": str(item.get("code") or "PHASE4_RELIABILITY_FINDING"),
                    "detail": str(
                        item.get("detail") or "Reliability review is required."
                    ),
                    "severity": str(item.get("severity") or "HIGH").upper(),
                }
            )
        if str(component.get("status") or "").upper() == "FAIL" and not findings:
            normalized.append(
                _finding(
                    component_name,
                    "PHASE4_COMPONENT_FAILED",
                    f"{component_name} failed without a diagnostic finding.",
                    "HIGH",
                )
            )
    return normalized


def summarize_components(components: dict[str, dict]) -> tuple[str, list[dict]]:
    findings = _normalized_findings(components)
    statuses = {
        str(component.get("status") or "FAIL").upper()
        for component in components.values()
    }
    status = _status_for_findings(findings)
    if "FAIL" in statuses:
        status = "FAIL"
    elif status == "PASS" and "REVIEW" in statuses:
        status = "REVIEW"
    return status, findings


def capture_reliability(
    *,
    stale_minutes: int = job_service.STALE_THRESHOLD_MINUTES,
    recent_failure_hours: int = 24,
) -> dict:
    """Run every Phase 4 read-only gate and return a privacy-safe report."""
    components = {
        "source": _capture_component("source", certification.capture_source_control),
        "database": _capture_component(
            "database", certification.capture_database_assurance
        ),
        "job_queue": _capture_component(
            "job_queue",
            lambda: capture_job_queue(
                stale_minutes=stale_minutes,
                recent_failure_hours=recent_failure_hours,
            ),
        ),
        "api": _capture_component(
            "api",
            lambda: certification.capture_api_latency(
                certification.DEFAULT_API_SAMPLES,
                certification.DEFAULT_MAX_API_SECONDS,
            ),
        ),
        "runtime": _capture_component(
            "runtime", certification.capture_runtime_supervisor
        ),
    }
    status, findings = summarize_components(components)
    return {
        "format_version": FORMAT_VERSION,
        "report_type": REPORT_TYPE,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "thresholds": {
            "stale_minutes": stale_minutes,
            "recent_failure_hours": recent_failure_hours,
            "maximum_api_seconds": certification.DEFAULT_MAX_API_SECONDS,
        },
        "components": components,
        "finding_count": len(findings),
        "findings": findings,
    }


def write_report(report: dict, destination: Path) -> Path:
    """Atomically write a report so an interruption cannot create partial JSON."""
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only original Phase 4 reliability gate."
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Require every source, database, queue, API, and runtime gate to pass.",
    )
    parser.add_argument(
        "--stale-minutes",
        type=_positive_int,
        default=job_service.STALE_THRESHOLD_MINUTES,
    )
    parser.add_argument("--recent-failure-hours", type=_positive_int, default=24)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    report = capture_reliability(
        stale_minutes=args.stale_minutes,
        recent_failure_hours=args.recent_failure_hours,
    )
    report["require_ready"] = bool(args.require_ready)
    destination = write_report(report, args.output)

    print("ORIGINAL PHASE 4 RELIABILITY PREFLIGHT")
    for name, component in report["components"].items():
        print(f"- {name}: {component['status']}")
    print(f"- Overall status: {report['status']}")
    print(f"- Privacy-safe report: {destination}")
    for item in report["findings"]:
        print(f"  - [{item['severity']}] {item['component']}/{item['code']}: {item['detail']}")

    if report["status"] == "PASS":
        print("  ORIGINAL PHASE 4 RELIABILITY PREFLIGHT PASSED")
        return 0
    if report["status"] == "REVIEW":
        print("  ORIGINAL PHASE 4 PREFLIGHT REQUIRES REVIEW")
        return 4
    print("  ORIGINAL PHASE 4 RELIABILITY PREFLIGHT BLOCKED")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
