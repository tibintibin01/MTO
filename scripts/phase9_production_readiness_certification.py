"""Consolidated original Phase 9 production-readiness certification.

The runner composes the already approved read-only gates from original Phases
4 through 8 with operations monitoring and explicit manual acceptance.  It
does not create backups, restore data, run migrations, restart services,
change configuration, or modify production records.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping


def _resolve_project_root(
    script_file: str | os.PathLike[str] = __file__,
    environment: Mapping[str, str] | None = None,
) -> Path:
    environment = os.environ if environment is None else environment
    configured = str(environment.get("MTO_PROJECT_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(script_file).resolve().parents[1]


PROJECT_ROOT = _resolve_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import operations_alerting  # noqa: E402
from scripts import operations_health_check  # noqa: E402
from scripts import phase4_reliability_preflight  # noqa: E402
from scripts import phase5_supply_chain_preflight  # noqa: E402
from scripts import phase6_financial_reconciliation_preflight  # noqa: E402
from scripts import phase7_performance_timeout_preflight  # noqa: E402
from scripts import phase8_accessibility_preflight  # noqa: E402

FORMAT_VERSION = 1
REPORT_TYPE = "MTO_ORIGINAL_PHASE_9_PRODUCTION_READINESS"
DEFAULT_REPORT = (
    PROJECT_ROOT / "logs" / "remediation-original-phase-9-certification.json"
)
OPERATIONS_TASK_NAME = "MTO Operations Health Check"
OPERATIONS_TASK_ARGUMENTS = (
    "-m scripts.run_operations_health_check --retention-days 400"
)
OPERATIONS_RETENTION_DAYS = 400
OPERATIONS_EXECUTION_LIMIT_SECONDS = 30 * 60

MANUAL_ACCEPTANCE_REQUIREMENTS = {
    "desktop_workflows": (
        "Login, logout, reopen, property search, payment ledger, duplicate-TD "
        "isolation, and PDF/report generation were accepted on the pilot client."
    ),
    "update_delivery_and_reconnection": (
        "The immutable update, client installation, API restart, and client "
        "reconnection were accepted."
    ),
    "isolated_restore_drill": (
        "A non-destructive backup was restored into an isolated database and "
        "its checksum and integrity checks were accepted."
    ),
    "operations_ownership": (
        "Named operators accepted the daily, weekly, monthly, quarterly, and "
        "annual maintenance and escalation schedule."
    ),
}

MAINTENANCE_SCHEDULE = (
    {
        "frequency": "daily",
        "owner": "System Administrator",
        "controls": (
            "operations health report",
            "API supervisor and authenticated readiness",
            "backup freshness and protection",
            "failed background jobs and disk capacity",
        ),
    },
    {
        "frequency": "weekly",
        "owner": "System Administrator and service owner",
        "controls": (
            "health-report trend review",
            "critical-query latency",
            "failed authentication and privileged events",
            "approved source identity",
        ),
    },
    {
        "frequency": "monthly",
        "owner": "System Administrator, maintainer, and Municipal Treasurer",
        "controls": (
            "security and dependency updates",
            "privileged-access review",
            "certificate renewal window",
            "availability and incident trends",
        ),
    },
    {
        "frequency": "quarterly",
        "owner": "Service owner and independent reviewer",
        "controls": (
            "fresh hybrid backup",
            "isolated restore drill",
            "financial and audit verification on restored data",
            "incident-response tabletop",
        ),
    },
    {
        "frequency": "annual",
        "owner": "Municipality and independent assessor",
        "controls": (
            "penetration test",
            "credential and signing-key lifecycle review",
            "certificate and CA lifecycle review",
            "records-retention review and recertification",
        ),
    },
)


def _finding(component: str, code: str, detail: str, severity: str = "HIGH") -> dict:
    return {
        "component": component,
        "code": code,
        "detail": detail,
        "severity": severity,
    }


def _capture_component(name: str, operation: Callable[[], dict]) -> dict:
    try:
        report = operation()
    except Exception as exc:
        return {
            "status": "FAIL",
            "findings": [
                _finding(
                    name,
                    "PHASE9_COMPONENT_CHECK_FAILED",
                    f"{name} failed with {type(exc).__name__}.",
                )
            ],
        }
    status = str(report.get("status") or "").upper()
    if status not in {"PASS", "WARN", "REVIEW", "FAIL"}:
        return {
            "status": "FAIL",
            "findings": [
                _finding(
                    name,
                    "PHASE9_COMPONENT_STATUS_INVALID",
                    f"{name} returned an invalid status.",
                )
            ],
        }
    return report


def _normalized_path(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).rstrip("\\/")


def _read_operations_task_payload() -> dict:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if os.name != "nt" or not powershell:
        raise RuntimeError("Windows PowerShell is required for task inspection.")
    command = r"""
