# -*- coding: utf-8 -*-
import os
from contextlib import asynccontextmanager
from typing import Mapping
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
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


class CaseInsensitiveTrustedHostMiddleware(TrustedHostMiddleware):
    """Apply Starlette's host allowlist using DNS case-insensitive matching."""

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            normalized_scope = dict(scope)
            normalized_scope["headers"] = [
                (name, value.lower() if name.lower() == b"host" else value)
                for name, value in scope.get("headers", [])
            ]
            scope = normalized_scope
        await super().__call__(scope, receive, send)


def _production(environment: Mapping[str, str]) -> bool:
    return environment.get("MTO_ENVIRONMENT", "development").lower() == "production"


def configured_cors_origins(
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    env = environment if environment is not None else os.environ
    origins = ["https://mto-portal-dipaculao.vercel.app"]
    if not _production(env):
        origins.extend(
            [
                "https://localhost",
                "https://127.0.0.1",
                "https://localhost:8001",
            ]
        )
    for variable in ("CORS_ORIGIN", "MTO_CORS_ORIGINS"):
        for raw_origin in env.get(variable, "").split(","):
            raw_origin = raw_origin.strip().rstrip("/")
            if not raw_origin:
                continue
            parsed = urlparse(raw_origin)
            if (
                raw_origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path
            ):
                raise RuntimeError(f"Unsafe CORS origin in {variable}: {raw_origin!r}")
            if parsed.scheme != "https" and (
                _production(env) or parsed.hostname not in {"localhost", "127.0.0.1"}
            ):
                raise RuntimeError(
                    f"Plaintext CORS origin is not permitted: {raw_origin!r}"
                )
            if raw_origin not in origins:
                origins.append(raw_origin)
    return origins


def configured_trusted_hosts(
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    env = environment if environment is not None else os.environ
    hosts: list[str] = []
    sources = (
        env.get("MTO_TRUSTED_HOSTS", ""),
        env.get("MTO_TLS_SERVER_NAMES", ""),
        env.get("VERCEL_URL", ""),
        env.get("VERCEL_PROJECT_PRODUCTION_URL", ""),
    )
    for source in sources:
        for raw_host in source.split(","):
            raw_host = raw_host.strip().lower().rstrip(".")
            if not raw_host:
                continue
            parsed = urlparse(raw_host if "://" in raw_host else f"//{raw_host}")
            host = (parsed.hostname or "").lower().rstrip(".")
            try:
                parsed.port
            except ValueError as exc:
                raise RuntimeError(f"Unsafe trusted host: {raw_host!r}") from exc
            if (
                not host
                or raw_host == "*"
                or "*" in host
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
                or (parsed.scheme and parsed.scheme not in {"http", "https"})
                or (_production(env) and parsed.scheme == "http")
            ):
                raise RuntimeError(f"Unsafe trusted host: {raw_host!r}")
            if host not in hosts:
                hosts.append(host)
    if not _production(env):
        for development_host in ("localhost", "127.0.0.1", "testserver"):
            if development_host not in hosts:
                hosts.append(development_host)
    if not hosts:
        raise RuntimeError(
            "Production requires MTO_TRUSTED_HOSTS or an approved hosting hostname."
        )
    return hosts


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Startup logic runs before `yield`; shutdown logic runs after.
    """
    # --- STARTUP ---
    mto_logger.info("API Server started successfully.")

    # Login depends on these columns. Treat schema repair failure as a startup
    # failure so the updater cannot report a false-ready API.
    from backend.database import SessionLocal
    from backend.services.migration_service import (
        ensure_refresh_token_session_columns,
    )

    try:
        with SessionLocal() as db:
            ensure_refresh_token_session_columns(db)
        mto_logger.info("Authentication session schema verified on startup.")
    except Exception as e:
        mto_logger.critical(f"Authentication session schema verification failed: {e}")
        raise RuntimeError("Authentication database schema is not ready") from e

    # Portfolios are an optional organizational feature. Create its two
    # association-only tables idempotently for installations whose updater does
    # not run Alembic, but never prevent the core revenue system from starting
    # if the configured DB account does not have DDL permission.
    try:
        from backend.services.portfolio_service import ensure_portfolio_schema

        with SessionLocal() as db:
            ensure_portfolio_schema(db)
        mto_logger.info("Property portfolio schema verified on startup.")
    except Exception as e:
        mto_logger.warning(f"Could not verify property portfolio schema: {e}")

    # Controlled duplicate TD accounts must remain independently visible in
    # billing-driven screens. Repair missing years idempotently for accounts
    # created before immediate billing initialization was introduced.
    try:
        from backend.services.billing_sync_service import (
            sync_verified_duplicate_td_billings,
        )

        with SessionLocal() as db:
            result = sync_verified_duplicate_td_billings(db)
            if result["records_created"]:
                db.commit()
                mto_logger.info(
                    "Verified duplicate TD billing readiness created "
                    f"{result['records_created']} missing year(s)."
                )
    except Exception as e:
        mto_logger.warning(f"Could not verify duplicate TD billing readiness: {e}")

    # Refresh dashboard stats so the first page load shows real numbers.
    try:
        from backend.services.migration_service import ensure_payment_remarks_column
        from backend.services.stats_service import refresh_system_stats

        with SessionLocal() as db:
            ensure_payment_remarks_column(db)
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
        redoc_url="/redoc",
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
    origins = configured_cors_origins()

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
            "X-Requested-With",
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

    app.add_middleware(
        CaseInsensitiveTrustedHostMiddleware,
        allowed_hosts=configured_trusted_hosts(),
    )

    # App Middlewares
    app.middleware("http")(maintenance_mode_middleware)
    app.middleware("http")(observability_middleware)
    app.middleware("http")(request_body_size_middleware)
    app.middleware("http")(security_headers_middleware)
    app.middleware("http")(request_timeout_middleware)

    # Import and Include Routers
    from backend.routes import (
        auth,
        users,
        properties,
        payments,
        billing,
        system,
        public,
        jobs,
        reports,
        portfolios,
    )

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(properties.router)
    app.include_router(payments.router)
    app.include_router(billing.router)
    app.include_router(system.router)
    app.include_router(public.router)
    app.include_router(jobs.router)
    app.include_router(reports.router)
    app.include_router(portfolios.router)

    # Serve static files (analytics dashboard HTML, etc.)
    # Must be mounted after all API routers so API paths take precedence.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    _static_dir = os.path.join(base_dir, "static")
    if os.path.isdir(_static_dir):
        app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    # Root endpoint
    @app.get("/")
    async def root():
        return {
            "message": "Municipal Revenue System API is running",
            "status": "online",
        }

    return app


# Instantiate the global application instance
app = create_app()
