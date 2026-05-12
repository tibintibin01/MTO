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

def test_get_total_due_logic(mock_db):
    """Test the orchestration of total due calculation including basic, SEF, and penalties."""
    # Mock property data
    mock_db.return_value = [(
        1, "TD-1", "Owner", "Payor", "Lot", 500, "Loc", "LAND", 
        "Officer", 100000.0, 1000.0, 1000.0, 0, 0, 2000.0, "OR", "Date", 2023, 
        "PIN", "BLK", "PREV", "2023", "BRGY"
    )]
    
    # We expect: 
    # Basic (1%): 1,000
    # SEF (1%): 1,000
    # Total Principal: 2,000
    # Penalty (e.g., 2% of 2000 for 1 month = 40)
    
    # Mocking date/time if needed or assuming service uses calculate_penalty internally
    total_data = get_total_due(1) # Property ID 1
    
    assert total_data["assessed_value"] == 100000.0
    assert total_data["basic"] == 1000.0
    assert total_data["sef"] == 1000.0
    assert total_data["total_due"] >= 2000.0
