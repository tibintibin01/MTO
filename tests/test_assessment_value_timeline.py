from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
import pytest
from fastapi import HTTPException

from backend.models import (
    Payment,
    PaymentBilling,
    Property,
    PropertyAssessmentHistory,
    PropertyBilling,
)
from backend.services.billing_service import repair_billing_assessed_value_snapshots
from backend.services.property_service import (
    resolve_payment_target,
    resolve_property_for_tax_year,
    save_property,
)


def _session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def test_prior_assessment_correction_updates_only_pre_effectivity_billings():
    db = _session()
    prop = Property(
        td_number="06-0012-02561",
        owner_name="AGRI COMPONENT CORPORATION",
        barangay="DINADIAWAN",
        assessed_value=7_098_520,
        effectivity_date="2027-01-01",
        version=1,
    )
    db.add(prop)
    db.flush()
    db.add_all(
        [
            PropertyBilling(
                property_id=prop.id,
                tax_year=year,
                assessed_value=7_098_520,
                amount_paid=0,
                is_archived=False,
            )
            for year in (2023, 2024, 2025, 2026, 2027)
        ]
    )
    db.commit()

    result = save_property(
        {
            "TD Number": prop.td_number,
            "Owner Name": prop.owner_name,
            "Barangay": prop.barangay,
            "Location": prop.barangay,
            "Assessed Value": "7098520",
            "Effectivity Date": "2027",
            "Prior Assessed Value": "60080",
            "Prior Effectivity Year": "2023",
            "version": 1,
        },
        editing_id=prop.id,
        user={"id": 1, "username": "tester"},
        db_session=db,
    )

    values = {
        row.tax_year: float(row.assessed_value)
        for row in db.query(PropertyBilling)
        .filter(PropertyBilling.property_id == prop.id)
        .all()
    }
    history = (
        db.query(PropertyAssessmentHistory)
        .filter(
            PropertyAssessmentHistory.property_id == prop.id,
            PropertyAssessmentHistory.tax_year == "2023",
        )
        .one()
    )

    assert result["prior_assessment_sync"] == {
        "updated": 4,
        "years": [2023, 2024, 2025, 2026],
    }
    assert all(values[year] == 60_080 for year in (2023, 2024, 2025, 2026))
    assert values[2027] == 7_098_520
    assert float(history.assessed_value) == 60_080
    assert history.change_reason == "Historical assessment correction"


def test_later_assessment_preserves_superseded_classification():
    db = _session()
    prop = Property(
        td_number="06-0012-09999",
        owner_name="CLASSIFICATION HISTORY TEST",
        barangay="DINADIAWAN",
        location="DINADIAWAN",
        kind_of_property="RESIDENTIAL",
        assessed_value=100_000,
        effectivity_date="2024-01-01",
        version=1,
    )
    db.add(prop)
    db.commit()

    save_property(
        {
            "TD Number": prop.td_number,
            "Owner Name": prop.owner_name,
            "Barangay": prop.barangay,
            "Location": prop.location,
            "Kind of Property": "COMMERCIAL",
            "Assessed Value": "200000",
            "Effectivity Date": "2027",
            "version": 1,
        },
        editing_id=prop.id,
        user={"id": 1, "username": "tester"},
        db_session=db,
    )

    history = (
        db.query(PropertyAssessmentHistory)
        .filter(
            PropertyAssessmentHistory.property_id == prop.id,
            PropertyAssessmentHistory.tax_year == "2024",
        )
        .one()
    )
    db.refresh(prop)

    assert history.kind_of_property == "RESIDENTIAL"
    assert float(history.assessed_value) == 100_000
    assert prop.kind_of_property == "COMMERCIAL"
    assert float(prop.assessed_value) == 200_000


def test_repair_does_not_guess_future_assessment_for_prior_years():
    db = _session()
    prop = Property(
        td_number="TD-FUTURE-AV",
        owner_name="Future Assessment",
        assessed_value=7_098_520,
        effectivity_date="2027-01-01",
    )
    db.add(prop)
    db.flush()
    prior = PropertyBilling(
        property_id=prop.id,
        tax_year=2026,
        assessed_value=60_080,
        amount_paid=0,
        is_archived=False,
    )
    db.add(prior)
    db.commit()

    result = repair_billing_assessed_value_snapshots(dry_run=False, db_session=db)

    db.refresh(prior)
    assert result["rows_updated"] == 0
    assert float(prior.assessed_value) == 60_080


