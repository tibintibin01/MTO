# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Add the project root to sys.path so we can import services
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

@pytest.fixture
def mock_db_session():
    """
    Fixture to provide a mock SQLAlchemy Session.
    """
    session = MagicMock()
    # Mock common session methods
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    return session

@pytest.fixture
def sample_property():
    """Returns a dummy property record for testing."""
    return {
        "id": 101,
        "td_number": "TD-2023-001",
        "pin": "123-45-678-00-001",
        "owner_name": "JUAN DELA CRUZ",
        "assessed_value": 100000.0,
        "barangay": "NORTH POBLACION",
        "effectivity_date": "2023-01-01",
        "deleted_at": None
    }
