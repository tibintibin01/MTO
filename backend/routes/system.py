import os
from typing import List, Optional, Union
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from jose import JWTError, jwt
from pydantic import BaseModel
import backend.services.system_service as sys_svc
import backend.services.search_service as search_svc
from backend.deps import get_current_user, admin_only, write_access, read_only, limiter, user_limiter, manager, get_db, Session, SECRET_KEY, ALGORITHM
from backend.schemas import PropertySaveSchema, LogActionSchema
from utils.logger import mto_logger

router = APIRouter(tags=["System"])

class RestoreRequest(BaseModel):
    file_path: str

# ---------------------------------------------------------------------------
# TD Number Format Audit
# ---------------------------------------------------------------------------

@router.get("/system/td-number-audit")
async def td_number_audit(
    current_user: dict = Depends(read_only),
    db_session: Session = Depends(get_db),
):
    """
    Scans all active properties and returns those whose TD number does NOT
    match the expected format: 06-XXXX-XXXXX
    (2 digits, dash, 4 digits, dash, 5 digits — total 14 characters)

    Returns:
      - invalid: list of {id, td_number, owner_name, reason}
      - total_scanned: total active properties checked
      - invalid_count: number of non-conforming TD numbers
    """
    import re
    from backend.models import Property

    # Pattern: exactly 2 digits, dash, 4 digits, dash, 5 digits
    PATTERN = re.compile(r"^\d{2}-\d{4}-\d{5}$")

    rows = (
        db_session.query(Property.id, Property.td_number, Property.owner_name)
        .filter(Property.deleted_at == None)
        .order_by(Property.id.asc())
        .all()
    )

    invalid = []
    for prop_id, td, owner in rows:
        td_str = (td or "").strip()
        if not td_str:
            reason = "Empty TD number"
        elif not PATTERN.match(td_str):
            # Give a specific reason
            parts = td_str.split("-")
            if len(parts) != 3:
                reason = f"Wrong number of segments (expected 3, got {len(parts)})"
            elif len(parts[0]) != 2:
                reason = f"First segment should be 2 digits, got '{parts[0]}' ({len(parts[0])} chars)"
            elif len(parts[1]) != 4:
                reason = f"Second segment should be 4 digits, got '{parts[1]}' ({len(parts[1])} chars)"
            elif len(parts[2]) != 5:
                reason = f"Third segment should be 5 digits, got '{parts[2]}' ({len(parts[2])} chars)"
            elif not parts[0].isdigit() or not parts[1].isdigit() or not parts[2].isdigit():
                reason = "Contains non-numeric characters"
            else:
                reason = f"Does not match 06-XXXX-XXXXX format"
        else:
            continue  # valid — skip

        invalid.append({
            "id": prop_id,
            "td_number": td_str or "(empty)",
            "owner_name": owner or "",
            "reason": reason,
        })

    return {
        "total_scanned": len(rows),
        "invalid_count": len(invalid),
        "invalid": invalid,
        "format": "DD-DDDD-DDDDD (e.g. 06-0014-00239)",
    }

# ---------------------------------------------------------------------------
# Tax Policy — configure RPT rates per tax year
# ---------------------------------------------------------------------------

class TaxPolicyUpdateSchema(BaseModel):
    basic_rate: float
    sef_rate: float
    penalty_rate: float


@router.get("/system/tax-policy")
async def list_tax_policies(
    current_user: dict = Depends(read_only),
    db_session: Session = Depends(get_db),
):
    """Returns all configured tax policies ordered by tax year descending."""
    from backend.models import TaxPolicy
    rows = db_session.query(TaxPolicy).order_by(TaxPolicy.tax_year.desc()).all()
    return [
        {
            "id": r.id,
            "tax_year": r.tax_year,
            "basic_rate": float(r.basic_rate),
            "sef_rate": float(r.sef_rate),
            "penalty_rate": float(r.penalty_rate),
        }
        for r in rows
    ]


