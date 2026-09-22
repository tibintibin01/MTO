"""Read-only Original Phase 6 financial reconciliation and integrity preflight."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PHASE3_MIGRATION_ID = "phase3_financial_transaction_safety_v1"
REQUIRED_TABLES = {
    "properties",
    "payments",
    "property_billings",
    "payment_billings",
    "property_assessment_history",
    "receipt_history",
    "system_migrations",
}
REQUIRED_COLUMNS = {
    "properties": {
        "id",
        "td_number",
        "deleted_at",
        "previous_property_id",
        "duplicate_td_verified",
        "duplicate_td_reason",
        "duplicate_td_reference",
        "duplicate_td_approved_by",
        "duplicate_td_approved_at",
    },
    "payments": {
        "id",
        "property_id",
        "amount",
        "penalty",
        "discount",
        "or_number",
        "tax_year",
        "date_paid",
    },
    "property_billings": {
        "id",
        "property_id",
        "tax_year",
        "assessed_value",
        "penalty",
        "discount",
        "amount_paid",
    },
    "payment_billings": {
        "id",
        "payment_id",
        "billing_id",
        "tax_year",
        "amount_paid",
    },
    "property_assessment_history": {"id", "property_id"},
    "receipt_history": {"id", "property_id", "payment_id", "amount"},
    "system_migrations": {"id"},
}
REQUIRED_UNIQUE_INDEXES = {
    ("payments", ("property_id", "or_number", "tax_year", "date_paid")),
    ("property_billings", ("property_id", "tax_year")),
    ("payment_billings", ("payment_id", "billing_id")),
}
REQUIRED_FOREIGN_KEYS = {
    ("payments", ("property_id",), "properties", ("id",)),
    ("property_billings", ("property_id",), "properties", ("id",)),
    ("payment_billings", ("payment_id",), "payments", ("id",)),
    ("payment_billings", ("billing_id",), "property_billings", ("id",)),
    ("receipt_history", ("property_id",), "properties", ("id",)),
    (
        "property_assessment_history",
        ("property_id",),
        "properties",
        ("id",),
    ),
}
MONEY_COLUMNS = {
    "payments": {"amount", "penalty", "discount"},
    "property_billings": {
        "assessed_value",
        "penalty",
        "discount",
        "amount_paid",
    },
    "payment_billings": {"amount_paid"},
    "receipt_history": {"amount"},
}

COUNT_CHECKS = {
    "orphan_payments": (
        {"payments", "properties"},
        "SELECT COUNT(*) FROM payments p "
        "LEFT JOIN properties prop ON prop.id = p.property_id "
        "WHERE prop.id IS NULL",
    ),
    "orphan_billings": (
        {"property_billings", "properties"},
        "SELECT COUNT(*) FROM property_billings b "
        "LEFT JOIN properties prop ON prop.id = b.property_id "
        "WHERE prop.id IS NULL",
    ),
    "orphan_allocations_payment": (
        {"payment_billings", "payments"},
        "SELECT COUNT(*) FROM payment_billings pb "
        "LEFT JOIN payments p ON p.id = pb.payment_id WHERE p.id IS NULL",
    ),
    "orphan_allocations_billing": (
        {"payment_billings", "property_billings"},
        "SELECT COUNT(*) FROM payment_billings pb "
        "LEFT JOIN property_billings b ON b.id = pb.billing_id WHERE b.id IS NULL",
    ),
    "allocation_tax_year_mismatch": (
        {"payment_billings", "property_billings"},
        "SELECT COUNT(*) FROM payment_billings pb "
        "JOIN property_billings b ON b.id = pb.billing_id "
        "WHERE pb.tax_year <> b.tax_year",
    ),
    "duplicate_billing_identity": (
        {"property_billings"},
        "SELECT COUNT(*) FROM ("
        " SELECT property_id, tax_year FROM property_billings"
        " GROUP BY property_id, tax_year HAVING COUNT(*) > 1"
        ") duplicate_billings",
    ),
    "invalid_payment_amount": (
        {"payments"},
        "SELECT COUNT(*) FROM payments "
        "WHERE amount <= 0 OR COALESCE(penalty, 0) < 0 "
        "OR COALESCE(discount, 0) < 0",
    ),
    "invalid_allocation_amount": (
        {"payment_billings"},
        "SELECT COUNT(*) FROM payment_billings WHERE amount_paid <= 0",
    ),
    "invalid_billing_amount": (
        {"property_billings"},
        "SELECT COUNT(*) FROM property_billings "
        "WHERE assessed_value < 0 OR penalty < 0 OR discount < 0 OR amount_paid < 0",
    ),
    "billing_paid_mismatch": (
        {"property_billings", "payment_billings"},
        "SELECT COUNT(*) FROM ("
        " SELECT b.id FROM property_billings b"
        " LEFT JOIN payment_billings pb ON pb.billing_id = b.id"
        " GROUP BY b.id, b.amount_paid"
        " HAVING ABS(COALESCE(b.amount_paid, 0)"
        " - COALESCE(SUM(pb.amount_paid), 0)) > 0.005"
        ") mismatched_billings",
    ),
    "billing_charge_summary_mismatch": (
        {"property_billings", "payment_billings", "payments"},
        "SELECT COUNT(*) FROM ("
        " SELECT b.id FROM property_billings b"
        " JOIN payment_billings pb ON pb.billing_id = b.id"
        " JOIN payments p ON p.id = pb.payment_id"
        " GROUP BY b.id, b.penalty, b.discount"
        " HAVING ABS(COALESCE(b.penalty, 0)"
        " - COALESCE(SUM(p.penalty), 0)) > 0.005"
        " OR ABS(COALESCE(b.discount, 0)"
        " - COALESCE(SUM(p.discount), 0)) > 0.005"
        ") mismatched_charges",
    ),
    "receipt_missing_payment": (
        {"receipt_history", "payments"},
        "SELECT COUNT(*) FROM receipt_history rh "
        "LEFT JOIN payments p ON p.id = rh.payment_id "
        "WHERE rh.payment_id IS NOT NULL AND p.id IS NULL",
    ),
    "receipt_cross_property": (
        {"receipt_history", "payments"},
        "SELECT COUNT(*) FROM receipt_history rh "
        "JOIN payments p ON p.id = rh.payment_id "
        "WHERE rh.property_id <> p.property_id",
    ),
    "assessment_history_missing_property": (
        {"property_assessment_history", "properties"},
        "SELECT COUNT(*) FROM property_assessment_history h "
        "LEFT JOIN properties p ON p.id = h.property_id WHERE p.id IS NULL",
    ),
    "self_referential_property_lineage": (
        {"properties"},
        "SELECT COUNT(*) FROM properties "
        "WHERE previous_property_id IS NOT NULL AND previous_property_id = id",
    ),
    "incomplete_payment_identity": (
        {"payments"},
        "SELECT COUNT(*) FROM payments "
        "WHERE or_number IS NULL OR TRIM(or_number) = '' "
        "OR tax_year IS NULL OR TRIM(tax_year) = '' OR date_paid IS NULL",
    ),
}


def _decimal_text(value: Any) -> str:
    return format(Decimal(str(value or 0)).quantize(Decimal("0.01")), "f")


def _scalar(session: Any, statement: str) -> int:
    return int(session.execute(text(statement)).scalar() or 0)


def _unique_index_signatures(inspector: Any, table_name: str) -> set[tuple[str, ...]]:
    signatures = {
        tuple(item.get("column_names") or ())
        for item in inspector.get_indexes(table_name)
        if item.get("unique") and item.get("column_names")
    }
    signatures.update(
        tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints(table_name)
        if item.get("column_names")
    )
    return signatures


def _foreign_key_signatures(inspector: Any, table_name: str) -> set[tuple]:
    return {
        (
            table_name,
            tuple(item.get("constrained_columns") or ()),
            str(item.get("referred_table") or ""),
            tuple(item.get("referred_columns") or ()),
        )
        for item in inspector.get_foreign_keys(table_name)
    }


def capture_schema_status(session: Any) -> dict[str, Any]:
    inspector = inspect(session.get_bind())
    tables = set(inspector.get_table_names())
    missing_tables = sorted(REQUIRED_TABLES - tables)
    table_columns = {
        table_name: {item["name"] for item in inspector.get_columns(table_name)}
        for table_name in tables & set(REQUIRED_COLUMNS)
    }
    missing_columns = [
        f"{table_name}.{column_name}"
        for table_name, required in sorted(REQUIRED_COLUMNS.items())
        if table_name in tables
        for column_name in sorted(required - table_columns.get(table_name, set()))
    ]
    missing_indexes = []
    for table_name, columns in sorted(REQUIRED_UNIQUE_INDEXES):
        if table_name not in tables or columns not in _unique_index_signatures(
            inspector, table_name
        ):
            missing_indexes.append(f"{table_name}.({','.join(columns)})")

    actual_foreign_keys: set[tuple] = set()
    for table_name in tables & {item[0] for item in REQUIRED_FOREIGN_KEYS}:
        actual_foreign_keys.update(_foreign_key_signatures(inspector, table_name))
    missing_foreign_keys = [
        f"{table}.{','.join(columns)}->{referred}.{','.join(referred_columns)}"
        for table, columns, referred, referred_columns in sorted(
            REQUIRED_FOREIGN_KEYS - actual_foreign_keys
        )
    ]

    receipt_payment_fk_present = False
    if "receipt_history" in tables:
        receipt_payment_fk_present = any(
            tuple(item.get("constrained_columns") or ()) == ("payment_id",)
            and item.get("referred_table") == "payments"
            and tuple(item.get("referred_columns") or ()) == ("id",)
            and str((item.get("options") or {}).get("ondelete") or "").upper()
            == "SET NULL"
            for item in inspector.get_foreign_keys("receipt_history")
        )

    missing_money_columns = []
    non_decimal_money_columns = []
    for table_name, required_columns in sorted(MONEY_COLUMNS.items()):
        if table_name not in tables:
            missing_money_columns.extend(
                f"{table_name}.{column}" for column in sorted(required_columns)
            )
            continue
        columns = {item["name"]: item for item in inspector.get_columns(table_name)}
        for column_name in sorted(required_columns):
            if column_name not in columns:
                missing_money_columns.append(f"{table_name}.{column_name}")
                continue
            type_name = str(columns[column_name]["type"]).upper()
            if "DECIMAL" not in type_name and "NUMERIC" not in type_name:
                non_decimal_money_columns.append(f"{table_name}.{column_name}")

    migration_applied = False
    if "system_migrations" in tables and "id" in table_columns.get(
        "system_migrations", set()
    ):
        migration_applied = bool(
            session.execute(
                text("SELECT COUNT(*) FROM system_migrations WHERE id = :id"),
                {"id": PHASE3_MIGRATION_ID},
            ).scalar()
        )

    return {
        "tables_present": sorted(tables & REQUIRED_TABLES),
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "missing_indexes": missing_indexes,
        "missing_foreign_keys": missing_foreign_keys,
        "missing_money_columns": missing_money_columns,
        "non_decimal_money_columns": non_decimal_money_columns,
        "receipt_payment_fk_present": receipt_payment_fk_present,
        "phase3_migration_applied": migration_applied,
    }


def _duplicate_td_snapshot(session: Any, tables: set[str]) -> dict[str, int]:
    if "properties" not in tables:
        return {
            "group_count": 0,
            "verified_group_count": 0,
            "unverified_group_count": 0,
        }
    inspector = inspect(session.get_bind())
    columns = {item["name"] for item in inspector.get_columns("properties")}
    required = {
        "td_number",
        "deleted_at",
        "duplicate_td_verified",
        "duplicate_td_reason",
        "duplicate_td_reference",
        "duplicate_td_approved_by",
        "duplicate_td_approved_at",
    }
    rows = (
        session.execute(
            text(
                "SELECT COUNT(*) AS member_count, "
                "SUM(CASE WHEN duplicate_td_verified = 1 "
                "AND NULLIF(TRIM(duplicate_td_reason), '') IS NOT NULL "
                "AND NULLIF(TRIM(duplicate_td_reference), '') IS NOT NULL "
                "AND NULLIF(TRIM(duplicate_td_approved_by), '') IS NOT NULL "
                "AND duplicate_td_approved_at IS NOT NULL THEN 1 ELSE 0 END) "
                "AS verified_count FROM properties "
                "WHERE deleted_at IS NULL GROUP BY UPPER(TRIM(td_number)) "
                "HAVING COUNT(*) > 1"
            )
        ).all()
        if required <= columns
        else []
    )
    group_count = len(rows)
    verified_count = sum(int(row[0] or 0) == int(row[1] or 0) for row in rows)
    return {
        "group_count": group_count,
        "verified_group_count": verified_count,
        "unverified_group_count": group_count - verified_count,
    }


def _financial_totals(
    session: Any, tables: set[str], invalid_tables: set[str]
) -> dict[str, str]:
    totals = {
        "payment_amount_total": "0.00",
        "allocation_amount_total": "0.00",
        "billing_amount_paid_total": "0.00",
        "payment_allocation_variance": "0.00",
        "billing_allocation_variance": "0.00",
    }
    if "payments" in tables and "payments" not in invalid_tables:
        totals["payment_amount_total"] = _decimal_text(
            session.execute(
                text("SELECT COALESCE(SUM(amount), 0) FROM payments")
            ).scalar()
        )
    if "payment_billings" in tables and "payment_billings" not in invalid_tables:
        totals["allocation_amount_total"] = _decimal_text(
            session.execute(
                text("SELECT COALESCE(SUM(amount_paid), 0) FROM payment_billings")
            ).scalar()
        )
    if "property_billings" in tables and "property_billings" not in invalid_tables:
        totals["billing_amount_paid_total"] = _decimal_text(
            session.execute(
                text("SELECT COALESCE(SUM(amount_paid), 0) FROM property_billings")
            ).scalar()
        )
    payment_total = Decimal(totals["payment_amount_total"])
    allocation_total = Decimal(totals["allocation_amount_total"])
    billing_total = Decimal(totals["billing_amount_paid_total"])
    totals["payment_allocation_variance"] = _decimal_text(
        payment_total - allocation_total
    )
    totals["billing_allocation_variance"] = _decimal_text(
        billing_total - allocation_total
    )
    return totals


def collect_reconciliation_snapshot(session: Any) -> dict[str, Any]:
    """Collect aggregate reconciliation evidence using SELECT statements only."""
    inspector = inspect(session.get_bind())
    tables = set(inspector.get_table_names())
    schema = capture_schema_status(session)
    invalid_tables = {
        item.split(".", 1)[0] for item in schema.get("missing_columns", [])
    }
    counts = {
        name: (
            _scalar(session, statement)
            if required <= tables and not (required & invalid_tables)
            else None
        )
        for name, (required, statement) in COUNT_CHECKS.items()
    }

    financial_invariants = {
        "duplicate_payment_identity": None,
        "duplicate_payment_allocations": None,
        "cross_property_allocations": None,
        "unbalanced_payment_allocations": None,
    }
    core_tables = {"payments", "property_billings", "payment_billings"}
    if core_tables <= tables and not (core_tables & invalid_tables):
        from backend.services.migration_service import financial_invariant_violations

        financial_invariants = financial_invariant_violations(session)

    return {
        "schema": schema,
        "financial_invariants": financial_invariants,
        "integrity_counts": counts,
        "financial_totals": _financial_totals(session, tables, invalid_tables),
        "duplicate_td": _duplicate_td_snapshot(session, tables),
    }


def _finding(
    code: str,
    detail: str,
    severity: str,
    *,
    blocking: bool,
    count: int | None = None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "code": code,
        "detail": detail,
        "severity": severity,
        "blocking": blocking,
    }
    if count is not None:
        finding["count"] = int(count)
    return finding


BLOCKING_INTEGRITY_CHECKS = {
    "orphan_payments": (
        "ORPHAN_PAYMENT_PROPERTY",
        "Payments reference a missing property.",
        "CRITICAL",
    ),
    "orphan_billings": (
        "ORPHAN_BILLING_PROPERTY",
        "Billing rows reference a missing property.",
        "CRITICAL",
    ),
    "orphan_allocations_payment": (
        "ORPHAN_ALLOCATION_PAYMENT",
        "Payment allocations reference a missing payment.",
        "CRITICAL",
    ),
    "orphan_allocations_billing": (
        "ORPHAN_ALLOCATION_BILLING",
        "Payment allocations reference a missing billing row.",
        "CRITICAL",
    ),
    "allocation_tax_year_mismatch": (
        "ALLOCATION_TAX_YEAR_MISMATCH",
        "Allocation tax years disagree with their billing rows.",
        "HIGH",
    ),
    "duplicate_billing_identity": (
        "DUPLICATE_BILLING_IDENTITY",
        "A property has duplicate billing rows for one tax year.",
        "CRITICAL",
    ),
    "invalid_payment_amount": (
        "INVALID_PAYMENT_AMOUNT",
        "Payments contain non-positive or negative monetary values.",
        "HIGH",
    ),
    "invalid_allocation_amount": (
        "INVALID_ALLOCATION_AMOUNT",
        "Payment allocations contain non-positive amounts.",
        "HIGH",
    ),
    "invalid_billing_amount": (
        "INVALID_BILLING_AMOUNT",
        "Billing rows contain negative monetary values.",
        "HIGH",
    ),
    "billing_paid_mismatch": (
        "BILLING_PAID_TOTAL_MISMATCH",
        "Billing paid totals disagree with their allocation totals.",
        "HIGH",
    ),
    "billing_charge_summary_mismatch": (
        "BILLING_CHARGE_SUMMARY_MISMATCH",
        "Billing penalty or discount summaries disagree with linked payments.",
        "HIGH",
    ),
    "receipt_missing_payment": (
        "RECEIPT_PAYMENT_MISSING",
        "Receipt history references a missing payment.",
        "HIGH",
    ),
    "receipt_cross_property": (
        "RECEIPT_PAYMENT_PROPERTY_MISMATCH",
        "Receipt history and its payment reference different properties.",
        "HIGH",
    ),
    "assessment_history_missing_property": (
        "ASSESSMENT_HISTORY_PROPERTY_MISSING",
        "Assessment history references a missing property.",
        "HIGH",
    ),
    "self_referential_property_lineage": (
        "SELF_REFERENTIAL_PROPERTY_LINEAGE",
        "A property names itself as its predecessor.",
        "HIGH",
    ),
}


def build_findings(
    snapshot: Mapping[str, Any],
    *,
    audit_status: str = "verified",
    readiness_issues: list[str] | None = None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    schema = snapshot.get("schema", {})
    for key, code, detail, severity in (
        (
            "missing_tables",
            "FINANCIAL_TABLE_MISSING",
            "Required tables are missing.",
            "CRITICAL",
        ),
        (
            "missing_columns",
            "FINANCIAL_COLUMN_MISSING",
            "Required financial columns are missing.",
            "CRITICAL",
        ),
        (
            "missing_indexes",
            "FINANCIAL_UNIQUE_INDEX_MISSING",
            "Required financial unique indexes are missing.",
            "HIGH",
        ),
        (
            "missing_foreign_keys",
            "FINANCIAL_FOREIGN_KEY_MISSING",
            "Required financial foreign keys are missing.",
            "HIGH",
        ),
        (
            "missing_money_columns",
            "FINANCIAL_MONEY_COLUMN_MISSING",
            "Required monetary columns are missing.",
            "CRITICAL",
        ),
        (
            "non_decimal_money_columns",
            "FINANCIAL_MONEY_TYPE_UNSAFE",
            "Monetary columns are not fixed-point numeric types.",
            "HIGH",
        ),
    ):
        values = list(schema.get(key) or [])
        if values:
            findings.append(
                _finding(
                    code,
                    f"{detail} Count: {len(values)}.",
                    severity,
                    blocking=True,
                    count=len(values),
                )
            )
    if not schema.get("phase3_migration_applied"):
        findings.append(
            _finding(
                "PHASE3_FINANCIAL_SCHEMA_INACTIVE",
                "The Phase 3 financial safety migration is not recorded.",
                "HIGH",
                blocking=True,
            )
        )
    if not schema.get("receipt_payment_fk_present"):
        findings.append(
            _finding(
                "RECEIPT_PAYMENT_FOREIGN_KEY_MISSING",
                "Receipt history payment identity is not protected by a database "
                "foreign key.",
                "MEDIUM",
                blocking=False,
            )
        )

    for name, count in (snapshot.get("financial_invariants") or {}).items():
        if count is None or int(count) == 0:
            continue
        findings.append(
            _finding(
                name.upper(),
                "A protected Phase 3 financial invariant is violated.",
                "CRITICAL",
                blocking=True,
                count=int(count),
            )
        )
    for name, (code, detail, severity) in BLOCKING_INTEGRITY_CHECKS.items():
        count = (snapshot.get("integrity_counts") or {}).get(name)
        if count is not None and int(count) > 0:
            findings.append(
                _finding(code, detail, severity, blocking=True, count=int(count))
            )

    incomplete_count = (snapshot.get("integrity_counts") or {}).get(
        "incomplete_payment_identity"
    )
    if incomplete_count is not None and int(incomplete_count) > 0:
        findings.append(
            _finding(
                "INCOMPLETE_PAYMENT_IDENTITY",
                "Payments are missing an OR number, tax year, or payment date.",
                "MEDIUM",
                blocking=False,
                count=int(incomplete_count),
            )
        )

    duplicate_td = snapshot.get("duplicate_td", {})
    unverified_groups = int(duplicate_td.get("unverified_group_count") or 0)
    if unverified_groups:
        findings.append(
            _finding(
                "UNVERIFIED_DUPLICATE_TD_GROUP",
                "Active duplicate-TD groups lack complete approval evidence.",
                "HIGH",
                blocking=True,
                count=unverified_groups,
            )
        )

    totals = snapshot.get("financial_totals", {})
    for key, code, detail in (
        (
            "payment_allocation_variance",
            "PAYMENT_ALLOCATION_AGGREGATE_VARIANCE",
            "Payment and allocation aggregate totals do not reconcile.",
        ),
        (
            "billing_allocation_variance",
            "BILLING_ALLOCATION_AGGREGATE_VARIANCE",
            "Billing paid and allocation aggregate totals do not reconcile.",
        ),
    ):
        if abs(Decimal(str(totals.get(key) or 0))) > Decimal("0.005"):
            findings.append(_finding(code, detail, "HIGH", blocking=True))

    if str(audit_status).lower() != "verified":
        findings.append(
            _finding(
                "AUDIT_CHAIN_NOT_VERIFIED",
                "The Phase 5 audit chain is not verified.",
                "HIGH",
                blocking=True,
            )
        )
    for issue in readiness_issues or []:
        findings.append(
            _finding(
                "BACKUP_OR_DATABASE_READINESS_BLOCKED",
                str(issue),
                "HIGH",
                blocking=True,
            )
        )
    return findings


def assemble_report(
    snapshot: Mapping[str, Any],
    *,
    audit: Mapping[str, Any] | None = None,
    backup: Mapping[str, Any] | None = None,
    readiness_issues: list[str] | None = None,
) -> dict[str, Any]:
    audit_payload = dict(audit or {"status": "verified"})
    findings = build_findings(
        snapshot,
        audit_status=str(audit_payload.get("status") or "unknown"),
        readiness_issues=readiness_issues,
    )
    blocking_count = sum(bool(item["blocking"]) for item in findings)
    status = "FAIL" if blocking_count else ("REVIEW" if findings else "PASS")
    return {
        "format_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "privacy": "Aggregate counts and totals only; no taxpayer or credential data.",
        "mode": "READ_ONLY",
        "status": status,
        "blocking_finding_count": blocking_count,
        "review_finding_count": len(findings) - blocking_count,
        "schema": snapshot.get("schema", {}),
        "financial_invariants": snapshot.get("financial_invariants", {}),
        "integrity_counts": snapshot.get("integrity_counts", {}),
        "financial_totals": snapshot.get("financial_totals", {}),
        "duplicate_td": snapshot.get("duplicate_td", {}),
        "audit": {
            "status": audit_payload.get("status"),
            "event_count": int(audit_payload.get("event_count") or 0),
            "live_event_count": int(audit_payload.get("live_event_count") or 0),
            "failure_count": int(audit_payload.get("failure_count") or 0),
        },
        "backup": dict(backup or {}),
        "findings": findings,
    }


def _begin_read_only_transaction(session: Any) -> None:
    dialect = session.get_bind().dialect.name.lower()
    if dialect in {"mysql", "mariadb", "postgresql"}:
        session.execute(text("SET TRANSACTION READ ONLY"))


def capture_configured_preflight() -> dict[str, Any]:
    from backend.database import SessionLocal
    from scripts.phase5_audit_observability_preflight import (
        capture_preflight as capture_phase5_preflight,
    )

    session = SessionLocal()
    try:
        _begin_read_only_transaction(session)
        snapshot = collect_reconciliation_snapshot(session)
    finally:
        session.rollback()
        session.close()

    phase5 = capture_phase5_preflight()
    return assemble_report(
        snapshot,
        audit=phase5.get("audit", {}),
        backup=phase5.get("backup", {}),
        readiness_issues=list(phase5.get("readiness_issues") or []),
    )


def write_report(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Require PASS rather than permitting a non-blocking REVIEW result.",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = capture_configured_preflight()
    if args.output:
        write_report(args.output.resolve(), report)

    schema = report["schema"]
    schema_ready = not any(
        schema.get(key)
        for key in (
            "missing_tables",
            "missing_columns",
            "missing_indexes",
            "missing_foreign_keys",
            "missing_money_columns",
            "non_decimal_money_columns",
        )
    ) and bool(schema.get("phase3_migration_applied"))
    print("ORIGINAL PHASE 6 FINANCIAL RECONCILIATION PREFLIGHT")
    print("- Mode: READ ONLY")
    print(f"- Schema: {'PASS' if schema_ready else 'FAIL'}")
    print(
        "- Phase 3 financial invariants: "
        + (
            "PASS"
            if not any(
                int(value or 0)
                for value in report["financial_invariants"].values()
                if value is not None
            )
            else "FAIL"
        )
    )
    print(
        "- Billing/allocation reconciliation: "
        + (
            "PASS"
            if not any(
                int((report["integrity_counts"] or {}).get(name) or 0)
                for name in (
                    "billing_paid_mismatch",
                    "billing_charge_summary_mismatch",
                )
            )
            else "FAIL"
        )
    )
    print(f"- Audit chain: {str(report['audit']['status']).upper()}")
    print(
        "- Backup readiness: "
        + (
            "PASS"
            if report["backup"]
            and not any(
                item["code"] == "BACKUP_OR_DATABASE_READINESS_BLOCKED"
                for item in report["findings"]
            )
            else "BLOCKED"
        )
    )
    print(f"- Gate status: {report['status']}")
    print(f"- Blocking findings: {report['blocking_finding_count']}")
    print(f"- Review findings: {report['review_finding_count']}")
    if args.output:
        print(f"- Privacy-safe report: {args.output.resolve()}")
    for finding in report["findings"]:
        print(f"  - [{finding['severity']}] {finding['code']}: " f"{finding['detail']}")

    if report["status"] == "FAIL":
        print("ORIGINAL PHASE 6 PREFLIGHT BLOCKED")
        return 2
    if report["status"] == "REVIEW":
        if args.require_ready:
            print("ORIGINAL PHASE 6 PREFLIGHT BLOCKED: review findings remain.")
            return 3
        print("ORIGINAL PHASE 6 PREFLIGHT REQUIRES REVIEW")
        return 0
    print("ORIGINAL PHASE 6 FINANCIAL RECONCILIATION PREFLIGHT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
