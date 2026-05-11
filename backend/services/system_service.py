# -*- coding: utf-8 -*-
import os
import subprocess
from datetime import datetime
import db_manager as db
from services.auth_service import get_username


def backup_database(destination_path):
    dump_path = db.DB_CONFIG.get("mysqldump_path", "mysqldump")
    db_user = db.DB_CONFIG["user"]
    db_pass = db.DB_CONFIG["password"]
    db_name = db.DB_CONFIG["database"]
    try:
        dest_dir = os.path.dirname(destination_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)
        with open(destination_path, "w", encoding="utf-8") as f:
            cmd = [dump_path, f"-u{db_user}", db_name]
            if db_pass:
                cmd.insert(2, f"-p{db_pass}")
            subprocess.run(cmd, stdout=f, check=True)
        return True
    except Exception as e:
        print(f"Backup Error: {e}")
        return False


def restore_database(sql_file_path):
    mysql_path = db.DB_CONFIG.get("mysql_path", "mysql")
    db_user = db.DB_CONFIG["user"]
    db_pass = db.DB_CONFIG["password"]
    db_name = db.DB_CONFIG["database"]

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

    cmd = [mysql_path, f"-u{db_user}", db_name]
    if db_pass:
        cmd.insert(2, f"-p{db_pass}")

    try:
        # Close any existing connection to avoid state issues
        db.close_db_connection()

        with open(sql_file_path, "r", encoding="utf-8", errors="ignore") as source:
            subprocess.run(cmd, stdin=source, check=True)
    except Exception as exc:
        raise RuntimeError(f"Restore failed: {exc}") from exc
    return {"ok": True, "safety_backup": safety_backup, "restored_file": sql_file_path}


def log_action(user, action):
    query = "INSERT INTO audit_logs (username, action, timestamp) VALUES (%s, %s, %s)"
    params = (get_username(user), action, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    db.db_query(query, params)


def get_dashboard_summary():
    summary = {
        "total_properties": 0,
        "unpaid_properties": 0,
        "collections_today": 0.0,
        "collections_month": 0.0,
    }
    result = db.db_query(
        """
        SELECT
            (SELECT COUNT(*) FROM properties WHERE is_deleted = 0),
            (SELECT COUNT(*) FROM properties p WHERE p.is_deleted = 0
                AND NOT EXISTS (SELECT 1 FROM payments pay WHERE pay.property_id = p.id)),
            (SELECT COALESCE(SUM(amount), 0) FROM payments WHERE DATE(date_paid) = CURDATE()),
            (SELECT COALESCE(SUM(amount), 0) FROM payments
                WHERE YEAR(date_paid) = YEAR(CURDATE()) AND MONTH(date_paid) = MONTH(CURDATE()))
        """,
        fetch=True,
        commit=False,
    )
    if result:
        row = result[0]
        summary["total_properties"] = int(row[0] or 0)
        summary["unpaid_properties"] = int(row[1] or 0)
        summary["collections_today"] = float(row[2] or 0)
        summary["collections_month"] = float(row[3] or 0)

    # Add backup status from backup_service
    try:
        from backend.services.backup_service import get_backup_status

        summary["backup"] = get_backup_status()
    except:
        summary["backup"] = {}

    return summary


def get_report_summary(selected_month="All", selected_year="All"):
    filters = []
    params = []
    if selected_month != "All":
        filters.append("MONTH(pay.date_paid) = %s")
        params.append(int(selected_month))
    if selected_year != "All":
        filters.append("YEAR(pay.date_paid) = %s")
        params.append(int(selected_year))

    where_clause = "WHERE prop.is_deleted = 0"
    if filters:
        where_clause += " AND " + " AND ".join(filters)

    rows = db.db_query(
        f"""
        SELECT
            COALESCE(SUM(pay.amount), 0),
            COUNT(pay.id),
            COUNT(DISTINCT pay.property_id),
            MAX(pay.date_paid)
        FROM payments pay
        JOIN properties prop ON prop.id = pay.property_id
        {where_clause}
        """,
        tuple(params),
        fetch=True,
        commit=False,
    )
    if not rows:
        return {
            "total_amount": 0.0,
            "payment_count": 0,
            "property_count": 0,
            "latest_payment": "",
        }
    row = rows[0]
    return {
        "total_amount": float(row[0] or 0),
        "payment_count": int(row[1] or 0),
        "property_count": int(row[2] or 0),
        "latest_payment": row[3] or "",
    }


def get_audit_stats():
    rows = db.db_query(
        """
        SELECT
            (SELECT COUNT(*) FROM audit_logs),
            (SELECT COUNT(*) FROM audit_logs WHERE DATE(timestamp) = CURDATE()),
            (SELECT COUNT(DISTINCT username) FROM audit_logs WHERE timestamp >= NOW() - INTERVAL 7 DAY)
        """,
        fetch=True,
        commit=False,
    )
    if not rows:
        return {"total": 0, "today": 0, "active_users": 0}
    row = rows[0]
    return {
        "total": int(row[0] or 0),
        "today": int(row[1] or 0),
        "active_users": int(row[2] or 0),
    }


def get_audit_logs(user_id=None, limit=100):
    filters = []
    params = []
    if user_id:
        filters.append("user_id = %s")
        params.append(user_id)

    where_clause = "WHERE 1=1"
    if filters:
        where_clause += " AND " + " AND ".join(filters)

    query = f"""
        SELECT id, timestamp, username, action, table_name, record_id, old_values, new_values, ip_address
        FROM audit_logs
        {where_clause}
        ORDER BY timestamp DESC
        LIMIT %s
    """
    params.append(limit)

    rows = db.db_query(query, tuple(params), fetch=True, commit=False) or []
    return [
        {
            "id": r[0],
            "timestamp": r[1],
            "username": r[2],
            "action": r[3],
            "table_name": r[4],
            "record_id": r[5],
            "old_values": r[6],
            "new_values": r[7],
            "ip_address": r[8],
        }
        for r in rows
    ]


def get_distinct_log_users():
    rows = (
        db.db_query(
            "SELECT DISTINCT username FROM audit_logs WHERE username IS NOT NULL AND TRIM(username) <> '' ORDER BY username ASC",
            fetch=True,
            commit=False,
        )
        or []
    )
    return [str(row[0]) for row in rows if row and row[0]]


def archive_audit_logs(days=365):
    old_rows = db.db_query(
        f"SELECT timestamp, username, action FROM audit_logs WHERE timestamp < NOW() - INTERVAL {int(days)} DAY ORDER BY timestamp ASC",
        fetch=True,
        commit=False,
    )
    return old_rows or []


def delete_old_audit_logs(days=365):
    def operation(cur):
        cur.execute(
            f"DELETE FROM audit_logs WHERE timestamp < NOW() - INTERVAL %s DAY",
            (int(days),),
        )
        return cur.rowcount

    return db.execute_transaction(operation)