@router.put("/system/tax-policy/{tax_year}")
async def update_tax_policy(
    tax_year: int,
    data: TaxPolicyUpdateSchema,
    current_user: dict = Depends(admin_only),
    db_session: Session = Depends(get_db),
):
    """
    Creates or updates the tax policy for a given tax year.
    Admin only — rate changes must be authorised by Sangguniang Bayan resolution.
    """
    from backend.models import TaxPolicy
    from decimal import Decimal

    # Validate rates are reasonable (0% to 10%)
    for field, val in [("basic_rate", data.basic_rate), ("sef_rate", data.sef_rate), ("penalty_rate", data.penalty_rate)]:
        if not (0 <= val <= 0.10):
            raise HTTPException(status_code=400, detail=f"{field} must be between 0 and 10% (0.0000–0.1000).")

    policy = db_session.query(TaxPolicy).filter(TaxPolicy.tax_year == tax_year).first()
    if policy:
        policy.basic_rate = Decimal(str(data.basic_rate))
        policy.sef_rate = Decimal(str(data.sef_rate))
        policy.penalty_rate = Decimal(str(data.penalty_rate))
    else:
        policy = TaxPolicy(
            tax_year=tax_year,
            basic_rate=Decimal(str(data.basic_rate)),
            sef_rate=Decimal(str(data.sef_rate)),
            penalty_rate=Decimal(str(data.penalty_rate)),
        )
        db_session.add(policy)

    db_session.commit()
    mto_logger.info(
        f"Tax policy updated for {tax_year}: basic={data.basic_rate}, "
        f"sef={data.sef_rate}, penalty={data.penalty_rate}",
        user=current_user.get("username"),
    )
    return {"status": "ok", "tax_year": tax_year}

# SECURITY: The unauthenticated /metrics endpoint was removed.
# Use GET /api/v1/metrics (admin_only) for Prometheus scraping instead.
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "unknown",
        "cache": "unknown",
        "storage": "unknown",
        "vault": "unknown",
        "job_workers": "unknown",
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

    # 5. Job Worker Health Check
    try:
        from backend.services.job_service import get_worker_health
        worker_health = get_worker_health()
        health["job_workers"] = {
            "overall": worker_health["overall"],
            "summary": worker_health["summary"],
        }
        # Dead workers degrade the health status — jobs will queue but not process.
        # Stale workers are only a warning (long-running job in progress).
        if worker_health["overall"] == "dead":
            health["status"] = "degraded"
    except Exception as e:
        health["job_workers"] = f"error: {str(e)}"

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

@router.post("/api/v1/system/undo")
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

@router.get("/api/v1/metrics")
async def get_metrics(current_user: dict = Depends(admin_only)):
    from utils.metrics import MetricsManager
    content, content_type = MetricsManager.get_latest_metrics()
    return Response(content=content, media_type=content_type)

@router.get("/system/stats")
async def get_system_stats(request: Request, current_user: dict = Depends(admin_only), db_session: Session = Depends(get_db)):

    return sys_svc.get_system_stats(db_session=db_session)


@router.post("/system/backup/trigger")
@limiter.limit("3/minute")
@user_limiter.limit("3/minute")
async def trigger_backup(
    request: Request,
    current_user: dict = Depends(admin_only)
):
    from backend.services.job_service import submit_job
    job_id = submit_job(job_type="backup", submitted_by=current_user["username"])
    return {
        "status": "backup_started",
        "job_id": job_id,
        "message": "Backup queued. Poll /jobs/{job_id} for progress.",
    }

