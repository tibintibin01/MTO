# -*- coding: utf-8 -*-
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from utils.logger import mto_logger
from backend.deps import limiter, user_limiter

# Import middlewares
from backend.middleware.security import (
    security_headers_middleware,
    request_body_size_middleware,
    request_timeout_middleware,
)
from backend.middleware.idempotency import idempotency_middleware
from backend.middleware.observability import (
    observability_middleware,
    maintenance_mode_middleware,
)

# Import exception handlers
from backend.exception_handlers import (
    rate_limit_handler,
    validation_exception_handler,
    http_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

try:
    import sentry_sdk
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Startup logic runs before `yield`; shutdown logic runs after.
    """
    # --- STARTUP ---
    mto_logger.info("API Server started successfully.")
    
    # Refresh dashboard stats so the first page load shows real numbers.
    try:
        from backend.database import SessionLocal
        from backend.services.stats_service import refresh_system_stats
        with SessionLocal() as db:
            refresh_system_stats(db_session=db)
        mto_logger.info("Dashboard stats refreshed successfully on startup.")
    except Exception as e:
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

    if SENTRY_AVAILABLE and os.getenv("SENTRY_DSN"):
        try:
            sentry_sdk.flush(timeout=2)
        except Exception:
            pass


def create_app() -> FastAPI:
    """
    Creates and configures a FastAPI application instance.
    """
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

    # Rate Limiting Configuration
    app.state.limiter = limiter
    app.state.user_limiter = user_limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Register Custom Exception Handlers
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # Register Middlewares (evaluated in reverse order of addition)
    # CORS Middleware (should be outer most/evaluated first for preflight requests)
    origins = [
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:8001",
        "https://localhost:8001",
        "http://localhost:3000",
        "https://mto-portal-dipaculao.vercel.app",
    ]

    # Allow extra origins configured via .env or hosting provider variables.
    for _origin_var in ("CORS_ORIGIN", "MTO_CORS_ORIGINS"):
        for _extra_origin in os.getenv(_origin_var, "").split(","):
            _extra_origin = _extra_origin.strip()
            if _extra_origin and _extra_origin not in origins:
                origins.append(_extra_origin)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "X-CSRF-Token",
            "X-Idempotency-Key",
            "X-Request-ID",
            "X-Correlation-ID",
        ],
        expose_headers=[
            "X-API-Version",
            "X-API-Min-Client-Version",
            "X-Request-ID",
            "X-Idempotency-Replayed",
            "Retry-After",
        ],
    )

    # App Middlewares
    app.middleware("http")(maintenance_mode_middleware)
    app.middleware("http")(observability_middleware)
    app.middleware("http")(idempotency_middleware)
    app.middleware("http")(request_body_size_middleware)
    app.middleware("http")(security_headers_middleware)

    # Import and Include Routers
    from backend.routes import auth, users, properties, payments, billing, system, public, jobs
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
    base_dir = os.path.dirname(os.path.abspath(__file__))
    _static_dir = os.path.join(base_dir, "static")
    if os.path.isdir(_static_dir):
        app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    # Root endpoint
    @app.get("/")
    async def root():
        return {"message": "Municipal Revenue System API is running", "status": "online"}

    return app

# Instantiate the global application instance
app = create_app()
