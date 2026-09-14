"""Controlled recovery for Phase 5 audit timestamps truncated by MariaDB.

This server-only utility preserves the original event UUIDs and chain hashes.
It enumerates the missing microseconds, accepts only values proven by the
existing SHA-256 hashes, creates a fresh hybrid backup, upgrades timestamp
storage to ``DATETIME(6)``, and verifies the complete chain before commit.

The MTO API must remain stopped for both preflight and apply operations::

    python -m scripts.phase5_audit_timestamp_recovery --preflight
    python -m scripts.phase5_audit_timestamp_recovery --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal  # noqa: E402
from backend.services.audit_integrity_service import (  # noqa: E402
    AUDIT_TIMESTAMP_RECOVERY_MIGRATION_ID,
    AUDIT_TIMESTAMP_REQUIRED_PRECISION,
    AuditTimestampRecoveryError,
    audit_timestamp_storage_status,
    build_audit_timestamp_recovery_plan,
    ensure_audit_timestamp_precision_recovery,
    verify_audit_chain,
)
from backend.services.backup_service import run_hybrid_backup  # noqa: E402
from scripts.capture_remediation_baseline import (  # noqa: E402
    assess_database_readiness,
    capture_configured_database,
)
from scripts.rotate_server_credentials import (  # noqa: E402
    _api_is_listening,
    _require_administrator,
    _require_backup_ready,
)

CONFIRMATION = "RECOVER PHASE 5 AUDIT TIMESTAMP PRECISION"
DEFAULT_PREFLIGHT_REPORT = (
    PROJECT_ROOT / "logs" / "remediation-phase-5-audit-timestamp-preflight.json"
)
DEFAULT_RECOVERY_REPORT = (
    PROJECT_ROOT / "logs" / "remediation-phase-5-audit-timestamp-recovery.json"
)


class RecoveryUtilityError(RuntimeError):
    """Privacy-safe, operator-actionable recovery failure."""


def _migration_applied(session) -> bool:
    return bool(
        session.execute(
            text("SELECT COUNT(*) FROM system_migrations WHERE id=:migration_id"),
            {"migration_id": AUDIT_TIMESTAMP_RECOVERY_MIGRATION_ID},
        ).scalar()
    )


def _backup_summary() -> tuple[dict, list[str]]:
    database = capture_configured_database()
    backup = database.get("backup", {})
    issues = assess_database_readiness(database)
    return (
        {
            "present": bool(backup.get("present")),
            "filename": backup.get("filename"),
            "status": backup.get("status"),
            "health": backup.get("health"),
            "timestamp_utc": backup.get("timestamp_utc"),
            "age_hours": backup.get("age_hours"),
            "checksum_short": backup.get("checksum_short"),
            "restore_verification_current": bool(
                backup.get("restore_verification_current")
            ),
            "file_present_on_server": bool(backup.get("file_present_on_server")),
            "checksum_present": bool(backup.get("checksum_present")),
        },
        issues,
    )


def capture_preflight() -> dict:
    with SessionLocal() as session:
        plan = build_audit_timestamp_recovery_plan(session)
        migration_applied = _migration_applied(session)
        session.rollback()

    backup, readiness_issues = _backup_summary()
    api_stopped = not _api_is_listening()
    recovery = plan.privacy_safe_report()
    issues = list(recovery["issues"])
    if migration_applied and recovery["verification_status"] != "verified":
        issues.append("The recovery migration is recorded but the chain is invalid.")
    if not api_stopped:
        issues.append("The MTO API is still listening on port 8001.")
    issues.extend(readiness_issues)

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "migration_id": AUDIT_TIMESTAMP_RECOVERY_MIGRATION_ID,
        "migration_applied": migration_applied,
        "api_stopped": api_stopped,
        "backup": backup,
        "backup_ready": not readiness_issues,
        "recovery": recovery,
        "issues": issues,
        "ready": recovery["ready"] and not issues,
    }


def _write_report(report: dict, destination: Path) -> Path:
    resolved = destination.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_suffix(resolved.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(resolved)
    return resolved


def _print_preflight(report: dict, destination: Path) -> None:
    recovery = report["recovery"]
    print("PHASE 5 AUDIT TIMESTAMP RECOVERY PREFLIGHT")
    print(f"- MTO API stopped: {'PASS' if report['api_stopped'] else 'BLOCKED'}")
    print(
        "- Audit chain before recovery: " f"{recovery['verification_status'].upper()}"
    )
    print(f"- Failure count: {recovery['failure_count']}")
    print(f"- Recoverable timestamp events: {recovery['recovered_event_count']}")
    print(f"- Timestamp precision: {recovery['timestamp_precision']}")
    print("- Backup readiness: " + ("PASS" if report["backup_ready"] else "BLOCKED"))
    print(f"- Privacy-safe report: {destination}")
    if report["issues"]:
        for issue in report["issues"]:
            print(f"  - {issue}")
        print("PHASE 5 AUDIT TIMESTAMP RECOVERY PREFLIGHT BLOCKED")
    else:
        print("PHASE 5 AUDIT TIMESTAMP RECOVERY PREFLIGHT PASSED")


def _create_fresh_incident_backup() -> dict:
    success, _message = asyncio.run(
        run_hybrid_backup(
            user={
                "id": 0,
                "username": "phase5-audit-recovery",
                "role": "admin",
            }
        )
    )
    if not success:
        raise RecoveryUtilityError(
            "Fresh hybrid backup failed; no timestamp recovery was attempted."
        )
    try:
        _require_backup_ready()
    except Exception as exc:
        raise RecoveryUtilityError(
            "Fresh hybrid backup did not pass the protection and restore gates."
        ) from exc
    backup, issues = _backup_summary()
    if issues:
        raise RecoveryUtilityError(
            "Fresh hybrid backup attestation is incomplete; no recovery was attempted."
        )
    return backup


def apply_recovery() -> dict:
    try:
        _require_administrator()
    except Exception as exc:
        raise RecoveryUtilityError(
            "Run this recovery from Command Prompt as Administrator."
        ) from exc
    if _api_is_listening():
        raise RecoveryUtilityError(
            "The MTO API is still listening on port 8001. Keep it stopped."
        )

    before = capture_preflight()
    if not before["ready"]:
        raise RecoveryUtilityError(
            "Recovery preflight is blocked; review the privacy-safe report."
        )
    expected_event_ids = before["recovery"]["affected_event_ids"]

    incident_backup = _create_fresh_incident_backup()
    if _api_is_listening():
        raise RecoveryUtilityError(
            "The MTO API restarted during backup; no recovery was attempted."
        )

    with SessionLocal() as session:
        current_plan = build_audit_timestamp_recovery_plan(session)
        if not current_plan.ready:
            raise RecoveryUtilityError(
                "Audit evidence changed after preflight; recovery was cancelled."
            )
        current_event_ids = [item.audit_id for item in current_plan.candidates]
        if current_event_ids != expected_event_ids:
            raise RecoveryUtilityError(
                "The affected audit event set changed after backup."
            )
        if _migration_applied(session):
            raise RecoveryUtilityError(
                "The recovery migration is already recorded; no write was performed."
            )

        try:
            result = ensure_audit_timestamp_precision_recovery(
                session,
                allow_evidence_recovery=True,
            )
            session.execute(
                text(
                    "INSERT INTO system_migrations (id, applied_at) "
                    "VALUES (:migration_id, :applied_at)"
                ),
                {
                    "migration_id": AUDIT_TIMESTAMP_RECOVERY_MIGRATION_ID,
                    "applied_at": datetime.now(timezone.utc).replace(tzinfo=None),
                },
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    with SessionLocal() as verification_session:
        verification = verify_audit_chain(
            verification_session,
            max_failures=1_000_000,
        )
        storage = audit_timestamp_storage_status(verification_session)
        applied = _migration_applied(verification_session)
        verification_session.rollback()

    if verification["status"] != "verified":
        raise RecoveryUtilityError(
            "Post-recovery audit verification failed; keep the API stopped."
        )
    if storage["datetime_precision"] != AUDIT_TIMESTAMP_REQUIRED_PRECISION:
        raise RecoveryUtilityError(
            "Post-recovery timestamp precision validation failed."
        )
    if not applied:
        raise RecoveryUtilityError("Recovery migration attestation is missing.")

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "migration_id": AUDIT_TIMESTAMP_RECOVERY_MIGRATION_ID,
        "migration_applied": True,
        "fresh_hybrid_backup": incident_backup,
        "affected_event_ids": expected_event_ids,
        "recovered_event_count": result["recovered_event_count"],
        "timestamp_precision_before": result["timestamp_precision"],
        "timestamp_precision_after": storage["datetime_precision"],
        "audit_chain_after": verification["status"],
        "hashes_modified": False,
        "timestamp_values_restored": bool(result["timestamp_values_restored"]),
        "non_timestamp_fields_modified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    destination = args.output or (
        DEFAULT_RECOVERY_REPORT if args.apply else DEFAULT_PREFLIGHT_REPORT
    )
    try:
        if args.preflight:
            report = capture_preflight()
            report_path = _write_report(report, destination)
            _print_preflight(report, report_path)
            return 0 if report["ready"] else 2

        print("This operation restores hash-proven audit timestamp precision.")
        print("It creates a fresh hybrid backup before changing the database.")
        typed = input(f"Type {CONFIRMATION} to continue: ").strip()
        if typed != CONFIRMATION:
            print("Recovery cancelled. No database change was made.")
            return 3

        report = apply_recovery()
        report_path = _write_report(report, destination)
        print("PHASE 5 AUDIT TIMESTAMP RECOVERY: PASS")
        print("- Fresh hybrid backup: PASS")
        print(f"- Backup file: {report['fresh_hybrid_backup']['filename']}")
        print(f"- Recovered audit events: {report['recovered_event_count']}")
        print(
            "- Timestamp precision: "
            f"{report['timestamp_precision_before']} -> "
            f"{report['timestamp_precision_after']}"
        )
        print(f"- Audit chain: {report['audit_chain_after'].upper()}")
        print("- Existing audit hashes modified: NO")
        print("- Non-timestamp audit fields modified: NO")
        print(f"- Privacy-safe report: {report_path}")
        print("Keep the API stopped and run the post-recovery verification.")
        return 0
    except (AuditTimestampRecoveryError, RecoveryUtilityError) as exc:
        print(f"PHASE 5 AUDIT TIMESTAMP RECOVERY BLOCKED: {exc}")
        return 4
    except Exception as exc:
        print(
            "PHASE 5 AUDIT TIMESTAMP RECOVERY FAILED: "
            f"{type(exc).__name__}. Keep the API stopped and preserve all evidence."
        )
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
