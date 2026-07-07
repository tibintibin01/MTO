# -*- coding: utf-8 -*-
import pytest
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Payment, PaymentBilling, Property, PropertyBilling
from backend.services.billing_service import (
    calculate_penalty,
    get_compliant_accounts,
    get_compliant_summary_by_barangay,
    get_reconciliation_diagnostics,
    get_reconciliation_metrics,
    get_rpt_receivables_summary,
    get_total_due,
    repair_billing_assessed_value_snapshots,
    repair_payment_billing_allocations,
    sync_existing_billing_assessed_value,
)
from backend.services.property_service import get_receivables_by_barangay
from backend.services.property_service import _sync_financial_records
from backend.services.payment_service import get_unified_payment_history


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(eng)
    eng.dispose()

def test_calculate_penalty_basic():
    """Test standard 2% monthly penalty logic."""
    # Scenario: 10,000 principal, 5 months late (10% total penalty)
    principal = 10000.0
    months_late = 5
    expected_penalty = 10000.0 * 0.02 * 5
    
    penalty = calculate_penalty(principal, months_late)
    assert penalty == expected_penalty
    assert penalty == 1000.0

def test_calculate_penalty_cap():
    """Test the maximum penalty cap (usually 72% in many PH local tax codes, but let's check system logic)."""
    # If the system implements a cap, we test it here. 
    # For now, let's assume it scales.
    principal = 1000.0
    months_late = 40 # 80% penalty
    penalty = calculate_penalty(principal, months_late)
    assert penalty == 800.0


def test_receivables_by_barangay_collections_use_billing_year_allocations(db):
    prop = Property(
        td_number="06-0012-TEST1",
        owner_name="Timing Test",
        barangay="DINADIAWAN",
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
    )
    db.add(prop)
    db.flush()

    billing_2026 = PropertyBilling(
        property_id=prop.id,
        tax_year=2026,
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
        amount_paid=0,
    )
    billing_2027 = PropertyBilling(
        property_id=prop.id,
        tax_year=2027,
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
        amount_paid=0,
    )
    db.add_all([billing_2026, billing_2027])
    db.flush()

    future_year_prepayment = Payment(
        property_id=prop.id,
        amount=700.0,
        penalty=0,
        discount=0,
        or_number="PREPAY",
        date_paid=datetime(2026, 5, 10),
        tax_year="2027",
    )
    late_posted_selected_year = Payment(
        property_id=prop.id,
        amount=500.0,
        penalty=0,
        discount=0,
        or_number="LATE2026",
        date_paid=datetime(2027, 1, 10),
        tax_year="2026",
    )
    db.add_all([future_year_prepayment, late_posted_selected_year])
    db.flush()

    db.add_all([
        PaymentBilling(
            payment_id=future_year_prepayment.id,
            billing_id=billing_2027.id,
            tax_year=2027,
            amount_paid=700.0,
        ),
        PaymentBilling(
            payment_id=late_posted_selected_year.id,
            billing_id=billing_2026.id,
            tax_year=2026,
            amount_paid=500.0,
        ),
    ])
    db.commit()

    rows = get_receivables_by_barangay(report_year=2026, db_session=db)
    row = next(r for r in rows if r[0] == "DINADIAWAN")

    assert row[2] == pytest.approx(2_000.0)
    assert row[5] == pytest.approx(500.0)
    assert row[6] == pytest.approx(1_500.0)

def test_get_total_due_logic(mock_db_session):
    """Test the orchestration of total due calculation including basic, SEF, and penalties."""
    # Mock property data
    mock_prop = Property(
        id=1, td_number="TD-1", owner_name="Owner", assessed_value=100000.0,
        deleted_at=None
    )
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_prop
    
    from unittest.mock import patch
    with patch("backend.services.billing_service.get_property_billing_history") as mock_hist:
        mock_hist.return_value = [
            [
                "2023", 100000.0, 1000.0, 1000.0, 0.0, 2000.0, 0.0, 2000.0, "Pending", None
            ]
        ]
        total_data = get_total_due(1, db_session=mock_db_session) # Property ID 1
    
    assert total_data["assessed_value"] == 100000.0
    assert total_data["basic"] == 1000.0
    assert total_data["sef"] == 1000.0
    assert total_data["total_due"] >= 2000.0


