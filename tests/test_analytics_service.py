from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Payment, PaymentBilling, Property, PropertyBilling
from backend.services.analytics_service import (
    get_barangay_distribution,
    get_collection_summary,
)
from backend.services.payment_service import get_operational_analytics
from utils.db_compat import today


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


def _seed_operational_payment(
    db,
    *,
    td_number,
    barangay,
    date_paid,
    raw_amount,
    allocated_amount,
):
    prop = Property(
        td_number=td_number,
        owner_name=f"Owner {td_number}",
        barangay=barangay,
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
    )
    db.add(prop)
    db.flush()

    billing = PropertyBilling(
        property_id=prop.id,
        tax_year=date_paid.year,
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
        amount_paid=allocated_amount,
    )
    db.add(billing)
    db.flush()

    payment = Payment(
        property_id=prop.id,
        amount=raw_amount,
        penalty=0,
        discount=0,
        or_number=f"OR-{td_number}",
        date_paid=datetime.combine(date_paid, datetime.min.time()),
        tax_year=str(date_paid.year),
    )
    db.add(payment)
    db.flush()
    db.add(
        PaymentBilling(
            payment_id=payment.id,
            billing_id=billing.id,
            tax_year=date_paid.year,
            amount_paid=allocated_amount,
        )
    )
    return payment


def test_operational_analytics_uses_allocations_and_barangay_filter(db):
    current_day = today()
    _seed_operational_payment(
        db,
        td_number="06-0012-OP001",
        barangay="DINADIAWAN",
        date_paid=current_day,
        raw_amount=9_999.0,
        allocated_amount=500.0,
    )
    _seed_operational_payment(
        db,
        td_number="06-0001-OP002",
        barangay="NORTH POBLACION",
        date_paid=current_day,
        raw_amount=8_888.0,
        allocated_amount=250.0,
    )
    db.commit()

    data = get_operational_analytics(
        year=current_day.year,
        barangay="DINADIAWAN",
        db_session=db,
    )

    assert data["kpis"]["total_collected"] == pytest.approx(500.0)
    assert data["kpis"]["transactions"] == 1
    assert data["kpis"]["properties_paid"] == 1
    assert sum(row["total"] for row in data["trend"]) == pytest.approx(500.0)
    assert data["barangays"] == [
        {"barangay": "DINADIAWAN", "total": pytest.approx(500.0)}
    ]
    assert data["recent"][0]["date"] == current_day.isoformat()


def test_operational_analytics_excludes_future_dated_payments(db):
    current_day = today()
    _seed_operational_payment(
        db,
        td_number="06-0012-FUTURE",
        barangay="DINADIAWAN",
        date_paid=current_day + timedelta(days=1),
        raw_amount=700.0,
        allocated_amount=700.0,
    )
    db.commit()

    data = get_operational_analytics(
        year=current_day.year,
        db_session=db,
    )

    assert data["kpis"]["total_collected"] == pytest.approx(0.0)
    assert data["quality"]["future_dated_payments"] == 1
