import os
import subprocess
from datetime import datetime, timedelta, timezone

from utils.config import config as mto_config
from utils.secrets_manager import secrets
from backend.database import engine
from sqlalchemy import or_, func, cast
from sqlalchemy.types import Date
from sqlalchemy.orm import Session
from backend.models import Payment, Property, AuditLog, User
from backend.services.auth_service import get_username
from utils.db_compat import year_of, month_of, days_ago

# Record the exact moment this module is first imported (i.e. server start).
# Used to calculate real uptime in get_system_stats().
_SERVER_START_TIME: datetime = datetime.now(timezone.utc)


def _format_uptime(start: datetime) -> str:
    """Returns a human-readable uptime string like '2d 4h 17m'."""
    delta = datetime.now(timezone.utc) - start
    total_seconds = int(delta.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def backup_database(destination_path):
    dump_path = mto_config.MYSQLDUMP_PATH
    db_user = mto_config.DB_USER
    db_pass = secrets.db_password
    db_name = mto_config.DB_NAME
    db_host = mto_config.DB_HOST
    db_port = mto_config.DB_PORT

    try:
        dest_dir = os.path.dirname(destination_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)
            
        with open(destination_path, "w", encoding="utf-8") as f:
            cmd = [
                dump_path, 
                f"-u{db_user}", 
                f"-h{db_host}",
                f"-P{db_port}",
                "--single-transaction",
                db_name
            ]
            if db_pass:
                cmd.insert(2, f"-p{db_pass}")
            
            subprocess.run(cmd, stdout=f, check=True, timeout=300)
        return True
    except Exception as e:
        print(f"Backup Error: {e}")
        return False


def restore_database(sql_file_path):
    mysql_path = mto_config.MYSQL_PATH
    db_user = mto_config.DB_USER
    db_pass = secrets.db_password
    db_name = mto_config.DB_NAME
    db_host = mto_config.DB_HOST
    db_port = mto_config.DB_PORT

    if not sql_file_path or not os.path.isfile(sql_file_path):
        raise FileNotFoundError("The selected SQL backup file was not found.")

    backups_dir = os.path.join(os.path.dirname(sql_file_path), "pre_restore_backups")
    os.makedirs(backups_dir, exist_ok=True)
    safety_backup = os.path.join(
        backups_dir, f"PRE_RESTORE_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')}.sql"
    )
    if not backup_database(safety_backup):
        raise RuntimeError(
            "Could not create the automatic safety backup. Restore cancelled."
        )

    cmd = [
        mysql_path, 
        f"-u{db_user}", 
        f"-h{db_host}",
        f"-P{db_port}",
        db_name
    ]
    if db_pass:
        cmd.insert(2, f"-p{db_pass}")

    try:
        # Proceed with restore without explicit close (handled by process isolation)
        with open(sql_file_path, "r", encoding="utf-8", errors="ignore") as source:
            result = subprocess.run(
                cmd, 
                stdin=source, 
                check=True, 
                capture_output=True, 
                text=True,
                timeout=600
            )
            print(f"Restore Output: {result.stdout}")
    except subprocess.CalledProcessError as cpe:
        error_msg = f"MySQL Error: {cpe.stderr or cpe.output}"
        print(error_msg)
        raise RuntimeError(error_msg) from cpe
    except Exception as exc:
        print(f"General Restore Error: {exc}")
        raise RuntimeError(f"Restore failed: {exc}") from exc
    return {"ok": True, "safety_backup": safety_backup, "restored_file": sql_file_path}


def log_action(user, action, db_session: Session = None):
    log = AuditLog(
        username=get_username(user),
        action=action,
        timestamp=datetime.now(timezone.utc)
    )
    db_session.add(log)
    # Intentionally no commit here — callers own the transaction boundary.


def get_dashboard_summary(db_session: Session = None):
    from backend.services.stats_service import get_cached_stat, refresh_system_stats
    
    total_props = int(get_cached_stat("total_properties", db_session=db_session))
    
    # Auto-refresh if the cache is empty (likely first run or empty table)
    if total_props == 0:
        refresh_system_stats(db_session=db_session)
        total_props = int(get_cached_stat("total_properties", db_session=db_session))

    summary = {
        "total_properties": total_props,
        "unpaid_properties": int(get_cached_stat("unpaid_properties", db_session=db_session)),
        "collections_today": float(get_cached_stat("collections_today", db_session=db_session)),
        "collections_month": float(get_cached_stat("collections_month", db_session=db_session)),
    }

    # Add backup status from backup_service
    try:
        from backend.services.backup_service import get_backup_status
        summary["backup"] = get_backup_status(db_session=db_session)
    except Exception as e:
        mto_logger.warning("Could not fetch backup status for dashboard: %s", e)
        summary["backup"] = {}

    return summary



def get_report_summary(selected_month="All", selected_year="All", db_session: Session = None):
    query = db_session.query(
        func.coalesce(func.sum(Payment.amount), 0),
        func.count(Payment.id),
        func.count(func.distinct(Payment.property_id)),
        func.max(Payment.date_paid)
    ).join(Property, Property.id == Payment.property_id).filter(Property.deleted_at == None)
    
    if selected_month != "All":
        query = query.filter(month_of(Payment.date_paid) == int(selected_month))
    if selected_year != "All":
        query = query.filter(year_of(Payment.date_paid) == int(selected_year))
        
    row = query.first()
    return {
        "total_amount": float(row[0] or 0),
        "payment_count": int(row[1] or 0),
        "property_count": int(row[2] or 0),
        "latest_payment": row[3] or "",
    }


def get_audit_stats(db_session: Session = None):
    from utils.db_compat import today
    today_date = today()
    week_ago = days_ago(7)

    total = db_session.query(func.count(AuditLog.id)).scalar()
    today_count = db_session.query(func.count(AuditLog.id)).filter(
        cast(AuditLog.timestamp, Date) == today_date
    ).scalar()
    active_users = db_session.query(func.count(func.distinct(AuditLog.username))).filter(
        AuditLog.timestamp >= week_ago
    ).scalar()

    return {
        "total": int(total or 0),
        "today": int(today_count or 0),
        "active_users": int(active_users or 0),
    }


def get_audit_logs(username=None, search="", date_from=None, date_to=None, limit=100, cursor=None, db_session: Session = None):
    query = db_session.query(AuditLog)
    
    if username and username != "ALL":
        query = query.filter(AuditLog.username == username)
        
    if search:
        like_search = f"%{search}%"
        query = query.filter(or_(
            AuditLog.action.like(like_search),
            AuditLog.table_name.like(like_search),
            func.cast(AuditLog.record_id, func.CHAR).like(like_search)
        ))
        
    if date_from:
        query = query.filter(cast(AuditLog.timestamp, Date) >= date_from)
    if date_to:
        query = query.filter(cast(AuditLog.timestamp, Date) <= date_to)
        
    if cursor:
        query = query.filter(AuditLog.id < int(cursor))
        
    rows = query.order_by(AuditLog.id.desc()).limit(int(limit)).all()
    
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M:%S") if r.timestamp else "",
            "username": r.username,
            "action": r.action,
            "table_name": r.table_name,
            "record_id": r.record_id,
            "old_values": r.old_values,
            "new_values": r.new_values,
            "ip_address": r.ip_address,
        }
        for r in rows
    ]