def _add_td_chain(db):
    old = Property(
        td_number="06-0009-00678",
        owner_name="Original Owner",
        barangay="DIARABASIN",
        location="DIARABASIN",
        kind_of_property="RESIDENTIAL LOT",
        assessed_value=100_000,
        effectivity_date="2023-01-01",
        version=1,
    )
    replacement_2026 = Property(
        td_number="06-0009-01254",
        owner_name="Replacement Owner",
        barangay="DIARABASIN",
        location="DIARABASIN",
        kind_of_property="RESIDENTIAL LOT",
        assessed_value=150_000,
        prev_td_number="06-0009-00678",
        effectivity_date="2026-01-01",
        version=1,
    )
    replacement_2027 = Property(
        td_number="06-0009-01256",
        owner_name="Latest Owner",
        barangay="DIARABASIN",
        location="DIARABASIN",
        kind_of_property="RESIDENTIAL LOT",
        assessed_value=200_000,
        prev_td_number="06-0009-01254",
        effectivity_date="2027-01-01",
        version=1,
    )
    db.add_all([old, replacement_2026, replacement_2027])
    db.commit()
    return old, replacement_2026, replacement_2027


def _payment_payload(prop, tax_year="2023"):
    return {
        "TD Number": prop.td_number,
        "Owner Name": prop.owner_name,
        "PIN": "",
        "Lot Number": "",
        "Area": "",
        "Location": prop.location,
        "Barangay": prop.barangay,
        "Kind of Property": prop.kind_of_property,
        "Previous TD Number": prop.prev_td_number or "",
        "Effectivity Date": prop.effectivity_date,
        "Assessed Value": str(prop.assessed_value),
        "Tax Year": tax_year,
        "OR Number": "8123456",
        "OR Date": "2026-01-05",
        "Penalty": "0",
        "Discount": "0",
        "Amount Paid": "2000",
        "Remarks": "",
    }


def test_payment_target_resolves_td_chain_by_tax_year():
    db = _session()
    old, replacement_2026, replacement_2027 = _add_td_chain(db)

    assert (
        resolve_property_for_tax_year(old.td_number, 2023, db).td_number
        == old.td_number
    )
    assert (
        resolve_property_for_tax_year(old.td_number, 2025, db).td_number
        == old.td_number
    )
    assert (
        resolve_property_for_tax_year(old.td_number, 2026, db).td_number
        == replacement_2026.td_number
    )
    assert (
        resolve_property_for_tax_year(old.td_number, 2027, db).td_number
        == replacement_2027.td_number
    )

    # Searching a newer TD for an old tax year still resolves back to the
    # historical TD that was active for that year.
    assert (
        resolve_property_for_tax_year(replacement_2026.td_number, 2023, db).td_number
        == old.td_number
    )


def test_requested_td_billing_prevents_silent_chain_redirect():
    db = _session()
    old, _replacement_2026, replacement_2027 = _add_td_chain(db)
    old.owner_name = "SAME OWNER"
    old.pin = "073-06-012-03-073"
    old.kind_of_property = "RESIDENTIAL LOT"
    replacement_2027.owner_name = "SAME OWNER"
    replacement_2027.pin = "073-06-012-03-069"
    replacement_2027.kind_of_property = "AGRICULTURAL - FORESTLAND"
    db.add_all(
        [
            PropertyBilling(
                property_id=old.id,
                tax_year=2027,
                assessed_value=15_000,
                amount_paid=0,
                is_archived=False,
            ),
            PropertyBilling(
                property_id=replacement_2027.id,
                tax_year=2027,
                assessed_value=9_110,
                amount_paid=145.76,
                is_archived=False,
            ),
        ]
    )
    db.commit()

    result = resolve_payment_target(old.td_number, 2027, db)

    assert result["id"] == old.id
    assert result["td_number"] == old.td_number
    assert [item["td_number"] for item in result["chain"]] == [
        old.td_number,
        "06-0009-01254",
        replacement_2027.td_number,
    ]


