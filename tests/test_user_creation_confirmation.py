from inspect import signature
from pathlib import Path
import sys

DESKTOP_DIR = Path(__file__).resolve().parents[1] / "clients" / "desktop"
if str(DESKTOP_DIR) not in sys.path:
    sys.path.insert(0, str(DESKTOP_DIR))

from unittest.mock import patch

from api_clients import auth_service
from ui.users import _user_creation_confirmation_message


def test_user_creation_confirmation_summarizes_account_without_password():
    message = _user_creation_confirmation_message(
        "Juan Dela Cruz",
        "juandc",
        "encoder",
    )

    assert "Full name: Juan Dela Cruz" in message
    assert "Username: juandc" in message
    assert "Role: ENCODER" in message
    assert "not displayed" in message
    assert "password" not in signature(
        _user_creation_confirmation_message
    ).parameters


def test_create_user_requires_live_server_confirmation():
    response = {"status": "created", "user_id": 17}

    with patch.object(
        auth_service,
        "api_request",
        return_value=response,
    ) as request:
        result = auth_service.create_user(
            "Juan Dela Cruz",
            "juandc",
            "ValidPassword9!",
            "encoder",
        )

    assert result == response
    request.assert_called_once_with(
        "POST",
        "/users",
        data={
            "full_name": "Juan Dela Cruz",
            "username": "juandc",
            "password": "ValidPassword9!",
            "role": "encoder",
        },
        queue_offline=False,
    )
