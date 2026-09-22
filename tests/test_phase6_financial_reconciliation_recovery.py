from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import (
    Payment,
    PaymentBilling,
    Property,
    PropertyBilling,
    ReceiptHistory,
)
from scripts import phase6_financial_reconciliation_recovery as recovery


@pytest.fixture()
def recovery_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    prop = Property(
        id=1,
        td_number="TD-PRIVATE",
        owner_name="PRIVATE OWNER",
        assessed_value=Decimal("1000.00"),
        duplicate_td_verified=False,
        archived=False,
    )
    billing = PropertyBilling(
        id=20,
        property_id=1,
        tax_year=2026,
        assessed_value=Decimal("1000.00"),
        penalty=Decimal("0.00"),
        discount=Decimal("0.00"),
        amount_paid=Decimal("100.00"),
    )
    payment = Payment(
        id=10,
        property_id=1,
        amount=Decimal("100.00"),
        penalty=Decimal("5.00"),
        discount=Decimal("0.00"),
        or_number="PRIVATE-OR",
        tax_year=None,
        date_paid=datetime(2026, 1, 5),
    )
    allocation = PaymentBilling(
        id=30,
        payment_id=10,
        billing_id=20,
        tax_year=2026,
        amount_paid=Decimal("100.00"),
    )
    orphan_receipt = ReceiptHistory(
        id=50,
        property_id=1,
        payment_id=999,
        or_number="PRESERVED-OR",
        amount=Decimal("0.00"),
        file_path="preserved.pdf",
        generated_at=datetime(2026, 1, 6),
    )
    session.add_all([prop, billing, payment, allocation, orphan_receipt])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_plan_accepts_only_deterministic_phase6_repairs(recovery_db):
    plan = recovery.build_recovery_plan(recovery_db)

    assert plan["ready"] is True
    assert plan["complete"] is False
    assert plan["change_count"] == 3
    assert plan["blockers"] == []
    assert plan["candidates"]["billing_summaries"] == [
        {
            "billing_id": 20,
            "old_penalty": "0.00",
            "new_penalty": "5.00",
            "old_discount": "0.00",
            "new_discount": "0.00",
        }
    ]
    assert plan["candidates"]["payment_tax_years"] == [
        {"payment_id": 10, "old_tax_year": None, "new_tax_year": "2026"}
    ]
    assert plan["candidates"]["receipt_references"] == [
        {"receipt_id": 50, "old_payment_id": 999, "new_payment_id": None}
    ]


def test_apply_plan_preserves_money_allocations_and_receipt(monkeypatch, recovery_db):
    plan = recovery.build_recovery_plan(recovery_db)
    audit_calls = []
    monkeypatch.setattr(
        recovery,
        "append_audit_event",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    counts = recovery._apply_plan(recovery_db, plan)
    recovery_db.commit()

    assert counts == {
        "billing_summaries": 1,
        "payment_tax_years": 1,
        "receipt_references": 1,
    }
    assert recovery_db.get(PropertyBilling, 20).penalty == Decimal("5.00")
    assert recovery_db.get(Payment, 10).amount == Decimal("100.00")
    assert recovery_db.get(Payment, 10).tax_year == "2026"
    assert recovery_db.get(PaymentBilling, 30).amount_paid == Decimal("100.00")
    assert recovery_db.get(ReceiptHistory, 50).payment_id is None
    assert recovery_db.get(ReceiptHistory, 50).or_number == "PRESERVED-OR"
    assert len(audit_calls) == 3
    assert recovery.build_recovery_plan(recovery_db)["complete"] is True


def test_ambiguous_multiple_allocation_years_block_payment_recovery(recovery_db):
    second_billing = PropertyBilling(
        id=21,
        property_id=1,
        tax_year=2025,
        assessed_value=Decimal("1000.00"),
        penalty=Decimal("0.00"),
        discount=Decimal("0.00"),
        amount_paid=Decimal("10.00"),
    )
    second_allocation = PaymentBilling(
        id=31,
        payment_id=10,
        billing_id=21,
        tax_year=2025,
        amount_paid=Decimal("10.00"),
    )
    recovery_db.add_all([second_billing, second_allocation])
    recovery_db.commit()

    plan = recovery.build_recovery_plan(recovery_db)

    assert plan["ready"] is False
    assert {item["code"] for item in plan["blockers"]} >= {
        "AMBIGUOUS_INCOMPLETE_PAYMENT_IDENTITY",
        "AMBIGUOUS_BILLING_CHARGE_SUMMARY",
    }


def test_plan_fingerprint_changes_with_evidence(recovery_db):
    before = recovery.build_recovery_plan(recovery_db)
    recovery_db.get(PropertyBilling, 20).penalty = Decimal("1.00")
    recovery_db.commit()
    after = recovery.build_recovery_plan(recovery_db)

    assert before["fingerprint"] != after["fingerprint"]