def test_payment_posts_to_requested_td_when_it_has_its_own_billing():
    db = _session()
    old, _replacement_2026, replacement_2027 = _add_td_chain(db)
    old_billing = PropertyBilling(
        property_id=old.id,
        tax_year=2027,
        assessed_value=100_000,
        amount_paid=0,
        is_archived=False,
    )
    replacement_billing = PropertyBilling(
        property_id=replacement_2027.id,
        tax_year=2027,
        assessed_value=200_000,
        amount_paid=4_000,
        is_archived=False,
    )
    db.add_all([old_billing, replacement_billing])
    db.commit()

    result = save_property(
        _payment_payload(old, tax_year="2027"),
        editing_id=old.id,
        user={"id": 1, "username": "tester"},
        db_session=db,
    )

    payment = db.query(Payment).one()
    link = db.query(PaymentBilling).one()
    db.refresh(old_billing)
    db.refresh(replacement_billing)

    assert result["target_changed"] is False
    assert result["td_number"] == old.td_number
    assert payment.property_id == old.id
    assert link.billing_id == old_billing.id
    assert float(old_billing.amount_paid) == 2_000
    assert float(replacement_billing.amount_paid) == 4_000


def test_manual_payment_refreshes_dashboard_stats_after_commit():
    db = _session()
    old, _replacement_2026, _replacement_2027 = _add_td_chain(db)
    db.add(
        PropertyBilling(
            property_id=old.id,
            tax_year=2027,
            assessed_value=100_000,
            amount_paid=0,
            is_archived=False,
        )
    )
    db.commit()

    with patch(
        "backend.services.stats_service.refresh_system_stats",
        return_value=True,
    ) as refresh_stats:
        save_property(
            _payment_payload(old, tax_year="2027"),
            editing_id=old.id,
            user={"id": 1, "username": "tester"},
            db_session=db,
        )

    refresh_stats.assert_called_once_with(db_session=db)
    assert db.query(Payment).count() == 1


def test_archived_requested_td_billing_does_not_override_effectivity():
    db = _session()
    old, _replacement_2026, replacement_2027 = _add_td_chain(db)
    db.add(
        PropertyBilling(
            property_id=old.id,
            tax_year=2027,
            assessed_value=100_000,
            amount_paid=0,
            is_archived=True,
        )
    )
    db.commit()

    result = resolve_payment_target(old.td_number, 2027, db)

    assert result["id"] == replacement_2027.id
    assert result["td_number"] == replacement_2027.td_number


def test_payment_save_redirects_to_historical_td_for_old_tax_year():
    db = _session()
    old, replacement_2026, _ = _add_td_chain(db)

    result = save_property(
        _payment_payload(replacement_2026, tax_year="2023"),
        editing_id=replacement_2026.id,
        user={"id": 1, "username": "tester"},
        db_session=db,
    )

    payment = db.query(Payment).one()
    billing = db.query(PropertyBilling).one()
    link = db.query(PaymentBilling).one()

    assert result["target_changed"] is True
    assert result["td_number"] == old.td_number
    assert payment.property_id == old.id
    assert billing.property_id == old.id
    assert billing.tax_year == 2023
    assert link.billing_id == billing.id
    assert float(link.amount_paid) == 2000


def test_payment_spanning_td_effectivity_change_requires_split_posting():
    db = _session()
    old, replacement_2026, _ = _add_td_chain(db)

    with pytest.raises(HTTPException) as exc:
        save_property(
            _payment_payload(old, tax_year="2025-2026"),
            editing_id=old.id,
            user={"id": 1, "username": "tester"},
            db_session=db,
        )

    assert exc.value.status_code == 422
    assert "spans TD changes" in exc.value.detail
    assert old.td_number in exc.value.detail
    assert replacement_2026.td_number in exc.value.detail


def test_payment_before_earliest_effectivity_is_rejected():
    db = _session()
    prop = Property(
        td_number="06-0009-09999",
        owner_name="Future Effective Owner",
        barangay="DIARABASIN",
        location="DIARABASIN",
        kind_of_property="RESIDENTIAL LOT",
        assessed_value=150_000,
        effectivity_date="2025-01-01",
        version=1,
    )
    db.add(prop)
    db.commit()

    assert resolve_property_for_tax_year(prop.td_number, 2023, db) is None

    with pytest.raises(HTTPException) as exc:
        save_property(
            _payment_payload(prop, tax_year="2023"),
            editing_id=prop.id,
            user={"id": 1, "username": "tester"},
            db_session=db,
        )

    assert exc.value.status_code == 422
    assert "not effective for tax year 2023" in exc.value.detail
    assert db.query(Payment).count() == 0
    assert db.query(PropertyBilling).count() == 0
