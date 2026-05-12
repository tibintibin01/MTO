# -*- coding: utf-8 -*-
import pytest
from backend.services.auth_service import has_permission, create_user
from unittest.mock import MagicMock

def test_has_permission_admin():
    """Verify that ADMIN users can access sensitive features."""
    admin_user = {"role": "ADMIN", "is_active": 1}
    assert has_permission(admin_user, "delete_property") is True
    assert has_permission(admin_user, "manage_users") is True

def test_has_permission_viewer():
    """Verify that VIEW_ONLY users are restricted."""
    viewer = {"role": "VIEW_ONLY", "is_active": 1}
    assert has_permission(viewer, "edit_property") is False
    assert has_permission(viewer, "view_reports") is True

def test_create_user_mocked(mock_db):
    """Test user creation logic without touching the DB."""
    # Mock existing user check to return None (no duplicate)
    mock_db.return_value = [] 
    
    admin_context = {"username": "superuser", "role": "ADMIN"}
    
    # We aren't testing the actual INSERT, just that the service doesn't crash 
    # and calls the DB correctly.
    try:
        create_user("newguy", "New Guy", "password123", "CASHIER", admin_context)
    except Exception as e:
        pytest.fail(f"create_user raised {e} unexpectedly!")
    
    assert mock_db.called
    # Check if INSERT was called (args[0] is the query)
    args, kwargs = mock_db.call_args
    assert "INSERT INTO users" in args[0]
