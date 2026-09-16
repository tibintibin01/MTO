"""Scheduled, single-instance runner for the read-only operations health check.

The runner writes one privacy-safe JSON report and removes only expired reports
whose names match the managed operations-health timestamp format. It does not
repair data, restart services, create backups, or modify configuration.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import operations_health_check as health  # noqa: E402


DEFAULT_RETENTION_DAYS = 400
MINIMUM_RETENTION_DAYS = 30
MAXIMUM_RETENTION_DAYS = 3650
LOCK_PATH = health.DEFAULT_REPORT_DIRECTORY / ".operations-health.lock"
REPORT_NAME_PATTERN = re.compile(
    r"^operations-health-(?P<timestamp>\d{8}T\d{6}Z)\.json$"
)


def _finding(code: str, detail: str, severity: str = "MEDIUM") -> dict:
    return {
        "component": "report_retention",
        "code": code,
        "detail": detail,
        "severity": severity,
    }


def acquire_single_instance_lock(path: Path = LOCK_PATH):
    """Acquire a non-blocking one-byte lock and return its open handle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)

    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def prune_expired_reports(
    report_directory: Path,
    retention_days: int,
    *,
    now: datetime | None = None,
) -> dict:
    """Delete only expired, regular managed reports from the report directory."""
    if not MINIMUM_RETENTION_DAYS <= retention_days <= MAXIMUM_RETENTION_DAYS:
        raise ValueError("Retention days are outside the approved range.")

    resolved_directory = report_directory.resolve()
    resolved_directory.mkdir(parents=True, exist_ok=True)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    cutoff = current_time.astimezone(timezone.utc) - timedelta(days=retention_days)
    removed_count = 0

    for candidate in resolved_directory.iterdir():
        match = REPORT_NAME_PATTERN.fullmatch(candidate.name)
        if not match or candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            resolved_candidate = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved_candidate.parent != resolved_directory:
            continue
        report_time = datetime.strptime(
            match.group("timestamp"), "%Y%m%dT%H%M%SZ"
        ).replace(tzinfo=timezone.utc)
        if report_time < cutoff:
            candidate.unlink()
            removed_count += 1

    return {
        "status": "PASS",
        "retention_days": retention_days,
        "expired_reports_removed": removed_count,
        "findings": [],
    }


def capture_report_retention(
    retention_days: int,
    *,
    report_directory: Path = health.DEFAULT_REPORT_DIRECTORY,
    now: datetime | None = None,
) -> dict:
    """Apply managed retention and convert errors to a privacy-safe warning."""
    try:
        return prune_expired_reports(report_directory, retention_days, now=now)
    except Exception as exc:
        return {
            "status": "WARN",
            "retention_days": retention_days,
            "expired_reports_removed": 0,
            "findings": [
                _finding(
                    "OPERATIONS_REPORT_RETENTION_FAILED",
                    "Managed report retention failed with "
                    f"{type(exc).__name__}; operator review is required.",
                )
            ],
        }


def run_once(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Run one scheduled check under a process lock and return its task result."""
    instance_lock = acquire_single_instance_lock()
    if instance_lock is None:
        print("MTO operations health check already running; duplicate run skipped.")
        return 0

    try:
        current_time = datetime.now(timezone.utc)
        retention = capture_report_retention(retention_days, now=current_time)
        report = health.capture_health()
        report["components"]["report_retention"] = retention
        status, findings, summary = health.summarize_components(report["components"])
        report["status"] = status
        report["findings"] = findings
        report["summary"] = summary
        report["scheduled_runner"] = {
            "single_instance": True,
            "retention_days": retention_days,
        }
        destination = health.write_report(
            report,
            health._default_report_path(current_time),
        )

        print("MTO SCHEDULED OPERATIONS HEALTH CHECK")
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
    finally:
        instance_lock.close()


def _retention_days(value: str) -> int:
    parsed = int(value)
    if not MINIMUM_RETENTION_DAYS <= parsed <= MAXIMUM_RETENTION_DAYS:
        raise argparse.ArgumentTypeError(
            f"value must be between {MINIMUM_RETENTION_DAYS} "
            f"and {MAXIMUM_RETENTION_DAYS}"
        )
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retention-days",
        type=_retention_days,
        default=DEFAULT_RETENTION_DAYS,
    )
    args = parser.parse_args(argv)
    try:
        return run_once(args.retention_days)
    except Exception as exc:
        print(
            "MTO scheduled operations health check failed safely with "
            f"{type(exc).__name__}."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
