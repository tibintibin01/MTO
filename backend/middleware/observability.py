# -*- coding: utf-8 -*-
import os
import time
from fastapi import Request, Response
from utils.resilience import CircuitBreaker
from utils.metrics import MetricsManager
from utils import set_request_id, get_request_id

try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False

# Initialize Sentry Telemetry with Circuit Protection
SENTRY_DSN = os.getenv("SENTRY_DSN")
sentry_circuit = CircuitBreaker(name="SentryTelemetry", failure_threshold=3, recovery_timeout=300)

if SENTRY_AVAILABLE and SENTRY_DSN:
    def init_sentry():
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[FastApiIntegration()],
            # Reduced tracing rate as per architectural review recommendation to avoid rate limits
            traces_sample_rate=0.2,
            profiles_sample_rate=0.2,
        )
        print(f"INFO: Sentry Telemetry INITIALIZED: {SENTRY_DSN[:20]}...")
    
    try:
        sentry_circuit.call(init_sentry)
    except Exception as e:
        print(f"WARNING: Sentry Initialization skipped due to circuit trip: {e}")
elif not SENTRY_AVAILABLE and SENTRY_DSN:
    print("WARNING: Sentry DSN provided but sentry_sdk NOT FOUND. Telemetry disabled.")


async def observability_middleware(request: Request, call_next):
    start_time = time.perf_counter()
    req_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
    set_request_id(req_id)
    
    if SENTRY_AVAILABLE and SENTRY_DSN:
        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("request_id", get_request_id())
            
    response: Response = await call_next(request)
    duration = time.perf_counter() - start_time
    
    if not request.url.path.endswith("/metrics"):
        MetricsManager.record_request(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code,
            duration=duration
        )
        MetricsManager.record_circuit_state("SentryTelemetry", sentry_circuit.get_state_numeric())
        
    response.headers["X-Request-ID"] = get_request_id()
    return response


async def maintenance_mode_middleware(request: Request, call_next):
    from utils import is_feature_enabled
    if is_feature_enabled("MAINTENANCE_MODE"):
        if not request.url.path.startswith("/docs") and not request.url.path.startswith("/redoc"):
             return Response(
                content="System is currently under maintenance. Please try again later.",
                status_code=503
            )
    return await call_next(request)
