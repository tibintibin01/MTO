from urllib.parse import parse_qs, urlsplit

import ui.notifications as notifications


def test_notification_endpoint_includes_encoded_session_token(monkeypatch):
    monkeypatch.setattr(notifications, "get_token", lambda: "token+with/slashes=")
    monkeypatch.setattr(notifications, "is_token_expired", lambda token: False)

    listener = notifications.NotificationListener({})
    endpoint = listener._build_endpoint()
    parsed = urlsplit(endpoint)

    assert parsed.path == "/ws/notifications"
    assert parse_qs(parsed.query)["token"] == ["token+with/slashes="]


def test_notification_endpoint_waits_until_authenticated(monkeypatch):
    monkeypatch.setattr(notifications, "get_token", lambda: None)

    listener = notifications.NotificationListener({})

    assert listener._build_endpoint() is None


def test_notification_listener_start_is_idempotent(monkeypatch):
    monkeypatch.setattr(notifications, "get_token", lambda: None)
    listener = notifications.NotificationListener({})

    listener.start()
    first_thread = listener._thread
    listener.start()

    assert listener._thread is first_thread
    listener.stop()
    first_thread.join(timeout=2)