$task = Get-ScheduledTask -TaskName 'MTO Operations Health Check' -ErrorAction SilentlyContinue
if (-not $task) {
    @{ Present = $false } | ConvertTo-Json -Compress
    exit 0
}
$info = Get-ScheduledTaskInfo -TaskName 'MTO Operations Health Check'
$action = $task.Actions | Select-Object -First 1
$trigger = $task.Triggers | Select-Object -First 1
$limit = [Xml.XmlConvert]::ToTimeSpan([string]$task.Settings.ExecutionTimeLimit)
@{
    Present = $true
    State = [string]$task.State
    Execute = [string]$action.Execute
    Arguments = [string]$action.Arguments
    WorkingDirectory = [string]$action.WorkingDirectory
    UserId = [string]$task.Principal.UserId
    LogonType = [string]$task.Principal.LogonType
    RunLevel = [string]$task.Principal.RunLevel
    TriggerClass = [string]$trigger.CimClass.CimClassName
    StartBoundary = [string]$trigger.StartBoundary
    MultipleInstances = [string]$task.Settings.MultipleInstances
    StartWhenAvailable = [bool]$task.Settings.StartWhenAvailable
    ExecutionLimitSeconds = [int]$limit.TotalSeconds
    LastRunTime = if ($info.LastRunTime) { $info.LastRunTime.ToUniversalTime().ToString('o') } else { $null }
    LastTaskResult = [int64]$info.LastTaskResult
} | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("Operations task inspection failed.")
    payload = json.loads(completed.stdout.strip())
    if not isinstance(payload, dict):
        raise ValueError("Operations task inspection returned invalid data.")
    return payload


