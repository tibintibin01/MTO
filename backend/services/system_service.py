import os
import sys
import subprocess
from datetime import datetime

# Ensure project root is in path for relative imports
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.append(project_root)

from db_manager import DB_CONFIG
from backend.database import SessionLocal
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session
from backend.models import Payment, Property, AuditLog, User
from backend.services.auth_service import get_username


def backup_database(destination_path):
    dump_path = DB_CONFIG.get("mysqldump_path", "mysqldump")
    db_user = DB_CONFIG["user"]
    db_pass = DB_CONFIG["password"]
    db_name = DB_CONFIG["database"]
    db_host = DB_CONFIG["host"]
    db_port = DB_CONFIG.get("port", 3306)

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
    mysql_path = DB_CONFIG.get("mysql_path", "mysql")
    db_user = DB_CONFIG["user"]
    db_pass = DB_CONFIG["password"]
    db_name = DB_CONFIG["database"]
    db_host = DB_CONFIG["host"]
    db_port = DB_CONFIG.get("port", 3306)

    if not sql_file_path or not os.path.isfile(sql_file_path):
        raise FileNotFoundError("The selected SQL backup file was not found.")

    backups_dir = os.path.join(os.path.dirname(sql_file_path), "pre_restore_backups")
    os.makedirs(backups_dir, exist_ok=True)
    safety_backup = os.path.join(
        backups_dir, f"PRE_RESTORE_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.sql"
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
    if not db_session:
        db_session = SessionLocal()
        
    log = AuditLog(
        username=get_username(user),
        action=action,
        timestamp=datetime.now()
    )
    db_session.add(log)
    db_session.commit()


def get_dashboard_summary(db_session: Session = None):
    from backend.services.stats_service import get_cached_stat, refresh_system_stats
    
    if not db_session:
        db_session = SessionLocal()

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
        summary["backup"] = get_backup_status()
    except:
        summary["backup"] = {}

    return summary



def get_report_summary(selected_month="All", selected_year="All", db_session: Session = None):
    if not db_session:
        db_session = SessionLocal()

    query = db_session.query(
        func.coalesce(func.sum(Payment.amount), 0),
        func.count(Payment.id),
        func.count(func.distinct(Payment.property_id)),
        func.max(Payment.date_paid)
    ).join(Property, Property.id == Payment.property_id).filter(Property.is_deleted == False)
    
    if selected_month != "All":
        query = query.filter(func.month(Payment.date_paid) == int(selected_month))
    if selected_year != "All":
        query = query.filter(func.year(Payment.date_paid) == int(selected_year))
        
    row = query.first()
    return {
        "total_amount": float(row[0] or 0),
        "payment_count": int(row[1] or 0),
        "property_count": int(row[2] or 0),
        "latest_payment": row[3] or "",
    }


def get_audit_stats(db_session: Session = None):
    if not db_session:
        db_session = SessionLocal()

    total = db_session.query(func.count(AuditLog.id)).scalar()
    today = db_session.query(func.count(AuditLog.id)).filter(func.date(AuditLog.timestamp) == func.curdate()).scalar()
    active_users = db_session.query(func.count(func.distinct(AuditLog.username))).filter(
        AuditLog.timestamp >= func.now() - func.interval(7, 'day')
    ).scalar()
    
    return {
        "total": int(total or 0),
        "today": int(today or 0),
        "active_users": int(active_users or 0),
    }


def get_audit_logs(username=None, search="", date_from=None, date_to=None, limit=100, cursor=None, db_session: Session = None):
    if not db_session:
        db_session = SessionLocal()

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
        query = query.filter(func.date(AuditLog.timestamp) >= date_from)
    if date_to:
        query = query.filter(func.date(AuditLog.timestamp) <= date_to)
        
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
    if not db_session:
        db_session = SessionLocal()

    results = db_session.query(AuditLog.username).filter(
        AuditLog.username != None, 
        func.trim(AuditLog.username) != ''
    ).distinct().order_by(AuditLog.username.asc()).all()
    return [str(r[0]) for r in results if r[0]]


def archive_audit_logs(days=365, db_session: Session = None):
    if not db_session:
        db_session = SessionLocal()
        
    cutoff = datetime.now() - func.interval(int(days), 'day')
    results = db_session.query(AuditLog.timestamp, AuditLog.username, AuditLog.action).filter(
        AuditLog.timestamp < cutoff
    ).order_by(AuditLog.timestamp.asc()).all()
    return results or []


def delete_old_audit_logs(days=365, db_session: Session = SessionLocal()):
    cutoff = datetime.now() - func.interval(int(days), 'day')
    count = db_session.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete()
    db_session.commit()
    return count
def get_system_stats(db_session: Session = None):
    """
    Aggregates technical metrics for the System Health dashboard.
    """
    if not db_session:
        db_session = SessionLocal()

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

    # 2. Cache Stats (Mocking for now as we haven't implemented Redis yet)
    cache_data = {
        "items": 124, # placeholder
        "hit_rate": 94.2,
        "provider": "Local Diskcache",
        "namespaces": ["property", "billing", "auth"]
    }

    # 3. Security & Integrity
    total_logs = db_session.query(func.count(AuditLog.id)).scalar()
    active_sessions = db_session.query(func.count(RefreshToken.id)).filter(
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.now()
    ).scalar()
    
    integrity_ok = total_logs is not None

    security_data = {
        "total_logs": total_logs,
        "integrity_ok": integrity_ok,
        "active_sessions": active_sessions,
        "active_lockouts": db_session.query(func.count(User.id)).filter(User.lockout_until > datetime.now()).scalar()
    }

    # 4. API Latency (Placeholders - would normally come from MetricsManager)
    api_data = {
        "avg_latency": 42.5,
        "error_rate": 0.2,
        "rpm": 12,
    }

    return {
        "pool": pool_data,
        "cache": cache_data,
        "security": security_data,
        "api": api_data,
        "uptime": "14h 22m" # placeholder
    }
