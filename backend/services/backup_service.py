import os
import shutil
import glob
import subprocess
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.database import SessionLocal, engine
from backend.models import BackupHistory
from backend.services.verification_service import verify_sql_dump
from backend.services.auth_service import require_permission

from utils.config import config as mto_config
from utils.secrets_manager import secrets

BACKUP_BASE_DIR = r"C:\RevenueSystem\backups"
LOCAL_DIR = os.path.join(BACKUP_BASE_DIR, "local")
USB_SECRET_FILE = "revenue_system_backup_drive.txt"

def _ensure_backup_table():
    """Creates the backup_history table if it doesn't exist."""
    # Using engine to create tables if they don't exist is handled by Base.metadata.create_all(bind=engine)
    # but since this script might be run independently, we can keep a check or rely on migration_service.
    pass

# State tracking for dashboard
backup_status = {
    "last_local": "Never",
    "last_usb": "Never",
    "last_cloud": "Never",
    "last_verify": "Unknown",
    "last_checksum": "None",
    "is_running": False,
}


def get_backup_status(db_session: Session = None):
    """Fetches the latest backup status from the database and maps it to UI keys."""
    if not db_session:
        db_session = SessionLocal()

    try:
        latest = db_session.query(BackupHistory).order_by(BackupHistory.id.desc()).first()
        if latest:
            ts_str = latest.timestamp.strftime("%Y-%m-%d %H:%M:%S") if latest.timestamp else "Never"
            # Sanitize health status
            raw_health = latest.health or "UNKNOWN"
            if raw_health in ["OK", "Success", "SUCCESS"] or "Success" in raw_health or "SUCCESS" in raw_health:
                health_display = "SUCCESS"
            else:
                health_display = raw_health.replace("Issue: ", "").strip()

            backup_status.update({
                "last_local": ts_str,
                "last_usb": ts_str,
                "last_cloud": ts_str,
                "last_verify": health_display,
                "last_checksum": latest.checksum or "None",
                "health": raw_health
            })
    except Exception as e:
        print(f"Error fetching backup status: {e}")
    return backup_status


