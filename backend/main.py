import os
from contextlib import asynccontextmanager

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

from utils.resilience import CircuitBreaker
from utils.metrics import MetricsManager
from utils.logger import mto_logger
from backend.deps import limiter, user_limiter, manager

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


# ---------------------------------------------------------------------------
# WIN 6: Replace deprecated @app.on_event("startup") with lifespan context
# manager. @app.on_event is deprecated since FastAPI 0.93 and will be removed.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Startup logic runs before `yield`; shutdown logic runs after.
    """
    # --- STARTUP ---
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

    yield  # Application runs here

    # --- SHUTDOWN ---
    mto_logger.info("API Server shutting down — draining workers and closing DB pool.")
    try:
        from backend.database import engine
        engine.dispose()
        mto_logger.info("DB connection pool disposed cleanly.")
    except Exception as e:
        mto_logger.warning(f"DB pool dispose on shutdown failed: {e}")

    if SENTRY_AVAILABLE and SENTRY_DSN:
        try:
            sentry_sdk.flush(timeout=2)
        except Exception:
            pass



app = FastAPI(
    title="Municipal Revenue System",
    description="Professional Enterprise API for Municipal Revenue Operations. Includes Property Assessment, Billing, and Collection management with high-entropy security controls.",
    version="2.1.0",
    lifespan=lifespan,
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
app.state.user_limiter = user_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# SECURITY RESPONSE HEADERS MIDDLEWARE
# ---------------------------------------------------------------------------
# Applied to every response. These headers instruct browsers to enforce
# security policies that reduce the attack surface of the public portal.
#
# X-Content-Type-Options: nosniff
#   Prevents browsers from MIME-sniffing a response away from the declared
#   content-type. Stops certain XSS vectors via crafted file uploads.
#
# X-Frame-Options: DENY
#   Prevents the portal from being embedded in an iframe on another site.
#   Blocks clickjacking attacks.
#
# X-XSS-Protection: 0
#   Disables the legacy browser XSS filter. Modern browsers use CSP instead;
#   the old filter can introduce vulnerabilities of its own.
#
# Referrer-Policy: strict-origin-when-cross-origin
#   Sends the full URL as referrer for same-origin requests, only the origin
#   for cross-origin HTTPS→HTTPS, and nothing for HTTPS→HTTP. Prevents
#   taxpayer TD numbers from leaking in referrer headers to third-party sites.
#
# Permissions-Policy
#   Disables browser features the portal never uses (camera, microphone,
#   geolocation). Reduces the attack surface if a script injection occurs.
#
# Content-Security-Policy
#   Restricts which sources can load scripts, styles, and other resources.
#   'self' only — no CDNs, no inline scripts (except Next.js needs 'unsafe-inline'
#   for its hydration scripts, which is why this is set to a permissive default
#   here and tightened in the nginx config for the frontend).

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """
    Injects security response headers into every API response.

    CSP is intentionally NOT set here — the backend only serves JSON, not HTML.
    CSP is only meaningful on HTML pages and is handled by Next.js (next.config.js).
    Setting CSP on JSON responses is harmless but confusing and can interfere
    with browser preflight handling in some edge cases.
    """
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    # HSTS: instruct browsers to only connect via HTTPS for 1 year.
    # includeSubDomains ensures subdomains are also HTTPS-only.
    # Only set when the request arrived over TLS to avoid breaking HTTP dev setups.
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# ---------------------------------------------------------------------------
# REQUEST BODY SIZE LIMIT MIDDLEWARE
# ---------------------------------------------------------------------------
# Rejects requests whose Content-Length exceeds the configured maximum.
# Without this, a malicious client can send a multi-GB payload that exhausts
# memory or blocks the event loop while the body is being read.
#
# Limits:
#   /system/import/*  → 50 MB  (bulk Excel imports can be large)
#   everything else   → 10 MB  (generous for JSON payloads)
#
# Note: This checks Content-Length only. Chunked-encoded requests without
# a Content-Length header are not blocked here — uvicorn's own limits apply.
# ---------------------------------------------------------------------------

_BODY_LIMIT_DEFAULT = 10 * 1024 * 1024   # 10 MB
_BODY_LIMIT_IMPORT  = 50 * 1024 * 1024   # 50 MB for bulk imports

@app.middleware("http")
async def request_body_size_middleware(request: Request, call_next):
    """Rejects oversized request bodies before they reach route handlers."""
    from fastapi.responses import JSONResponse as _JSONResponse

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            size = int(content_length)
        except ValueError:
            return _JSONResponse(
                status_code=400,
                content={"code": "VALIDATION_ERROR", "detail": "Invalid Content-Length header."},
            )

        path = request.url.path
        limit = _BODY_LIMIT_IMPORT if path.startswith("/system/import") else _BODY_LIMIT_DEFAULT

        if size > limit:
            limit_mb = limit // (1024 * 1024)
            return _JSONResponse(
                status_code=413,
                content={
                    "code": "PAYLOAD_TOO_LARGE",
                    "detail": f"Request body exceeds the {limit_mb} MB limit for this endpoint.",
                },
            )

    return await call_next(request)


# ---------------------------------------------------------------------------
# RATE LIMIT 429 — add Retry-After header
# ---------------------------------------------------------------------------
# slowapi's default 429 handler doesn't include Retry-After, which means
# legitimate clients (browsers, the desktop app) don't know when to retry.
# We override it to add the header so clients back off gracefully.

from slowapi.errors import RateLimitExceeded as _RateLimitExceeded
from fastapi.responses import JSONResponse as _JSONResponse

@app.exception_handler(_RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: _RateLimitExceeded):
    """Returns 429 with Retry-After header so clients know when to retry."""
    retry_after = getattr(exc, "retry_after", 60)
    return _JSONResponse(
        status_code=429,
        content={
            "code": "RATE_LIMITED",
            "detail": "Too many requests. Please slow down.",
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )

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

# Maximum response body size to cache in the idempotency store.
# Responses larger than this (e.g. PDF redirects, bulk import results) are
# processed normally but not cached — the client must retry with a new key.
_IDEMPOTENCY_MAX_CACHE_BYTES = 64 * 1024  # 64 KB

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

    # --- WIN 7: Bind idempotency key to (user_id, sha256(request_body)) ---
    # A bare UUID key allows two different cashiers using the same UUID to
    # receive each other's cached response, and allows a different payload
    # with the same UUID to silently return a stale result.
    # Binding to (user_id, sha256(body)) scopes the cache correctly.
    import hashlib
    import json as _json

    # Read the body so we can hash it. We must re-inject it for the handler.
    body_bytes = await request.body()
    body_hash = hashlib.sha256(body_bytes).hexdigest()

    # Extract user_id from the JWT for scoping (no full auth — key extraction only)
    user_scope = "anon"
    try:
        import base64
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
        if not token:
            token = request.cookies.get("access_token")
        if token:
            parts = token.split(".")
            if len(parts) == 3:
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = _json.loads(base64.b64decode(padded).decode("utf-8"))
                uid = payload.get("id") or payload.get("sub")
                if uid:
                    user_scope = str(uid)
    except Exception:
        pass

    # Composite cache key: UUID + user scope + body hash
    composite_key = f"{idempotency_key}:{user_scope}:{body_hash}"

    # Check for an existing non-expired response for this composite key
    try:
        from backend.database import SessionLocal
        from backend.models import IdempotencyKey
        from datetime import datetime, timezone

        with SessionLocal() as db:
            existing = db.query(IdempotencyKey).filter(
                IdempotencyKey.key == composite_key,
                IdempotencyKey.expires_at > datetime.now(timezone.utc),
            ).first()

            if existing:
                mto_logger.info(
                    f"Idempotency cache hit for key {idempotency_key[:8]}...",
                    method=request.method,
                    path=path,
                )
                cached_body = _json.loads(existing.response_body) if existing.response_body else {}
                return JSONResponse(
                    status_code=existing.status_code,
                    content=cached_body,
                    headers={"X-Idempotency-Replayed": "true"},
                )
    except Exception as e:
        # DB error checking idempotency — log and proceed rather than blocking
        mto_logger.warning(f"Idempotency check failed, proceeding: {e}")
        return await call_next(request)

    # Key is new — process the request and cache the response.
    # Re-inject the consumed body bytes so the route handler can read them.

    async def receive_with_body():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    # Patch the request's receive callable so the handler sees the body
    request._receive = receive_with_body

    response = await call_next(request)

    # Only cache successful JSON responses within the size limit
    content_type = response.headers.get("content-type", "")
    if 200 <= response.status_code < 300 and "application/json" in content_type:
        try:
            resp_body_bytes = b""
            async for chunk in response.body_iterator:
                resp_body_bytes += chunk
                if len(resp_body_bytes) > _IDEMPOTENCY_MAX_CACHE_BYTES:
                    # Response too large to cache — stream it through uncached
                    mto_logger.info(
                        f"Idempotency response too large to cache ({len(resp_body_bytes)} bytes), skipping.",
                        path=path,
                    )
                    from starlette.responses import Response as StarletteResponse
                    return StarletteResponse(
                        content=resp_body_bytes,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        media_type=response.media_type,
                    )

            body_str = resp_body_bytes.decode("utf-8")

            from backend.database import SessionLocal
            from backend.models import IdempotencyKey
            from datetime import datetime, timedelta, timezone

            with SessionLocal() as db:
                record = IdempotencyKey(
                    key=composite_key,
                    method=request.method,
                    path=path,
                    status_code=response.status_code,
                    response_body=body_str,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                )
                db.add(record)
                db.commit()

            from starlette.responses import Response as StarletteResponse
            return StarletteResponse(
                content=resp_body_bytes,
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

# ---------------------------------------------------------------------------
# WIN 8: Tighten CORS — explicit methods and headers instead of wildcards.
# allow_methods=["*"] + allow_headers=["*"] + allow_credentials=True means
# any whitelisted origin can send any method with any header including cookies.
# Restricting to the actual methods and headers the API uses closes that gap.
# ---------------------------------------------------------------------------
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
    # Explicit methods — DELETE is needed for property/payment deletion endpoints
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # Explicit headers — only what the API actually reads from requests
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-CSRF-Token",
        "X-Idempotency-Key",
        "X-Request-ID",
        "X-Correlation-ID",
    ],
    # Expose these response headers so the browser JS can read them
    expose_headers=[
        "X-API-Version",
        "X-API-Min-Client-Version",
        "X-Request-ID",
        "X-Idempotency-Replayed",
        "Retry-After",
    ],
)


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


# NOTE: /readyz and /api/v1/version are now defined in backend/routes/health.py
# and registered via app.include_router(system.router) above.
# They are intentionally removed here to avoid duplicate route registration.

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
