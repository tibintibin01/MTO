# -*- coding: utf-8 -*-
"""
Health, metrics, observability, and worker status routes.

Split from the monolithic system.py to keep each router focused.
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from backend.deps import admin_only, get_db, Session

router = APIRouter(tags=["Health"])


@router.get("/readyz")
async def readyz():
    """
    Lightweight liveness probe for Kubernetes.
    Returns 200 immediately — no DB check.
    """
    return {"status": "alive"}


@router.get("/healthz")
@router.get("/health")
@router.get("/ready")
async def health_check(db_session: Session = Depends(get_db)):
    """Deep readiness probe: checks DB, cache, storage, vault, and job workers."""
    import shutil
    from utils.cache_manager import cache
    from utils.secrets_manager import secrets

    health = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "unknown",
        "cache": "unknown",
        "storage": "unknown",
        "vault": "unknown",
        "job_workers": "unknown",
    }

    # 1. Database
    try:
        from sqlalchemy import text
        db_session.execute(text("SELECT 1"))
        health["database"] = "connected"
    except Exception as e:
        health["status"] = "unhealthy"
        health["database"] = f"disconnected: {str(e)}"

    # 2. Cache
    try:
        health["cache"] = {
            "engine": cache.engine,
            "status": "online" if (cache.engine.startswith("REDIS") or
                                   cache.engine.startswith("IN-MEMORY")) else "degraded",
        }
    except Exception as e:
        health["cache"] = f"error: {str(e)}"
        health["status"] = "unhealthy"

    # 3. Disk / Storage
    try:
        backup_dir = os.path.expanduser("~/.mto")
        os.makedirs(backup_dir, exist_ok=True)
        total, used, free = shutil.disk_usage(backup_dir)
        health["storage"] = {
            "path": backup_dir,
            "total_gb": round(total / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2),
            "status": "sufficient" if free > 500 * 1024 * 1024 else "low_space",
        }
        if health["storage"]["status"] == "low_space":
            health["status"] = "degraded"
    except Exception as e:
        health["storage"] = f"error: {str(e)}"

    # 4. Vault / Secrets
    try:
        jwt_ok = len(secrets.jwt_secret) > 0
        health["vault"] = {"status": "accessible" if jwt_ok else "unauthorized"}
    except Exception as e:
        health["vault"] = f"error: {str(e)}"
        health["status"] = "unhealthy"

    # 5. Job Workers
    try:
        from backend.services.job_service import get_worker_health
        worker_health = get_worker_health()
        health["job_workers"] = {"overall": worker_health["overall"], "summary": worker_health["summary"]}
        if worker_health["overall"] == "dead":
            health["status"] = "degraded"
    except Exception as e:
        health["job_workers"] = f"error: {str(e)}"

    if health["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health)
    return health


@router.get("/api/v1/metrics")
async def get_metrics(current_user: dict = Depends(admin_only)):
    """Prometheus metrics endpoint. Admin only."""
    from utils.metrics import MetricsManager
    content, content_type = MetricsManager.get_latest_metrics()
    return Response(content=content, media_type=content_type)


@router.get("/system/stats")
async def get_system_stats(
    current_user: dict = Depends(admin_only),
    db_session: Session = Depends(get_db),
):
    import backend.services.system_service as sys_svc
    return sys_svc.get_system_stats(db_session=db_session)


@router.get("/system/workers")
async def get_worker_health(current_user: dict = Depends(admin_only)):
    """Returns live health status of all background job worker threads."""
    from backend.services.job_service import get_worker_health as _get_health
    return _get_health()


@router.get("/api/v1/version")
async def api_version():
    """Returns the current API version and build info."""
    import platform
    return {
        "api_version": "1.0",
        "min_client_version": "1.0",
        "app_name": "MTO Treasury System",
        "app_version": "2.1.0",
        "python_version": platform.python_version(),
        "status": "online",
    }