@require_permission("backup_restore")
async def run_hybrid_backup(user=None, db_session: Session = None):
    """Main orchestrator for the Hybrid Backup process (Async)."""
    import asyncio
    from backend.services.auth_service import get_username

    if not db_session:
        db_session = SessionLocal()

    user_name = get_username(user)
    if backup_status["is_running"]:
        return False, "Backup already in progress."

    from utils import log_error_to_file

    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Hybrid Backup Started by {user_name}"
    )

    backup_status["is_running"] = True
    
    async def report_progress(step, percentage, msg):
        try:
            from backend.main import manager
            await manager.broadcast({
                "type": "PROGRESS",
                "module": "backup",
                "step": step,
                "percentage": percentage,
                "message": msg
            })
        except: pass

    try:
        # 1. Local Backup
        await report_progress(1, 10, "Creating local SQL dump...")
        os.makedirs(LOCAL_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"revenue_backup_{timestamp}.sql"
        local_path = os.path.join(LOCAL_DIR, filename)

        success = await asyncio.to_thread(_create_local_dump, local_path)
        if not success:
            await report_progress(1, 0, "ERROR: Local dump failed")
            return False, "Local dump failed."

        backup_status["last_local"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1.5 Generate Checksum
        await report_progress(1, 20, "Generating checksum...")
        checksum = await asyncio.to_thread(_generate_checksum, local_path)
        
        def save_checksum():
            with open(local_path + ".sha256", "w") as f:
                f.write(checksum)
        await asyncio.to_thread(save_checksum)
        
        backup_status["last_checksum"] = checksum

        # 2. Verify Local Backup
        await report_progress(2, 40, "Verifying backup integrity...")
        v_success, v_msg = await asyncio.to_thread(verify_sql_dump, local_path)
        backup_status["last_verify"] = "Success" if v_success else f"Failed: {v_msg}"

        # 3. Rotation (Local)
        await report_progress(3, 50, "Rotating old local backups...")
        await asyncio.to_thread(_rotate_backups, LOCAL_DIR, keep=7)

        # 4. USB Mirroring
        await report_progress(4, 70, "Syncing to USB Drive...")
        usb_path = await asyncio.to_thread(_find_usb_drive)
        if usb_path:
            def sync_usb():
                usb_dest = os.path.join(usb_path, "RevenueSystem_Backups")
                os.makedirs(usb_dest, exist_ok=True)
                shutil.copy2(local_path, os.path.join(usb_dest, filename))
                shutil.copy2(local_path + ".sha256", os.path.join(usb_dest, filename + ".sha256"))
                _rotate_backups(usb_dest, keep=14)
            
            await asyncio.to_thread(sync_usb)
            backup_status["last_usb"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 5. Cloud Sync
        await report_progress(5, 90, "Syncing to Cloud...")
        cloud_success = False
        for _ in range(3):
            if await asyncio.to_thread(_sync_to_cloud, local_path):
                cloud_success = True
                break
        
        backup_status["last_cloud"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if cloud_success else "FAILED"
        
        # 6. Store in Database
        await report_progress(6, 100, "Finalizing backup logs...")
        try:
            health_detail = backup_status["last_verify"]
            cloud_status = "SYNCED" if cloud_success else "PENDING"
            
            history = BackupHistory(
                filename=filename,
                file_path=local_path,
                checksum=checksum,
                status=cloud_status,
                health="OK" if v_success else health_detail,
                user_name=user_name,
                timestamp=datetime.now()
            )
            db_session.add(history)
            db_session.commit()
            
        except Exception as db_err:
            print(f"Failed to log backup to DB: {db_err}")

        return True, "Hybrid backup completed successfully."
    except Exception as e:
        log_error_to_file("Hybrid Backup Orchestrator Error", e)
        await report_progress(0, 0, f"CRITICAL ERROR: {str(e)}")
        await asyncio.to_thread(_alert_failure, f"Hybrid Backup Orchestrator Error: {str(e)}", user_name)
        return False, str(e)
    finally:
        backup_status["is_running"] = False


def _create_local_dump(dest_path):
    from utils import log_error_to_file

    dump_path = mto_config.MYSQLDUMP_PATH
    db_user = mto_config.DB_USER
    db_pass = secrets.db_password
    db_name = mto_config.DB_NAME
    db_host = mto_config.DB_HOST
    db_port = mto_config.DB_PORT

    # Standard search paths for mysqldump on Windows/XAMPP
    COMMON_DUMP_PATHS = [
        dump_path,
        r"C:\xampp\mysql\bin\mysqldump.exe",
        r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
        r"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysqldump.exe",
        r"D:\xampp\mysql\bin\mysqldump.exe",
    ]

    actual_dump_executable = None
    for p in COMMON_DUMP_PATHS:
        if "\\" not in p and "/" not in p:
            if shutil.which(p):
                actual_dump_executable = p
                break
        elif os.path.exists(p):
            actual_dump_executable = p
            break
    
    if not actual_dump_executable:
        log_error_to_file("Backup Dump Error", "Could not locate mysqldump executable in common paths or System PATH.")
        return False

    try:
        with open(dest_path, "w", encoding="utf-8") as f:
            cmd = [
                actual_dump_executable,
                f"-u{db_user}",
                f"-h{db_host}",
                f"-P{db_port}",
                "--single-transaction",
                db_name,
            ]
            if db_pass:
                cmd.insert(2, f"-p{db_pass}")
            
            subprocess.run(cmd, stdout=f, check=True, timeout=300)
        return True
    except subprocess.TimeoutExpired:
        log_error_to_file(
            "Backup Dump Timeout", "mysqldump took longer than 5 minutes."
        )
        return False
    except Exception as e:
        log_error_to_file("Backup Dump Error", e)
        return False


def _rotate_backups(directory, keep=7):
    files = sorted(glob.glob(os.path.join(directory, "*.sql")), key=os.path.getmtime)
    while len(files) > keep:
        to_delete = files.pop(0)
        try:
            os.remove(to_delete)
        except:
            pass


def _find_usb_drive():
    """Scans all drive letters for the secret file."""
    import string

    for letter in string.ascii_uppercase[4:]:  # E through Z
        drive = f"{letter}:\\"
        if os.path.exists(os.path.join(drive, USB_SECRET_FILE)):
            return drive
        if os.path.exists(os.path.join(drive, "mto_backup_drive.txt")):
            return drive
    return None


def _sync_to_cloud(file_path):
    """Placeholder for cloud upload."""
    print(f"Simulating cloud upload for {file_path}...")
    import time
    time.sleep(2)  # Simulate network lag
    return True


def _generate_checksum(file_path):
    import hashlib
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def _alert_failure(message, user="System"):
    """Dispatches a critical alert event for monitoring tools."""
    from utils import log_critical_event
    print(f"!!! ALERT !!! {message} (Triggered by {user})")
    log_critical_event("BACKUP_FAILURE", message, user)
