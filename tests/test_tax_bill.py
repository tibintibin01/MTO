from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.generators.tax_bill_gen import generate_tax_bill, split_installments
from backend.models import Property, PropertyBilling, TaxPolicy
from backend.services.billing_service import (
    TaxBillUnavailableError,
    get_collections_worklist,
    get_compliant_accounts,
    get_delinquent_accounts,
    get_property_delinquency_statement_data,
    get_property_tax_bill_data,
)


AS_OF_2026 = date(2026, 7, 29)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _property(db, td_number):
    prop = Property(
        td_number=td_number,
        owner_name="TEST OWNER",
        barangay="DINADIAWAN",
        location="DINADIAWAN",
        kind_of_property="RESIDENTIAL LOT",
        pin=f"PIN-{td_number}",
        assessed_value=100_000,
        penalty=0,
        discount=0,
    )
    db.add(prop)
    db.flush()
    return prop


def _billing(db, property_id, tax_year, paid=0):
    billing = PropertyBilling(
        property_id=property_id,
        tax_year=tax_year,
        assessed_value=100_000,
        amount_paid=paid,
        penalty=0,
        discount=0,
    )
    db.add(billing)
    db.flush()
    return billing


def test_future_year_only_balance_is_not_delinquent(db):
    prop = _property(db, "TD-FUTURE-ONLY")
    _billing(db, prop.id, 2026, paid=2_000)
    _billing(db, prop.id, 2027, paid=0)
    db.commit()

    worklist = get_collections_worklist(
        as_of_date=AS_OF_2026,
        db_session=db,
    )
    delinquent = get_delinquent_accounts(
        as_of_date=AS_OF_2026,
        db_session=db,
    )
    compliant = get_compliant_accounts(as_of_year=2026, db_session=db)

    assert prop.td_number not in [row["td_number"] for row in worklist["items"]]
    assert prop.td_number not in [row["td_number"] for row in delinquent["items"]]
    assert prop.td_number in [row["td_number"] for row in compliant["items"]]
    assert worklist["summary"]["delinquent_count"] == 0


def test_prior_balance_remains_delinquent_but_future_year_is_excluded(db):
    prop = _property(db, "TD-PRIOR-AND-FUTURE")
    _billing(db, prop.id, 2025, paid=0)
    _billing(db, prop.id, 2027, paid=0)
    db.commit()

    worklist = get_collections_worklist(
        as_of_date=AS_OF_2026,
        db_session=db,
    )
    row = next(item for item in worklist["items"] if item["id"] == prop.id)

    assert row["earliest_year"] == 2025
    assert row["years_billed"] == 1
    assert row["balance"] == pytest.approx(2_760.0)

    statement = get_property_delinquency_statement_data(
        prop.id,
        as_of_date=AS_OF_2026,
        db_session=db,
    )
    assert [item["tax_year"] for item in statement["billing_rows"]] == [2025]
    assert statement["total_balance"] == pytest.approx(2_760.0)


def test_tax_bill_uses_exact_target_year_and_marks_advance(db):
    prop = _property(db, "TD-TAX-BILL")
    _billing(db, prop.id, 2026, paid=2_000)
    _billing(db, prop.id, 2027, paid=0)
    db.commit()

    tax_bill = get_property_tax_bill_data(
        prop.id,
        2027,
        as_of_date=AS_OF_2026,
        db_session=db,
    )

    assert tax_bill["document_type"] == "ADVANCE"
    assert tax_bill["tax_year"] == 2027
    assert [row["tax_year"] for row in tax_bill["billing_rows"]] == [2027]
    assert tax_bill["basic_amount"] == pytest.approx(1_000.0)
    assert tax_bill["sef_amount"] == pytest.approx(1_000.0)
    assert tax_bill["penalty"] == 0
    assert tax_bill["amount_payable"] == pytest.approx(2_000.0)
    assert tax_bill["prior_balance"] == 0
    assert tax_bill["compliant_through_year"] == 2026


def test_tax_bill_calculates_virtual_advance_without_posting_receivable(db):
    prop = _property(db, "TD-NO-ADVANCE-BILL")
    _billing(db, prop.id, 2026, paid=2_000)
    db.add(
        TaxPolicy(
            tax_year=2027,
            basic_rate=Decimal("0.0100"),
            sef_rate=Decimal("0.0100"),
            penalty_rate=Decimal("0.0200"),
        )
    )
    db.commit()

    billing_count_before = db.query(PropertyBilling).count()
    tax_bill = get_property_tax_bill_data(
        prop.id,
        2027,
        as_of_date=AS_OF_2026,
        db_session=db,
    )
    billing_count_after = db.query(PropertyBilling).count()

    assert tax_bill["document_type"] == "ADVANCE"
    assert tax_bill["calculation_source"] == "VIRTUAL_ADVANCE"
    assert tax_bill["billing_record_exists"] is False
    assert tax_bill["tax_year"] == 2027
    assert tax_bill["assessed_value"] == pytest.approx(100_000.0)
    assert tax_bill["basic_amount"] == pytest.approx(1_000.0)
    assert tax_bill["sef_amount"] == pytest.approx(1_000.0)
    assert tax_bill["amount_payable"] == pytest.approx(2_000.0)
    assert tax_bill["billing_rows"][0]["billing_status"] == "Advance"
    assert billing_count_before == billing_count_after == 1


def test_virtual_advance_requires_configured_target_year_policy(db):
    prop = _property(db, "TD-NO-TAX-POLICY")
    _billing(db, prop.id, 2026, paid=2_000)
    db.commit()

    with pytest.raises(
        TaxBillUnavailableError,
        match="Configure and approve the 2027 Tax Policy",
    ):
        get_property_tax_bill_data(
            prop.id,
            2027,
            as_of_date=AS_OF_2026,
            db_session=db,
        )


def test_installment_split_is_cent_exact():
    installments = split_installments(Decimal("201.01"))

    assert installments == [
        Decimal("50.26"),
        Decimal("50.25"),
        Decimal("50.25"),
        Decimal("50.25"),
    ]
    assert sum(installments) == Decimal("201.01")


def test_advance_tax_bill_pdf_is_generated(tmp_path):
    data = {
        "document_type": "ADVANCE",
        "tax_year": 2027,
        "td_number": "06-0012-02563",
        "pin": "010-02-1002",
        "owner_name": "AGRI COMPONENT CORPORATION",
        "location": "DINADIAWAN",
        "kind_of_property": "COMMERCIAL - 2 STOREY HOTEL",
        "assessed_value": 11_606_340,
        "basic_amount": 116_063.40,
        "sef_amount": 116_063.40,
        "discount": 0,
        "amount_paid": 0,
        "annual_tax_after_discount": 232_126.80,
        "amount_payable": 232_126.80,
        "prior_balance": 0,
        "prepared_by": "MTO TEST USER",
    }

    output = Path(generate_tax_bill(data, str(tmp_path)))

    assert output.exists()
    assert output.name.startswith("ADVANCE_TAX_BILL_06-0012-02563_2027_")
    assert output.read_bytes().startswith(b"%PDF")
    assert output.stat().st_size > 10_000