def _property_with_billing(db, td, barangay, paid=2_000.0):
    prop = Property(
        td_number=td,
        owner_name=f"Owner {td}",
        barangay=barangay,
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
    )
    db.add(prop)
    db.flush()
    db.add(
        PropertyBilling(
            property_id=prop.id,
            tax_year="2024",
            assessed_value=100_000.0,
            penalty=0,
            discount=0,
            amount_paid=paid,
        )
    )
    db.flush()
    return prop


def test_compliant_summary_excludes_unassigned_barangay_rows(db):
    _property_with_billing(db, "TD-REAL", "NORTH POBLACION")
    _property_with_billing(db, "TD-NULL", None)
    _property_with_billing(db, "TD-BLANK", "  ")
    _property_with_billing(db, "TD-UNSPECIFIED", "UNSPECIFIED")
    db.commit()

    summary = get_compliant_summary_by_barangay(db_session=db)

    assert [row["barangay"] for row in summary] == ["NORTH POBLACION"]
    assert summary[0]["total_properties"] == 1
    assert summary[0]["compliant_count"] == 1


def test_compliance_through_year_ignores_later_unpaid_billing(db):
    prop = Property(
        td_number="TD-AS-OF",
        owner_name="Owner As Of",
        barangay="BUENAVISTA",
        assessed_value=100_000.0,
        effectivity_date="2025-01-01",
        penalty=0,
        discount=0,
    )
    db.add(prop)
    db.flush()
    db.add_all([
        PropertyBilling(
            property_id=prop.id,
            tax_year=2025,
            assessed_value=100_000.0,
            penalty=0,
            discount=0,
            amount_paid=2_000.0,
        ),
        PropertyBilling(
            property_id=prop.id,
            tax_year=2026,
            assessed_value=100_000.0,
            penalty=0,
            discount=0,
            amount_paid=0,
        ),
    ])
    db.commit()

    through_2025 = get_compliant_accounts(as_of_year=2025, db_session=db)
    through_2026 = get_compliant_accounts(as_of_year=2026, db_session=db)
    summary_2025 = get_compliant_summary_by_barangay(
        as_of_year=2025, db_session=db
    )
    summary_2026 = get_compliant_summary_by_barangay(
        as_of_year=2026, db_session=db
    )

    assert [row["td_number"] for row in through_2025["items"]] == ["TD-AS-OF"]
    assert through_2025["items"][0]["years_covered"] == 1
    assert through_2026["items"] == []
    assert summary_2025[0]["compliant_count"] == 1
    assert summary_2026[0]["compliant_count"] == 0


def test_compliance_through_year_switches_to_effective_replacement(db):
    old_prop = Property(
        td_number="TD-OLD",
        owner_name="Old Owner",
        barangay="BUENAVISTA",
        assessed_value=100_000.0,
        effectivity_date="2023-01-01",
        penalty=0,
        discount=0,
    )
    replacement = Property(
        td_number="TD-NEW",
        prev_td_number="TD-OLD",
        owner_name="New Owner",
        barangay="BUENAVISTA",
        assessed_value=100_000.0,
        effectivity_date="2025-01-01",
        penalty=0,
        discount=0,
    )
    db.add_all([old_prop, replacement])
    db.flush()
    db.add_all([
        PropertyBilling(
            property_id=old_prop.id,
            tax_year=2024,
            assessed_value=100_000.0,
            penalty=0,
            discount=0,
            amount_paid=2_000.0,
        ),
        PropertyBilling(
            property_id=replacement.id,
            tax_year=2025,
            assessed_value=100_000.0,
            penalty=0,
            discount=0,
            amount_paid=2_000.0,
        ),
    ])
    db.commit()

    rows_2024 = get_compliant_accounts(as_of_year=2024, db_session=db)["items"]
    rows_2025 = get_compliant_accounts(as_of_year=2025, db_session=db)["items"]

    assert [row["td_number"] for row in rows_2024] == ["TD-OLD"]
    assert [row["td_number"] for row in rows_2025] == ["TD-NEW"]