@router.get("/system/backup/status", dependencies=[Depends(read_only)])
async def get_backup_health(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    from backend.services.backup_service import get_backup_status
    return get_backup_status(db_session=db_session)


@router.get("/system/backup/schedule", dependencies=[Depends(read_only)])
async def get_backup_schedule(current_user: dict = Depends(get_current_user)):
    """
    Returns the configured automatic backup schedule and when the next
    backup is expected to run. Read-only — all roles can view this.
    """
    from utils.config import config as _cfg
    from datetime import datetime

    schedule    = _cfg.BACKUP_SCHEDULE.strip().lower()
    hour        = _cfg.BACKUP_SCHEDULE_HOUR
    minute      = _cfg.BACKUP_SCHEDULE_MINUTE
    day_of_week = _cfg.BACKUP_SCHEDULE_DAY_OF_WEEK

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]

    if schedule == "disabled":
        return {
            "schedule": "disabled",
            "description": "Automatic backups are disabled. Trigger manually via the backup button.",
            "next_run": None,
        }

    now = datetime.now()

    if schedule == "daily":
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            from datetime import timedelta
            candidate += timedelta(days=1)
        description = f"Daily at {hour:02d}:{minute:02d} (local server time)"

    elif schedule == "weekly":
        from datetime import timedelta
        days_ahead = (day_of_week - now.weekday()) % 7
        candidate = (now + timedelta(days=days_ahead)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(weeks=1)
        description = (
            f"Weekly on {day_names[day_of_week]} at {hour:02d}:{minute:02d} (local server time)"
        )
    else:
        return {
            "schedule": schedule,
            "description": f"Unknown schedule value: {schedule!r}",
            "next_run": None,
        }

    return {
        "schedule": schedule,
        "description": description,
        "next_run": candidate.strftime("%Y-%m-%d %H:%M:%S"),
        "next_run_in_hours": round((candidate - now).total_seconds() / 3600, 1),
        "scheduled_hour": hour,
        "scheduled_minute": minute,
        "scheduled_day_of_week": day_names[day_of_week] if schedule == "weekly" else None,
    }

@router.post("/system/import/validate", dependencies=[Depends(write_access)])
async def validate_bulk_import(
    request: Request, file: UploadFile = File(...), current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    from utils import is_feature_enabled
    if not is_feature_enabled("BULK_IMPORT"):
        raise HTTPException(status_code=403, detail="Bulk Import feature is currently disabled.")
    content = await file.read()
    ext = os.path.splitext(file.filename)[1]
    mode = request.query_params.get("mode", "property")
    if mode == "assessment":
        from backend.services.import_service import validate_assessment_import
        res = validate_assessment_import(content, ext, db_session=db_session)
    elif mode == "payments":
        from backend.services.import_service import validate_payment_import
        res = validate_payment_import(content, ext, db_session=db_session)
    else:
        from backend.services.import_service import validate_property_import
        res = validate_property_import(content, ext, db_session=db_session)

    if isinstance(res, dict) and res.get("success") and "data" in res:
        from backend.services.import_service import save_import_cache
        token = save_import_cache(res["data"])
        if token:
            res["validation_token"] = token
            res["cache_token"] = token

    return res

@router.post("/system/import/commit", dependencies=[Depends(write_access)])
async def commit_bulk_import(
    request: Request, data: Union[List[dict], dict], current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    from utils import is_feature_enabled
    if not is_feature_enabled("BULK_IMPORT"):
        raise HTTPException(status_code=403, detail="Bulk Import feature is currently disabled.")
    mode = request.query_params.get("mode", "property")

    if isinstance(data, dict):
        token = data.get("validation_token") or data.get("cache_token")
        if not token:
            raise HTTPException(status_code=400, detail="Missing validation_token or cache_token in request body.")
        from backend.services.import_service import load_import_cache
        payload = load_import_cache(token)
        if payload is None:
            raise HTTPException(status_code=400, detail="Invalid, expired, or missing import validation token.")
    else:
        if data and hasattr(data[0], "model_dump"):
            payload = [d.model_dump(exclude_unset=True) for d in data]
        else:
            payload = data

    if mode == "assessment":
        from backend.services.import_service import commit_assessment_import
        res = commit_assessment_import(payload, current_user, db_session=db_session)
        return {"status": "success", "imported": res["inserted"] + res["updated"], "details": res}
    if mode == "payments":
        from backend.services.import_service import commit_payment_import
        res = commit_payment_import(payload, current_user, db_session=db_session)
        return {"status": "success", "imported": res["inserted"]}
    from backend.services.import_service import commit_property_import
    count = commit_property_import(payload, current_user, db_session=db_session)
    return {"status": "success", "imported": count}

@router.post("/system/logs")
async def log_system_action(
    log: LogActionSchema, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    sys_svc.log_action(current_user, log.action, db_session=db_session)
    db_session.commit()
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
                f.write(f"\n[{datetime.now(timezone.utc)}] RESTORE FAILURE\nFile: {request.file_path}\nError: {str(e)}\nTraceback:\n{error_detail}\n" + "-" * 40 + "\n")
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Restore operation failed. Check server logs for details.")

@router.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """
    Authenticated WebSocket endpoint for real-time notifications.

    Clients must supply a valid JWT via query parameter on connect:
        wss://host/ws/notifications?token=<access_token>

    The cookie-based token is not available during the WebSocket handshake
    in most browser/client implementations, so the query parameter is the
    supported transport here. The token is validated before the connection
    is accepted — unauthenticated clients are rejected with close code 1008
    (policy violation) before any data is exchanged.
    """
    # Extract token from query string if not passed as a parameter
    if not token:
        token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=1008, reason="Missing authentication token")
        mto_logger.security(
            "WebSocket connection rejected: no token provided",
            ip=websocket.client.host if websocket.client else "unknown",
        )
        return

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        user_id: int = payload.get("id")
        if not username or not role or not user_id:
            raise JWTError("Incomplete token payload")
    except JWTError as e:
        await websocket.close(code=1008, reason="Invalid or expired token")
        mto_logger.security(
            f"WebSocket connection rejected: invalid token — {e}",
            ip=websocket.client.host if websocket.client else "unknown",
        )
        return

    # Token is valid — accept the connection
    await manager.connect(websocket)
    mto_logger.info(
        "WebSocket connection established",
        user=username,
        role=role,
        ip=websocket.client.host if websocket.client else "unknown",
    )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        mto_logger.info("WebSocket connection closed", user=username)

@router.post("/system/sync-billing-years", dependencies=[Depends(admin_only)])
async def sync_billing_years(
    background_tasks: BackgroundTasks,
    dry_run: bool = False,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """
    Creates missing PropertyBilling records for all active properties.

    For each property, determines the start year from effectivity_date or
    tax_year, then creates billing rows for every year from start_year to
    the current year that doesn't already have one.

    This fixes the Delinquency Dashboard showing only one year's balance
    for properties that have been unpaid for multiple years.

    Set dry_run=true to preview what would be created without writing to DB.
    """
    from backend.services.billing_sync_service import sync_billing_years as _sync

    mto_logger.info(
        f"Billing year sync requested by {current_user.get('username')} "
        f"(dry_run={dry_run})"
    )

    if dry_run:
        # Dry run is fast — run synchronously and return the preview
        result = _sync(db_session=db_session, dry_run=True)
        return result

    # Live run — submit as a background job so the UI doesn't time out
    from backend.services.job_service import submit_job
    job_id = submit_job(
        job_type="sync_billing_years",
        submitted_by=current_user["username"],
        payload={},
        db_session=db_session,
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Billing year sync queued. Poll /jobs/{job_id} for progress.",
    }


# ---------------------------------------------------------------------------
# Data Retention Policy — RA 10173 (NPC) & DICT MC 2022-002 Compliance
# ---------------------------------------------------------------------------

@router.get("/system/retention/policies", dependencies=[Depends(admin_only)])
async def list_retention_policies(
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """
    Returns all configured retention policies with their last execution info.
    Admin only.
    """
    from backend.services.retention_service import get_all_policies
    return get_all_policies(db_session=db_session)


@router.get("/system/retention/logs", dependencies=[Depends(admin_only)])
async def list_retention_logs(
    limit: int = 100,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """
    Returns paginated retention execution history for COA/NPC audit trail.
    Admin only.
    """
    from backend.services.retention_service import get_retention_logs
    return get_retention_logs(limit=limit, cursor=cursor, db_session=db_session)


@router.post("/system/retention/run", dependencies=[Depends(admin_only)])
async def run_retention_policy(
    dry_run: bool = False,
    data_type: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """
    Triggers the data retention policy as a background job.

    - dry_run=true  → preview what would be affected, no changes written
    - dry_run=false → execute archival/purge per the configured schedule
    - data_type     → run only for this data type (e.g. "deleted_users")
                      omit to run all active policies

    Returns a job_id to poll for progress.
    Admin only.
    """
    from backend.services.job_service import submit_job

    mto_logger.info(
        "Retention policy run requested by %s (dry_run=%s, data_type=%s)",
        current_user.get("username"), dry_run, data_type,
    )

    job_id = submit_job(
        job_type="retention_run",
        submitted_by=current_user["username"],
        payload={"dry_run": dry_run, "data_type": data_type},
        db_session=db_session,
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "dry_run": dry_run,
        "message": (
            f"{'DRY RUN — ' if dry_run else ''}"
            "Retention policy queued. Poll /jobs/{job_id} for progress."
        ),
    }


@router.get("/system/workers")
async def get_worker_health(current_user: dict = Depends(admin_only)):
    """
    Returns the live health status of all background job worker threads.

    Use this to detect dead or hung workers without waiting for the full
    /healthz probe. Useful for the admin dashboard and monitoring tools.

    Worker states:
      healthy  — thread is alive and beat within the last 60 seconds
      stale    — thread is alive but hasn't beat in 60–300 seconds
                 (normal during long-running jobs like backup or bulk import)
      dead     — thread has exited or hasn't beat in over 5 minutes

    Overall status:
      healthy  — all workers healthy
      stale    — at least one worker is stale (long job in progress)
      dead     — at least one worker has died (jobs will queue but not process)

    Admin only.
    """
    from backend.services.job_service import get_worker_health as _get_health
    return _get_health()


@router.post("/system/restart", dependencies=[Depends(admin_only)])
async def restart_server(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """
    Gracefully restarts the backend server process.
    Admin only. Used for applying software updates without physical access
    to the server PC.

    The response is sent first, then the process exits after a 2-second
    delay so the client receives the confirmation before the connection drops.
    The OS / startup script (run_silently.vbs or a process manager) is
    responsible for restarting the process automatically.
    """
    mto_logger.info(
        "Server restart requested",
        user=current_user.get("username"),
    )

    async def _do_restart():
        import asyncio
        import sys
        await asyncio.sleep(2)  # Give the response time to reach the client
        mto_logger.info("Server process exiting for restart...")
        os._exit(0)  # Hard exit — process manager / VBS script will relaunch

    background_tasks.add_task(_do_restart)
    return {
        "status": "restarting",
        "message": "Server will restart in ~2 seconds. Reconnect after 5–10 seconds.",
        "requested_by": current_user.get("username"),
    }
