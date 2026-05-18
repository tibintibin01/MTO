# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock
from backend.services.property_service import save_property, SyncConflictError
from backend.models import Property

def test_occ_save_property_success(mock_db_session):
    """Verify property updates successfully when the client version matches the server version."""
    # Mock pre-existing property record in the database with version 1
    mock_prop = Property(
        id=101,
        td_number="TD-2023-001",
        owner_name="JUAN DELA CRUZ",
        assessed_value=100000.0,
        version=1,
        is_deleted=False
    )
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_prop
    
    # Input data matches the current server version (1)
    client_data = {
        "TD Number": "TD-2023-001",
        "Owner Name": "JUAN DELA CRUZ",
        "Assessed Value": "100000.00",
        "version": 1
    }
    
    # Execute the save orchestrator
    res = save_property(client_data, editing_id=101, user={"id": 1}, db_session=mock_db_session)
    
    # Assertions
    assert res is not None
    assert mock_prop.version == 2  # Correctly auto-incremented by OCC
    mock_db_session.flush.assert_called_once()

def test_occ_save_property_conflict(mock_db_session):
    """Verify property update throws SyncConflictError when the client version is older than the server version."""
    # Mock property record that was ALREADY updated on the server to version 2
    mock_prop = Property(
        id=101,
        td_number="TD-2023-001",
        owner_name="JUAN DELA CRUZ",
        assessed_value=100000.0,
        version=2,
        is_deleted=False
    )
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_prop
    
    # Client submits data based on older version 1
    client_data = {
        "TD Number": "TD-2023-001",
        "Owner Name": "JUAN DELA CRUZ MODIFIED",
        "Assessed Value": "100000.00",
        "version": 1
    }
    
    # Execute and verify that the OCC check correctly triggers SyncConflictError
    with pytest.raises(SyncConflictError) as exc_info:
        save_property(client_data, editing_id=101, user={"id": 1}, db_session=mock_db_session)
        
    assert exc_info.value.is_sync_conflict is True
    # Verify no version changes were persisted
    assert mock_prop.version == 2
