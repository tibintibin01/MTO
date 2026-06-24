# -*- coding: utf-8 -*-
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Payment, PaymentBilling, Property, PropertyBilling
from backend.services.payment_service import (
    delete_payment_record,
    get_payment_cleanup_candidates,
)


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


def _property_with_billings(db):
    prop = Property(
        td_number="06-0015-00522",
        owner_name="Cleanup Test",
        barangay="IPIL",
        assessed_value=220455.0,
    )
    db.add(prop)
    db.flush()

    billing_2024 = PropertyBilling(
        property_id=prop.id,
        tax_year=2024,
        assessed_value=220455.0,
        penalty=0,
        discount=0,
        amount_paid=0,
    )
    billing_2026 = PropertyBilling(
        property_id=prop.id,
        tax_year=2026,
        assessed_value=220455.0,
        penalty=0,
        discount=0,
        amount_paid=2204.56,
    )
    db.add_all([billing_2024, billing_2026])
    db.flush()
    return prop, billing_2024, billing_2026


def test_cleanup_candidates_flag_visible_year_linked_to_wrong_billing_year(db):
    prop, _billing_2024, billing_2026 = _property_with_billings(db)
    payment = Payment(
        property_id=prop.id,
        date_paid=datetime(2024, 9, 12),
        or_number="3183913",
        tax_year="3RD QTR 2024",
        amount=2204.56,
        penalty=0,
        discount=0,
    )
    db.add(payment)
    db.flush()
    db.add(PaymentBilling(
        payment_id=payment.id,
        billing_id=billing_2026.id,
        tax_year=2026,
        amount_paid=2204.56,
    ))
    db.commit()

    result = get_payment_cleanup_candidates(year=2026, db_session=db)

    row = next(item for item in result["preview"] if item["payment_id"] == payment.id)
    assert row["billing_tax_year"] == 2026
    assert "Visible year 2024 is linked to billing year 2026" in row["cleanup_reason"]


def test_delete_payment_recalculates_linked_billing_even_with_quarter_tax_year_text(db):
    prop, _billing_2024, billing_2026 = _property_with_billings(db)
    payment = Payment(
        property_id=prop.id,
        date_paid=datetime(2024, 9, 12),
        or_number="3183913",
        tax_year="3RD QTR 2024",
        amount=2204.56,
        penalty=0,
        discount=0,
    )
    db.add(payment)
    db.flush()
    db.add(PaymentBilling(
        payment_id=payment.id,
        billing_id=billing_2026.id,
        tax_year=2026,
        amount_paid=2204.56,
    ))
    db.commit()

    delete_payment_record(
        payment.id,
        {"username": "tester", "role": "admin"},
        db_session=db,
        current_user={"username": "tester", "role": "admin"},
    )

    refreshed = db.query(PropertyBilling).filter(PropertyBilling.id == billing_2026.id).one()
    assert float(refreshed.amount_paid) == 0.0
    assert db.query(PaymentBilling).filter(PaymentBilling.payment_id == payment.id).count() == 0
