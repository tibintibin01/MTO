import asyncio
import re
from types import SimpleNamespace

import pytest
from fastapi import Request, Response

from backend.middleware.observability import (
    observability_middleware,
    scrub_sentry_event,
)
from utils import sanitize_request_id
from utils.metrics import MetricsManager, normalize_endpoint_label


def _request(path: str, request_id: str = "safe-id") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"x-request-id", request_id.encode())],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 443),
            "root_path": "",
            "route": SimpleNamespace(path="/properties/{property_id}"),
        }
    )


def test_request_ids_are_bounded_and_log_safe():
    assert sanitize_request_id("client_123-OK") == "client_123-OK"

    generated = sanitize_request_id("x" * 500)

    assert generated != "x" * 500
    assert re.fullmatch(r"[0-9a-f-]{36}", generated)


def test_metric_endpoint_normalization_removes_record_ids():
    assert normalize_endpoint_label("/properties/123456") == "/properties/{id}"
    assert (
        normalize_endpoint_label("/properties/{property_id}")
        == "/properties/{property_id}"
    )
    assert normalize_endpoint_label("not-a-path") == "<unmatched>"


def test_middleware_records_template_and_failure_latency(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        MetricsManager,
        "record_request",
        lambda **kwargs: recorded.append(kwargs),
    )
    monkeypatch.setattr(MetricsManager, "record_circuit_state", lambda *args: None)

    async def fail(_request):
        raise RuntimeError("simulated")

    with pytest.raises(RuntimeError, match="simulated"):
        asyncio.run(
            observability_middleware(
                _request("/properties/987654"),
                fail,
            )
        )

    assert recorded[0]["endpoint"] == "/properties/{property_id}"
    assert recorded[0]["status"] == 500
    assert recorded[0]["duration"] >= 0


def test_middleware_replaces_invalid_client_request_id(monkeypatch):
    monkeypatch.setattr(MetricsManager, "record_request", lambda **kwargs: None)
    monkeypatch.setattr(MetricsManager, "record_circuit_state", lambda *args: None)

    async def okay(_request):
        return Response("ok")

    response = asyncio.run(
        observability_middleware(
            _request("/properties/123", request_id="bad id with spaces"),
            okay,
        )
    )

    assert re.fullmatch(r"[0-9a-f-]{36}", response.headers["X-Request-ID"])


def test_sentry_scrubber_removes_credentials_and_taxpayer_data():
    event = {
        "request": {
            "url": "https://server/properties/06-0012-00094?owner=Citizen",
            "data": {"owner_name": "Citizen", "amount": 100},
            "query_string": "owner=Citizen",
            "cookies": {"access_token": "secret"},
            "headers": {
                "Authorization": "Bearer secret",
                "User-Agent": "test",
            },
        },
        "extra": {"td_number": "06-0012-00094", "password": "secret"},
        "user": {"id": "7", "username": "operator", "ip_address": "10.0.0.7"},
    }

    scrubbed = scrub_sentry_event(event)

    assert scrubbed["request"]["url"] == "[REDACTED_ROUTE]"
    assert scrubbed["request"]["data"] == "[REDACTED]"
    assert scrubbed["request"]["headers"] == {"User-Agent": "test"}
    assert scrubbed["extra"]["td_number"] == "[REDACTED]"
    assert scrubbed["user"] == {"id": "7"}
