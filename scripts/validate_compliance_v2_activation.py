"""Fail-closed preflight for enabling the compliance V2 feature flag.

This command is read-only. It requires a recent verified backup, rejects any
newly-compliant accounts, and requires an exact signed-off list for accounts
that V2 would remove from the compliant area.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal
from backend.models import BackupHistory
from backend.services.compliance_impact_service import build_compliance_impact_report


SUCCESS_BACKUP_STATUSES = {
    "LOCAL_ONLY",
    "USB_ONLY",
    "CLOUD_ONLY",
    "SYNCED",
    "SUCCESS",
    "OK",
    "COMPLETED",
}
SUCCESS_BACKUP_HEALTH = {"OK", "SUCCESS", "Success"}


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evaluate_activation(
    *,
    report: dict[str, Any],
    backup: dict[str, Any] | None,
    approval: dict[str, Any] | None,
    max_backup_age_hours: int = 24,
    now: datetime | None = None,
) -> list[str]:
    """Return every blocking reason; an empty list means activation may proceed."""
    errors: list[str] = []
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if not backup:
        errors.append("No completed database backup record exists.")
    else:
        status = str(backup.get("status") or "").upper()
        health = str(backup.get("health") or "")
        checksum = str(backup.get("checksum") or "")
        file_path = str(backup.get("file_path") or "")
        created_at = _timestamp(backup.get("timestamp"))
        if status not in SUCCESS_BACKUP_STATUSES:
            errors.append(
                f"Latest backup status is not successful: {status or 'missing'}."
            )
        if health not in SUCCESS_BACKUP_HEALTH and "Success" not in health:
            errors.append(
                f"Latest backup verification is not successful: {health or 'missing'}."
            )
        if len(checksum) != 64:
            errors.append("Latest backup does not have a complete SHA256 checksum.")
        if not file_path or not os.path.isfile(file_path):
            errors.append("Latest verified backup file is missing from the server.")
        if created_at is None:
            errors.append("Latest backup timestamp is missing or invalid.")
        elif current - created_at > timedelta(hours=max_backup_age_hours):
            errors.append(
                f"Latest verified backup is older than {max_backup_age_hours} hours."
            )

    newly = {
        str(row.get("td_number"))
        for row in report.get("affected_accounts", [])
        if row.get("change") == "newly_compliant"
    }
    removed = {
        str(row.get("td_number"))
        for row in report.get("affected_accounts", [])
        if row.get("change") == "removed_from_compliant"
    }
    counts = report.get("counts") or {}
    newly_count = int(counts.get("newly_compliant") or 0)
    removed_count = int(counts.get("removed_from_compliant") or 0)
    if report.get("details_truncated"):
        errors.append(
            "Impact details are truncated; rerun with a sufficient detail limit."
        )
    if newly_count != len(newly) or removed_count != len(removed):
        errors.append(
            "Impact counts do not match the listed accounts; activation cannot be verified."
        )
    if newly_count:
        errors.append(
            f"V2 would add {newly_count} newly compliant account(s); "
            "review policy/data first: " + ", ".join(sorted(newly))
        )

    if removed and not approval:
        errors.append(
            "V2 removals require an approval file listing exactly: "
            + ", ".join(sorted(removed))
        )
    elif approval:
        approved_removed = {
            str(value) for value in approval.get("approved_removed_td_numbers", [])
        }
        if approved_removed != removed:
            errors.append(
                "Approval removal list does not exactly match the current preview."
            )
        if int(approval.get("as_of_year") or 0) != int(report.get("as_of_year") or 0):
            errors.append("Approval year does not match the current preview year.")
        if approval.get("billing_data_start_year") != report.get(
            "billing_data_start_year"
        ):
            errors.append("Approval data-start-year policy does not match the preview.")
        if bool(approval.get("exclude_archived_billings")) != bool(
            report.get("exclude_archived_billings")
        ):
            errors.append(
                "Approval archived-billing policy does not match the preview."
            )
        if not str(approval.get("approved_by") or "").strip():
            errors.append("Approval file must identify approved_by.")
        if _timestamp(approval.get("approved_at")) is None:
            errors.append("Approval file must contain a valid approved_at timestamp.")
    return errors


def _latest_backup(session) -> dict[str, Any] | None:
    row = (
        session.query(BackupHistory)
        .filter(BackupHistory.filename != "__lock__", BackupHistory.status != "RUNNING")
        .order_by(BackupHistory.id.desc())
        .first()
    )
    if not row:
        return None
    return {
        "filename": row.filename,
        "file_path": row.file_path,
        "checksum": row.checksum,
        "status": row.status,
        "health": row.health,
        "timestamp": row.timestamp,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--detail-limit", type=int, default=5000)
    parser.add_argument("--max-backup-age-hours", type=int, default=24)
    args = parser.parse_args()

    approval = None
    if args.approval:
        approval = json.loads(args.approval.read_text(encoding="utf-8"))

    session = SessionLocal()
    try:
        report = build_compliance_impact_report(
            as_of_year=args.year,
            detail_limit=args.detail_limit,
            db_session=session,
        )
        backup = _latest_backup(session)
    finally:
        session.rollback()
        session.close()

    payload = {"report": report, "backup": backup}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    errors = evaluate_activation(
        report=report,
        backup=backup,
        approval=approval,
        max_backup_age_hours=args.max_backup_age_hours,
    )
    if errors:
        print("COMPLIANCE V2 ACTIVATION BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 2

    print("COMPLIANCE V2 ACTIVATION PREFLIGHT PASSED")
    print("The feature flag may be enabled, followed by API restart and smoke tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