def test_sync_existing_billing_assessed_value_respects_effectivity_year(db):
    prop = Property(
        td_number="TD-SYNC",
        owner_name="Owner Sync",
        barangay="DINADIAWAN",
        assessed_value=1_139_960.0,
        effectivity_date="2024-01-01",
    )
    db.add(prop)
    db.flush()

    db.add_all([
        PropertyBilling(property_id=prop.id, tax_year=2023, assessed_value=180_000.0, amount_paid=0, is_archived=False),
        PropertyBilling(property_id=prop.id, tax_year=2024, assessed_value=180_000.0, amount_paid=18_239.36, is_archived=False),
        PropertyBilling(property_id=prop.id, tax_year=2025, assessed_value=180_000.0, amount_paid=20_519.28, is_archived=False),
    ])
    db.flush()

    result = sync_existing_billing_assessed_value(
        prop.id,
        prop.assessed_value,
        effective_year=prop.effectivity_date,
        db_session=db,
    )

    rows = {
        row.tax_year: float(row.assessed_value)
        for row in db.query(PropertyBilling).filter(PropertyBilling.property_id == prop.id).all()
    }

    assert result == {"updated": 2, "years": [2024, 2025]}
    assert rows[2023] == 180_000.0
    assert rows[2024] == 1_139_960.0
    assert rows[2025] == 1_139_960.0

def test_repair_billing_assessed_value_snapshots_previews_and_applies(db):
    prop = Property(
        td_number="TD-REPAIR",
        owner_name="Owner Repair",
        barangay="DINADIAWAN",
        assessed_value=1_139_960.0,
        effectivity_date="2025-01-01",
    )
    db.add(prop)
    db.flush()

    db.add_all([
        PropertyBilling(property_id=prop.id, tax_year=2024, assessed_value=180_000.0, amount_paid=0, is_archived=False),
        PropertyBilling(property_id=prop.id, tax_year=2025, assessed_value=180_000.0, amount_paid=20_519.28, is_archived=False),
        PropertyBilling(property_id=prop.id, tax_year=2026, assessed_value=180_000.0, amount_paid=18_239.36, is_archived=False),
    ])
    db.flush()

    preview = repair_billing_assessed_value_snapshots(dry_run=True, db_session=db)

    rows_after_preview = {
        row.tax_year: float(row.assessed_value)
        for row in db.query(PropertyBilling).filter(PropertyBilling.property_id == prop.id).all()
    }
    assert preview["rows_to_update"] == 2
    assert preview["rows_updated"] == 0
    assert rows_after_preview[2025] == 180_000.0

    applied = repair_billing_assessed_value_snapshots(dry_run=False, db_session=db)
    rows_after_apply = {
        row.tax_year: float(row.assessed_value)
        for row in db.query(PropertyBilling).filter(PropertyBilling.property_id == prop.id).all()
    }

    assert applied["rows_to_update"] == 2
    assert applied["rows_updated"] == 2
    assert rows_after_apply[2024] == 180_000.0
    assert rows_after_apply[2025] == 1_139_960.0
    assert rows_after_apply[2026] == 1_139_960.0

def _payment_for_billing(db, prop, billing, amount, date_paid, or_number):
    payment = Payment(
        property_id=prop.id,
        amount=amount,
        or_number=or_number,
        date_paid=date_paid,
        tax_year=str(billing.tax_year),
    )
    db.add(payment)
    db.flush()
    db.add(PaymentBilling(
        payment_id=payment.id,
        billing_id=billing.id,
        tax_year=billing.tax_year,
        amount_paid=amount,
    ))
    billing.amount_paid = float(billing.amount_paid or 0) + amount
    db.flush()
    return payment


def test_reconciliation_flags_prior_year_gap_before_later_payment(db):
    prop = Property(
        td_number="TD-SEQUENCE-GAP",
        owner_name="Sequence Gap Owner",
        barangay="NORTH POBLACION",
        assessed_value=100_000.0,
        effectivity_date="2023-01-01",
    )
    db.add(prop)
    db.flush()

    billings = {}
    for year in range(2023, 2027):
        billing = PropertyBilling(
            property_id=prop.id,
            tax_year=year,
            assessed_value=100_000.0,
            penalty=0,
            discount=0,
            amount_paid=0,
        )
        db.add(billing)
        billings[year] = billing
    db.flush()

    for year in (2023, 2024, 2026):
        _payment_for_billing(
            db,
            prop,
            billings[year],
            2_000.0,
            datetime(year, 1, 15),
            f"OR-{year}",
        )
    db.commit()

    diagnostics = get_reconciliation_diagnostics(2026, db_session=db)
    gaps = [
        row for row in diagnostics["payment_sequence_gaps"]
        if row["td_number"] == "TD-SEQUENCE-GAP"
    ]

    assert diagnostics["payment_sequence_gap_count"] == 1
    assert len(gaps) == 1
    assert gaps[0]["tax_year"] == 2025
    assert gaps[0]["gap_status"] == "unpaid"
    assert gaps[0]["later_paid_year"] == 2026
    assert gaps[0]["outstanding"] == pytest.approx(2_000.0)


