# -*- coding: utf-8 -*-
from datetime import datetime, timezone, timedelta, time
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend.models import RateLimitBlock
from backend.deps import limiter, user_limiter
from utils.logger import mto_logger

_PH_TZ = timezone(timedelta(hours=8))

def log_rate_limit_block(
    db_session: Session,
    ip_address: str,
    username: str | None,
    endpoint: str,
    limit_rule: str,
    retry_after: int,
) -> RateLimitBlock | None:
    """
    Saves a rate limit block audit log to the database.
    """
    try:
        block = RateLimitBlock(
            timestamp=datetime.now(timezone.utc),
            ip_address=ip_address,
            username=username,
            endpoint=endpoint,
            limit_rule=limit_rule,
            retry_after=retry_after,
        )
        db_session.add(block)
        db_session.commit()
        mto_logger.info(
            f"Rate limit block logged to database for client: {username or ip_address}",
            ip=ip_address,
            user=username,
            endpoint=endpoint,
            rule=limit_rule,
        )
        return block
    except Exception as e:
        db_session.rollback()
        mto_logger.error(f"Failed to log rate limit block to database: {e}", exc_info=True)
        return None

def get_rate_limit_stats(db_session: Session) -> dict:
    """
    Compiles rate limiting metrics and statistics.
    """
    # 1. Total Blocks
    total_blocks = db_session.query(func.count(RateLimitBlock.id)).scalar() or 0

    # 2. Blocks Today (Philippine Standard Time calendar day)
    today = datetime.now(_PH_TZ).date()
    start_time = datetime.combine(today, time.min, tzinfo=_PH_TZ).astimezone(timezone.utc)
    end_time = datetime.combine(today, time.max, tzinfo=_PH_TZ).astimezone(timezone.utc)
    
    blocks_today = (
        db_session.query(func.count(RateLimitBlock.id))
        .filter(RateLimitBlock.timestamp >= start_time, RateLimitBlock.timestamp <= end_time)
        .scalar()
        or 0
    )

    # 3. Top blocked IPs (Limit to 10)
    top_ips_query = (
        db_session.query(RateLimitBlock.ip_address, func.count(RateLimitBlock.id).label("count"))
        .group_by(RateLimitBlock.ip_address)
        .order_by(func.count(RateLimitBlock.id).desc())
        .limit(10)
        .all()
    )
    top_blocked_ips = [{"ip_address": row[0], "count": row[1]} for row in top_ips_query]

    # 4. Top blocked Users (Limit to 10)
    top_users_query = (
        db_session.query(RateLimitBlock.username, func.count(RateLimitBlock.id).label("count"))
        .filter(RateLimitBlock.username.isnot(None))
        .group_by(RateLimitBlock.username)
        .order_by(func.count(RateLimitBlock.id).desc())
        .limit(10)
        .all()
    )
    top_blocked_users = [{"username": row[0], "count": row[1]} for row in top_users_query]

    # 5. Blocks by Endpoint (Limit to 10)
    endpoints_query = (
        db_session.query(RateLimitBlock.endpoint, func.count(RateLimitBlock.id).label("count"))
        .group_by(RateLimitBlock.endpoint)
        .order_by(func.count(RateLimitBlock.id).desc())
        .limit(10)
        .all()
    )
    blocks_by_endpoint = [{"endpoint": row[0], "count": row[1]} for row in endpoints_query]

    return {
        "total_blocks": total_blocks,
        "blocks_today": blocks_today,
        "top_blocked_ips": top_blocked_ips,
        "top_blocked_users": top_blocked_users,
        "blocks_by_endpoint": blocks_by_endpoint,
    }

def get_rate_limit_blocks(
    db_session: Session, limit: int = 100, cursor: int | None = None
) -> tuple[list[dict], int | None]:
    """
    Retrieves paginated logs of rate limit blocks in descending order.
    Returns (blocks_list, next_cursor).
    """
    query = db_session.query(RateLimitBlock)
    if cursor is not None:
        query = query.filter(RateLimitBlock.id < cursor)
        
    blocks = query.order_by(RateLimitBlock.id.desc()).limit(limit).all()
    
    blocks_list = [
        {
            "id": b.id,
            "timestamp": b.timestamp.isoformat() + "Z",
            "ip_address": b.ip_address,
            "username": b.username,
            "endpoint": b.endpoint,
            "limit_rule": b.limit_rule,
            "retry_after": b.retry_after,
        }
        for b in blocks
    ]
    
    next_cursor = blocks[-1].id if len(blocks) == limit else None
    return blocks_list, next_cursor

def reset_client_rate_limits(identifier: str) -> int:
    """
    Clears rate limiting keys matching the given client identifier (IP or Username)
    across all active limiters and storage backends.
    """
    cleared_count = 0
    if not identifier:
        return 0

    # Ensure clean matching string
    search_str = identifier.strip()

    for limiter_instance in (limiter, user_limiter):
        storage = limiter_instance._storage
        
        # Check MemoryStorage
        if hasattr(storage, "storage") and isinstance(storage.storage, dict):
            keys_to_clear = [k for k in list(storage.storage.keys()) if search_str in k]
            for k in keys_to_clear:
                storage.clear(k)
                cleared_count += 1
                
        # Check RedisStorage (or ValkeyStorage)
        elif hasattr(storage, "storage") and not isinstance(storage.storage, dict):
            try:
                redis_client = storage.storage
                prefix = getattr(storage, "key_prefix", "LIMITS")
                # Look for matching keys anywhere in redis (which contains the identifier)
                pattern = f"*{search_str}*"
                matching_keys = redis_client.keys(pattern)
                for byte_key in matching_keys:
                    key_str = byte_key.decode("utf-8") if isinstance(byte_key, bytes) else byte_key
                    # Strip standard prefix + ":" to pass key to storage.clear
                    prefix_str = f"{prefix}:"
                    if key_str.startswith(prefix_str):
                        unprefixed = key_str[len(prefix_str):]
                    else:
                        unprefixed = key_str
                    storage.clear(unprefixed)
                    cleared_count += 1
            except Exception as e:
                mto_logger.error(f"Failed to query/clear Redis rate limiting keys: {e}", exc_info=True)
                
    mto_logger.info(f"Unblocked rate limit keys for identifier '{search_str}'. Cleared {cleared_count} keys.")
    return cleared_count
