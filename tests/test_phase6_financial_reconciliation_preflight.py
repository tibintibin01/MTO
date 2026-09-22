import json
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import (
    Payment,
    PaymentBilling,
    Property,
    PropertyAssessmentHistory,
    PropertyBilling,
    ReceiptHistory,
)
from scripts import phase6_financial_reconciliation_preflight as preflight


@pytest.fixture()
def reconciliation_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE system_migrations "
                "(id VARCHAR(255) PRIMARY KEY, applied_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO system_migrations (id, applied_at) "
                "VALUES (:id, CURRENT_TIMESTAMP)"
            ),
            {"id": preflight.PHASE3_MIGRATION_ID},
        )

    session = sessionmaker(bind=engine)()
    prop = Property(
        id=1,
        td_number="TD-PRIVATE-001",
        owner_name="PRIVATE OWNER",
        assessed_value=Decimal("5000.00"),
        duplicate_td_verified=False,
        archived=False,
    )
    payment = Payment(
        id=10,
        property_id=1,
        amount=Decimal("100.00"),
        penalty=Decimal("0.00"),
        discount=Decimal("0.00"),
        or_number="OR-PRIVATE-001",
        date_paid=datetime(2026, 1, 5),
        tax_year="2026",
    )
    billing = PropertyBilling(
        id=20,
        property_id=1,
        tax_year=2026,
        assessed_value=Decimal("5000.00"),
        penalty=Decimal("0.00"),
        discount=Decimal("0.00"),
        amount_paid=Decimal("100.00"),
    )
    allocation = PaymentBilling(
        id=30,
        payment_id=10,
        billing_id=20,
        tax_year=2026,
        amount_paid=Decimal("100.00"),
    )
    assessment = PropertyAssessmentHistory(
        id=40,
        property_id=1,
        td_number="TD-PRIVATE-001",
        assessed_value=Decimal("5000.00"),
        tax_year="2026",
    )
    receipt = ReceiptHistory(
        id=50,
        property_id=1,
        payment_id=10,
        td_number="TD-PRIVATE-001",
        owner_name="PRIVATE OWNER",
        or_number="OR-PRIVATE-001",
        tax_year="2026",
        amount=Decimal("100.00"),
        file_path="private.pdf",
        generated_at=datetime(2026, 1, 5),
    )
    session.add_all([prop, payment, billing, allocation, assessment, receipt])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_clean_snapshot_reconciles_aggregate_financial_totals(reconciliation_db):
    snapshot = preflight.collect_reconciliation_snapshot(reconciliation_db)

    assert snapshot["financial_invariants"] == {
        "duplicate_payment_identity": 0,
        "duplicate_payment_allocations": 0,
        "cross_property_allocations": 0,
        "unbalanced_payment_allocations": 0,
    }
    assert not any(int(value or 0) for value in snapshot["integrity_counts"].values())
    assert snapshot["financial_totals"] == {
        "payment_amount_total": "100.00",
        "allocation_amount_total": "100.00",
        "billing_amount_paid_total": "100.00",
        "payment_allocation_variance": "0.00",
        "billing_allocation_variance": "0.00",
    }
    assert snapshot["schema"]["phase3_migration_applied"] is True
    assert snapshot["schema"]["missing_foreign_keys"] == []


def test_missing_receipt_payment_foreign_key_is_explicit_review(reconciliation_db):
    snapshot = preflight.collect_reconciliation_snapshot(reconciliation_db)
    report = preflight.assemble_report(snapshot, audit={"status": "verified"})

    assert report["status"] == "REVIEW"
    assert report["blocking_finding_count"] == 0
    assert {item["code"] for item in report["findings"]} == {
        "RECEIPT_PAYMENT_FOREIGN_KEY_MISSING"
    }