def test_reconciliation_payment_sequence_respects_effectivity_year(db):
    prop = Property(
        td_number="TD-NEW-IN-2025",
        owner_name="New TD Owner",
        barangay="PUANGI",
        assessed_value=50_000.0,
        effectivity_date="2025",
    )
    db.add(prop)
    db.flush()

    for year in (2025, 2026):
        billing = PropertyBilling(
            property_id=prop.id,
            tax_year=year,
            assessed_value=50_000.0,
            penalty=0,
            discount=0,
            amount_paid=0,
        )
        db.add(billing)
        db.flush()
        _payment_for_billing(db, prop, billing, 1_000.0, datetime(year, 1, 15), f"NEW-{year}")
    db.commit()

    diagnostics = get_reconciliation_diagnostics(2026, db_session=db)

    assert not any(
        row["td_number"] == "TD-NEW-IN-2025"
        for row in diagnostics["payment_sequence_gaps"]
    )


def test_partial_installments_remain_separate_when_later_year_is_posted(db):
    prop = Property(
        td_number="06-0001-00001",
        owner_name="Installment Owner",
        barangay="NORTH POBLACION",
        assessed_value=100_000.0,
    )
    db.add(prop)
    db.commit()

    def post(year, or_number, or_date, amount, remarks=""):
        _sync_financial_records(prop.id, {
            "TD Number": prop.td_number,
            "Owner Name": prop.owner_name,
            "Assessed Value": "100000",
            "Tax Year": str(year),
            "OR Number": or_number,
            "OR Date": or_date,
            "Penalty": "0",
            "Discount": "0",
            "Amount Paid": str(amount),
            "Remarks": remarks,
        }, db)
        db.commit()

    post(2023, "OR-PARTIAL", "2023-01-10", 500.0, "1st quarter only")
    post(2023, "OR-FINAL", "2023-02-10", 1_500.0)
    # Reusing an OR/date for a different tax year must create another ledger
    # entry, not mutate the existing 2023 installment.
    post(2024, "OR-FINAL", "2023-02-10", 2_000.0)

    payments = db.query(Payment).filter(Payment.property_id == prop.id).order_by(Payment.id).all()
    assert [(row.tax_year, float(row.amount)) for row in payments] == [
        ("2023", 500.0),
        ("2023", 1_500.0),
        ("2024", 2_000.0),
    ]
    assert payments[0].remarks == "1st quarter only"

    billing_2023 = db.query(PropertyBilling).filter_by(property_id=prop.id, tax_year=2023).one()
    billing_2024 = db.query(PropertyBilling).filter_by(property_id=prop.id, tax_year=2024).one()
    assert float(billing_2023.amount_paid) == pytest.approx(2_000.0)
    assert float(billing_2024.amount_paid) == pytest.approx(2_000.0)
    assert db.query(PaymentBilling).filter_by(billing_id=billing_2023.id).count() == 2
    assert db.query(PaymentBilling).filter_by(billing_id=billing_2024.id).count() == 1
    ledger_rows = get_unified_payment_history(prop.td_number, db_session=db)
    assert len(ledger_rows) == 3
    assert any(row[10] == "1st quarter only" for row in ledger_rows)

    with pytest.raises(HTTPException) as duplicate_error:
        _sync_financial_records(prop.id, {
            "TD Number": prop.td_number,
            "Owner Name": prop.owner_name,
            "Assessed Value": "100000",
            "Tax Year": "2024",
            "OR Number": "OR-FINAL",
            "OR Date": "2023-02-10",
            "Penalty": "0",
            "Discount": "0",
            "Amount Paid": "2000",
        }, db)
    db.rollback()
    assert duplicate_error.value.status_code == 409
    assert db.query(Payment).filter(Payment.property_id == prop.id).count() == 3


