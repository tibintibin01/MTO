# -*- coding: utf-8 -*-
"""Request correlation, bounded metrics, and privacy-safe telemetry."""

import os
import time
from contextlib import nullcontext
from typing import Any

from fastapi import Request, Response

from utils import get_request_id, set_request_id
from utils.metrics import MetricsManager, normalize_endpoint_label
from utils.resilience import CircuitBreaker

try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False


SENTRY_DSN = os.getenv("SENTRY_DSN")
sentry_circuit = CircuitBreaker(
    name="SentryTelemetry", failure_threshold=3, recovery_timeout=300
)

_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "owner_name",
    "payor_name",
    "td_number",
    "pin",
    "or_number",
    "document",
    "file_content",
}


def _scrub_telemetry(value: Any, key: str = "") -> Any:
    key_lower = str(key).lower()
    if any(sensitive in key_lower for sensitive in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): _scrub_telemetry(item, str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_telemetry(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_telemetry(item) for item in value)
    return value


def scrub_sentry_event(event: dict, hint: dict | None = None) -> dict:
    """Remove credentials, request bodies, record URLs, and taxpayer fields."""
    scrubbed = _scrub_telemetry(event)
    request_data = scrubbed.get("request")
    if isinstance(request_data, dict):
        request_data["data"] = "[REDACTED]"
        request_data["query_string"] = "[REDACTED]"
        request_data["cookies"] = "[REDACTED]"
        request_data["url"] = "[REDACTED_ROUTE]"
        headers = request_data.get("headers")
        if isinstance(headers, dict):
            request_data["headers"] = {
                key: value
                for key, value in headers.items()
                if str(key).lower() in {"content-type", "user-agent"}
            }
    user = scrubbed.get("user")
    if isinstance(user, dict):
        scrubbed["user"] = {"id": user.get("id")} if user.get("id") else {}
    return scrubbed


if SENTRY_AVAILABLE and SENTRY_DSN:

    def init_sentry():
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[FastApiIntegration()],
            traces_sample_rate=0.05,
            profiles_sample_rate=0.0,
            send_default_pii=False,
            max_request_body_size="never",
            include_local_variables=False,
            before_send=scrub_sentry_event,
        )
        print("INFO: Sentry telemetry initialized with privacy filtering.")

    try:
        sentry_circuit.call(init_sentry)
    except Exception as exc:
        print("WARNING: Sentry initialization skipped: " f"{type(exc).__name__}")
elif not SENTRY_AVAILABLE and SENTRY_DSN:
    print("WARNING: Sentry SDK is unavailable. Telemetry is disabled.")


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return normalize_endpoint_label(template) if template else "<unmatched>"


async def observability_middleware(request: Request, call_next):
    start_time = time.perf_counter()
    supplied_id = request.headers.get("X-Request-ID") or request.headers.get(
        "X-Correlation-ID"
    )
    request_id = set_request_id(supplied_id)

    scope_context = (
        sentry_sdk.push_scope() if SENTRY_AVAILABLE and SENTRY_DSN else nullcontext()
    )
    with scope_context as scope:
        if scope is not None:
            scope.set_tag("request_id", request_id)

        response: Response | None = None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - start_time
            endpoint = _route_label(request)
            if endpoint != "/api/v1/metrics":
                MetricsManager.record_request(
                    method=request.method,
                    endpoint=endpoint,
                    status=status_code,
                    duration=duration,
                )
                MetricsManager.record_circuit_state(
                    "SentryTelemetry", sentry_circuit.get_state_numeric()
                )


async def maintenance_mode_middleware(request: Request, call_next):
    from utils import is_feature_enabled

    if is_feature_enabled("MAINTENANCE_MODE"):
        if not request.url.path.startswith("/docs") and not request.url.path.startswith(
            "/redoc"
        ):
            return Response(
                content="System is currently under maintenance. Please try again later.",
                status_code=503,
            )
    return await call_next(request)
