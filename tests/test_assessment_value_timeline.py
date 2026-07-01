from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property, PropertyAssessmentHistory, PropertyBilling
from backend.services.billing_service import repair_billing_assessed_value_snapshots
from backend.services.property_service import save_property


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

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
    db.add_all([
        PropertyBilling(
            property_id=prop.id,
            tax_year=year,
            assessed_value=7_098_520,
            amount_paid=0,
            is_archived=False,
        )
        for year in (2023, 2024, 2025, 2026, 2027)
    ])
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
        for row in db.query(PropertyBilling).filter(PropertyBilling.property_id == prop.id).all()
    }
    history = db.query(PropertyAssessmentHistory).filter(
        PropertyAssessmentHistory.property_id == prop.id,
        PropertyAssessmentHistory.tax_year == "2023",
    ).one()

    assert result["prior_assessment_sync"] == {
        "updated": 4,
        "years": [2023, 2024, 2025, 2026],
    }
    assert all(values[year] == 60_080 for year in (2023, 2024, 2025, 2026))
    assert values[2027] == 7_098_520
    assert float(history.assessed_value) == 60_080
    assert history.change_reason == "Historical assessment correction"


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