def capture_operations_task() -> dict:
    findings: list[dict] = []
    try:
        payload = _read_operations_task_payload()
    except Exception as exc:
        return {
            "status": "FAIL",
            "present": False,
            "findings": [
                _finding(
                    "operations_task",
                    "OPERATIONS_TASK_INSPECTION_FAILED",
                    f"Scheduled monitoring inspection failed with {type(exc).__name__}.",
                )
            ],
        }
    present = bool(payload.get("Present"))
    if not present:
        findings.append(
            _finding(
                "operations_task",
                "OPERATIONS_TASK_MISSING",
                "The daily operations-health scheduled task is not installed.",
            )
        )
        return {"status": "FAIL", "present": False, "findings": findings}

    expected_python = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    checks = (
        (
            _normalized_path(str(payload.get("Execute") or ""))
            == _normalized_path(expected_python),
            "OPERATIONS_TASK_EXECUTABLE_INVALID",
            "The operations task does not use the managed production Python.",
        ),
        (
            str(payload.get("Arguments") or "") == OPERATIONS_TASK_ARGUMENTS,
            "OPERATIONS_TASK_ARGUMENTS_INVALID",
            "The operations task does not use the approved runner and retention.",
        ),
        (
            _normalized_path(str(payload.get("WorkingDirectory") or ""))
            == _normalized_path(PROJECT_ROOT),
            "OPERATIONS_TASK_DIRECTORY_INVALID",
            "The operations task working directory is not the production checkout.",
        ),
        (
            str(payload.get("UserId") or "").upper()
            in {"SYSTEM", "NT AUTHORITY\\SYSTEM"},
            "OPERATIONS_TASK_PRINCIPAL_INVALID",
            "The operations task is not owned by SYSTEM.",
        ),
        (
            str(payload.get("LogonType") or "") == "ServiceAccount"
            and str(payload.get("RunLevel") or "") == "Highest",
            "OPERATIONS_TASK_PRIVILEGE_INVALID",
            "The operations task principal settings are not approved.",
        ),
        (
            str(payload.get("TriggerClass") or "") == "MSFT_TaskDailyTrigger",
            "OPERATIONS_TASK_TRIGGER_INVALID",
            "The operations task does not have a daily trigger.",
        ),
        (
            str(payload.get("MultipleInstances") or "") == "IgnoreNew"
            and bool(payload.get("StartWhenAvailable")),
            "OPERATIONS_TASK_SETTINGS_INVALID",
            "The operations task overlap and availability settings are invalid.",
        ),
        (
            int(payload.get("ExecutionLimitSeconds") or 0)
            == OPERATIONS_EXECUTION_LIMIT_SECONDS,
            "OPERATIONS_TASK_LIMIT_INVALID",
            "The operations task execution limit is not 30 minutes.",
        ),
        (
            str(payload.get("State") or "") in {"Ready", "Running"},
            "OPERATIONS_TASK_STATE_INVALID",
            "The operations task is not ready or running.",
        ),
        (
            bool(payload.get("LastRunTime"))
            and payload.get("LastTaskResult") is not None
            and int(payload["LastTaskResult"]) == 0,
            "OPERATIONS_TASK_SMOKE_MISSING",
            "The operations task does not have a successful smoke-test result.",
        ),
    )
    for passed, code, detail in checks:
        if not passed:
            findings.append(_finding("operations_task", code, detail))
    return {
        "status": "PASS" if not findings else "FAIL",
        "present": True,
        "state": str(payload.get("State") or "UNKNOWN"),
        "daily_trigger": str(payload.get("TriggerClass") or "")
        == "MSFT_TaskDailyTrigger",
        "retention_days": OPERATIONS_RETENTION_DAYS,
        "last_run_utc": payload.get("LastRunTime"),
        "last_task_result": payload.get("LastTaskResult"),
        "findings": findings,
    }


def capture_operations_monitoring() -> dict:
    health = _capture_component(
        "operations_health", operations_health_check.capture_health
    )
    task = _capture_component("operations_task", capture_operations_task)
    alerting = _capture_component("alerting", operations_alerting.capture_preflight)
    if alerting.get("status") == "PASS" and alerting.get("state") != "VALID":
        alerting = dict(alerting)
        alerting["status"] = "FAIL"
        alerting["findings"] = [
            _finding(
                "alerting",
                "OPERATIONS_ALERT_STATE_NOT_INITIALIZED",
                "The scheduled operations monitor has not produced valid alert state.",
            )
        ]
    components = {"health": health, "task": task, "alerting": alerting}
    findings = [
        item
        for component in components.values()
        for item in component.get("findings", [])
    ]
    passed = all(component.get("status") == "PASS" for component in components.values())
    return {
        "status": "PASS" if passed else "FAIL",
        "external_notifications": "DISABLED_LOCAL_ESCALATION_ACTIVE",
        "components": components,
        "findings": findings,
    }


def capture_manual_acceptance(
    *, final: bool, confirmations: Mapping[str, bool]
) -> dict:
    normalized = {
        name: bool(confirmations.get(name)) for name in MANUAL_ACCEPTANCE_REQUIREMENTS
    }
    if not final:
        return {
            "status": "PENDING",
            "confirmations": normalized,
            "requirements": dict(MANUAL_ACCEPTANCE_REQUIREMENTS),
            "findings": [],
        }
    findings = [
        _finding(
            "manual_acceptance",
            f"{name.upper()}_NOT_CONFIRMED",
            detail,
        )
        for name, detail in MANUAL_ACCEPTANCE_REQUIREMENTS.items()
        if not normalized[name]
    ]
    return {
        "status": "PASS" if not findings else "FAIL",
        "confirmations": normalized,
        "requirements": dict(MANUAL_ACCEPTANCE_REQUIREMENTS),
        "findings": findings,
    }


