from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.services import auth_service


def _session(session_id, user_id=7, device_name="MTO-CLIENT-01"):
    now = datetime(2026, 7, 20, 9, 30)
    return SimpleNamespace(
        id=session_id,
        user_id=user_id,
        device_name=device_name,
        client_ip="192.168.1.25",
        user_agent="MTO Desktop",
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=7),
        is_revoked=False,
        revoked_at=None,
    )


def test_active_sessions_expose_metadata_without_token_secret():
    db = MagicMock()
    row = _session(41)
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        row
    ]

    result = auth_service.get_active_sessions(
        row.user_id,
        {"id": row.user_id, "username": "kevin", "session_id": row.id},
        db,
    )

    assert result == [
        {
            "id": 41,
            "user_id": 7,
            "device_name": "MTO-CLIENT-01",
            "client_ip": "192.168.1.25",
            "user_agent": "MTO Desktop",
            "created_at": "2026-07-20T09:30:00",
            "last_used_at": "2026-07-20T09:30:00",
            "expires_at": "2026-07-27T09:30:00",
            "is_current": True,
        }
    ]
    assert "token" not in result[0]


def test_admin_cannot_revoke_current_session_from_session_manager():
    db = MagicMock()
    row = _session(52)
    db.query.return_value.filter.return_value.first.return_value = row

    with pytest.raises(ValueError, match="current session"):
        auth_service.revoke_managed_session(
            row.id,
            {"id": row.user_id, "username": "kevin", "session_id": row.id},
            db,
        )

    assert row.is_revoked is False
    db.commit.assert_not_called()


def test_admin_can_revoke_another_workstation_session():
    db = MagicMock()
    row = _session(63)
    db.query.return_value.filter.return_value.first.return_value = row

    with patch("backend.services.history_service.log_data_change") as audit:
        user_id = auth_service.revoke_managed_session(
            row.id,
            {"id": 1, "username": "kevin", "session_id": 10},
            db,
        )

    assert user_id == row.user_id
    assert row.is_revoked is True
    assert row.revoked_at is not None
    db.commit.assert_called_once()
    audit.assert_called_once()


def test_revoke_others_preserves_current_session_for_same_user():
    db = MagicMock()
    current = _session(70)
    other_a = _session(71)
    other_b = _session(72)

    active_query = MagicMock()
    other_query = MagicMock()
    db.query.return_value.filter.return_value = active_query
    active_query.filter.return_value = other_query
    other_query.all.return_value = [other_a, other_b]

    with patch("backend.services.history_service.log_data_change") as audit:
        count = auth_service.revoke_other_user_sessions(
            current.user_id,
            {
                "id": current.user_id,
                "username": "kevin",
                "session_id": current.id,
            },
            db,
        )

    assert count == 2
    assert current.is_revoked is False
    assert other_a.is_revoked is True
    assert other_b.is_revoked is True
    active_query.filter.assert_called_once()
    db.commit.assert_called_once()
    audit.assert_called_once()
