"""Read-only Phase 6 production certification for the MTO deployment.

The runner consolidates source, database, audit, backup, TLS, runtime,
dependency, desktop-boundary, API-latency, and critical-query checks. It never
changes business data, configuration, credentials, certificates, or services.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

FORMAT_VERSION = 1
DEFAULT_REPORT = PROJECT_ROOT / "logs" / "remediation-phase-6-certification.json"
DEFAULT_API_SAMPLES = 3
DEFAULT_QUERY_SAMPLES = 2
DEFAULT_MAX_API_SECONDS = 3.0
DEFAULT_MAX_QUERY_SECONDS = 5.0
DEFAULT_MINIMUM_CERTIFICATE_DAYS = 30
TASK_NAME = "MTO Treasury API"


def _finding(component: str, code: str, detail: str, severity: str) -> dict:
    return {
        "component": component,
        "code": code,
        "detail": detail,
        "severity": severity,
    }


def _status(findings: list[dict]) -> str:
    return "PASS" if not findings else "FAIL"


def capture_source_control() -> dict:
    from scripts.capture_remediation_baseline import collect_source_snapshot

    findings: list[dict] = []
    try:
        snapshot = collect_source_snapshot()
    except Exception as exc:
        findings.append(
            _finding(
                "source",
                "SOURCE_INSPECTION_FAILED",
                f"Source-control inspection failed with {type(exc).__name__}.",
                "HIGH",
            )
        )
        return {"status": "FAIL", "findings": findings}

    if snapshot["branch"] != "master":
        findings.append(
            _finding(
                "source",
                "SOURCE_BRANCH_NOT_MASTER",
                "Production certification requires the master branch.",
                "HIGH",
            )
        )
    if snapshot["dirty"]:
        findings.append(
            _finding(
                "source",
                "SOURCE_WORKTREE_DIRTY",
                "Production source contains tracked or untracked local changes.",
                "MEDIUM",
            )
        )
    return {
        "status": _status(findings),
        "commit": snapshot["commit"],
        "branch": snapshot["branch"],
        "clean": not snapshot["dirty"],
        "changed_file_count": snapshot["changed_file_count"],
        "python": snapshot["python"],
        "platform": snapshot["platform"],
        "dependency_manifest_sha256": snapshot["dependency_manifest_sha256"],
        "findings": findings,
    }


def _capture_migrations() -> dict:
    from backend.database import SessionLocal
    from backend.services.migration_service import MIGRATIONS
    from scripts.capture_remediation_baseline import _begin_read_only_transaction

    required = [str(item["id"]) for item in MIGRATIONS]
    with SessionLocal() as session:
        _begin_read_only_transaction(session)
        applied = {
            str(row[0])
            for row in session.execute(text("SELECT id FROM system_migrations")).all()
        }
        session.rollback()
    missing = sorted(set(required) - applied)
    return {
        "required_count": len(required),
        "applied_required_count": len(required) - len(missing),
        "missing": missing,
    }


def capture_database_assurance() -> dict:
    from scripts.phase3_financial_preflight import capture_preflight as financial
    from scripts.phase5_audit_observability_preflight import (
        capture_preflight as audit,
    )

    findings: list[dict] = []
    try:
        financial_report = financial()
        audit_report = audit()
        migrations = _capture_migrations()
    except Exception as exc:
        findings.append(
            _finding(
                "database",
                "DATABASE_CERTIFICATION_FAILED",
                f"Database certification failed with {type(exc).__name__}.",
                "CRITICAL",
            )
        )
        return {"status": "FAIL", "findings": findings}

    if not financial_report["financial_invariants_pass"]:
        findings.append(
            _finding(
                "database",
                "FINANCIAL_INVARIANTS_FAILED",
                "One or more financial invariants are violated.",
                "CRITICAL",
            )
        )
    if not financial_report["schema"]["active"]:
        findings.append(
            _finding(
                "database",
                "FINANCIAL_SCHEMA_INACTIVE",
                "Phase 3 financial-safety schema is not active.",
                "CRITICAL",
            )
        )
    if audit_report["audit"]["status"] != "verified":
        findings.append(
            _finding(
                "database",
                "AUDIT_CHAIN_NOT_VERIFIED",
                "The complete audit chain is not verified.",
                "CRITICAL",
            )
        )
    if not audit_report["schema"]["active"]:
        findings.append(
            _finding(
                "database",
                "AUDIT_SCHEMA_INACTIVE",
                "Phase 5 audit schema is not active.",
                "CRITICAL",
            )
        )
    if (
        audit_report["schema"]["timestamp_precision"]
        != audit_report["schema"]["required_timestamp_precision"]
    ):
        findings.append(
            _finding(
                "database",
                "AUDIT_TIMESTAMP_PRECISION_INVALID",
                "Audit timestamp storage is not DATETIME(6).",
                "CRITICAL",
            )
        )
    if int(audit_report["audit"].get("live_event_count") or 0) < 1:
        findings.append(
            _finding(
                "database",
                "AUDIT_LIVE_EVENT_MISSING",
                "No verified live Phase 5 audit event exists.",
                "HIGH",
            )
        )
    for issue in audit_report["readiness_issues"]:
        findings.append(_finding("backup", "BACKUP_NOT_READY", str(issue), "CRITICAL"))
    if migrations["missing"]:
        findings.append(
            _finding(
                "database",
                "MIGRATIONS_MISSING",
                "Required server migrations are missing.",
                "CRITICAL",
            )
        )

    return {
        "status": _status(findings),
        "financial": {
            "invariants": financial_report["financial_invariants"],
            "invariants_pass": financial_report["financial_invariants_pass"],
            "schema_active": financial_report["schema"]["active"],
        },
        "audit": {
            "status": audit_report["audit"]["status"],
            "event_count": audit_report["audit"]["event_count"],
            "legacy_event_count": audit_report["audit"]["legacy_event_count"],
            "live_event_count": audit_report["audit"]["live_event_count"],
            "failure_count": audit_report["audit"]["failure_count"],
            "schema_active": audit_report["schema"]["active"],
            "timestamp_precision": audit_report["schema"]["timestamp_precision"],
        },
        "backup": audit_report["backup"],
        "migrations": migrations,
        "findings": findings,
    }


def capture_dependency_policy() -> dict:
    from scripts.check_dependency_policy import validate_repository

    findings, counts = validate_repository(PROJECT_ROOT)
    normalized = [
        _finding(
            "dependencies",
            str(item.get("code") or "DEPENDENCY_POLICY_FAILURE"),
            str(item.get("detail") or "Dependency policy validation failed."),
            "HIGH",
        )
        for item in findings
    ]
    return {
        "status": _status(normalized),
        "counts": counts,
        "findings": normalized,
    }


def capture_desktop_boundary(distribution: Path) -> dict:
    from scripts.verify_desktop_trust_boundary import (
        verify_distribution,
        verify_source_boundary,
        verify_spec_boundary,
    )

    errors = verify_source_boundary()
    errors.extend(verify_spec_boundary())
    errors.extend(verify_distribution(distribution.resolve()))
    findings = [
        _finding("desktop", "DESKTOP_TRUST_BOUNDARY_FAILED", error, "CRITICAL")
        for error in errors
    ]
    return {
        "status": _status(findings),
        "distribution_checked": distribution.name,
        "findings": findings,
    }


def capture_tls(minimum_certificate_days: int) -> dict:
    from backend.tls_config import load_server_tls_config, validate_server_tls_config

    findings: list[dict] = []
    try:
        config = load_server_tls_config()
        identity = validate_server_tls_config(config)
    except Exception as exc:
        findings.append(
            _finding(
                "tls",
                "TLS_VALIDATION_FAILED",
                f"Authenticated TLS validation failed with {type(exc).__name__}.",
                "CRITICAL",
            )
        )
        return {"status": "FAIL", "findings": findings}

    if not config.required or not config.enabled or identity is None:
        findings.append(
            _finding(
                "tls",
                "TLS_NOT_REQUIRED",
                "Production API transport does not require authenticated TLS.",
                "CRITICAL",
            )
        )
        return {"status": "FAIL", "findings": findings}

    remaining = (identity.not_valid_after - datetime.now(timezone.utc)).total_seconds()
    days_remaining = remaining / 86400
    if days_remaining < minimum_certificate_days:
        findings.append(
            _finding(
                "tls",
                "TLS_CERTIFICATE_EXPIRING",
                "The server certificate is inside the minimum renewal window.",
                "HIGH",
            )
        )
    fingerprint = identity.fingerprint_sha256
    return {
        "status": _status(findings),
        "required": config.required,
        "enabled": config.enabled,
        "server_names": list(identity.server_names),
        "certificate_expires_utc": identity.not_valid_after.isoformat(),
        "certificate_days_remaining": round(days_remaining, 1),
        "certificate_sha256_short": f"{fingerprint[:12]}...{fingerprint[-12:]}",
        "minimum_certificate_days": minimum_certificate_days,
        "findings": findings,
    }


def _sanitized_endpoint(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "path": parsed.path,
    }


def capture_api_latency(samples: int, maximum_seconds: float) -> dict:
    from scripts.tls_health import health_url, ssl_context_for_health_url

    findings: list[dict] = []
    timings: list[float] = []
    try:
        target = health_url()
        parsed_target = urlparse(target)
        if parsed_target.scheme != "https" or not parsed_target.hostname:
            raise RuntimeError("Production certification requires an HTTPS endpoint.")
        context = ssl_context_for_health_url(target)
        for _index in range(samples):
            started = time.perf_counter()
            request = Request(target, method="GET")
            # The HTTPS scheme and hostname are checked immediately above.
            with urlopen(request, timeout=5, context=context) as response:  # nosec B310
                if response.status != 200:
                    raise RuntimeError("Readiness endpoint did not return HTTP 200.")
            timings.append(time.perf_counter() - started)
    except Exception as exc:
        findings.append(
            _finding(
                "api",
                "API_READINESS_FAILED",
                f"Authenticated readiness failed with {type(exc).__name__}.",
                "CRITICAL",
            )
        )
        return {
            "status": "FAIL",
            "sample_count": len(timings),
            "maximum_seconds_allowed": maximum_seconds,
            "findings": findings,
        }

    observed_max = max(timings)
    if observed_max > maximum_seconds:
        findings.append(
            _finding(
                "api",
                "API_LATENCY_EXCEEDED",
                "Authenticated readiness latency exceeded the certification limit.",
                "HIGH",
            )
        )
    return {
        "status": _status(findings),
        "endpoint": _sanitized_endpoint(target),
        "sample_count": len(timings),
        "samples_seconds": [round(value, 4) for value in timings],
        "median_seconds": round(statistics.median(timings), 4),
        "maximum_seconds": round(observed_max, 4),
        "maximum_seconds_allowed": maximum_seconds,
        "findings": findings,
    }


def _result_count(result: Any) -> int:
    if isinstance(result, dict):
        if "count" in result:
            return int(result["count"] or 0)
        if isinstance(result.get("items"), list):
            return len(result["items"])
    if isinstance(result, list):
        return len(result)
    return 0


def capture_critical_query_latency(samples: int, maximum_seconds: float) -> dict:
    from backend.database import SessionLocal
    from backend.services import billing_service
    from scripts.capture_remediation_baseline import _begin_read_only_transaction
    from utils.config import config

    findings: list[dict] = []
    operations: dict[str, dict] = {}
    compliance_page: Callable[..., Any] = (
        billing_service.get_compliant_accounts_v2
        if config.ENABLE_COMPLIANCE_V2
        else billing_service.get_compliant_accounts
    )
    compliance_summary: Callable[..., Any] = (
        billing_service.get_compliant_summary_by_barangay_v2
        if config.ENABLE_COMPLIANCE_V2
        else billing_service.get_compliant_summary_by_barangay
    )

    with SessionLocal() as session:
        try:
            _begin_read_only_transaction(session)
            checks: tuple[tuple[str, Callable[[], Any]], ...] = (
                (
                    "delinquent_page",
                    lambda: billing_service.get_delinquent_accounts(
                        limit=50, db_session=session
                    ),
                ),
                (
                    "compliant_page",
                    lambda: compliance_page(limit=50, db_session=session),
                ),
                (
                    "compliant_summary",
                    lambda: compliance_summary(db_session=session),
                ),
            )
            for name, operation in checks:
                timings: list[float] = []
                count = 0
                try:
                    for _index in range(samples):
                        started = time.perf_counter()
                        result = operation()
                        timings.append(time.perf_counter() - started)
                        count = _result_count(result)
                    observed_max = max(timings)
                    if observed_max > maximum_seconds:
                        findings.append(
                            _finding(
                                "latency",
                                "CRITICAL_QUERY_LATENCY_EXCEEDED",
                                f"{name} exceeded the certification limit.",
                                "HIGH",
                            )
                        )
                    operations[name] = {
                        "status": (
                            "PASS" if observed_max <= maximum_seconds else "FAIL"
                        ),
                        "result_count": count,
                        "samples_seconds": [round(value, 4) for value in timings],
                        "median_seconds": round(statistics.median(timings), 4),
                        "maximum_seconds": round(observed_max, 4),
                    }
                except Exception as exc:
                    findings.append(
                        _finding(
                            "latency",
                            "CRITICAL_QUERY_FAILED",
                            f"{name} failed with {type(exc).__name__}.",
                            "HIGH",
                        )
                    )
                    operations[name] = {
                        "status": "FAIL",
                        "result_count": 0,
                        "samples_seconds": [],
                    }
        finally:
            session.rollback()

    return {
        "status": _status(findings),
        "classification_version": (
            "v2_per_year" if config.ENABLE_COMPLIANCE_V2 else "legacy_currency_safe"
        ),
        "sample_count_per_query": samples,
        "maximum_seconds_allowed": maximum_seconds,
        "operations": operations,
        "findings": findings,
    }


def capture_runtime_supervisor() -> dict:
    findings: list[dict] = []
    if os.name != "nt":
        findings.append(
            _finding(
                "runtime",
                "WINDOWS_RUNTIME_CHECK_UNAVAILABLE",
                "The MTO production supervisor check requires Windows.",
                "HIGH",
            )
        )
        return {"status": "FAIL", "findings": findings}

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        findings.append(
            _finding(
                "runtime",
                "POWERSHELL_NOT_FOUND",
                "PowerShell is required to inspect the MTO scheduled task.",
                "HIGH",
            )
        )
        return {"status": "FAIL", "findings": findings}

    command = (
        f"$task=Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction Stop;"
        f"$info=Get-ScheduledTaskInfo -TaskName '{TASK_NAME}' -ErrorAction Stop;"
        "$action=$task.Actions | Select-Object -First 1;"
        "[pscustomobject]@{State=[string]$task.State;"
        "UserId=[string]$task.Principal.UserId;"
        "Execute=[string]$action.Execute;Arguments=[string]$action.Arguments;"
        "WorkingDirectory=[string]$action.WorkingDirectory;"
        "LastTaskResult=[int64]$info.LastTaskResult}|ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if completed.returncode != 0:
            raise RuntimeError("Scheduled task query failed.")
        payload = json.loads(completed.stdout.strip())
    except Exception as exc:
        findings.append(
            _finding(
                "runtime",
                "RUNTIME_SUPERVISOR_INSPECTION_FAILED",
                f"Runtime supervisor inspection failed with {type(exc).__name__}.",
                "HIGH",
            )
        )
        return {"status": "FAIL", "findings": findings}

    state = str(payload.get("State") or "").upper()
    user_id = str(payload.get("UserId") or "").upper()
    arguments = str(payload.get("Arguments") or "")
    working_directory = str(payload.get("WorkingDirectory") or "")
    running = state == "RUNNING"
    runs_as_system = user_id == "SYSTEM" or user_id.endswith("\\SYSTEM")
    supervisor_module = "-m scripts.run_api_supervisor" in arguments
    working_directory_matches = (
        Path(working_directory).resolve() == PROJECT_ROOT.resolve()
        if working_directory
        else False
    )
    for condition, code, detail in (
        (running, "RUNTIME_TASK_NOT_RUNNING", "MTO API supervisor is not running."),
        (
            runs_as_system,
            "RUNTIME_TASK_WRONG_PRINCIPAL",
            "MTO API supervisor is not running as SYSTEM.",
        ),
        (
            supervisor_module,
            "RUNTIME_TASK_WRONG_ACTION",
            "MTO API scheduled task does not run the supervisor module.",
        ),
        (
            working_directory_matches,
            "RUNTIME_TASK_WRONG_DIRECTORY",
            "MTO API scheduled task uses the wrong working directory.",
        ),
    ):
        if not condition:
            findings.append(_finding("runtime", code, detail, "HIGH"))
    return {
        "status": _status(findings),
        "task_name": TASK_NAME,
        "state": state,
        "runs_as_system": runs_as_system,
        "supervisor_module": supervisor_module,
        "working_directory_matches": working_directory_matches,
        "last_task_result": payload.get("LastTaskResult"),
        "findings": findings,
    }


def _capture_component(name: str, operation: Callable[[], dict]) -> dict:
    try:
        return operation()
    except Exception as exc:
        finding = _finding(
            name,
            "COMPONENT_CHECK_FAILED",
            f"{name} check failed with {type(exc).__name__}.",
            "HIGH",
        )
        return {"status": "FAIL", "findings": [finding]}


def capture_certification(
    *,
    distribution: Path,
    final: bool,
    desktop_smoke_confirmed: bool,
    api_samples: int,
    query_samples: int,
    maximum_api_seconds: float,
    maximum_query_seconds: float,
    minimum_certificate_days: int,
) -> dict:
    components = {
        "source": _capture_component("source", capture_source_control),
        "database": _capture_component("database", capture_database_assurance),
        "dependencies": _capture_component("dependencies", capture_dependency_policy),
        "desktop": _capture_component(
            "desktop", lambda: capture_desktop_boundary(distribution)
        ),
        "tls": _capture_component("tls", lambda: capture_tls(minimum_certificate_days)),
        "api": _capture_component(
            "api", lambda: capture_api_latency(api_samples, maximum_api_seconds)
        ),
        "critical_queries": _capture_component(
            "latency",
            lambda: capture_critical_query_latency(
                query_samples, maximum_query_seconds
            ),
        ),
        "runtime": _capture_component("runtime", capture_runtime_supervisor),
    }
    findings = [
        item
        for component in components.values()
        for item in component.get("findings", [])
    ]
    if final and not desktop_smoke_confirmed:
        findings.append(
            _finding(
                "manual_acceptance",
                "DESKTOP_SMOKE_NOT_CONFIRMED",
                "Final certification requires the documented desktop smoke test.",
                "HIGH",
            )
        )
    automated_pass = all(
        component.get("status") == "PASS" for component in components.values()
    )
    if final:
        certification_status = (
            "PASS" if automated_pass and desktop_smoke_confirmed else "FAIL"
        )
    else:
        certification_status = (
            "READY_FOR_MANUAL_ACCEPTANCE" if automated_pass else "FAIL"
        )
    return {
        "format_version": FORMAT_VERSION,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "privacy": (
            "Aggregate operational metadata only; no taxpayer, receipt, "
            "credential, secret, or private-key data."
        ),
        "mode": "FINAL" if final else "PREFLIGHT",
        "status": certification_status,
        "automated_gates_pass": automated_pass,
        "manual_acceptance": {
            "desktop_smoke_confirmed": desktop_smoke_confirmed,
            "required_actions": [
                "login and dashboard",
                "property search",
                "payment ledger",
                "duplicate-TD isolation",
                "PDF or report generation",
                "logout and reopen",
            ],
        },
        "thresholds": {
            "maximum_api_seconds": maximum_api_seconds,
            "maximum_query_seconds": maximum_query_seconds,
            "minimum_certificate_days": minimum_certificate_days,
        },
        "components": components,
        "finding_count": len(findings),
        "findings": findings,
    }


def _write_report(path: Path, report: dict) -> Path:
    from scripts.capture_remediation_baseline import write_report

    destination = path.resolve()
    write_report(destination, report)
    return destination


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
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--final", action="store_true")
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--confirm-desktop-smoke", action="store_true")
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
    parser.add_argument(
        "--max-query-seconds",
        type=_positive_float,
        default=DEFAULT_MAX_QUERY_SECONDS,
    )
    parser.add_argument(
        "--minimum-certificate-days",
        type=_positive_int,
        default=DEFAULT_MINIMUM_CERTIFICATE_DAYS,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    if args.preflight and args.confirm_desktop_smoke:
        parser.error("--confirm-desktop-smoke is valid only with --final")

    report = capture_certification(
        distribution=args.distribution,
        final=args.final,
        desktop_smoke_confirmed=args.confirm_desktop_smoke,
        api_samples=args.api_samples,
        query_samples=args.query_samples,
        maximum_api_seconds=args.max_api_seconds,
        maximum_query_seconds=args.max_query_seconds,
        minimum_certificate_days=args.minimum_certificate_days,
    )
    destination = _write_report(args.output, report)
    print("PHASE 6 FINAL PRODUCTION CERTIFICATION")
    print(f"- Mode: {report['mode']}")
    for name, component in report["components"].items():
        print(f"- {name}: {component['status']}")
    print(
        "- Manual desktop smoke: "
        + (
            "CONFIRMED"
            if report["manual_acceptance"]["desktop_smoke_confirmed"]
            else "PENDING"
        )
    )
    print(f"- Certification status: {report['status']}")
    print(f"- Privacy-safe report: {destination}")
    for item in report["findings"]:
        print(
            f"  - [{item['severity']}] {item['component']}/"
            f"{item['code']}: {item['detail']}"
        )
    if report["status"] == "FAIL":
        print("PHASE 6 CERTIFICATION BLOCKED")
        return 2
    if report["status"] == "READY_FOR_MANUAL_ACCEPTANCE":
        print("PHASE 6 AUTOMATED PREFLIGHT PASSED")
        return 0
    print("PHASE 6 PRODUCTION CERTIFICATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