def _capture_automated_components(
    *,
    distribution: Path,
    distribution_scope: str,
    risk_acceptance: Path | None,
) -> dict[str, dict]:
    return {
        "release": _capture_component(
            "release",
            lambda: phase5_supply_chain_preflight.capture_supply_chain(
                root=PROJECT_ROOT,
                distribution=distribution,
                distribution_scope=distribution_scope,
                risk_acceptance=risk_acceptance,
            ),
        ),
        "reliability": _capture_component(
            "reliability", phase4_reliability_preflight.capture_reliability
        ),
        "financial_reconciliation": _capture_component(
            "financial_reconciliation",
            phase6_financial_reconciliation_preflight.capture_configured_preflight,
        ),
        "performance": _capture_component(
            "performance",
            phase7_performance_timeout_preflight.capture_phase7_assessment,
        ),
        "accessibility": _capture_component(
            "accessibility",
            lambda: phase8_accessibility_preflight.capture_phase8_assessment(
                PROJECT_ROOT
            ),
        ),
        "operations_monitoring": _capture_component(
            "operations_monitoring", capture_operations_monitoring
        ),
    }


def _accepted_risk_register(release: Mapping[str, object]) -> list[dict]:
    components = release.get("components")
    if not isinstance(components, Mapping):
        return []
    acceptance = components.get("risk_acceptance")
    if not isinstance(acceptance, Mapping) or not acceptance.get("active"):
        return []
    return [
        {
            "risk_id": acceptance.get("risk_id"),
            "title": "Unsigned executable and installer for internal municipal use",
            "status": "ACCEPTED_ACTIVE",
            "distribution_scope": release.get("distribution_scope"),
            "effective_date": acceptance.get("effective_date"),
            "review_due_date": acceptance.get("review_due_date"),
            "residual_severity": "MEDIUM",
            "waived_findings": list(acceptance.get("waived_findings") or []),
            "required_control_count": int(
                acceptance.get("required_control_count") or 0
            ),
            "restriction": "Controlled municipal computers only; no public distribution.",
        }
    ]


def _component_findings(components: Mapping[str, dict]) -> list[dict]:
    findings: list[dict] = []
    for name, component in components.items():
        if component.get("status") == "PASS":
            continue
        component_findings = list(component.get("findings") or [])
        if component_findings:
            findings.extend(component_findings)
        else:
            findings.append(
                _finding(
                    name,
                    "PHASE9_COMPONENT_NOT_READY",
                    f"{name} did not pass production-readiness certification.",
                )
            )
    return findings


