import os
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel
# import db_manager as db # Unused in route
import backend.services.system_service as sys_svc
import backend.services.search_service as search_svc
from backend.deps import get_current_user, admin_only, write_access, read_only, limiter, manager, get_db, Session
from backend.schemas import PropertySaveSchema, LogActionSchema
from utils.logger import mto_logger

router = APIRouter(tags=["System"])

class RestoreRequest(BaseModel):
    file_path: str

# SECURITY: The unauthenticated /metrics endpoint was removed.
# Use GET /api/v2/metrics (admin_only) for Prometheus scraping instead.
# Configure infra/prometheus.yml to include an Authorization header.

@router.get("/healthz")
@router.get("/health")
@router.get("/ready")
async def health_check(db_session: Session = Depends(get_db)):
    """Enterprise-grade deep health probe for K8s Liveness & Readiness checks."""
    import shutil
    from utils.cache_manager import cache
    from utils.secrets_manager import secrets

    health = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "database": "unknown",
        "cache": "unknown",
        "storage": "unknown",
        "vault": "unknown"
    }
    
    # 1. Database Connection Check
    try:
        from sqlalchemy import text
        db_session.execute(text("SELECT 1"))
        health["database"] = "connected"
    except Exception as e:
        health["status"] = "unhealthy"
        health["database"] = f"disconnected: {str(e)}"

    # 2. Cache Connection Check
    try:
        health["cache"] = {
            "engine": cache.engine,
            "status": "online" if (cache.engine.startswith("REDIS") or cache.engine.startswith("IN-MEMORY")) else "degraded"
        }
    except Exception as e:
        health["cache"] = f"error: {str(e)}"
        health["status"] = "unhealthy"

    # 3. Disk Space / Backup Volume Storage Check
    try:
        # Check free disk space in the current database backup directory
        backup_dir = os.path.expanduser("~/.mto")
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir, exist_ok=True)
        total, used, free = shutil.disk_usage(backup_dir)
        health["storage"] = {
            "path": backup_dir,
            "total_gb": round(total / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "status": "sufficient" if (free > 500 * 1024 * 1024) else "low_space"
        }
        if health["storage"]["status"] == "low_space":
            health["status"] = "degraded"
    except Exception as e:
        health["storage"] = f"error: {str(e)}"
        
    # 4. Vault Check
    try:
        jwt_ok = len(secrets.jwt_secret) > 0
        health["vault"] = {
            "status": "accessible" if jwt_ok else "unauthorized"
        }
    except Exception as e:
        health["vault"] = f"error: {str(e)}"
        health["status"] = "unhealthy"

    if health["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health)
    return health


@router.get("/search/global")
async def global_search(q: str = "", current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    """Unified search for the Command Palette."""
    if not q:
        return {"results": search_svc.get_quick_actions()}
    results = search_svc.global_search(q, db_session=db_session)
    return {"results": results}

@router.post("/api/v2/system/undo")
async def undo_last_system_action(current_user: dict = Depends(get_current_user)):
    """Reverses the last critical action (UPDATE/DELETE) performed by the current user."""
    from backend.services.history_service import undo_last_action
    success, message = undo_last_action(current_user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=message)
    await manager.broadcast({
        "type": "NOTIFICATION",
        "title": "Action Reversed",
        "message": message,
        "level": "success"
    })
    return {"status": "success", "message": message}

@router.get("/api/v2/metrics")
async def get_metrics(current_user: dict = Depends(admin_only)):
    from utils.metrics import MetricsManager
    content, content_type = MetricsManager.get_latest_metrics()
    return Response(content=content, media_type=content_type)

@router.get("/system/stats")
async def get_system_stats(request: Request, current_user: dict = Depends(admin_only), db_session: Session = Depends(get_db)):

    return sys_svc.get_system_stats(db_session=db_session)


@router.post("/system/backup/trigger")
@limiter.limit("3/minute")
async def trigger_backup(
    request: Request,
    background_tasks: BackgroundTasks, 
    current_user: dict = Depends(admin_only)
):
    from backend.services.backup_service import run_hybrid_backup
    async def backup_wrapper():
        from backend.database import SessionLocal
        with SessionLocal() as db:
            await run_hybrid_backup(user=current_user, db_session=db)
        await manager.broadcast({
            "type": "NOTIFICATION",
            "title": "Backup Complete",
            "message": "The Hybrid Backup process has finished successfully.",
            "level": "success"
        })
    background_tasks.add_task(backup_wrapper)
    return {"status": "backup_started", "message": "Hybrid backup is running in the background."}

@router.get("/system/backup/status", dependencies=[Depends(read_only)])
async def get_backup_health(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    from backend.services.backup_service import get_backup_status
    return get_backup_status(db_session=db_session)

@router.post("/system/import/validate", dependencies=[Depends(write_access)])
async def validate_bulk_import(
    request: Request, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)
):
    from utils import is_feature_enabled
    if not is_feature_enabled("BULK_IMPORT"):
        raise HTTPException(status_code=403, detail="Bulk Import feature is currently disabled.")
    from backend.services.import_service import validate_property_import
    content = await file.read()
    ext = os.path.splitext(file.filename)[1]
    mode = request.query_params.get("mode", "property")
    if mode == "assessment":
        from backend.services.import_service import validate_assessment_import
        return validate_assessment_import(content, ext)
    if mode == "payments":
        from backend.services.import_service import validate_payment_import
        return validate_payment_import(content, ext)
    return validate_property_import(content, ext)

@router.post("/system/import/commit", dependencies=[Depends(write_access)])
async def commit_bulk_import(
    request: Request, data: List[dict], current_user: dict = Depends(get_current_user)
):
    from utils import is_feature_enabled
    if not is_feature_enabled("BULK_IMPORT"):
        raise HTTPException(status_code=403, detail="Bulk Import feature is currently disabled.")
    mode = request.query_params.get("mode", "property")
    if data and hasattr(data[0], "model_dump"):
        payload = [d.model_dump(exclude_unset=True) for d in data]
    else:
        payload = data
    if mode == "assessment":
        from backend.services.import_service import commit_assessment_import
        res = commit_assessment_import(payload, current_user)
        return {"status": "success", "imported": res["inserted"] + res["updated"], "details": res}
    if mode == "payments":
        from backend.services.import_service import commit_payment_import
        res = commit_payment_import(payload, current_user)
        return {"status": "success", "imported": res["inserted"]}
    from backend.services.import_service import commit_property_import
    count = commit_property_import(payload, current_user)
    return {"status": "success", "imported": count}

@router.post("/system/logs")
async def log_system_action(
    log: LogActionSchema, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    sys_svc.log_action(current_user, log.action, db_session=db_session)
    return {"status": "logged"}

@router.get("/system/audit-stats", dependencies=[Depends(admin_only)])
async def get_audit_stats(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return sys_svc.get_audit_stats(db_session=db_session)

@router.get("/system/audit-logs", dependencies=[Depends(admin_only)])
async def list_audit_logs(
    username: Optional[str] = None,
    search: Optional[str] = "",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    results = sys_svc.get_audit_logs(
        username=username, search=search, date_from=date_from, date_to=date_to, limit=limit + 1, cursor=cursor, db_session=db_session
    )
    has_more = len(results) > limit
    items = results[:limit]
    next_cursor = items[-1]["id"] if has_more and items else None
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}

@router.get("/system/audit-users", dependencies=[Depends(admin_only)])
async def list_audit_users(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return sys_svc.get_distinct_log_users(db_session=db_session)

@router.get("/system/logs", dependencies=[Depends(admin_only)])
async def get_system_logs(
    lines: int = 100, current_user: dict = Depends(get_current_user)
):
    try:
        from utils import ERROR_LOG_PATH
        if not os.path.exists(ERROR_LOG_PATH):
            return {"logs": "Log file not found."}
        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            log_lines = f.readlines()
            return {"logs": "".join(log_lines[-lines:])}
    except Exception as e:
        return {"logs": f"Error reading logs: {str(e)}"}

@router.post("/system/restore", dependencies=[Depends(admin_only)])
async def restore_system_backup(
    request: RestoreRequest, current_user: dict = Depends(get_current_user)
):
    from backend.services.system_service import restore_database
    import traceback
    try:
        file_path = request.file_path.replace("\\", "/").strip()
        result = restore_database(file_path)
        return {"status": "success", "data": result}
    except Exception as e:
        error_detail = traceback.format_exc()
        try:
            with open("logs/restore_debug.log", "a") as f:
                f.write(f"\n[{datetime.now()}] RESTORE FAILURE\nFile: {request.file_path}\nError: {str(e)}\nTraceback:\n{error_detail}\n" + "-" * 40 + "\n")
        except: pass
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
