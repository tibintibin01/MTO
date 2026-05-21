import os
import sys
from typing import List, Optional

try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False

from fastapi import (
    FastAPI,
    Request,
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from utils.config import config as mto_config
from utils.resilience import CircuitBreaker
from utils.metrics import MetricsManager
from utils.logger import mto_logger
from backend.deps import limiter, manager

# Initialize Sentry Telemetry with Circuit Protection
SENTRY_DSN = os.getenv("SENTRY_DSN")
sentry_circuit = CircuitBreaker(name="SentryTelemetry", failure_threshold=3, recovery_timeout=300)



if SENTRY_AVAILABLE and SENTRY_DSN:
    def init_sentry():
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[FastApiIntegration()],
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
        )
        print(f"INFO: Sentry Telemetry INITIALIZED: {SENTRY_DSN[:20]}...")
    
    try:
        sentry_circuit.call(init_sentry)
    except Exception as e:
        print(f"WARNING: Sentry Initialization skipped due to circuit trip: {e}")
elif not SENTRY_AVAILABLE and SENTRY_DSN:
    print("WARNING: Sentry DSN provided but sentry_sdk NOT FOUND. Telemetry disabled.")



app = FastAPI(
    title="Municipal Revenue System",
    description="Professional Enterprise API for Municipal Revenue Operations. Includes Property Assessment, Billing, and Collection management with high-entropy security controls.",
    version="2.1.0",
    contact={
        "name": "MTO IT Support",
        "email": "support@mto.gov.ph",
    },
    license_info={
        "name": "Proprietary",
    },
    docs_url="/docs",
    redoc_url="/redoc"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------------------------
# API VERSIONING POLICY
# ---------------------------------------------------------------------------
# All routes in this application are considered v1.
# URL versioning is NOT enforced at the path level for internal routes
# (e.g. /properties, /payments) because the desktop client and the backend
# are deployed together and versioned as a unit.
#
# The Next.js frontend proxies /api/v1/* → backend root, so frontend calls
# are already version-prefixed at the proxy layer.
#
# Explicit /api/v1/ prefixes are used only for:
#   - Auth endpoints (/api/auth/login, /api/auth/logout, /api/auth/csrf)
#   - Analytics dashboard (/api/analytics/dashboard)
#   - System utilities (/api/v1/metrics, /api/v1/system/undo)
#   - Version info (/api/v1/version)
#
# Every response carries X-API-Version and X-API-Deprecation-Policy headers
# so clients can detect version mismatches without parsing URLs.
# ---------------------------------------------------------------------------

API_VERSION = "1.0"
API_MIN_CLIENT_VERSION = "1.0"  # Bump this to force client upgrades

@app.middleware("http")
async def api_version_middleware(request: Request, call_next):
    """Injects API version headers into every response."""
    response: Response = await call_next(request)
    response.headers["X-API-Version"] = API_VERSION
    response.headers["X-API-Min-Client-Version"] = API_MIN_CLIENT_VERSION
    return response

# --- IDEMPOTENCY MIDDLEWARE ---
# Protects POST/PUT requests against duplicate execution from double-clicks
# or network retries. Clients send X-Idempotency-Key: <uuid> with each
# state-changing request. If the same key arrives again within 24 hours,
# the cached response is returned without re-executing the handler.
#
# Only applies to paths that create or modify financial records.
# Read-only GET requests and auth endpoints are excluded.

_IDEMPOTENCY_PATHS = (
    "/properties",
    "/payments",
    "/billing",
    "/users",
)

@app.middleware("http")
async def idempotency_middleware(request: Request, call_next):
    from fastapi.responses import JSONResponse

    # Only apply to state-changing methods on financial paths
    if request.method not in ("POST", "PUT", "PATCH"):
        return await call_next(request)

    path = request.url.path
    if not any(path.startswith(p) for p in _IDEMPOTENCY_PATHS):
        return await call_next(request)

    idempotency_key = request.headers.get("X-Idempotency-Key")
    if not idempotency_key:
        # No key provided — process normally (backwards compatible)
        return await call_next(request)

    # Validate key format — must be a UUID to prevent injection
    import re
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", idempotency_key.lower()):
        return JSONResponse(
            status_code=400,
            content={"code": "VALIDATION_ERROR", "detail": "X-Idempotency-Key must be a valid UUID v4."},
        )

    # Check for an existing non-expired response for this key
    try:
        from backend.database import SessionLocal
        from backend.models import IdempotencyKey
        from datetime import datetime, timezone
        import json

        with SessionLocal() as db:
            existing = db.query(IdempotencyKey).filter(
                IdempotencyKey.key == idempotency_key,
                IdempotencyKey.expires_at > datetime.now(timezone.utc),
            ).first()

            if existing:
                mto_logger.info(
                    f"Idempotency cache hit for key {idempotency_key[:8]}...",
                    method=request.method,
                    path=path,
                )
                cached_body = json.loads(existing.response_body) if existing.response_body else {}
                return JSONResponse(
                    status_code=existing.status_code,
                    content=cached_body,
                    headers={"X-Idempotency-Replayed": "true"},
                )
    except Exception as e:
        # DB error checking idempotency — log and proceed rather than blocking
        mto_logger.warning(f"Idempotency check failed, proceeding: {e}")
        return await call_next(request)

    # Key is new — process the request and cache the response
    response = await call_next(request)

    # Only cache successful responses (2xx)
    if 200 <= response.status_code < 300:
        try:
            from backend.database import SessionLocal
            from backend.models import IdempotencyKey
            from datetime import datetime, timedelta, timezone
            import json

            # Read the response body — we need to consume and re-wrap it
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk

            body_str = body_bytes.decode("utf-8")

            with SessionLocal() as db:
                record = IdempotencyKey(
                    key=idempotency_key,
                    method=request.method,
                    path=path,
                    status_code=response.status_code,
                    response_body=body_str,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                )
                db.add(record)
                db.commit()

            # Re-wrap the consumed body into a new response
            from starlette.responses import Response as StarletteResponse
            return StarletteResponse(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception as e:
            mto_logger.warning(f"Failed to cache idempotency response: {e}")

    return response

# --- REQUEST TIMEOUT MIDDLEWARE ---
# Protects against slow queries or hung requests blocking the server indefinitely.
# Returns HTTP 504 Gateway Timeout if a request exceeds the limit.
#
# Per-path overrides allow long-running operations (bulk import, backup,
# PDF generation) to have a higher limit than normal API calls.
#
# Timeouts (seconds):
#   /system/backup/trigger  → 600s  (backup can take several minutes)
#   /system/import/*        → 300s  (bulk import of large Excel files)
#   /billing/bulk-soa-pdf   → 120s  (multi-property PDF generation)
#   /system/restore         → 600s  (DB restore)
#   everything else         → 30s   (normal API calls)

_DEFAULT_TIMEOUT = 30
_PATH_TIMEOUTS = {
    "/system/backup/trigger": 600,
    "/system/restore":        600,
    "/system/import/commit":  300,
    "/system/import/validate":300,
    "/billing/bulk-soa-pdf":  120,
    # NOTE: /properties/import-assessment was removed (replaced by async job queue).
    # Its timeout entry is intentionally absent.
}

@app.middleware("http")
async def request_timeout_middleware(request: Request, call_next):
    import asyncio
    from fastapi.responses import JSONResponse

    path = request.url.path
    timeout = _DEFAULT_TIMEOUT
    for prefix, t in _PATH_TIMEOUTS.items():
        if path.startswith(prefix):
            timeout = t
            break

    try:
        return await asyncio.wait_for(call_next(request), timeout=timeout)
    except asyncio.TimeoutError:
        mto_logger.warning(
            f"Request timeout after {timeout}s",
            method=request.method,
            path=path,
            ip=request.client.host if request.client else "unknown",
        )
        from backend.error_codes import error_response, E
        return error_response(
            E.TIMEOUT,
            f"Request timed out after {timeout} seconds. "
            "The operation may still be running in the background. "
            "Please refresh and check if the action completed.",
            request=request,
        )

# --- OBSERVABILITY & TELEMETRY MIDDLEWARE ---
@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    from utils import set_request_id, get_request_id
    import time
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

@app.middleware("http")
async def maintenance_mode_middleware(request: Request, call_next):
    from utils import is_feature_enabled
    if is_feature_enabled("MAINTENANCE_MODE"):
        if not request.url.path.startswith("/docs") and not request.url.path.startswith("/redoc"):
             return Response(
                content="System is currently under maintenance. Please try again later.",
                status_code=503
            )
    return await call_next(request)

# CORS Configuration
# Origins are read from the environment so the server IP doesn't need to be
# hardcoded. Set CORS_ORIGIN in .env to add your office network address.
# run_system.bat writes this automatically on every startup, so changing
# the server PC requires no code changes — just re-run run_system.bat.
import os as _os
_extra_origin = _os.getenv("CORS_ORIGIN", "").strip()

origins = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8001",
    "https://localhost:8001",
    "http://localhost:3000",
]

# Allow an extra origin configured via .env (written automatically by run_system.bat)
if _extra_origin and _extra_origin not in origins:
    origins.append(_extra_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    mto_logger.info("API Server started successfully.")
    # DB is guaranteed to be up at this point (wait_for_db ran before uvicorn).
    # Refresh dashboard stats so the first page load shows real numbers.
    try:
        from backend.database import SessionLocal
        from backend.services.stats_service import refresh_system_stats
        with SessionLocal() as db:
            refresh_system_stats(db_session=db)
        mto_logger.info("Dashboard stats refreshed successfully on startup.")
    except Exception as e:
        # Non-fatal — stats will refresh on the next request
        mto_logger.warning(f"Could not refresh dashboard stats on startup: {e}")

    # Start the background job worker thread
    from backend.services.job_service import start_worker
    start_worker()
    mto_logger.info("Background job worker started.")


from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = exc.body
    if hasattr(body, "items"):
        try:
            body = dict(body)
        except:
            body = str(body)
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "detail": "Request validation failed.",
            "errors": exc.errors(),
            "request_id": _get_req_id(),
        },
    )

