"""Privacy-safe, read-only operational health check for the MTO server.

The checker reuses the certified Phase 3, 5, and 6 controls. It never repairs
data, restarts services, creates backups, changes configuration, or performs a
database commit. Reports contain aggregate health metadata only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import phase6_production_certification as certification  # noqa: E402


FORMAT_VERSION = 1
REPORT_TYPE = "MTO_OPERATIONS_HEALTH"
DEFAULT_REPORT_DIRECTORY = PROJECT_ROOT / "logs" / "operations"
DEFAULT_API_SAMPLES = 1
DEFAULT_QUERY_SAMPLES = 1
DEFAULT_MAXIMUM_API_SECONDS = 5.0
DEFAULT_MAXIMUM_QUERY_SECONDS = 10.0
DEFAULT_MINIMUM_CERTIFICATE_DAYS = 60
DEFAULT_MINIMUM_FREE_DISK_PERCENT = 15.0
DEFAULT_MINIMUM_FREE_DISK_GB = 10.0
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
        return "WARN"
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
                    "OPERATIONS_COMPONENT_CHECK_FAILED",
                    f"{name} check failed with {type(exc).__name__}.",
                    "HIGH",
                )
            ],
        }
    status = str(result.get("status") or "").upper()
    if status not in {"PASS", "WARN", "FAIL"}:
        return {
            "status": "FAIL",
            "findings": [
                _finding(
                    name,
                    "OPERATIONS_COMPONENT_STATUS_INVALID",
                    f"{name} returned an invalid health status.",
                    "HIGH",
                )
            ],
        }
    return result


def capture_backup_schedule() -> dict:
    """Capture configured schedule metadata without exposing filesystem paths."""
    from utils.config import config

    schedule = str(config.BACKUP_SCHEDULE or "").strip().lower()
    findings: list[dict] = []
    if schedule == "disabled":
        findings.append(
            _finding(
                "backup_schedule",
                "AUTOMATIC_BACKUP_DISABLED",
                "Automatic backups are disabled; daily protection depends on manual operation.",
                "MEDIUM",
            )
        )
    elif schedule == "weekly":
        findings.append(
            _finding(
                "backup_schedule",
                "AUTOMATIC_BACKUP_NOT_DAILY",
                "The configured weekly schedule cannot by itself meet the 24-hour backup target.",
                "MEDIUM",
            )
        )
    elif schedule != "daily":
        findings.append(
            _finding(
                "backup_schedule",
                "AUTOMATIC_BACKUP_SCHEDULE_INVALID",
                "The automatic backup schedule is not a supported value.",
                "HIGH",
            )
        )

    return {
        "status": _status_for_findings(findings),
        "schedule": schedule or "invalid",
        "enabled": schedule in {"daily", "weekly"},
        "meets_daily_target": schedule == "daily",
        "scheduled_hour": int(config.BACKUP_SCHEDULE_HOUR),
        "scheduled_minute": int(config.BACKUP_SCHEDULE_MINUTE),
        "scheduled_day_of_week": (
            int(config.BACKUP_SCHEDULE_DAY_OF_WEEK) if schedule == "weekly" else None
        ),
        "findings": findings,
    }


def _existing_disk_probe(path: Path) -> tuple[Path, bool]:
    configured_exists = path.exists()
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    if not candidate.exists():
        raise OSError("No existing filesystem ancestor is available.")
    return candidate, configured_exists


def capture_disk_capacity(
    minimum_free_percent: float,
    minimum_free_gb: float,
    *,
    application_path: Path | None = None,
    backup_path: Path | None = None,
) -> dict:
    """Check application and backup storage without reporting absolute paths."""
    from utils.config import config

    targets = {
        "application": application_path or PROJECT_ROOT,
        "backup": backup_path or Path(config.BACKUP_DIR).expanduser(),
    }
    findings: list[dict] = []
    volumes: dict[str, dict] = {}
    minimum_free_bytes = minimum_free_gb * 1024**3

    for label, configured_path in targets.items():
        try:
            probe, configured_exists = _existing_disk_probe(configured_path)
            usage = shutil.disk_usage(probe)
            free_percent = (usage.free / usage.total * 100) if usage.total else 0.0
            volumes[label] = {
                "configured_path_present": configured_exists,
                "total_gb": round(usage.total / 1024**3, 2),
                "free_gb": round(usage.free / 1024**3, 2),
                "free_percent": round(free_percent, 2),
            }
            if label == "backup" and not configured_exists:
                findings.append(
                    _finding(
                        "disk",
                        "BACKUP_DIRECTORY_MISSING",
                        "The configured local backup directory is missing.",
                        "HIGH",
                    )
                )
            if usage.free < minimum_free_bytes or free_percent < minimum_free_percent:
                findings.append(
                    _finding(
                        "disk",
                        "DISK_CAPACITY_BELOW_THRESHOLD",
                        f"{label} storage is below the approved free-space threshold.",
                        "HIGH",
                    )
                )
        except Exception as exc:
            volumes[label] = {"configured_path_present": False}
            findings.append(
                _finding(
                    "disk",
                    "DISK_CAPACITY_CHECK_FAILED",
                    f"{label} storage check failed with {type(exc).__name__}.",
                    "HIGH",
                )
            )

    return {
        "status": _status_for_findings(findings),
        "minimum_free_percent": minimum_free_percent,
        "minimum_free_gb": minimum_free_gb,
        "volumes": volumes,
        "findings": findings,
    }


def _normalized_findings(components: dict[str, dict]) -> list[dict]:
    normalized: list[dict] = []
    for component_name, component in components.items():
        findings = component.get("findings") or []
        for item in findings:
            normalized.append(
                {
                    "component": str(item.get("component") or component_name),
                    "code": str(item.get("code") or "OPERATIONS_FINDING"),
                    "detail": str(item.get("detail") or "Operational review required."),
                    "severity": str(item.get("severity") or "HIGH").upper(),
                }
            )
        if str(component.get("status") or "").upper() == "FAIL" and not findings:
            normalized.append(
                _finding(
                    component_name,
                    "OPERATIONS_COMPONENT_FAILED",
                    f"{component_name} failed without a diagnostic finding.",
                    "HIGH",
                )
            )
    return normalized


def summarize_components(components: dict[str, dict]) -> tuple[str, list[dict], dict]:
    """Return the aggregate status, normalized findings, and summary counts."""
    findings = _normalized_findings(components)
    component_statuses = {
        name: str(component.get("status") or "FAIL").upper()
        for name, component in components.items()
    }
    status = _status_for_findings(findings)
    if "FAIL" in component_statuses.values():
        status = "FAIL"
    elif status == "PASS" and "WARN" in component_statuses.values():
        status = "WARN"

    component_counts = {
        name: sum(1 for value in component_statuses.values() if value == name)
        for name in ("PASS", "WARN", "FAIL")
    }
    summary = {
        "component_counts": component_counts,
        "finding_count": len(findings),
        "highest_severity": max(
            (str(item["severity"]) for item in findings),
            key=lambda value: SEVERITY_ORDER.get(value, 3),
            default=None,
        ),
    }
    return status, findings, summary


def capture_health(
    *,
    api_samples: int = DEFAULT_API_SAMPLES,
    query_samples: int = DEFAULT_QUERY_SAMPLES,
    maximum_api_seconds: float = DEFAULT_MAXIMUM_API_SECONDS,
    maximum_query_seconds: float = DEFAULT_MAXIMUM_QUERY_SECONDS,
    minimum_certificate_days: int = DEFAULT_MINIMUM_CERTIFICATE_DAYS,
    minimum_free_disk_percent: float = DEFAULT_MINIMUM_FREE_DISK_PERCENT,
    minimum_free_disk_gb: float = DEFAULT_MINIMUM_FREE_DISK_GB,
) -> dict:
    """Run every read-only operations gate and return a privacy-safe report."""
    components = {
        "source": _capture_component("source", certification.capture_source_control),
        "database": _capture_component(
            "database", certification.capture_database_assurance
        ),
        "backup_schedule": _capture_component(
            "backup_schedule", capture_backup_schedule
        ),
        "dependencies": _capture_component(
            "dependencies", certification.capture_dependency_policy
        ),
        "tls": _capture_component(
            "tls", lambda: certification.capture_tls(minimum_certificate_days)
        ),
        "api": _capture_component(
            "api",
            lambda: certification.capture_api_latency(api_samples, maximum_api_seconds),
        ),
        "critical_queries": _capture_component(
            "critical_queries",
            lambda: certification.capture_critical_query_latency(
                query_samples, maximum_query_seconds
            ),
        ),
        "runtime": _capture_component(
            "runtime", certification.capture_runtime_supervisor
        ),
        "disk": _capture_component(
            "disk",
            lambda: capture_disk_capacity(
                minimum_free_disk_percent, minimum_free_disk_gb
            ),
        ),
    }
    status, findings, summary = summarize_components(components)
    return {
        "format_version": FORMAT_VERSION,
        "report_type": REPORT_TYPE,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "thresholds": {
            "maximum_api_seconds": maximum_api_seconds,
            "maximum_query_seconds": maximum_query_seconds,
            "minimum_certificate_days": minimum_certificate_days,
            "minimum_free_disk_percent": minimum_free_disk_percent,
            "minimum_free_disk_gb": minimum_free_disk_gb,
        },
        "summary": summary,
        "components": components,
        "findings": findings,
    }


def _default_report_path(now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_REPORT_DIRECTORY / f"operations-health-{timestamp}.json"


def write_report(report: dict, destination: Path) -> Path:
    """Atomically write a report so interrupted checks never leave partial JSON."""
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
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--api-samples", type=_positive_int, default=DEFAULT_API_SAMPLES
    )
    parser.add_argument(
        "--query-samples", type=_positive_int, default=DEFAULT_QUERY_SAMPLES
    )
    parser.add_argument(
        "--maximum-api-seconds",
        type=_positive_float,
        default=DEFAULT_MAXIMUM_API_SECONDS,
    )
    parser.add_argument(
        "--maximum-query-seconds",
        type=_positive_float,
        default=DEFAULT_MAXIMUM_QUERY_SECONDS,
    )
    parser.add_argument(
        "--minimum-certificate-days",
        type=_positive_int,
        default=DEFAULT_MINIMUM_CERTIFICATE_DAYS,
    )
    parser.add_argument(
        "--minimum-free-disk-percent",
        type=_positive_float,
        default=DEFAULT_MINIMUM_FREE_DISK_PERCENT,
    )
    parser.add_argument(
        "--minimum-free-disk-gb",
        type=_positive_float,
        default=DEFAULT_MINIMUM_FREE_DISK_GB,
    )
    args = parser.parse_args(argv)

    report = capture_health(
        api_samples=args.api_samples,
        query_samples=args.query_samples,
        maximum_api_seconds=args.maximum_api_seconds,
        maximum_query_seconds=args.maximum_query_seconds,
        minimum_certificate_days=args.minimum_certificate_days,
        minimum_free_disk_percent=args.minimum_free_disk_percent,
        minimum_free_disk_gb=args.minimum_free_disk_gb,
    )
    destination = write_report(report, args.output or _default_report_path())

    print("MTO OPERATIONS HEALTH CHECK")
    for name, component in report["components"].items():
        print(f"- {name}: {component['status']}")
    print(f"- Overall status: {report['status']}")
    print(f"- Findings: {report['summary']['finding_count']}")
    print(f"- Privacy-safe report: {destination}")
    for item in report["findings"]:
        print(f"  - [{item['severity']}] {item['component']}/{item['code']}")

    if report["status"] == "FAIL":
        return 2
    if report["status"] == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
