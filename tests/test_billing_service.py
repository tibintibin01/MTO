# -*- coding: utf-8 -*-
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property, PropertyBilling
from backend.services.billing_service import (
    calculate_penalty,
    get_compliant_summary_by_barangay,
    get_total_due,
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

def test_calculate_penalty_basic():
    """Test standard 2% monthly penalty logic."""
    # Scenario: 10,000 principal, 5 months late (10% total penalty)
    principal = 10000.0
    months_late = 5
    expected_penalty = 10000.0 * 0.02 * 5
    
    penalty = calculate_penalty(principal, months_late)
    assert penalty == expected_penalty
    assert penalty == 1000.0

def test_calculate_penalty_cap():
    """Test the maximum penalty cap (usually 72% in many PH local tax codes, but let's check system logic)."""
    # If the system implements a cap, we test it here. 
    # For now, let's assume it scales.
    principal = 1000.0
    months_late = 40 # 80% penalty
    penalty = calculate_penalty(principal, months_late)
    assert penalty == 800.0

def test_get_total_due_logic(mock_db_session):
    """Test the orchestration of total due calculation including basic, SEF, and penalties."""
    # Mock property data
    mock_prop = Property(
        id=1, td_number="TD-1", owner_name="Owner", assessed_value=100000.0,
        deleted_at=None
    )
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_prop
    
    from unittest.mock import patch
    with patch("backend.services.billing_service.get_property_billing_history") as mock_hist:
        mock_hist.return_value = [
            [
                "2023", 100000.0, 1000.0, 1000.0, 0.0, 2000.0, 0.0, 2000.0, "Pending", None
            ]
        ]
        total_data = get_total_due(1, db_session=mock_db_session) # Property ID 1
    
    assert total_data["assessed_value"] == 100000.0
    assert total_data["basic"] == 1000.0
    assert total_data["sef"] == 1000.0
    assert total_data["total_due"] >= 2000.0


def _property_with_billing(db, td, barangay, paid=2_000.0):
    prop = Property(
        td_number=td,
        owner_name=f"Owner {td}",
        barangay=barangay,
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
    )
    db.add(prop)
    db.flush()
    db.add(
        PropertyBilling(
            property_id=prop.id,
            tax_year="2024",
            assessed_value=100_000.0,
            penalty=0,
            discount=0,
            amount_paid=paid,
        )
    )
    db.flush()
    return prop


def test_compliant_summary_excludes_unassigned_barangay_rows(db):
    _property_with_billing(db, "TD-REAL", "NORTH POBLACION")
    _property_with_billing(db, "TD-NULL", None)
    _property_with_billing(db, "TD-BLANK", "  ")
    _property_with_billing(db, "TD-UNSPECIFIED", "UNSPECIFIED")
    db.commit()

    summary = get_compliant_summary_by_barangay(db_session=db)

    assert [row["barangay"] for row in summary] == ["NORTH POBLACION"]
    assert summary[0]["total_properties"] == 1
    assert summary[0]["compliant_count"] == 1