def test_reconciliation_is_time_aware_for_prepayments_and_future_postings(db):
    prepaid_prop = Property(
        td_number="TD-PREPAID-2026",
        owner_name="Prepaid Owner",
        barangay="DINADIAWAN",
        assessed_value=100_000.0,
    )
    late_prop = Property(
        td_number="TD-LATE-POSTED-2026",
        owner_name="Late Posted Owner",
        barangay="DINADIAWAN",
        assessed_value=100_000.0,
    )
    db.add_all([prepaid_prop, late_prop])
    db.flush()

    prepaid_billing = PropertyBilling(
        property_id=prepaid_prop.id,
        tax_year=2026,
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
        amount_paid=0,
    )
    late_billing = PropertyBilling(
        property_id=late_prop.id,
        tax_year=2026,
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
        amount_paid=0,
    )
    db.add_all([prepaid_billing, late_billing])
    db.flush()

    _payment_for_billing(
        db,
        prepaid_prop,
        prepaid_billing,
        2_000.0,
        datetime(2025, 12, 20),
        "OR-PREPAID",
    )
    _payment_for_billing(
        db,
        late_prop,
        late_billing,
        2_000.0,
        datetime(2029, 1, 19),
        "OR-FUTURE-DATED",
    )
    db.commit()

    summary = get_rpt_receivables_summary(2026, db_session=db)
    diagnostics = get_reconciliation_diagnostics(2026, db_session=db)

    assert summary["current_year_net_collectible"] == pytest.approx(4_000.0)
    assert summary["prepaid_current_year"] == pytest.approx(2_000.0)
    assert summary["applied_collections"] == pytest.approx(2_000.0)
    assert summary["ending_receivable"] == pytest.approx(2_000.0)
    assert summary["equation_variance"] == pytest.approx(0.0)

    assert diagnostics["tracker_variance"] == pytest.approx(0.0)
    assert diagnostics["raw_tracker_variance"] == pytest.approx(-2_000.0)
    assert any(
        row["td_number"] == "TD-LATE-POSTED-2026" and row["payment_year"] == 2029
        for row in diagnostics["current_year_paid_outside_details"]
    )



def test_reconciliation_flags_unlinked_ledger_payment(db):
    prop = Property(
        td_number="TD-UNLINKED",
        owner_name="Unlinked Owner",
        barangay="IPIL",
        assessed_value=65_820.0,
    )
    db.add(prop)
    db.flush()

    billing = PropertyBilling(
        property_id=prop.id,
        tax_year=2026,
        assessed_value=65_820.0,
        penalty=0,
        discount=0,
        amount_paid=0,
    )
    db.add(billing)
    payment = Payment(
        property_id=prop.id,
        amount=1_448.04,
        penalty=131.64,
        discount=0,
        or_number="8333352",
        date_paid=datetime(2026, 5, 14),
        tax_year="2026",
    )
    db.add(payment)
    db.commit()

    diagnostics = get_reconciliation_diagnostics(2026, db_session=db)

    assert any(
        row["td_number"] == "TD-UNLINKED" and row["or_number"] == "8333352"
        for row in diagnostics["unlinked_payments"]
    )


def test_repair_payment_billing_allocations_links_payment_and_recalculates(db):
    prop = Property(
        td_number="TD-REPAIR-LINK",
        owner_name="Repair Link Owner",
        barangay="IPIL",
        assessed_value=65_820.0,
    )
    db.add(prop)
    db.flush()

    billing = PropertyBilling(
        property_id=prop.id,
        tax_year=2026,
        assessed_value=65_820.0,
        penalty=0,
        discount=0,
        amount_paid=0,
    )
    db.add(billing)
    payment = Payment(
        property_id=prop.id,
        amount=1_448.04,
        penalty=131.64,
        discount=0,
        or_number="8333352",
        date_paid=datetime(2026, 5, 14),
        tax_year="2026",
    )
    db.add(payment)
    db.commit()

    preview = repair_payment_billing_allocations(dry_run=True, db_session=db)
    assert preview["missing_links"] == 1
    assert db.query(PaymentBilling).count() == 0

    applied = repair_payment_billing_allocations(dry_run=False, db_session=db)
    db.commit()

    assert applied["missing_links"] == 1
    assert applied["billing_rows_recalculated"] == 1
    link = db.query(PaymentBilling).filter(PaymentBilling.payment_id == payment.id).one()
    assert link.billing_id == billing.id
    assert float(link.amount_paid) == pytest.approx(1_448.04)
    db.refresh(billing)
    assert float(billing.amount_paid) == pytest.approx(1_448.04)

    diagnostics = get_reconciliation_diagnostics(2026, db_session=db)
    assert not any(row["td_number"] == "TD-REPAIR-LINK" for row in diagnostics["unlinked_payments"])


