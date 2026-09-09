"""Read-only Phase 3 financial integrity and schema preflight."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MIGRATION_ID = "phase3_financial_transaction_safety_v1"
REQUIRED_IDEMPOTENCY_COLUMNS = {
    "key",
    "user_id",
    "request_hash",
    "method",
    "path",
    "state",
    "status_code",
    "response_body",
    "created_at",
    "updated_at",
    "expires_at",
}
REQUIRED_INDEXES = {
    ("payment_billings", "uq_payment_billings_payment_billing"),
    ("payments", "uq_payments_property_or_tax_year_text"),
    ("idempotency_keys", "ix_idempotency_keys_user_id"),
    ("idempotency_keys", "ix_idempotency_keys_state"),
}


def _index_names(inspector, table_name):
    names = {
        item.get("name")
        for item in inspector.get_indexes(table_name)
        if item.get("name")
    }
    names.update(
        item.get("name")
        for item in inspector.get_unique_constraints(table_name)
        if item.get("name")
    )
    return names


def capture_preflight():
    from backend.database import SessionLocal
    from backend.services.migration_service import financial_invariant_violations

    with SessionLocal() as session:
        connection = session.connection()
        inspector = inspect(connection)
        violations = financial_invariant_violations(session)
        has_idempotency_table = inspector.has_table("idempotency_keys")
        columns = (
            {item["name"] for item in inspector.get_columns("idempotency_keys")}
            if has_idempotency_table
            else set()
        )
        missing_indexes = []
        for table_name, index_name in sorted(REQUIRED_INDEXES):
            if not inspector.has_table(table_name) or index_name not in _index_names(
                inspector, table_name
            ):
                missing_indexes.append(f"{table_name}.{index_name}")
        migration_applied = bool(
            session.execute(
                text("SELECT COUNT(*) FROM system_migrations WHERE id = :id"),
                {"id": MIGRATION_ID},
            ).scalar()
        )
        session.rollback()

    schema_active = (
        migration_applied
        and has_idempotency_table
        and not (REQUIRED_IDEMPOTENCY_COLUMNS - columns)
        and not missing_indexes
    )
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "migration_id": MIGRATION_ID,
        "financial_invariants": violations,
        "financial_invariants_pass": not any(violations.values()),
        "schema": {
            "migration_applied": migration_applied,
            "idempotency_table": has_idempotency_table,
            "missing_idempotency_columns": sorted(
                REQUIRED_IDEMPOTENCY_COLUMNS - columns
            ),
            "missing_indexes": missing_indexes,
            "active": schema_active,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-active", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = capture_preflight()
    if args.output:
        destination = args.output.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    print("PHASE 3 FINANCIAL SAFETY PREFLIGHT")
    for name, count in report["financial_invariants"].items():
        print(f"- {name}: {count}")
    print(
        "- Phase 3 schema: "
        + ("ACTIVE" if report["schema"]["active"] else "NOT YET ACTIVE")
    )
    if args.output:
        print(f"- Privacy-safe report: {args.output.resolve()}")

    if not report["financial_invariants_pass"]:
        print("PHASE 3 PREFLIGHT BLOCKED: repair financial invariants first.")
        return 2
    if args.require_active and not report["schema"]["active"]:
        print("PHASE 3 PREFLIGHT BLOCKED: required schema is not active.")
        return 3
    print("PHASE 3 PREFLIGHT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
