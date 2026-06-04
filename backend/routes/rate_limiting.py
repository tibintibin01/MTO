# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.deps import admin_only, get_db
import backend.services.rate_limit_service as rate_limit_svc

router = APIRouter(tags=["Rate Limiting Admin"])

class RateLimitResetRequest(BaseModel):
    identifier: str

@router.get("/system/rate-limiting/stats", dependencies=[Depends(admin_only)])
async def get_rate_limiting_stats(db_session: Session = Depends(get_db)):
    """
    Returns rate limiting stats and metrics for administrator review.
    """
    try:
        stats = rate_limit_svc.get_rate_limit_stats(db_session)
        return stats
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to compile rate limiting stats: {str(e)}"
        )

@router.get("/system/rate-limiting/blocks", dependencies=[Depends(admin_only)])
async def get_rate_limiting_blocks(
    limit: int = Query(50, ge=1, le=100),
    cursor: int | None = Query(None),
    db_session: Session = Depends(get_db),
):
    """
    Returns paginated audit logs of rate limit blocks.
    """
    try:
        blocks, next_cursor = rate_limit_svc.get_rate_limit_blocks(
            db_session, limit=limit, cursor=cursor
        )
        return {"blocks": blocks, "next_cursor": next_cursor}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve rate limit blocks: {str(e)}"
        )

@router.post("/system/rate-limiting/reset", dependencies=[Depends(admin_only)])
async def reset_rate_limits(
    data: RateLimitResetRequest,
    db_session: Session = Depends(get_db)
):
    """
    Manually clears rate limit counters/keys for a specific client IP or username.
    """
    identifier = data.identifier.strip()
    if not identifier:
        raise HTTPException(
            status_code=400,
            detail="Client identifier (IP address or Username) is required."
        )
        
    try:
        cleared_count = rate_limit_svc.reset_client_rate_limits(identifier)
        return {
            "status": "success",
            "message": f"Successfully cleared rate limit keys for '{identifier}'.",
            "cleared_keys_count": cleared_count,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset rate limits: {str(e)}"
        )