def test_repair_payment_billing_allocations_fixes_stale_credit_amounts(db):
    prop = Property(
        td_number="TD-STALE-CREDIT",
        owner_name="Stale Credit Owner",
        barangay="MALIGAYA",
        assessed_value=12_220.0,
    )
    db.add(prop)
    db.flush()

    billing = PropertyBilling(
        property_id=prop.id,
        tax_year=2026,
        assessed_value=12_220.0,
        penalty=0,
        discount=224.44,
        amount_paid=2_019.96,
    )
    db.add(billing)
    payment = Payment(
        property_id=prop.id,
        amount=219.96,
        penalty=0,
        discount=24.44,
        or_number="5970936",
        date_paid=datetime(2026, 1, 13),
        tax_year="2026",
    )
    db.add(payment)
    db.flush()
    db.add(PaymentBilling(
        payment_id=payment.id,
        billing_id=billing.id,
        tax_year=2026,
        amount_paid=2_019.96,
    ))
    db.commit()

    diagnostics_before = get_reconciliation_diagnostics(2026, db_session=db)
    assert any(
        row["td_number"] == "TD-STALE-CREDIT" and row["balance"] == pytest.approx(-1_800.0)
        for row in diagnostics_before["overpaid_or_credit_rows"]
    )

    preview = repair_payment_billing_allocations(dry_run=True, db_session=db)
    assert preview["stale_link_amounts"] == 1
    assert preview["stale_billing_summaries"] == 1

    applied = repair_payment_billing_allocations(dry_run=False, db_session=db)
    db.commit()

    assert applied["stale_link_amounts"] == 1
    assert applied["stale_billing_summaries"] == 1
    db.refresh(billing)
    link = db.query(PaymentBilling).filter(PaymentBilling.payment_id == payment.id).one()
    assert float(link.amount_paid) == pytest.approx(219.96)
    assert float(billing.amount_paid) == pytest.approx(219.96)
    assert float(billing.discount) == pytest.approx(24.44)

    diagnostics_after = get_reconciliation_diagnostics(2026, db_session=db)
    assert not any(row["td_number"] == "TD-STALE-CREDIT" for row in diagnostics_after["overpaid_or_credit_rows"])


def test_reconciliation_overpaid_uses_linked_penalty(db):
    prop = Property(
        td_number="06-0009-01219",
        owner_name="Penalty Owner",
        barangay="DIARABASIN",
        assessed_value=30_000.0,
    )
    db.add(prop)
    db.flush()

    billing = PropertyBilling(
        property_id=prop.id,
        tax_year=2024,
        assessed_value=30_000.0,
        penalty=0,
        discount=0,
        amount_paid=624.0,
    )
    db.add(billing)
    payment = Payment(
        property_id=prop.id,
        amount=624.0,
        penalty=24.0,
        discount=0,
        or_number="TEST-PEN-24",
        date_paid=datetime(2024, 6, 1),
        tax_year="2024",
    )
    db.add(payment)
    db.flush()
    db.add(PaymentBilling(
        payment_id=payment.id,
        billing_id=billing.id,
        tax_year=2024,
        amount_paid=624.0,
    ))
    db.commit()

    diagnostics = get_reconciliation_diagnostics(2024, db_session=db)
    assert not any(
        row["td_number"] == "06-0009-01219"
        for row in diagnostics["overpaid_or_credit_rows"]
    )

    summary = get_rpt_receivables_summary(2024, db_session=db)
    metrics = get_reconciliation_metrics(2024, db_session=db)
    assert summary["current_year_penalty"] == pytest.approx(24.0)
    assert summary["current_year_net_collectible"] == pytest.approx(624.0)
    assert summary["equation_variance"] == pytest.approx(0.0)
    assert metrics["assessor"]["current_year_penalty"] == pytest.approx(24.0)
    assert metrics["assessor"]["current_year_net_collectible"] == pytest.approx(624.0)
