"""Privacy-safe local alert state and escalation for operations health reports.

This module creates local JSON evidence only. It does not send email, SMS,
webhooks, desktop messages, or data to an external service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import operations_health_check as health  # noqa: E402


FORMAT_VERSION = 1
ALERT_DIRECTORY = health.DEFAULT_REPORT_DIRECTORY / "alerts"
STATE_FILE_NAME = "current-alert.json"
DEFAULT_REMINDER_HOURS = 24
MINIMUM_RETENTION_DAYS = 30
MAXIMUM_RETENTION_DAYS = 3650
VALID_HEALTH_STATUSES = {"PASS", "WARN", "FAIL"}
EVENT_NAME_PATTERN = re.compile(
    r"^operations-alert-(?P<timestamp>\d{8}T\d{12}Z)\.json$"
)


def _finding(code: str, detail: str, severity: str = "HIGH") -> dict:
    return {
        "component": "alerting",
        "code": code,
        "detail": detail,
        "severity": severity,
    }


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat()


def _finding_references(report: dict) -> list[dict]:
    references: list[dict] = []
    for item in report.get("findings") or []:
        if not isinstance(item, dict):
            continue
        references.append(
            {
                "component": str(item.get("component") or "operations"),
                "code": str(item.get("code") or "OPERATIONS_FINDING"),
                "severity": str(item.get("severity") or "HIGH").upper(),
            }
        )
    return sorted(
        references,
        key=lambda item: (item["component"], item["code"], item["severity"]),
    )


def _fingerprint(status: str, references: list[dict]) -> str:
    payload = json.dumps(
        {"status": status, "findings": references},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Alert timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc)


def load_alert_state(path: Path) -> dict | None:
    """Load and minimally validate the local alert state without mutating it."""
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("Alert state is not a regular file.")
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("Alert state is not an object.")
    if state.get("format_version") != FORMAT_VERSION:
        raise ValueError("Alert state format is unsupported.")
    if not isinstance(state.get("active"), bool):
        raise ValueError("Alert state active flag is invalid.")
    if str(state.get("status") or "") not in VALID_HEALTH_STATUSES:
        raise ValueError("Alert state health status is invalid.")
    _parse_timestamp(state.get("last_seen_utc"))
    if state["active"]:
        if state["status"] == "PASS" or not state.get("fingerprint"):
            raise ValueError("Active alert state is incomplete.")
        _parse_timestamp(state.get("first_seen_utc"))
        _parse_timestamp(state.get("last_event_utc"))
    return state


def _write_event(alert_directory: Path, event: dict, now: datetime) -> Path:
    stamp = _utc(now).strftime("%Y%m%dT%H%M%S%fZ")
    destination = alert_directory / f"operations-alert-{stamp}.json"
    return health.write_report(event, destination)


def prune_alert_events(
    alert_directory: Path,
    retention_days: int,
    *,
    now: datetime | None = None,
) -> int:
    """Delete only expired managed alert-event files."""
    if not MINIMUM_RETENTION_DAYS <= retention_days <= MAXIMUM_RETENTION_DAYS:
        raise ValueError("Alert retention days are outside the approved range.")
    if not alert_directory.exists():
        return 0
    if alert_directory.is_symlink() or not alert_directory.is_dir():
        raise ValueError("Alert directory is not a regular directory.")

    resolved_directory = alert_directory.resolve()
    cutoff = _utc(now) - timedelta(days=retention_days)
    removed = 0
    for candidate in resolved_directory.iterdir():
        match = EVENT_NAME_PATTERN.fullmatch(candidate.name)
        if not match or candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            resolved_candidate = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved_candidate.parent != resolved_directory:
            continue
        event_time = datetime.strptime(
            match.group("timestamp"), "%Y%m%dT%H%M%S%fZ"
        ).replace(tzinfo=timezone.utc)
        if event_time < cutoff:
            candidate.unlink()
            removed += 1
    return removed


def process_health_report(
    report: dict,
    report_path: Path,
    *,
    alert_directory: Path = ALERT_DIRECTORY,
    reminder_hours: int = DEFAULT_REMINDER_HOURS,
    now: datetime | None = None,
) -> dict:
    """Update local alert state and emit a transition event when required."""
    if reminder_hours < 1:
        raise ValueError("Reminder interval must be at least one hour.")
    current_time = _utc(now)
    status = str(report.get("status") or "").upper()
    if status not in VALID_HEALTH_STATUSES:
        raise ValueError("Operations report status is invalid.")

    if alert_directory.exists() and (
        alert_directory.is_symlink() or not alert_directory.is_dir()
    ):
        raise ValueError("Alert directory is not a regular directory.")
    alert_directory.mkdir(parents=True, exist_ok=True)
    state_path = alert_directory / STATE_FILE_NAME
    previous = load_alert_state(state_path)
    references = _finding_references(report)
    fingerprint = _fingerprint(status, references) if status != "PASS" else None
    event_type = "NONE"
    occurrence_count = 0
    first_seen = None
    last_event = None

    if status == "PASS":
        if previous and previous["active"]:
            event_type = "RESOLVED"
    else:
        if (
            previous
            and previous["active"]
            and previous.get("fingerprint") == fingerprint
        ):
            occurrence_count = int(previous.get("occurrence_count") or 0) + 1
            first_seen = _parse_timestamp(previous["first_seen_utc"])
            last_event = _parse_timestamp(previous["last_event_utc"])
            if current_time - last_event >= timedelta(hours=reminder_hours):
                event_type = "REMINDER"
            else:
                event_type = "SUPPRESSED"
        else:
            occurrence_count = 1
            first_seen = current_time
            event_type = "CHANGED" if previous and previous["active"] else "OPENED"

    escalation = {
        "PASS": "NONE",
        "WARN": "SAME_BUSINESS_DAY",
        "FAIL": "IMMEDIATE",
    }[status]
    if event_type in {"OPENED", "CHANGED", "REMINDER", "RESOLVED"}:
        event = {
            "format_version": FORMAT_VERSION,
            "report_type": "MTO_OPERATIONS_ALERT_EVENT",
            "timestamp_utc": _timestamp(current_time),
            "event_type": event_type,
            "status": status,
            "previous_status": previous.get("status") if previous else None,
            "escalation": escalation,
            "report_name": report_path.name,
            "finding_references": references,
            "fingerprint": fingerprint,
            "external_notifications": "DISABLED",
        }
        _write_event(alert_directory, event, current_time)
        last_event = current_time

    state = {
        "format_version": FORMAT_VERSION,
        "report_type": "MTO_OPERATIONS_ALERT_STATE",
        "active": status != "PASS",
        "status": status,
        "escalation": escalation,
        "fingerprint": fingerprint,
        "first_seen_utc": _timestamp(first_seen) if first_seen else None,
        "last_seen_utc": _timestamp(current_time),
        "last_event_utc": _timestamp(last_event) if last_event else None,
        "occurrence_count": occurrence_count,
        "report_name": report_path.name,
        "finding_references": references,
        "external_notifications": "DISABLED",
    }
    health.write_report(state, state_path)
    return {
        "event_action": event_type,
        "alert_active": state["active"],
        "alert_status": status,
        "escalation": escalation,
        "occurrence_count": occurrence_count,
        "external_notifications": "DISABLED",
    }


def capture_alerting(
    report: dict,
    report_path: Path,
    retention_days: int,
    *,
    alert_directory: Path = ALERT_DIRECTORY,
    now: datetime | None = None,
) -> dict:
    """Capture local alert evidence and fail closed without exposing paths."""
    try:
        result = process_health_report(
            report,
            report_path,
            alert_directory=alert_directory,
            now=now,
        )
        removed = prune_alert_events(
            alert_directory,
            retention_days,
            now=now,
        )
        return {
            "status": "PASS",
            **result,
            "expired_events_removed": removed,
            "findings": [],
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "alert_active": None,
            "external_notifications": "DISABLED",
            "findings": [
                _finding(
                    "OPERATIONS_ALERT_EVIDENCE_FAILED",
                    "Local alert evidence failed with "
                    f"{type(exc).__name__}; operator review is required.",
                )
            ],
        }


def capture_preflight(alert_directory: Path = ALERT_DIRECTORY) -> dict:
    """Read-only validation for the local alert evidence directory and state."""
    try:
        if alert_directory.exists() and (
            alert_directory.is_symlink() or not alert_directory.is_dir()
        ):
            raise ValueError("Alert directory is not a regular directory.")
        state = load_alert_state(alert_directory / STATE_FILE_NAME)
        event_count = 0
        if alert_directory.exists():
            event_count = sum(
                1
                for item in alert_directory.iterdir()
                if EVENT_NAME_PATTERN.fullmatch(item.name)
                and item.is_file()
                and not item.is_symlink()
            )
        return {
            "status": "PASS",
            "state": "ABSENT" if state is None else "VALID",
            "active": state.get("active") if state else False,
            "alert_status": state.get("status") if state else None,
            "managed_event_count": event_count,
            "external_notifications": "DISABLED",
            "findings": [],
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "state": "INVALID",
            "external_notifications": "DISABLED",
            "findings": [
                _finding(
                    "OPERATIONS_ALERT_PREFLIGHT_FAILED",
                    "Alerting preflight failed with "
                    f"{type(exc).__name__}; no state was changed.",
                )
            ],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Validate local alert state without changing it.",
    )
    parser.parse_args(argv)
    report = capture_preflight()
    print("OPERATIONS WORKSTREAM 3 ALERTING PREFLIGHT")
    print(f"- Local alert evidence: {report['status']}")
    print(f"- Alert state: {report['state']}")
    print(f"- Active alert: {report.get('active', 'UNKNOWN')}")
    print(f"- Managed alert events: {report.get('managed_event_count', 0)}")
    print("- External notifications: DISABLED")
    if report["status"] == "PASS":
        print(
            "  No alert state, task, service, configuration, or database was changed."
        )
        return 0
    for item in report["findings"]:
        print(f"  - [{item['severity']}] {item['component']}/{item['code']}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
