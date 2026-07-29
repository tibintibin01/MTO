from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property, PropertyBilling, TaxPolicy
from backend.services.tax_year_readiness_service import get_tax_year_readiness


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
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _property(db, suffix):
    prop = Property(
        td_number=f"TD-READINESS-{suffix}",
        owner_name=f"OWNER {suffix}",
        assessed_value=100_000,
        effectivity_date="2023",
    )
    db.add(prop)
    db.flush()
    return prop


def test_outside_rollover_window_skips_warning_and_database_scan(db):
    result = get_tax_year_readiness(db, current_date=date(2026, 7, 29))

    assert result == {
        "season_active": False,
        "action_required": False,
        "status": "OUTSIDE_ROLLOVER_WINDOW",
        "office_date": "2026-07-29",
        "target_year": 2026,
    }


def test_december_warns_admin_to_prepare_next_tax_year(db):
    _property(db, "DEC")
    db.commit()

    result = get_tax_year_readiness(db, current_date=date(2026, 12, 15))

    assert result["target_year"] == 2027
    assert result["status"] == "PREPARATION_REQUIRED"
    assert result["action_required"] is True
    assert result["sync_available"] is False
    assert result["recommended_tab"] == "Tax Policy"
    assert "On or after January 1" in result["message"]


def test_january_reports_missing_current_year_billings(db):
    first = _property(db, "JAN-A")
    _property(db, "JAN-B")
    db.add(
        PropertyBilling(
            property_id=first.id,
            tax_year=2027,
            assessed_value=100_000,
        )
    )
    db.add(TaxPolicy(tax_year=2027))
    db.commit()

    result = get_tax_year_readiness(db, current_date=date(2027, 1, 2))

    assert result["status"] == "ACTION_REQUIRED"
    assert result["active_properties"] == 2
    assert result["billed_properties"] == 1
    assert result["missing_billing_properties"] == 1
    assert result["recommended_tab"] == "Database & Backup"
    assert "1 active properties" in result["message"]


def test_january_is_ready_when_policy_and_billing_coverage_are_complete(db):
    prop = _property(db, "READY")
    db.add(
        PropertyBilling(
            property_id=prop.id,
            tax_year=2027,
            assessed_value=100_000,
        )
    )
    db.add(TaxPolicy(tax_year=2027))
    db.commit()

    result = get_tax_year_readiness(db, current_date=date(2027, 1, 8))

    assert result["status"] == "READY"
    assert result["action_required"] is False
    assert result["missing_billing_properties"] == 0