def capture_certification(
    *,
    distribution: Path,
    distribution_scope: str,
    risk_acceptance: Path | None,
    final: bool,
    confirmations: Mapping[str, bool],
) -> dict:
    components = _capture_automated_components(
        distribution=distribution,
        distribution_scope=distribution_scope,
        risk_acceptance=risk_acceptance,
    )
    manual = capture_manual_acceptance(final=final, confirmations=confirmations)
    automated_pass = all(
        component.get("status") == "PASS" for component in components.values()
    )
    manual_pass = manual.get("status") == "PASS"
    accepted_risks = _accepted_risk_register(components.get("release", {}))
    findings = _component_findings(components)
    if final:
        findings.extend(manual.get("findings", []))
        status = "PASS" if automated_pass and manual_pass else "FAIL"
        if status == "PASS" and accepted_risks:
            status = "PASS_WITH_ACCEPTED_RISK"
    else:
        status = "READY_FOR_MANUAL_ACCEPTANCE" if automated_pass else "FAIL"
    automated_passed = sum(
        component.get("status") == "PASS" for component in components.values()
    )
    manual_confirmed = sum(manual["confirmations"].values())
    return {
        "format_version": FORMAT_VERSION,
        "report_type": REPORT_TYPE,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "FINAL" if final else "PREFLIGHT",
        "status": status,
        "decision": (
            "CERTIFIED_FOR_CONTROLLED_INTERNAL_MUNICIPAL_USE"
            if status in {"PASS", "PASS_WITH_ACCEPTED_RISK"}
            else status
        ),
        "privacy": (
            "Aggregate control status only; no taxpayer, receipt, credential, "
            "secret, private-key, or backup-path data."
        ),
        "components": components,
        "manual_acceptance": manual,
        "accepted_residual_risks": accepted_risks,
        "maintenance_schedule": list(MAINTENANCE_SCHEDULE),
        "scorecard": {
            "automated_controls_passed": automated_passed,
            "automated_controls_total": len(components),
            "manual_controls_confirmed": manual_confirmed,
            "manual_controls_total": len(MANUAL_ACCEPTANCE_REQUIREMENTS),
            "accepted_residual_risk_count": len(accepted_risks),
            "blocking_finding_count": len(findings),
        },
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--final", action="store_true")
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument(
        "--distribution-scope",
        choices=(
            phase5_supply_chain_preflight.SIGNED_PRODUCTION_SCOPE,
            phase5_supply_chain_preflight.INTERNAL_MUNICIPAL_SCOPE,
        ),
        default=phase5_supply_chain_preflight.SIGNED_PRODUCTION_SCOPE,
    )
    parser.add_argument("--risk-acceptance", type=Path)
    parser.add_argument("--confirm-desktop-workflows", action="store_true")
    parser.add_argument("--confirm-update-and-reconnection", action="store_true")
    parser.add_argument("--confirm-isolated-restore-drill", action="store_true")
    parser.add_argument("--confirm-operations-ownership", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    confirmations = {
        "desktop_workflows": args.confirm_desktop_workflows,
        "update_delivery_and_reconnection": args.confirm_update_and_reconnection,
        "isolated_restore_drill": args.confirm_isolated_restore_drill,
        "operations_ownership": args.confirm_operations_ownership,
    }
    if args.preflight and any(confirmations.values()):
        parser.error("manual confirmation switches are valid only with --final")
    report = capture_certification(
        distribution=args.distribution,
        distribution_scope=args.distribution_scope,
        risk_acceptance=args.risk_acceptance,
        final=args.final,
        confirmations=confirmations,
    )
    destination = write_report(report, args.output)
    print("ORIGINAL PHASE 9 PRODUCTION-READINESS CERTIFICATION")
    print(f"- Mode: {report['mode']}")
    for name, component in report["components"].items():
        print(f"- {name}: {component['status']}")
    print(f"- Manual acceptance: {report['manual_acceptance']['status']}")
    scorecard = report["scorecard"]
    print(
        "- Automated scorecard: "
        f"{scorecard['automated_controls_passed']}/"
        f"{scorecard['automated_controls_total']}"
    )
    print(
        "- Manual scorecard: "
        f"{scorecard['manual_controls_confirmed']}/"
        f"{scorecard['manual_controls_total']}"
    )
    print("- Accepted residual risks: " f"{scorecard['accepted_residual_risk_count']}")
    print(f"- Certification status: {report['status']}")
    print(f"- Privacy-safe report: {destination}")
    for item in report["findings"]:
        print(
            f"  - [{item['severity']}] {item['component']}/"
            f"{item['code']}: {item['detail']}"
        )
    if report["status"] == "FAIL":
        print("  ORIGINAL PHASE 9 CERTIFICATION BLOCKED")
        return 2
    if report["status"] == "READY_FOR_MANUAL_ACCEPTANCE":
        print("  ORIGINAL PHASE 9 AUTOMATED PREFLIGHT PASSED")
        return 0
    print("  ORIGINAL PHASE 9 PRODUCTION CERTIFICATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