def get_distinct_log_users(db_session: Session = None):
    results = db_session.query(AuditLog.username).filter(
        AuditLog.username != None, 
        func.trim(AuditLog.username) != ''
    ).distinct().order_by(AuditLog.username.asc()).all()
    return [str(r[0]) for r in results if r[0]]


def archive_audit_logs(days=365, db_session: Session = None):
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    results = db_session.query(AuditLog.timestamp, AuditLog.username, AuditLog.action).filter(
        AuditLog.timestamp < cutoff
    ).order_by(AuditLog.timestamp.asc()).all()
    return results or []


def delete_old_audit_logs(db_session: Session, days: int = 365):
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    count = db_session.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete()
    db_session.commit()
    return count


def get_system_stats(db_session: Session = None):
    """
    Aggregates technical metrics for the System Health dashboard.
    """
    from backend.database import engine
    from backend.models import RefreshToken
    
    # 1. Pool Stats
    pool = engine.pool
    pool_data = {
        "active": pool.checkedout(),
        "idle": pool.size() - pool.checkedout(),
        "overflow": max(0, pool.overflow()) if hasattr(pool, 'overflow') else 0,
        "size": pool.size()
    }

    # 2. Cache Stats — read from the live CacheManager singleton
    from utils.cache_manager import cache as _cache

    try:
        if _cache._redis_client:
            # Redis mode — query the server for real stats
            try:
                info = _cache._redis_client.info()
                redis_keys = _cache._redis_client.dbsize()
                cache_data = {
                    "items": redis_keys,
                    "hit_rate": round(
                        info.get("keyspace_hits", 0) /
                        max(1, info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0)) * 100,
                        1
                    ),
                    "provider": _cache.engine,
                    "memory_used": info.get("used_memory_human", "N/A"),
                    "namespaces": len(set(
                        k.split(":")[1] for k in (_cache._redis_client.keys("mto:*") or [])
                        if isinstance(k, (str, bytes)) and b":" in (k if isinstance(k, bytes) else k.encode())
                    )),
                }
            except Exception:
                cache_data = {"items": 0, "hit_rate": 0.0, "provider": _cache.engine, "namespaces": 0}
        else:
            # In-memory mode — count live (non-expired) items across all namespaces
            import time as _time
            live_items = 0
            namespaces = list(_cache._memory_cache.keys())
            for ns, entries in _cache._memory_cache.items():
                live_items += sum(
                    1 for _, (_, exp) in entries.items()
                    if exp is None or exp > _time.time()
                )
            cache_data = {
                "items": live_items,
                "hit_rate": -1,  # -1 signals N/A — in-memory cache doesn't track hits
                "provider": _cache.engine,
                "namespaces": len(namespaces),
            }
    except Exception:
        cache_data = {"items": 0, "hit_rate": 0.0, "provider": "Unknown", "namespaces": 0}

    # 3. Security & Integrity
    total_logs = db_session.query(func.count(AuditLog.id)).scalar()
    active_sessions = db_session.query(func.count(RefreshToken.id)).filter(
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.now(timezone.utc)
    ).scalar()
    
    integrity_ok = total_logs is not None

    security_data = {
        "total_logs": total_logs,
        "integrity_ok": integrity_ok,
        "active_sessions": active_sessions,
        "active_lockouts": db_session.query(func.count(User.id)).filter(User.lockout_until > datetime.now(timezone.utc)).scalar()
    }

    # 4. API Performance — read from the live Prometheus metrics that the
    # observability middleware populates on every request.
    from utils.metrics import REQUEST_COUNT, REQUEST_LATENCY

    try:
        # Total requests since server start
        total_requests = sum(
            sample.value
            for metric in REQUEST_COUNT.collect()
            for sample in metric.samples
            if sample.name.endswith("_total")
        )

        # Error count = requests with status 4xx or 5xx
        error_requests = sum(
            sample.value
            for metric in REQUEST_COUNT.collect()
            for sample in metric.samples
            if sample.name.endswith("_total")
            and str(sample.labels.get("status", "")).startswith(("4", "5"))
        )

        error_rate = round((error_requests / total_requests * 100), 2) if total_requests > 0 else 0.0

        # Average latency from histogram sum/count
        latency_sum = sum(
            sample.value
            for metric in REQUEST_LATENCY.collect()
            for sample in metric.samples
            if sample.name.endswith("_sum")
        )
        latency_count = sum(
            sample.value
            for metric in REQUEST_LATENCY.collect()
            for sample in metric.samples
            if sample.name.endswith("_count")
        )
        avg_latency_ms = round((latency_sum / latency_count) * 1000, 2) if latency_count > 0 else 0.0

        # Requests per minute since server start
        uptime_minutes = max(1, (datetime.now(timezone.utc) - _SERVER_START_TIME).total_seconds() / 60)
        rpm = round(total_requests / uptime_minutes, 1)

    except Exception:
        avg_latency_ms = 0.0
        error_rate = 0.0
        rpm = 0.0

    api_data = {
        "avg_latency": avg_latency_ms,
        "error_rate": error_rate,
        "rpm": rpm,
        "total_requests": int(total_requests) if "total_requests" in locals() else 0,
    }

    return {
        "pool": pool_data,
        "cache": cache_data,
        "security": security_data,
        "api": api_data,
        "uptime": _format_uptime(_SERVER_START_TIME),
        "started_at": _SERVER_START_TIME.strftime("%Y-%m-%d %H:%M:%S"),
    }
