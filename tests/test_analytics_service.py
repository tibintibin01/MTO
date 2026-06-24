from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Payment, PaymentBilling, Property, PropertyBilling
from backend.services.analytics_service import (
    get_barangay_distribution,
    get_collection_summary,
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


def _seed_allocated_payment(db):
    prop = Property(
        td_number="06-0012-AN001",
        owner_name="Analytics Test",
        barangay="DINADIAWAN",
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
    )
    db.add(prop)
    db.flush()

    billing = PropertyBilling(
        property_id=prop.id,
        tax_year=2026,
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
        amount_paid=500.0,
    )
    db.add(billing)
    db.flush()

    payment = Payment(
        property_id=prop.id,
        amount=9_999.0,
        penalty=0,
        discount=0,
        or_number="ANALYTICS",
        date_paid=datetime(2026, 6, 24),
        tax_year="2026",
    )
    db.add(payment)
    db.flush()

    db.add(
        PaymentBilling(
            payment_id=payment.id,
            billing_id=billing.id,
            tax_year=2026,
            amount_paid=500.0,
        )
    )
    db.commit()


def test_collection_summary_uses_allocations_for_receivable_math(db):
    _seed_allocated_payment(db)

    summary = get_collection_summary(db_session=db)

    assert summary["total_collected"] == pytest.approx(500.0)
    assert summary["total_receivables"] == pytest.approx(1_500.0)
    assert summary["collection_rate"] == pytest.approx(25.0)


def test_barangay_distribution_uses_allocations_for_collection_rate(db):
    _seed_allocated_payment(db)

    rows = get_barangay_distribution(db_session=db)
    dinadiawan = next(row for row in rows if row["name"] == "DINADIAWAN")

    assert dinadiawan["collected"] == pytest.approx(500.0)
    assert dinadiawan["value"] == pytest.approx(1_500.0)
    assert dinadiawan["percentage"] == pytest.approx(25.0)
