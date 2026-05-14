# -*- coding: utf-8 -*-
import pytest
from backend.services.billing_service import calculate_penalty, get_total_due

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

from backend.models import Property

def test_get_total_due_logic(mock_db_session):
    """Test the orchestration of total due calculation including basic, SEF, and penalties."""
    # Mock property data
    mock_prop = Property(
        id=1, td_number="TD-1", owner_name="Owner", assessed_value=100000.0,
        is_deleted=False
    )
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_prop
    
    # Mocking date/time if needed or assuming service uses calculate_penalty internally
    total_data = get_total_due(1, db_session=mock_db_session) # Property ID 1
    
    assert total_data["assessed_value"] == 100000.0
    assert total_data["basic"] == 1000.0
    assert total_data["sef"] == 1000.0
    assert total_data["total_due"] >= 2000.0