def test_cross_property_and_receipt_mismatches_fail_closed(reconciliation_db):
    second_property = Property(
        id=2,
        td_number="TD-PRIVATE-002",
        owner_name="SECOND PRIVATE OWNER",
        assessed_value=Decimal("4000.00"),
        duplicate_td_verified=False,
        archived=False,
    )
    second_billing = PropertyBilling(
        id=21,
        property_id=2,
        tax_year=2026,
        assessed_value=Decimal("4000.00"),
        penalty=Decimal("0.00"),
        discount=Decimal("0.00"),
        amount_paid=Decimal("100.00"),
    )
    reconciliation_db.add_all([second_property, second_billing])
    reconciliation_db.query(PaymentBilling).filter_by(id=30).update(
        {"billing_id": 21, "tax_year": 2025}
    )
    reconciliation_db.query(ReceiptHistory).filter_by(id=50).update({"property_id": 2})
    reconciliation_db.commit()

    snapshot = preflight.collect_reconciliation_snapshot(reconciliation_db)
    report = preflight.assemble_report(snapshot, audit={"status": "verified"})
    codes = {item["code"] for item in report["findings"]}

    assert report["status"] == "FAIL"
    assert snapshot["financial_invariants"]["cross_property_allocations"] == 1
    assert snapshot["integrity_counts"]["allocation_tax_year_mismatch"] == 1
    assert snapshot["integrity_counts"]["receipt_cross_property"] == 1
    assert "CROSS_PROPERTY_ALLOCATIONS" in codes
    assert "ALLOCATION_TAX_YEAR_MISMATCH" in codes
    assert "RECEIPT_PAYMENT_PROPERTY_MISMATCH" in codes


def test_missing_financial_schema_fails_without_querying_absent_tables():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE properties (id INTEGER PRIMARY KEY)"))
    session = sessionmaker(bind=engine)()
    try:
        snapshot = preflight.collect_reconciliation_snapshot(session)
        report = preflight.assemble_report(snapshot, audit={"status": "verified"})
    finally:
        session.close()
        engine.dispose()

    assert report["status"] == "FAIL"
    assert report["schema"]["missing_tables"]
    assert "FINANCIAL_TABLE_MISSING" in {item["code"] for item in report["findings"]}


def test_report_is_aggregate_and_privacy_safe(reconciliation_db):
    snapshot = preflight.collect_reconciliation_snapshot(reconciliation_db)
    report = preflight.assemble_report(
        snapshot,
        audit={"status": "verified", "event_count": 10, "live_event_count": 2},
        backup={"present": True, "status": "CLOUD_ONLY"},
    )
    serialized = json.dumps(report)

    assert report["mode"] == "READ_ONLY"
    assert "PRIVATE OWNER" not in serialized
    assert "TD-PRIVATE-001" not in serialized
    assert "OR-PRIVATE-001" not in serialized
    assert "private.pdf" not in serialized


def test_backup_or_audit_readiness_blocks_closure(reconciliation_db):
    snapshot = preflight.collect_reconciliation_snapshot(reconciliation_db)
    report = preflight.assemble_report(
        snapshot,
        audit={"status": "failed", "failure_count": 1},
        readiness_issues=["Latest protected backup is stale."],
    )
    codes = {item["code"] for item in report["findings"]}

    assert report["status"] == "FAIL"
    assert "AUDIT_CHAIN_NOT_VERIFIED" in codes
    assert "BACKUP_OR_DATABASE_READINESS_BLOCKED" in codes


def test_main_writes_report_and_require_ready_blocks_review(
    monkeypatch, tmp_path, reconciliation_db
):
    snapshot = preflight.collect_reconciliation_snapshot(reconciliation_db)
    report = preflight.assemble_report(snapshot, audit={"status": "verified"})
    destination = tmp_path / "phase6.json"
    monkeypatch.setattr(preflight, "capture_configured_preflight", lambda: report)

    exit_code = preflight.main(["--require-ready", "--output", str(destination)])

    assert exit_code == 3
    assert json.loads(destination.read_text(encoding="utf-8"))["status"] == "REVIEW"
    assert not destination.with_suffix(".json.tmp").exists()
