import requests
from io import BytesIO

import api_clients.api_helper as api
from api_clients.offline_manager import OfflineManager
from api_clients.sync_monitor import SyncMonitor


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self.content = b"{}"
        self.text = ""
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


def test_successful_request_recovers_online_state_and_uses_short_connect_timeout(
    monkeypatch,
):
    captured = {}

    def fake_request(*args, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(api.requests, "request", fake_request)
    api.set_connection_status("OFFLINE")

    result = api.api_request(
        "GET",
        "/",
        queue_offline=False,
        timeout=19,
    )

    assert result == {"ok": True}
    assert api.get_connection_status() == "ONLINE"
    assert captured["timeout"] == (api.DEFAULT_CONNECT_TIMEOUT, 19)


def test_repeated_connection_failures_transition_through_degraded(monkeypatch):
    def fail_request(*args, **kwargs):
        raise requests.exceptions.ConnectionError("server unavailable")

    monkeypatch.setattr(api.requests, "request", fail_request)
    api.set_connection_status("ONLINE")

    for attempt in range(1, api.CONNECTION_FAILURE_THRESHOLD + 1):
        try:
            api.api_request("GET", "/", queue_offline=False)
        except Exception as exc:
            assert "Cannot reach API server" in str(exc)
        else:
            raise AssertionError("Expected an API connection failure")

        expected = (
            "OFFLINE" if attempt == api.CONNECTION_FAILURE_THRESHOLD else "DEGRADED"
        )
        assert api.get_connection_status() == expected

    assert api.get_connection_failure_count() == api.CONNECTION_FAILURE_THRESHOLD
    assert api.get_connection_status() == "OFFLINE"


def test_success_resets_transient_connection_failures(monkeypatch):
    monkeypatch.setattr(
        api.requests,
        "request",
        lambda *args, **kwargs: _Response(),
    )
    api.set_connection_status("ONLINE")
    api.record_connection_failure()
    api.record_connection_failure()

    assert api.get_connection_status() == "DEGRADED"
    api.api_request("GET", "/readyz", queue_offline=False)

    assert api.get_connection_status() == "ONLINE"
    assert api.get_connection_failure_count() == 0


def test_health_probe_can_retry_immediately(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(status_code=200)

    monkeypatch.setattr("api_clients.sync_monitor.requests.get", fake_get)
    monitor = SyncMonitor(interval=10)

    assert monitor._check_connection() is True
    assert monitor._check_connection() is True
    assert len(calls) == 2
    assert calls[0][0].endswith("/readyz")
    assert calls[0][1]["timeout"] == (2, 3)
    assert calls[0][1]["verify"] is not None


def test_queue_flush_stops_after_first_connection_failure(monkeypatch):
    calls = []

    def fail_request(*args, **kwargs):
        calls.append((args, kwargs))
        api.record_connection_failure()
        raise Exception("Cannot reach API server")

    monkeypatch.setattr(api, "api_request", fail_request)
    monitor = SyncMonitor(interval=10)
    pending = [
        {"id": 1, "method": "POST", "endpoint": "/payments", "payload": {}},
        {"id": 2, "method": "POST", "endpoint": "/payments", "payload": {}},
    ]

    api.set_connection_status("ONLINE")
    monitor._flush_queue(pending)

    assert len(calls) == 1


def test_offline_queue_count_is_updated_without_requerying(tmp_path):
    manager = OfflineManager(str(tmp_path / "offline.db"))

    assert manager.get_queue_count() == 0
    assert manager.queue_action("POST", "/payments", {"amount": 100}) is True
    assert manager.get_queue_count() == 1

    action = manager.get_pending_actions()[0]
    manager.mark_as_synced(action["id"])
    assert manager.get_queue_count() == 0


def test_failed_file_upload_is_not_added_to_offline_queue(monkeypatch):
    def fail_request(*args, **kwargs):
        raise requests.exceptions.ConnectionError("server unavailable")

    queued_actions = []
    monkeypatch.setattr(api.requests, "request", fail_request)
    monkeypatch.setattr(
        api.manager,
        "queue_action",
        lambda *args, **kwargs: queued_actions.append((args, kwargs)),
    )

    try:
        api.api_request(
            "POST",
            "/system/import/validate?mode=payments",
            files={"file": ("payments.xlsx", BytesIO(b"test"))},
        )
    except Exception as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected an API connection failure")

    assert queued_actions == []
    assert "File uploads cannot be queued" in message
    assert "reselect the file" in message


def test_failed_json_write_remains_eligible_for_offline_queue(monkeypatch):
    def fail_request(*args, **kwargs):
        raise requests.exceptions.ConnectionError("server unavailable")

    queued_actions = []
    monkeypatch.setattr(api.requests, "request", fail_request)
    monkeypatch.setattr(
        api.manager,
        "queue_action",
        lambda *args: queued_actions.append(args) or True,
    )

    result = api.api_request("POST", "/payments", data={"amount": 100})

    assert result["status"] == "queued"
    assert queued_actions == [("POST", "/payments", {"amount": 100})]
