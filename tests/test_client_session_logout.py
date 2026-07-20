from api_clients import auth_service
from api_clients import api_helper


def test_logout_revokes_refresh_session_and_clears_local_tokens(monkeypatch):
    calls = []

    def fake_api_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        return {"message": "Successfully logged out"}

    monkeypatch.setattr(auth_service, "api_request", fake_api_request)
    api_helper.set_token("access-token")
    api_helper.set_refresh_token("refresh-token")

    auth_service.logout()

    assert calls == [
        (
            "POST",
            "/api/auth/logout",
            {
                "data": {"refresh_token": "refresh-token"},
                "queue_offline": False,
                "timeout": 10,
            },
        )
    ]
    assert api_helper.get_token() is None
    assert api_helper.get_refresh_token() is None


def test_logout_clears_local_tokens_when_server_revoke_fails(monkeypatch):
    def fail_api_request(*args, **kwargs):
        raise Exception("server unavailable")

    monkeypatch.setattr(auth_service, "api_request", fail_api_request)
    api_helper.set_token("access-token")
    api_helper.set_refresh_token("refresh-token")

    auth_service.logout()

    assert api_helper.get_token() is None
    assert api_helper.get_refresh_token() is None
