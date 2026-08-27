from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property, PropertyBilling
from backend.services.billing_sync_service import (
    sync_property_billing_years,
    sync_verified_duplicate_td_billings,
)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _property(td_number, owner, effectivity="2023-01-01"):
    return Property(
        td_number=td_number,
        owner_name=owner,
        barangay="DINADIAWAN",
        location="DINADIAWAN",
        kind_of_property="RESIDENTIAL LOT",
        assessed_value=50_000,
        effectivity_date=effectivity,
    )


def test_single_property_sync_creates_each_missing_year_once():
    engine, db = _session()
    try:
        prop = _property("06-0012-00094", "FIRST OWNER")
        db.add(prop)
        db.flush()

        first = sync_property_billing_years(prop, db, through_year=2026)
        db.flush()
        second = sync_property_billing_years(prop, db, through_year=2026)

        years = [
            row.tax_year
            for row in db.query(PropertyBilling)
            .filter(PropertyBilling.property_id == prop.id)
            .order_by(PropertyBilling.tax_year.asc())
            .all()
        ]
        assert years == [2023, 2024, 2025, 2026]
        assert first["records_created"] == 4
        assert second["records_created"] == 0
        assert second["records_skipped"] == 4
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_future_effective_property_is_not_billed_early():
    engine, db = _session()
    try:
        prop = _property("06-0012-00999", "FUTURE OWNER", effectivity="2027-01-01")
        db.add(prop)
        db.flush()

        result = sync_property_billing_years(prop, db, through_year=2026)
        db.flush()

        assert result["future_effective"] is True
        assert result["records_created"] == 0
        assert db.query(PropertyBilling).count() == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_verified_duplicate_repair_initializes_both_property_accounts():
    engine, db = _session()
    try:
        first = _property("06-0012-00094", "FIRST OWNER", effectivity="2026-01-01")
        second = _property("06-0012-00094", "SECOND OWNER", effectivity="2026-01-01")
        first.duplicate_td_verified = True
        second.duplicate_td_verified = True
        db.add_all([first, second])
        db.flush()

        result = sync_verified_duplicate_td_billings(db, through_year=2026)
        db.flush()

        rows = (
            db.query(PropertyBilling).order_by(PropertyBilling.property_id.asc()).all()
        )
        assert result["properties_scanned"] == 2
        assert result["records_created"] == 2
        assert {row.property_id for row in rows} == {first.id, second.id}
        assert {row.tax_year for row in rows} == {2026}
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
