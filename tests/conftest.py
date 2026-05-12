# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Add the project root to sys.path so we can import services
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

@pytest.fixture
def mock_db():
    """
    Fixture to mock db_manager.db_query globally for tests.
    Prevents any actual database interaction.
    """
    with patch('db_manager.db_query') as mock:
        yield mock

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
        "is_deleted": 0
    }
