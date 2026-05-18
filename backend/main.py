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

from backend.services.migration_service import run_migrations
run_migrations()

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

from backend.services.migration_service import run_migrations
run_migrations()

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

# --- CSRF PROTECTION MIDDLEWARE ---
@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
        custom_header = request.headers.get("X-Requested-With")
        if custom_header != "XMLHttpRequest":
            mto_logger.security(
                "CSRF ATTEMPT DETECTED: Missing or invalid X-Requested-With header",
                method=request.method,
                url=str(request.url),
                ip=request.client.host
            )
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Security violation: CSRF protection triggered."}
            )
    response = await call_next(request)
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
origins = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8001",
    "https://localhost:8001",
    "http://localhost:3000",
]

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
    try:
        from backend.services.stats_service import refresh_system_stats
        refresh_system_stats()
        mto_logger.info("Dashboard stats refreshed successfully on startup.")
    except Exception as e:
        mto_logger.error(f"Failed to refresh dashboard stats on startup: {e}")


from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = exc.body
    # FormData objects are not JSON serializable, so we convert them
    if hasattr(body, "items"):
        try:
            body = dict(body)
        except:
            body = str(body)
    
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": body},
    )


# --- Import Routers ---
from backend.routes import auth, users, properties, payments, billing, system, public

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(properties.router)
app.include_router(payments.router)
app.include_router(billing.router)
app.include_router(system.router)
app.include_router(public.router)


@app.get("/")
async def root():
    return {"message": "Municipal Revenue System API is running", "status": "online"}

if __name__ == "__main__":
    import uvicorn
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_path = os.path.join(base_dir, "certs", "cert.pem")
    key_path = os.path.join(base_dir, "certs", "key.pem")
    if os.path.exists(cert_path) and os.path.exists(key_path):
        print("Starting Secure API (HTTPS) with CORS Enabled...")
        uvicorn.run(app, host="0.0.0.0", port=8001, ssl_keyfile=key_path, ssl_certfile=cert_path)
    else:
        print("Starting Standard API (HTTP) - SSL Certs not found.")
        uvicorn.run(app, host="0.0.0.0", port=8001)