from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Global HTTP exception handler — ensures every error response has a
    structured `code` field regardless of where the exception was raised.

    If the exception detail is already a dict with a `code` key (raised via
    raise_api_error()), it is passed through unchanged.
    If it is a plain string (legacy HTTPException), a code is inferred from
    the HTTP status so the client always gets a machine-parseable response.
    """
    from utils import get_request_id

    detail = exc.detail

    # Already structured — raised via raise_api_error()
    if isinstance(detail, dict) and "code" in detail:
        body = {**detail, "request_id": get_request_id()}
        return JSONResponse(status_code=exc.status_code, content=body)

    # Plain string detail — infer a code from the status
    _inferred = {
        400: "BAD_REQUEST",
        401: "AUTH_TOKEN_INVALID",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        503: "DB_UNAVAILABLE",
        504: "TIMEOUT",
    }
    code = _inferred.get(exc.status_code, "INTERNAL_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "detail": str(detail) if detail else "An error occurred.",
            "request_id": get_request_id(),
        },
    )

def _get_req_id() -> str:
    try:
        from utils import get_request_id
        return get_request_id()
    except Exception:
        return "SYSTEM"


# --- Import Routers ---
from backend.routes import auth, users, properties, payments, billing, system, public
from backend.routes import jobs

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(properties.router)
app.include_router(payments.router)
app.include_router(billing.router)
app.include_router(system.router)
app.include_router(public.router)
app.include_router(jobs.router)

# Serve static files (analytics dashboard HTML, etc.)
# Must be mounted after all API routers so API paths take precedence.
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
async def root():
    return {"message": "Municipal Revenue System API is running", "status": "online"}

@app.get("/api/v1/version")
async def api_version():
    """
    Returns the current API version and build info.
    The desktop client calls this on startup to detect version mismatches
    between the client app and the server.
    """
    import platform
    return {
        "api_version": API_VERSION,
        "min_client_version": API_MIN_CLIENT_VERSION,
        "app_name": "MTO Treasury System",
        "app_version": "2.1.0",
        "python_version": platform.python_version(),
        "status": "online",
    }

if __name__ == "__main__":
    import uvicorn
    from backend.database import wait_for_db

    # Wait for MariaDB to be ready before accepting traffic.
    # On Windows with XAMPP, the DB takes 5–15s to start after boot.
    # This prevents the server from crashing due to a startup race condition.
    wait_for_db(max_attempts=10, base_delay=2.0)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_path = os.path.join(base_dir, "certs", "cert.pem")
    key_path = os.path.join(base_dir, "certs", "key.pem")
    if os.path.exists(cert_path) and os.path.exists(key_path):
        print("Starting Secure API (HTTPS) with CORS Enabled...")
        uvicorn.run(app, host="0.0.0.0", port=8001, ssl_keyfile=key_path, ssl_certfile=cert_path)
    else:
        print("Starting Standard API (HTTP) - SSL Certs not found.")
        uvicorn.run(app, host="0.0.0.0", port=8001)
