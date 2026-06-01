# -*- coding: utf-8 -*-
"""
Maintenance routes: backup, restore, import, server restart, retention policies.

Split from the monolithic system.py to keep each router focused.
"""

import os
from typing import List, Optional, Union
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, BackgroundTasks
from pydantic import BaseModel

from backend.deps import get_current_user, admin_only, write_access, read_only, limiter, user_limiter, get_db, Session
from backend.schemas import LogActionSchema
from utils.logger import mto_logger

router = APIRouter(tags=["Maintenance"])


class RestoreRequest(BaseModel):
    file_path: str


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

@router.post("/system/backup/trigger")
@limiter.limit("3/minute")
@user_limiter.limit("3/minute")
async def trigger_backup(
    request: Request,
    current_user: dict = Depends(admin_only),
):
    """Queues a hybrid backup job. Returns job_id immediately."""
    from backend.services.job_service import submit_job
    job_id = submit_job(job_type="backup", submitted_by=current_user["username"])
    return {"status": "backup_started", "job_id": job_id,
            "message": "Backup queued. Poll /jobs/{job_id} for progress."}


@router.get("/system/backup/status", dependencies=[Depends(read_only)])
async def get_backup_health(
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    from backend.services.backup_service import get_backup_status
    return get_backup_status(db_session=db_session)


@router.get("/system/backup/schedule", dependencies=[Depends(read_only)])
async def get_backup_schedule(current_user: dict = Depends(get_current_user)):
    """Returns the configured automatic backup schedule and next run time."""
    from utils.config import config as _cfg

    schedule    = _cfg.BACKUP_SCHEDULE.strip().lower()
    hour        = _cfg.BACKUP_SCHEDULE_HOUR
    minute      = _cfg.BACKUP_SCHEDULE_MINUTE
    day_of_week = _cfg.BACKUP_SCHEDULE_DAY_OF_WEEK
    day_names   = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    if schedule == "disabled":
        return {"schedule": "disabled",
                "description": "Automatic backups are disabled.",
                "next_run": None}

    from datetime import timedelta
    now = datetime.now()

    if schedule == "daily":
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        description = f"Daily at {hour:02d}:{minute:02d} (local server time)"
    elif schedule == "weekly":
        days_ahead = (day_of_week - now.weekday()) % 7
        candidate = (now + timedelta(days=days_ahead)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(weeks=1)
        description = f"Weekly on {day_names[day_of_week]} at {hour:02d}:{minute:02d}"
    else:
        return {"schedule": schedule, "description": f"Unknown schedule: {schedule!r}", "next_run": None}

    return {
        "schedule": schedule, "description": description,
        "next_run": candidate.strftime("%Y-%m-%d %H:%M:%S"),
        "next_run_in_hours": round((candidate - now).total_seconds() / 3600, 1),
        "scheduled_hour": hour, "scheduled_minute": minute,
        "scheduled_day_of_week": day_names[day_of_week] if schedule == "weekly" else None,
    }


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

@router.post("/system/restore", dependencies=[Depends(admin_only)])
async def restore_system_backup(
    request: RestoreRequest,
    current_user: dict = Depends(get_current_user),
):
    from backend.services.system_service import restore_database
    from backend.services.backup_service import BACKUP_BASE_DIR
    import traceback
    try:
        file_path = request.file_path.replace("\\", "/").strip()

        # Security: constrain restore paths to the configured backup directory.
        # Without this, an admin could read arbitrary files on the server via
        # path traversal (e.g. "../../etc/passwd" fed to mysql stdin).
        import os
        resolved = os.path.realpath(file_path)
        allowed_base = os.path.realpath(BACKUP_BASE_DIR)
        if not resolved.startswith(allowed_base + os.sep) and resolved != allowed_base:
            raise HTTPException(
                status_code=400,
                detail=f"Restore path must be inside the backup directory ({BACKUP_BASE_DIR})."
            )

        result = restore_database(file_path)
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        error_detail = traceback.format_exc()
        try:
            with open("logs/restore_debug.log", "a") as f:
                f.write(f"\n[{datetime.now(timezone.utc)}] RESTORE FAILURE\n"
                        f"File: {request.file_path}\nError: {str(e)}\n{error_detail}\n" + "-" * 40 + "\n")
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Restore operation failed. Check server logs.")


# ---------------------------------------------------------------------------
# Bulk Import
# ---------------------------------------------------------------------------

@router.post("/system/import/validate", dependencies=[Depends(write_access)])
async def validate_bulk_import(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
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
    request: Request,
    data: Union[List[dict], dict],
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    from utils import is_feature_enabled
    if not is_feature_enabled("BULK_IMPORT"):
        raise HTTPException(status_code=403, detail="Bulk Import feature is currently disabled.")
    mode = request.query_params.get("mode", "property")

    if isinstance(data, dict):
        token = data.get("validation_token") or data.get("cache_token")
        if not token:
            raise HTTPException(status_code=400, detail="Missing validation_token in request body.")
        from backend.services.import_service import load_import_cache
        payload = load_import_cache(token)
        if payload is None:
            raise HTTPException(status_code=400, detail="Invalid, expired, or missing import validation token.")
    else:
        payload = [d.model_dump(exclude_unset=True) if hasattr(d, "model_dump") else d for d in data]

    if mode == "assessment":
        from backend.services.import_service import commit_assessment_import
        res = commit_assessment_import(payload, current_user, db_session=db_session)
        msg = f"{res['inserted']} inserted, {res['updated']} updated"
        if res.get("failed", 0):
            msg += f", {res['failed']} failed"
        return {"status": "success", "imported": res["inserted"] + res["updated"], "message": msg, "details": res}
    if mode == "payments":
        from backend.services.import_service import commit_payment_import
        res = commit_payment_import(payload, current_user, db_session=db_session)
        return {"status": "success", "imported": res["inserted"]}
    from backend.services.import_service import commit_property_import
    count = commit_property_import(payload, current_user, db_session=db_session)
    return {"status": "success", "imported": count}


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------

@router.post("/system/logs")
async def log_system_action(
    log: LogActionSchema,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    import backend.services.system_service as sys_svc
    sys_svc.log_action(current_user, log.action, db_session=db_session)
    db_session.commit()
    return {"status": "logged"}


@router.get("/system/audit-stats", dependencies=[Depends(admin_only)])
async def get_audit_stats(
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    import backend.services.system_service as sys_svc
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
    import backend.services.system_service as sys_svc
    results = sys_svc.get_audit_logs(
        username=username, search=search, date_from=date_from, date_to=date_to,
        limit=limit + 1, cursor=cursor, db_session=db_session,
    )
    has_more = len(results) > limit
    items = results[:limit]
    next_cursor = items[-1]["id"] if has_more and items else None
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


@router.get("/system/audit-users", dependencies=[Depends(admin_only)])
async def list_audit_users(
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    import backend.services.system_service as sys_svc
    return sys_svc.get_distinct_log_users(db_session=db_session)


@router.get("/system/logs", dependencies=[Depends(admin_only)])
async def get_system_logs(
    lines: int = 100,
    current_user: dict = Depends(get_current_user),
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


# ---------------------------------------------------------------------------
# Retention Policies
# ---------------------------------------------------------------------------

@router.get("/system/retention/policies", dependencies=[Depends(admin_only)])
async def list_retention_policies(
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    from backend.services.retention_service import get_all_policies
    return get_all_policies(db_session=db_session)


@router.get("/system/retention/logs", dependencies=[Depends(admin_only)])
async def list_retention_logs(
    limit: int = 100,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    from backend.services.retention_service import get_retention_logs
    return get_retention_logs(limit=limit, cursor=cursor, db_session=db_session)


@router.post("/system/retention/run", dependencies=[Depends(admin_only)])
async def run_retention_policy(
    dry_run: bool = False,
    data_type: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    from backend.services.job_service import submit_job
    mto_logger.info("Retention policy run requested", user=current_user.get("username"),
                    dry_run=dry_run, data_type=data_type)
    job_id = submit_job(job_type="retention_run", submitted_by=current_user["username"],
                        payload={"dry_run": dry_run, "data_type": data_type}, db_session=db_session)
    return {"job_id": job_id, "status": "queued", "dry_run": dry_run,
            "message": f"{'DRY RUN — ' if dry_run else ''}Retention policy queued."}


# ---------------------------------------------------------------------------
# Server Restart
# ---------------------------------------------------------------------------

@router.post("/system/restart", dependencies=[Depends(admin_only)])
async def restart_server(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """
    Gracefully restarts the backend server process.
    The response is sent first, then the process exits after a 2-second delay.
    The OS / startup script is responsible for restarting the process.
    """
    mto_logger.info("Server restart requested", user=current_user.get("username"))

    async def _do_restart():
        import asyncio
        await asyncio.sleep(2)
        mto_logger.info("Server process exiting for restart...")
        os._exit(0)

    background_tasks.add_task(_do_restart)
    return {"status": "restarting",
            "message": "Server will restart in ~2 seconds. Reconnect after 5–10 seconds.",
            "requested_by": current_user.get("username")}


# ---------------------------------------------------------------------------
# Penalty Accrual — manual trigger for admins
# ---------------------------------------------------------------------------

@router.post("/system/accrue-penalties", dependencies=[Depends(admin_only)])
async def trigger_penalty_accrual(
    dry_run: bool = False,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """
    Manually triggers the monthly penalty accrual job.

    Adds 2% of the outstanding balance to the penalty column for every
    delinquent PropertyBilling row from prior years.

    dry_run=true  → preview totals, no DB changes.
    dry_run=false → applies accrual and commits.

    This runs automatically on the 1st of each month via the maintenance
    scheduler. Use this endpoint to trigger it manually (e.g. after a
    bulk import of historical data).

    Admin only.
    """
    from backend.services.job_service import submit_job

    mto_logger.info(
        "Manual penalty accrual triggered",
        user=current_user.get("username"),
        dry_run=dry_run,
    )

    job_id = submit_job(
        job_type="accrue_penalties",
        submitted_by=current_user["username"],
        payload={"dry_run": dry_run},
        db_session=db_session,
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "dry_run": dry_run,
        "message": (
            f"{'DRY RUN — ' if dry_run else ''}"
            "Penalty accrual queued. Poll /jobs/{job_id} for progress."
        ),
    }
