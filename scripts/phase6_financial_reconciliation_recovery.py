"""Deterministic, backup-gated recovery for Original Roadmap Phase 6.

The command repairs only evidence-backed legacy inconsistencies:

* billing penalty/discount summaries when every linked payment belongs to one
  billing only;
* a missing payment tax year when exactly one allocation year proves it; and
* receipt rows whose referenced payment no longer exists, preserving the
  receipt while clearing only the dead reference.

The API must be stopped. Apply mode creates a fresh hybrid backup, recaptures
the exact candidate fingerprint, writes sealed audit events, and leaves the API
stopped for the release migration and post-recovery checks.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text

_configured_root = os.environ.get("MTO_PROJECT_ROOT")
PROJECT_ROOT = (
    Path(_configured_root).resolve()
    if _configured_root
    else Path(__file__).resolve().parents[1]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal  # noqa: E402
from backend.services.audit_integrity_service import (  # noqa: E402
    append_audit_event,
    canonical_snapshot,
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

CONFIRMATION = "RECOVER ORIGINAL PHASE 6 FINANCIAL RECONCILIATION"
DEFAULT_PREFLIGHT_REPORT = (
    PROJECT_ROOT / "logs" / "remediation-original-phase-6-recovery-preflight.json"
)
DEFAULT_RECOVERY_REPORT = (
    PROJECT_ROOT / "logs" / "remediation-original-phase-6-recovery.json"
)
RECOVERY_USERNAME = "phase6-financial-recovery"


class RecoveryUtilityError(RuntimeError):
    """Privacy-safe, operator-actionable recovery failure."""


def _money(value: Any) -> str:
    return format(Decimal(str(value or 0)).quantize(Decimal("0.01")), "f")


def _billing_candidates(session: Any) -> tuple[list[dict[str, Any]], list[dict]]:
    rows = session.execute(
        text(
            "SELECT b.id AS billing_id, b.penalty AS stored_penalty, "
            "COALESCE(SUM(p.penalty), 0) AS linked_penalty, "
            "b.discount AS stored_discount, "
            "COALESCE(SUM(p.discount), 0) AS linked_discount, "
            "COUNT(pb.id) AS allocation_rows, "
            "MAX(plc.link_count) AS maximum_payment_allocation_rows, "
            "SUM(CASE WHEN plc.link_count > 1 THEN 1 ELSE 0 END) "
            "AS multi_billing_payment_links "
            "FROM property_billings b "
            "JOIN payment_billings pb ON pb.billing_id = b.id "
            "JOIN payments p ON p.id = pb.payment_id "
            "JOIN (SELECT payment_id, COUNT(*) AS link_count "
            "      FROM payment_billings GROUP BY payment_id) plc "
            "  ON plc.payment_id = p.id "
            "GROUP BY b.id, b.penalty, b.discount "
            "HAVING ABS(COALESCE(b.penalty, 0) "
            "       - COALESCE(SUM(p.penalty), 0)) > 0.005 "
            "OR ABS(COALESCE(b.discount, 0) "
            "       - COALESCE(SUM(p.discount), 0)) > 0.005 "
            "ORDER BY b.id"
        )
    ).mappings()
    candidates: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for row in rows:
        billing_id = int(row["billing_id"])
        if (
            int(row["allocation_rows"] or 0) < 1
            or int(row["maximum_payment_allocation_rows"] or 0) != 1
            or int(row["multi_billing_payment_links"] or 0) != 0
        ):
            blockers.append(
                {
                    "code": "AMBIGUOUS_BILLING_CHARGE_SUMMARY",
                    "record_type": "property_billings",
                    "record_id": billing_id,
                }
            )
            continue
        candidates.append(
            {
                "billing_id": billing_id,
                "old_penalty": _money(row["stored_penalty"]),
                "new_penalty": _money(row["linked_penalty"]),
                "old_discount": _money(row["stored_discount"]),
                "new_discount": _money(row["linked_discount"]),
            }
        )
    return candidates, blockers


def _payment_candidates(session: Any) -> tuple[list[dict[str, Any]], list[dict]]:
    rows = session.execute(
        text(
            "SELECT p.id AS payment_id, p.property_id, p.or_number, "
            "p.tax_year, p.date_paid, "
            "CASE WHEN NULLIF(TRIM(p.or_number), '') IS NULL "
            "THEN 1 ELSE 0 END AS missing_or_number, "
            "CASE WHEN p.tax_year IS NULL OR TRIM(p.tax_year) = '' "
            "THEN 1 ELSE 0 END AS missing_tax_year, "
            "CASE WHEN p.date_paid IS NULL THEN 1 ELSE 0 END "
            "AS missing_payment_date, "
            "COUNT(DISTINCT pb.id) AS allocation_rows, "
            "COUNT(DISTINCT pb.tax_year) AS allocation_year_count, "
            "MIN(pb.tax_year) AS allocation_year "
            "FROM payments p "
            "LEFT JOIN payment_billings pb ON pb.payment_id = p.id "
            "WHERE NULLIF(TRIM(p.or_number), '') IS NULL "
            "OR p.tax_year IS NULL OR TRIM(p.tax_year) = '' "
            "OR p.date_paid IS NULL "
            "GROUP BY p.id, p.property_id, p.or_number, p.tax_year, p.date_paid "
            "ORDER BY p.id"
        )
    ).mappings()
    candidates: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for row in rows:
        payment_id = int(row["payment_id"])
        deterministic = (
            not bool(row["missing_or_number"])
            and bool(row["missing_tax_year"])
            and not bool(row["missing_payment_date"])
            and int(row["allocation_rows"] or 0) >= 1
            and int(row["allocation_year_count"] or 0) == 1
            and row["allocation_year"] is not None
        )
        if not deterministic:
            blockers.append(
                {
                    "code": "AMBIGUOUS_INCOMPLETE_PAYMENT_IDENTITY",
                    "record_type": "payments",
                    "record_id": payment_id,
                }
            )
            continue
        new_tax_year = str(row["allocation_year"])
        collision_count = int(
            session.execute(
                text(
                    "SELECT COUNT(*) FROM payments other "
                    "WHERE other.id <> :payment_id "
                    "AND other.property_id = :property_id "
                    "AND UPPER(TRIM(other.or_number)) = "
                    "    UPPER(TRIM(:or_number)) "
                    "AND UPPER(TRIM(other.tax_year)) = "
                    "    UPPER(TRIM(:tax_year)) "
                    "AND DATE(other.date_paid) = DATE(:date_paid)"
                ),
                {
                    "payment_id": payment_id,
                    "property_id": row["property_id"],
                    "or_number": row["or_number"],
                    "tax_year": new_tax_year,
                    "date_paid": row["date_paid"],
                },
            ).scalar()
            or 0
        )
        if collision_count:
            blockers.append(
                {
                    "code": "PAYMENT_IDENTITY_COLLISION",
                    "record_type": "payments",
                    "record_id": payment_id,
                }
            )
            continue
        candidates.append(
            {
                "payment_id": payment_id,
                "old_tax_year": None,
                "new_tax_year": new_tax_year,
            }
        )
    return candidates, blockers


def _receipt_candidates(session: Any) -> list[dict[str, Any]]:
    return [
        {
            "receipt_id": int(row["receipt_id"]),
            "old_payment_id": int(row["payment_id"]),
            "new_payment_id": None,
        }
        for row in session.execute(
            text(
                "SELECT rh.id AS receipt_id, rh.payment_id "
                "FROM receipt_history rh "
                "LEFT JOIN payments p ON p.id = rh.payment_id "
                "WHERE rh.payment_id IS NOT NULL AND p.id IS NULL "
                "ORDER BY rh.id"
            )
        ).mappings()
    ]


def build_recovery_plan(session: Any) -> dict[str, Any]:
    billing, billing_blockers = _billing_candidates(session)
    payments, payment_blockers = _payment_candidates(session)
    receipts = _receipt_candidates(session)
    candidates = {
        "billing_summaries": billing,
        "payment_tax_years": payments,
        "receipt_references": receipts,
    }
    fingerprint = hashlib.sha256(
        json.dumps(candidates, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    change_count = sum(len(items) for items in candidates.values())
    blockers = billing_blockers + payment_blockers
    return {
        "ready": not blockers,
        "complete": not blockers and change_count == 0,
        "change_count": change_count,
        "candidates": candidates,
        "blockers": blockers,
        "fingerprint": fingerprint,
    }


def _backup_summary() -> tuple[dict, list[str]]:
    database = capture_configured_database()
    backup = database.get("backup", {})
    issues = assess_database_readiness(database)
    return (
        {
            "present": bool(backup.get("present")),
            "filename": backup.get("filename"),
            "status": backup.get("status"),
            "timestamp_utc": backup.get("timestamp_utc"),
            "age_hours": backup.get("age_hours"),
            "restore_verification_current": bool(
                backup.get("restore_verification_current")
            ),
            "checksum_present": bool(backup.get("checksum_present")),
        },
        issues,
    )


def capture_preflight() -> dict[str, Any]:
    with SessionLocal() as session:
        plan = build_recovery_plan(session)
        audit = verify_audit_chain(session)
        session.rollback()
    backup, backup_issues = _backup_summary()
    api_stopped = not _api_is_listening()
    issues = list(backup_issues)
    if audit["status"] != "verified":
        issues.append("The Phase 5 audit chain is not verified.")
    if not api_stopped:
        issues.append("The MTO API is still listening on port 8001.")
    if plan["blockers"]:
        issues.append(
            f"Ambiguous financial records require review: {len(plan['blockers'])}."
        )
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "api_stopped": api_stopped,
        "backup": backup,
        "backup_ready": not backup_issues,
        "audit_chain": audit["status"],
        "plan": plan,
        "issues": issues,
        "ready": (
            plan["ready"]
            and not plan["complete"]
            and api_stopped
            and not backup_issues
            and audit["status"] == "verified"
        ),
    }


def _create_fresh_backup() -> dict:
    success, _message = asyncio.run(
        run_hybrid_backup(
            user={"id": 0, "username": RECOVERY_USERNAME, "role": "admin"}
        )
    )
    if not success:
        raise RecoveryUtilityError(
            "Fresh hybrid backup failed; no financial recovery was attempted."
        )
    try:
        _require_backup_ready()
    except Exception as exc:
        raise RecoveryUtilityError(
            "Fresh hybrid backup did not pass protection and restore gates."
        ) from exc
    backup, issues = _backup_summary()
    if issues:
        raise RecoveryUtilityError(
            "Fresh hybrid backup attestation is incomplete; no write was attempted."
        )
    return backup


def _require_one(result: Any, record_type: str, record_id: int) -> None:
    if result.rowcount != 1:
        raise RecoveryUtilityError(
            f"{record_type} record {record_id} changed after preflight."
        )


def _apply_plan(session: Any, plan: Mapping[str, Any]) -> dict[str, int]:
    counts = {"billing_summaries": 0, "payment_tax_years": 0, "receipt_references": 0}
    for item in plan["candidates"]["billing_summaries"]:
        result = session.execute(
            text(
                "UPDATE property_billings SET penalty=:new_penalty, "
                "discount=:new_discount WHERE id=:record_id "
                "AND ABS(COALESCE(penalty, 0)-:old_penalty) <= 0.005 "
                "AND ABS(COALESCE(discount, 0)-:old_discount) <= 0.005"
            ),
            {
                "record_id": item["billing_id"],
                "old_penalty": item["old_penalty"],
                "new_penalty": item["new_penalty"],
                "old_discount": item["old_discount"],
                "new_discount": item["new_discount"],
            },
        )
        _require_one(result, "property_billings", item["billing_id"])
        append_audit_event(
            db_session=session,
            user_id=0,
            username=RECOVERY_USERNAME,
            table_name="property_billings",
            record_id=item["billing_id"],
            action="PHASE6_FINANCIAL_RECONCILIATION",
            old_values=canonical_snapshot(
                {
                    "penalty": item["old_penalty"],
                    "discount": item["old_discount"],
                }
            ),
            new_values=canonical_snapshot(
                {
                    "penalty": item["new_penalty"],
                    "discount": item["new_discount"],
                }
            ),
        )
        counts["billing_summaries"] += 1

    for item in plan["candidates"]["payment_tax_years"]:
        result = session.execute(
            text(
                "UPDATE payments SET tax_year=:new_tax_year "
                "WHERE id=:record_id "
                "AND (tax_year IS NULL OR TRIM(tax_year)='')"
            ),
            {
                "record_id": item["payment_id"],
                "new_tax_year": item["new_tax_year"],
            },
        )
        _require_one(result, "payments", item["payment_id"])
        append_audit_event(
            db_session=session,
            user_id=0,
            username=RECOVERY_USERNAME,
            table_name="payments",
            record_id=item["payment_id"],
            action="PHASE6_FINANCIAL_RECONCILIATION",
            old_values=canonical_snapshot({"tax_year": None}),
            new_values=canonical_snapshot({"tax_year": item["new_tax_year"]}),
        )
        counts["payment_tax_years"] += 1

    for item in plan["candidates"]["receipt_references"]:
        result = session.execute(
            text(
                "UPDATE receipt_history SET payment_id=NULL "
                "WHERE id=:record_id AND payment_id=:old_payment_id"
            ),
            {
                "record_id": item["receipt_id"],
                "old_payment_id": item["old_payment_id"],
            },
        )
        _require_one(result, "receipt_history", item["receipt_id"])
        append_audit_event(
            db_session=session,
            user_id=0,
            username=RECOVERY_USERNAME,
            table_name="receipt_history",
            record_id=item["receipt_id"],
            action="PHASE6_FINANCIAL_RECONCILIATION",
            old_values=canonical_snapshot({"payment_id": item["old_payment_id"]}),
            new_values=canonical_snapshot({"payment_id": None}),
        )
        counts["receipt_references"] += 1
    return counts


def apply_recovery() -> dict[str, Any]:
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

    with SessionLocal() as session:
        before_plan = build_recovery_plan(session)
        audit_before = verify_audit_chain(session)
        session.rollback()
    if before_plan["blockers"]:
        raise RecoveryUtilityError(
            "Recovery contains ambiguous records; no database change was attempted."
        )
    if before_plan["complete"]:
        raise RecoveryUtilityError("Phase 6 data recovery is already complete.")
    if audit_before["status"] != "verified":
        raise RecoveryUtilityError(
            "The Phase 5 audit chain is not verified; no database change was attempted."
        )

    incident_backup = _create_fresh_backup()
    if _api_is_listening():
        raise RecoveryUtilityError(
            "The MTO API restarted during backup; no database change was attempted."
        )

    with SessionLocal() as session:
        current_plan = build_recovery_plan(session)
        if (
            current_plan["blockers"]
            or current_plan["complete"]
            or current_plan["fingerprint"] != before_plan["fingerprint"]
        ):
            session.rollback()
            raise RecoveryUtilityError(
                "Financial evidence changed after backup; recovery was cancelled."
            )
        try:
            counts = _apply_plan(session, current_plan)
            session.commit()
        except Exception:
            session.rollback()
            raise

    with SessionLocal() as session:
        after_plan = build_recovery_plan(session)
        audit_after = verify_audit_chain(session, max_failures=1_000_000)
        session.rollback()
    if not after_plan["complete"]:
        raise RecoveryUtilityError(
            "Post-recovery financial verification failed; keep the API stopped."
        )
    if audit_after["status"] != "verified":
        raise RecoveryUtilityError(
            "Post-recovery audit verification failed; keep the API stopped."
        )

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "fresh_hybrid_backup": incident_backup,
        "plan_fingerprint": before_plan["fingerprint"],
        "changed_records": counts,
        "changed_record_count": sum(counts.values()),
        "financial_recovery_after": "complete",
        "audit_chain_after": audit_after["status"],
        "receipt_records_deleted": 0,
        "payment_amounts_modified": 0,
        "allocation_records_modified": 0,
    }


def write_report(path: Path, payload: Mapping[str, Any]) -> Path:
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_suffix(resolved.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(resolved)
    return resolved


def _print_preflight(report: Mapping[str, Any], destination: Path) -> None:
    plan = report["plan"]
    print("ORIGINAL PHASE 6 FINANCIAL RECOVERY PREFLIGHT")
    print(f"- MTO API stopped: {'PASS' if report['api_stopped'] else 'BLOCKED'}")
    print(f"- Audit chain: {str(report['audit_chain']).upper()}")
    print(f"- Backup readiness: {'PASS' if report['backup_ready'] else 'BLOCKED'}")
    print(f"- Billing summaries: {len(plan['candidates']['billing_summaries'])}")
    print(f"- Payment tax years: {len(plan['candidates']['payment_tax_years'])}")
    print(
        f"- Stale receipt references: {len(plan['candidates']['receipt_references'])}"
    )
    print(f"- Ambiguous records: {len(plan['blockers'])}")
    print(f"- Privacy-safe report: {destination}")
    if plan["complete"]:
        print("ORIGINAL PHASE 6 FINANCIAL DATA RECOVERY ALREADY COMPLETE")
    elif report["ready"]:
        print("ORIGINAL PHASE 6 FINANCIAL RECOVERY PREFLIGHT PASSED")
    else:
        for issue in report["issues"]:
            print(f"  - {issue}")
        print("ORIGINAL PHASE 6 FINANCIAL RECOVERY PREFLIGHT BLOCKED")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    destination = args.output or (
        DEFAULT_RECOVERY_REPORT if args.apply else DEFAULT_PREFLIGHT_REPORT
    )
    try:
        if args.preflight:
            report = capture_preflight()
            path = write_report(destination, report)
            _print_preflight(report, path)
            return 0 if report["ready"] or report["plan"]["complete"] else 2

        print("This operation repairs only deterministic Phase 6 legacy records.")
        print("It creates a fresh hybrid backup and appends sealed audit events.")
        typed = input(f"Type {CONFIRMATION} to continue: ").strip()
        if typed != CONFIRMATION:
            print("Recovery cancelled. No database change was made.")
            return 3
        report = apply_recovery()
        path = write_report(destination, report)
        print("ORIGINAL PHASE 6 FINANCIAL RECOVERY: PASS")
        print("- Fresh hybrid backup: PASS")
        print(f"- Changed records: {report['changed_record_count']}")
        print(
            "- Billing/payment/receipt changes: "
            f"{report['changed_records']['billing_summaries']}/"
            f"{report['changed_records']['payment_tax_years']}/"
            f"{report['changed_records']['receipt_references']}"
        )
        print("- Receipt records deleted: 0")
        print("- Payment amounts modified: 0")
        print("- Allocation records modified: 0")
        print(f"- Audit chain: {report['audit_chain_after'].upper()}")
        print(f"- Privacy-safe report: {path}")
        print("Keep the API stopped and activate the approved Phase 6 release.")
        return 0
    except RecoveryUtilityError as exc:
        print(f"ORIGINAL PHASE 6 FINANCIAL RECOVERY BLOCKED: {exc}")
        return 4
    except Exception as exc:
        print(
            "ORIGINAL PHASE 6 FINANCIAL RECOVERY FAILED: "
            f"{type(exc).__name__}. Keep the API stopped and preserve evidence."
        )
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
