"""Read-only Phase 5 audit-integrity and activation preflight."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MIGRATION_ID = "phase5_audit_integrity_observability_v1"


def capture_preflight() -> dict:
    from backend.database import SessionLocal
    from backend.services.audit_integrity_service import (
        audit_chain_schema_status,
        verify_audit_chain,
    )
    from scripts.capture_remediation_baseline import (
        assess_database_readiness,
        capture_configured_database,
    )

    with SessionLocal() as session:
        schema = audit_chain_schema_status(session)
        audit_count = int(
            session.execute(text("SELECT COUNT(*) FROM audit_logs")).scalar() or 0
        )
        migration_applied = bool(
            session.execute(
                text("SELECT COUNT(*) FROM system_migrations WHERE id = :id"),
                {"id": MIGRATION_ID},
            ).scalar()
        )
        verification = (
            verify_audit_chain(session)
            if schema["active"]
            else {
                "status": "inactive",
                "schema_active": False,
                "event_count": audit_count,
                "verified_event_count": 0,
                "legacy_event_count": 0,
                "live_event_count": 0,
                "failure_count": 0,
                "failures": [],
            }
        )
        session.rollback()

    database = capture_configured_database()
    readiness_issues = assess_database_readiness(database)
    backup = database.get("backup", {})
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "migration_id": MIGRATION_ID,
        "schema": {
            **schema,
            "migration_applied": migration_applied,
        },
        "audit": verification,
        "backup": {
            "present": bool(backup.get("present")),
            "status": backup.get("status"),
            "health": backup.get("health"),
            "age_hours": backup.get("age_hours"),
            "restore_verification_current": bool(
                backup.get("restore_verification_current")
            ),
            "file_present_on_server": bool(backup.get("file_present_on_server")),
            "checksum_present": bool(backup.get("checksum_present")),
        },
        "readiness_issues": readiness_issues,
        "activation_ready": not readiness_issues
        and verification.get("status") in {"inactive", "verified"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--require-active", action="store_true")
    parser.add_argument("--require-live-event", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = capture_preflight()
    if args.output:
        destination = args.output.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print("PHASE 5 AUDIT INTEGRITY AND OBSERVABILITY PREFLIGHT")
    print(f"- Existing audit events: {report['audit']['event_count']}")
    print(f"- Sealed legacy events: {report['audit']['legacy_event_count']}")
    print(f"- Live Phase 5 events: {report['audit']['live_event_count']}")
    print(
        "- Phase 5 schema: "
        + ("ACTIVE" if report["schema"]["active"] else "NOT YET ACTIVE")
    )
    print(f"- Audit chain: {str(report['audit']['status']).upper()}")
    print(
        "- Backup readiness: "
        + ("PASS" if not report["readiness_issues"] else "BLOCKED")
    )
    if args.output:
        print(f"- Privacy-safe report: {args.output.resolve()}")

    if args.require_ready and report["readiness_issues"]:
        for issue in report["readiness_issues"]:
            print(f"  - {issue}")
        print("PHASE 5 PREFLIGHT BLOCKED: backup/readiness gate failed.")
        return 2
    if report["audit"]["status"] == "failed":
        print("PHASE 5 PREFLIGHT BLOCKED: audit-chain verification failed.")
        return 3
    if args.require_active and report["audit"]["status"] != "verified":
        print("PHASE 5 PREFLIGHT BLOCKED: required audit schema is not active.")
        return 4
    if (
        args.require_live_event
        and int(report["audit"].get("live_event_count") or 0) < 1
    ):
        print("PHASE 5 PREFLIGHT BLOCKED: no live Phase 5 audit event was found.")
        return 5
    print("PHASE 5 PREFLIGHT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
