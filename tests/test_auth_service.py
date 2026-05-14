# -*- coding: utf-8 -*-
import pytest
from backend.services.auth_service import has_permission, create_user
from unittest.mock import MagicMock

def test_has_permission_admin():
    """Verify that admin users can access sensitive features."""
    admin_user = {"role": "admin", "is_active": 1}
    assert has_permission(admin_user, "property_delete") is True
    assert has_permission(admin_user, "manage_users") is True

def test_has_permission_viewer():
    """Verify that viewer users are restricted."""
    viewer = {"role": "viewer", "is_active": 1}
    assert has_permission(viewer, "property_edit") is False
    assert has_permission(viewer, "report_view") is True

def test_create_user_mocked(mock_db_session):
    """Test user creation logic without touching the DB."""
    admin_context = {"username": "superuser", "role": "ADMIN"}
    
    try:
        create_user("newguy", "New Guy", "password123", "CASHIER", admin_context, db_session=mock_db_session)
    except Exception as e:
        pytest.fail(f"create_user raised {e} unexpectedly!")
    
    assert mock_db_session.add.called
    assert mock_db_session.commit.called

