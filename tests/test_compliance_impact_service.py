from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Payment, PaymentBilling, Property, PropertyBilling
from backend.services.compliance_impact_service import build_compliance_impact_report


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(connection, _):
        connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _property(db, td_number):
    prop = Property(
        td_number=td_number,
        owner_name="Impact Test",
        barangay="BUENAVISTA",
        assessed_value=100_000,
    )
    db.add(prop)
    db.flush()
    return prop


def _billing(db, prop, year, paid=0, archived=False):
    billing = PropertyBilling(
        property_id=prop.id,
        tax_year=year,
        assessed_value=100_000,
        penalty=0,
        discount=0,
        amount_paid=paid,
        is_archived=archived,
    )
    db.add(billing)
    db.flush()
    return billing


def test_report_marks_stale_paid_cache_as_newly_compliant(db):
    prop = _property(db, "TD-STALE-CACHE")
    billing = _billing(db, prop, 2025, paid=0)
    payment = Payment(
        property_id=prop.id,
        amount=2_000,
        or_number="OR-PAID",
        date_paid=datetime(2025, 6, 1),
        tax_year="2025",
    )
    db.add(payment)
    db.flush()
    db.add(PaymentBilling(payment_id=payment.id, billing_id=billing.id, tax_year=2025, amount_paid=2_000))
    db.commit()

    report = build_compliance_impact_report(as_of_year=2025, db_session=db)

    assert report["counts"]["newly_compliant"] == 1
    assert report["affected_accounts"][0]["td_number"] == "TD-STALE-CACHE"
    assert "linked_payments_reconcile_stale_billing_cache" in report["affected_accounts"][0]["reasons"]


def test_report_removes_aggregate_cross_year_credit_from_compliant(db):
    prop = _property(db, "TD-CROSS-YEAR")
    _billing(db, prop, 2024, paid=4_000)
    _billing(db, prop, 2025, paid=0)
    db.commit()

    report = build_compliance_impact_report(as_of_year=2025, db_session=db)
    account = report["affected_accounts"][0]

    assert report["counts"]["removed_from_compliant"] == 1
    assert account["legacy"]["compliant"] is True
    assert account["proposed"]["compliant"] is False
    assert account["reasons"] == ["cross_year_credit_masks_unpaid_year"]
    assert account["proposed"]["year_balances"][1]["balance"] == pytest.approx(2_000)


def test_report_excludes_unpaid_pre_2023_and_archived_rows(db):
    prop = _property(db, "TD-SUPPORTED-WINDOW")
    _billing(db, prop, 2022, paid=0)
    _billing(db, prop, 2024, paid=2_000)
    _billing(db, prop, 2025, paid=0, archived=True)
    db.commit()

    report = build_compliance_impact_report(as_of_year=2025, db_session=db)
    account = report["affected_accounts"][0]

    assert report["counts"]["newly_compliant"] == 1
    assert "legacy_pre_2023_balance_excluded" in account["reasons"]
    assert "archived_balance_excluded" in account["reasons"]
    assert [row["tax_year"] for row in account["proposed"]["year_balances"]] == [2024]
