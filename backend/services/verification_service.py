import os
import subprocess
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from utils.config import config as mto_config
from utils.secrets_manager import secrets

DB_CONFIG = {
    "mysql_path": getattr(mto_config, "MYSQL_PATH", "mysql"),
    "user": mto_config.DB_USER,
    "password": secrets.db_password,
    "host": mto_config.DB_HOST,
}

def verify_sql_dump(file_path, db_session: Session = None):
    """
    Performs a multi-point integrity check on a MySQL dump file.
    1. Shallow Check: File presence and completion marker.
    2. Deep Check: Automated Restore Test into a temp database (skipped if
       no DB session is available or DB credentials are not configured).
    """
    # 1. Shallow Check
    if not os.path.exists(file_path):
        return False, "Backup file was not created."
    
    file_size = os.path.getsize(file_path)
    if file_size < 100:
        return False, f"Backup file is suspiciously small ({file_size} bytes)."

    try:
        with open(file_path, "rb") as f:
            if file_size > 1024:
                f.seek(-1024, os.SEEK_END)
            footer = f.read().decode("utf-8", errors="ignore")
            if "-- Dump completed" not in footer and "UNLOCK TABLES;" not in footer:
                return False, "Incomplete SQL dump (no completion marker)."
    except Exception as e:
        return False, f"Shallow Verification Error: {str(e)}"

    # 2. Deep Check — requires a live DB session and configured credentials
    if db_session is None:
        try:
            with SessionLocal() as session:
                return perform_restore_test(file_path, db_session=session)
        except Exception:
            # If we can't get a session (e.g. DB not configured), skip deep check
            return True, "Shallow check passed. Deep restore test skipped (no DB session)."

    return perform_restore_test(file_path, db_session=db_session)


def perform_restore_test(file_path, db_session: Session = None):
    """
    Verifies that the backup can actually be restored by performing
    a dry-run restore into a temporary validation database.
    """
    # Create a safe temp name (sanitize filename to be a valid DB name)
    base_name = os.path.basename(file_path).split('.')[0]
    safe_name = "".join([c if c.isalnum() else "_" for c in base_name])
    temp_db_name = f"mto_verify_{safe_name}"
    
    mysql_path = DB_CONFIG.get("mysql_path", "mysql")
    db_user = DB_CONFIG["user"]
    db_pass = DB_CONFIG["password"]
    db_host = DB_CONFIG["host"]

    # Search paths in priority order: config value first, then common locations
    # for Windows (XAMPP, standard installer), Linux, Docker, and macOS Homebrew.
    COMMON_MYSQL_PATHS = [
        mysql_path,
        # Windows
        r"C:\xampp\mysql\bin\mysql.exe",
        r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
        r"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysql.exe",
        r"D:\xampp\mysql\bin\mysql.exe",
        r"C:\mysql\bin\mysql.exe",
        # Linux / Docker
        "/usr/bin/mysql",
        "/usr/local/bin/mysql",
        # macOS Homebrew
        "/opt/homebrew/bin/mysql",
        "/usr/local/mysql/bin/mysql",
    ]

    import shutil
    actual_mysql_executable = None
    for p in COMMON_MYSQL_PATHS:
        if "\\" not in p and "/" not in p:
            if shutil.which(p):
                actual_mysql_executable = p
                break
        elif os.path.exists(p):
            actual_mysql_executable = p
            break
    
    if not actual_mysql_executable:
        return False, "Could not locate 'mysql' executable for restore test."

    try:
        # 1. Create temporary database
        db_session.execute(text(f"CREATE DATABASE IF NOT EXISTS {temp_db_name}"))
        db_session.commit()
        
        # 2. Restore the dump
        cmd = [
            actual_mysql_executable,
            f"-u{db_user}",
            f"-h{db_host}",
            temp_db_name
        ]
        if db_pass:
            cmd.insert(2, f"-p{db_pass}")

        is_win = os.name == 'nt'
        # On windows, mysql command sometimes needs shell=True to find the executable if it's just 'mysql'
        shell_required = is_win and "\\" not in mysql_path
        
        with open(file_path, "r", encoding="utf-8") as f:
            subprocess.run(cmd, stdin=f, check=True, timeout=600, shell=shell_required)

        # 3. Verify data exists (e.g., check properties table)
        res = db_session.execute(text(f"SELECT COUNT(*) FROM {temp_db_name}.properties")).first()
        count = res[0] if res else 0
        
        # 4. Cleanup
        db_session.execute(text(f"DROP DATABASE {temp_db_name}"))
        db_session.commit()
        
        if count > 0:
            return True, f"Restore Test Passed: {count} records verified."
        else:
            return False, "Restore Test Failed: Database is empty after restoration."

    except Exception as e:
        # Cleanup on failure if DB was created
        try:
            db_session.rollback()
            db_session.execute(text(f"DROP DATABASE IF EXISTS {temp_db_name}"))
            db_session.commit()
        except Exception as cleanup_err:
            # Cleanup failure is non-fatal — log it and return the original error
            from utils.logger import mto_logger
            mto_logger.warning(
                "verification_service: failed to drop temp DB '%s' during cleanup: %s",
                temp_db_name, cleanup_err,
            )
        return False, f"Restore Test Failed: {str(e)}"
