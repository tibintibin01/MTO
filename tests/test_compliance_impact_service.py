from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Payment, PaymentBilling, Property, PropertyBilling
from backend.services.billing_service import (
    get_compliant_accounts,
    get_compliant_accounts_v2,
)
from backend.services.compliance_impact_service import build_compliance_impact_report
from utils.config import config as mto_config


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )

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


def _billing(db, prop, year, paid=0, archived=False, assessed=100_000):
    billing = PropertyBilling(
        property_id=prop.id,
        tax_year=year,
        assessed_value=assessed,
        penalty=0,
        discount=0,
        amount_paid=paid,
        is_archived=archived,
    )
    db.add(billing)
    db.flush()
    return billing


def test_report_uses_same_linked_payment_baseline_as_live_service(db):
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
    db.add(
        PaymentBilling(
            payment_id=payment.id,
            billing_id=billing.id,
            tax_year=2025,
            amount_paid=2_000,
        )
    )
    db.commit()

    report = build_compliance_impact_report(as_of_year=2025, db_session=db)

    assert report["counts"]["unchanged_compliant"] == 1
    assert report["changed_total"] == 0
    assert report["affected_accounts"] == []


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


def test_report_previews_explicit_old_and_archived_exclusion_policy(db, monkeypatch):
    monkeypatch.setattr(mto_config, "COMPLIANCE_DATA_START_YEAR", 2023)
    monkeypatch.setattr(
        mto_config,
        "COMPLIANCE_EXCLUDE_ARCHIVED_BILLINGS",
        True,
    )
    prop = _property(db, "TD-SUPPORTED-WINDOW")
    _billing(db, prop, 2022, paid=0)
    _billing(db, prop, 2024, paid=2_000)
    _billing(db, prop, 2025, paid=0, archived=True)
    db.commit()

    report = build_compliance_impact_report(as_of_year=2025, db_session=db)
    account = report["affected_accounts"][0]

    assert report["counts"]["newly_compliant"] == 1
    assert "pre_policy_start_year_balance_excluded" in account["reasons"]
    assert "archived_balance_excluded" in account["reasons"]
    assert [row["tax_year"] for row in account["proposed"]["year_balances"]] == [2024]


def test_report_conservative_default_does_not_hide_old_or_archived_debt(
    db, monkeypatch
):
    monkeypatch.setattr(mto_config, "COMPLIANCE_DATA_START_YEAR", 0)
    monkeypatch.setattr(
        mto_config,
        "COMPLIANCE_EXCLUDE_ARCHIVED_BILLINGS",
        False,
    )
    prop = _property(db, "TD-CONSERVATIVE-SCOPE")
    _billing(db, prop, 2022, paid=0)
    _billing(db, prop, 2024, paid=2_000)
    _billing(db, prop, 2025, paid=0, archived=True)
    db.commit()

    report = build_compliance_impact_report(as_of_year=2025, db_session=db)

    assert report["counts"]["newly_compliant"] == 0
    assert report["billing_data_start_year"] is None
    assert report["exclude_archived_billings"] is False


def test_report_separates_currency_tolerance_corrections_from_v2_changes(db):
    prop = _property(db, "TD-SUBCENT-PRECISION")
    _billing(db, prop, 2025, assessed=51_077.20, paid=1_021.54)
    db.commit()

    report = build_compliance_impact_report(as_of_year=2025, db_session=db)

    assert report["changed_total"] == 0
    assert report["counts"]["unchanged_compliant"] == 1
    assert report["currency_precision_corrections"]["count"] == 1
    assert (
        report["currency_precision_corrections"]["accounts"][0]["td_number"]
        == "TD-SUBCENT-PRECISION"
    )


def test_report_change_membership_matches_the_two_live_services(db):
    paid = _property(db, "TD-PAID")
    _billing(db, paid, 2025, paid=2_000)
    cross_year = _property(db, "TD-CROSS")
    _billing(db, cross_year, 2024, paid=4_000)
    _billing(db, cross_year, 2025, paid=0)
    unpaid = _property(db, "TD-UNPAID")
    _billing(db, unpaid, 2025, paid=0)
    db.commit()

    legacy_ids = {
        row["id"]
        for row in get_compliant_accounts(as_of_year=2025, limit=200, db_session=db)[
            "items"
        ]
    }
    proposed_ids = {
        row["id"]
        for row in get_compliant_accounts_v2(as_of_year=2025, limit=200, db_session=db)[
            "items"
        ]
    }
    report = build_compliance_impact_report(as_of_year=2025, db_session=db)
    newly = {
        row["property_id"]
        for row in report["affected_accounts"]
        if row["change"] == "newly_compliant"
    }
    removed = {
        row["property_id"]
        for row in report["affected_accounts"]
        if row["change"] == "removed_from_compliant"
    }

    assert newly == proposed_ids - legacy_ids
    assert removed == legacy_ids - proposed_ids
