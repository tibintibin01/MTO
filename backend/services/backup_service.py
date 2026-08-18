import os
import shutil
import glob
import subprocess
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.database import SessionLocal, engine
from backend.models import BackupHistory
from backend.services.verification_service import verify_sql_dump
from backend.services.auth_service import require_permission

from utils.config import config as mto_config
from utils.secrets_manager import secrets
from utils.logger import mto_logger

# Resolve backup directory from config so .env values are honored. The config
# field reads MTO_BACKUP_DIR because MTOSettings uses the MTO_ env prefix.
BACKUP_BASE_DIR = mto_config.BACKUP_DIR
LOCAL_DIR = os.path.join(BACKUP_BASE_DIR, "local")
USB_SECRET_FILE = "revenue_system_backup_drive.txt"

# Stale lock threshold — a RUNNING record older than this is considered orphaned
# (e.g. worker crashed mid-backup) and will be overridden.
BACKUP_LOCK_STALE_MINUTES = 30


def _acquire_backup_lock(user_name: str, db_session: Session) -> tuple[bool, str]:
    """
    Acquires a DB-backed backup lock by inserting a RUNNING sentinel row.

    Using the database as the lock store means all workers sharing the same
    DB see the same lock state — a module-level flag is invisible across
    gunicorn/uvicorn workers.

    Returns (acquired: bool, message: str).
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=BACKUP_LOCK_STALE_MINUTES)

    # Check for an active (non-stale) RUNNING record
    active = db_session.query(BackupHistory).filter(
        BackupHistory.status == "RUNNING",
        BackupHistory.timestamp >= stale_cutoff,
    ).first()

    if active:
        # active.timestamp is a naive datetime from MariaDB — compare with naive now()
        elapsed = int((datetime.now() - active.timestamp).total_seconds() // 60)
        return False, f"Backup already in progress (started {elapsed}m ago by {active.user_name})."

    # Clean up any stale RUNNING records from crashed workers
    db_session.query(BackupHistory).filter(
        BackupHistory.status == "RUNNING",
        BackupHistory.timestamp < stale_cutoff,
    ).update({BackupHistory.status: "ABANDONED"}, synchronize_session=False)

    # Insert the lock sentinel
    lock_row = BackupHistory(
        filename="__lock__",
        file_path="",
        status="RUNNING",
        health="IN_PROGRESS",
        user_name=user_name,
        timestamp=datetime.now(timezone.utc),
    )
    db_session.add(lock_row)
    db_session.commit()
    return True, lock_row.id


def _release_backup_lock(lock_id: int, final_status: str, health: str,
                          filename: str, file_path: str, checksum: str,
                          db_session: Session):
    """Updates the lock sentinel row with the final backup result."""
    row = db_session.query(BackupHistory).filter(BackupHistory.id == lock_id).first()
    if row:
        row.status = final_status
        row.health = health
        row.filename = filename
        row.file_path = file_path
        row.checksum = checksum
        db_session.commit()


def _display_file_timestamp(path: str) -> str:
    """Formats a file modification time in Philippine Standard Time."""
    if not path or not os.path.exists(path):
        return "Not yet created"
    pst = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).astimezone(pst).strftime("%Y-%m-%d %H:%M:%S")


def _latest_sql_file(directory: str) -> str | None:
    files = glob.glob(os.path.join(directory, "*.sql")) if os.path.isdir(directory) else []
    return max(files, key=os.path.getmtime) if files else None


def get_backup_status(db_session: Session = None):
    """Returns live backup health, destination readiness, and latest recorded run."""
    if not db_session:
        with SessionLocal() as session:
            return get_backup_status(db_session=session)

    try:
        latest = (
            db_session.query(BackupHistory)
            .filter(BackupHistory.filename != "__lock__", BackupHistory.status != "RUNNING")
            .order_by(BackupHistory.id.desc())
            .first()
        )
        stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=BACKUP_LOCK_STALE_MINUTES)
        running = db_session.query(BackupHistory).filter(
            BackupHistory.status == "RUNNING", BackupHistory.timestamp >= stale_cutoff
        ).first()

        local_file = _latest_sql_file(LOCAL_DIR)
        if latest and latest.file_path and os.path.exists(latest.file_path):
            local_file = latest.file_path
        usb_path = _find_usb_drive()
        usb_file = _latest_sql_file(os.path.join(usb_path, "MTO_Backups")) if usb_path else None
        cloud_enabled = bool(mto_config.ENABLE_CLOUD_BACKUP)
        try:
            from backend.services.storage_service import storage_service
            cloud_configured = cloud_enabled and bool(storage_service.enabled)
        except Exception:
            cloud_configured = False

        result = {
            "is_running": running is not None,
            "has_backup_history": latest is not None,
            "last_local": _display_file_timestamp(local_file) if local_file else "Not yet created",
            "last_usb": _display_file_timestamp(usb_file) if usb_file else (f"Ready: {usb_path}" if usb_path else "USB drive not detected"),
            "last_cloud": "No upload recorded" if cloud_configured else ("Cloud storage not configured" if cloud_enabled else "Cloud backup disabled"),
            "last_verify": "Not yet tested",
            "last_checksum": "None",
            "last_checksum_short": "None",
            "health": "IN_PROGRESS" if running else "NOT_RUN",
            "last_status": "RUNNING" if running else "NOT_RUN",
            "last_file": local_file,
            "last_backup": f"Local file: {os.path.basename(local_file)}" if local_file else "No backup has been created yet",
            "storage_status": "Backup in progress" if running else "Waiting for first verified backup",
            "backup_dir": BACKUP_BASE_DIR,
            "local_dir": LOCAL_DIR,
            "local_ready": os.path.isdir(LOCAL_DIR) or os.path.isdir(BACKUP_BASE_DIR),
            "usb_detected": usb_path is not None,
            "usb_path": usb_path,
            "cloud_enabled": cloud_enabled,
            "cloud_configured": cloud_configured,
            "status_source": "backup_history" if latest else ("local_files" if local_file else "configuration"),
            "checked_at": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
        }

        if latest:
            pst = timezone(timedelta(hours=8))
            ts = latest.timestamp
            if ts:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                ts_str = ts.astimezone(pst).strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts_str = "Timestamp unavailable"

            raw_health = latest.health or "UNKNOWN"
            cloud_failure_messages = {
                "CLOUD_QUOTA_BLOCKED": "CLOUD QUOTA OR RETENTION BLOCKED",
                "CLOUD_CONFIG_ERROR": "CLOUD CONFIGURATION ERROR",
                "CLOUD_UPLOAD_FAILED": "CLOUD UPLOAD FAILED",
            }
            health_display = (
                "SUCCESS" if raw_health in ("OK", "Success", "SUCCESS") or "Success" in raw_health
                else "RESTORE SKIPPED" if raw_health == "RESTORE_SKIPPED"
                else cloud_failure_messages[raw_health] if raw_health in cloud_failure_messages
                else raw_health.replace("Issue: ", "").strip()
            )
            status = (latest.status or "UNKNOWN").upper()
            local_statuses = {"LOCAL_ONLY", "USB_ONLY", "CLOUD_ONLY", "SYNCED", "SUCCESS", "OK", "COMPLETED"}
            local_status = ts_str if status in local_statuses else f"FAILED: {ts_str}"
            usb_status = ts_str if status in {"USB_ONLY", "SYNCED"} else (f"Ready: {usb_path}" if usb_path else "USB drive not detected")
            cloud_status = ts_str if status in {"CLOUD_ONLY", "SYNCED"} else ("No upload in latest run" if cloud_configured else result["last_cloud"])
            if raw_health in cloud_failure_messages:
                cloud_status = cloud_failure_messages[raw_health]
            checksum = latest.checksum or "None"
            checksum_short = f"{checksum[:12]}...{checksum[-8:]}" if checksum != "None" and len(checksum) > 24 else checksum
            storage_status = {
                "SYNCED": "Protected on server, USB, and cloud",
                "CLOUD_ONLY": "Protected on server and cloud",
                "USB_ONLY": "Protected on server and USB",
                "LOCAL_ONLY": "Protected on server only",
                "SUCCESS": "Protected on server",
                "OK": "Protected on server",
                "COMPLETED": "Protected on server",
                "VERIFY_FAILED": "Backup created but verification failed",
                "FAILED": "Latest backup failed",
            }.get(status, status.replace("_", " ").title())
            if raw_health in cloud_failure_messages and status in {"LOCAL_ONLY", "USB_ONLY"}:
                storage_status = f"{storage_status}; cloud was not updated"
            if status in local_statuses and not local_file:
                local_status = "Backup file missing"
                storage_status = "Latest backup record exists, but the server file is missing"
                raw_health = "FILE_MISSING"
                health_display = "FILE MISSING"
            result.update({
                "last_local": local_status, "last_usb": usb_status, "last_cloud": cloud_status,
                "last_verify": health_display, "last_checksum": checksum,
                "last_checksum_short": checksum_short, "health": raw_health,
                "last_status": status, "last_file": latest.file_path or local_file,
                "last_backup": f"{latest.filename} @ {ts_str}", "storage_status": storage_status,
            })
        return result
    except Exception as e:
        mto_logger.error(f"Error fetching backup status: {e}")
        return {
            "is_running": False, "last_local": "Status unavailable", "last_usb": "Status unavailable",
            "last_cloud": "Status unavailable", "last_verify": "Status unavailable", "health": "ERROR",
            "last_status": "ERROR", "storage_status": "Could not load backup health",
            "checked_at": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"), "error": str(e),
        }

@require_permission("backup_restore")
async def run_hybrid_backup(user=None, db_session: Session = None):
    """
    Main orchestrator for the Hybrid Backup process.

    Concurrency control uses a DB-backed lock (a RUNNING sentinel row in
    backup_history) so all workers sharing the same database see the same
    lock state. A module-level flag would be invisible across gunicorn/uvicorn
    workers and would allow concurrent backups in multi-worker deployments.
    """
    if not db_session:
        with SessionLocal() as db:
            return await run_hybrid_backup(user=user, db_session=db)

    import asyncio
    from backend.services.auth_service import get_username
    from utils import log_error_to_file

    user_name = get_username(user)

    # Acquire DB-backed lock — visible to all workers
    acquired, lock_result = _acquire_backup_lock(user_name, db_session)
    if not acquired:
        return False, lock_result
    lock_id = lock_result

    async def report_progress(step, percentage, msg):
        try:
            from backend.deps import manager
            await manager.broadcast({
                "type": "PROGRESS",
                "module": "backup",
                "step": step,
                "percentage": percentage,
                "message": msg,
            })
        except Exception:
            pass

    mto_logger.info(f"Hybrid Backup started by {user_name}")
    checksum = "None"
    filename = "__lock__"
    local_path = ""
    final_status = "FAILED"
    health = "FAILED"

    try:
        # 1. Local Backup
        await report_progress(1, 10, "Creating local SQL dump...")
        os.makedirs(LOCAL_DIR, exist_ok=True)
        # Use Philippine Standard Time (UTC+8) for the backup filename
        PST = timezone(timedelta(hours=8))
        timestamp = datetime.now(PST).strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"revenue_backup_{timestamp}.sql"
        local_path = os.path.join(LOCAL_DIR, filename)

        success = await asyncio.to_thread(_create_local_dump, local_path)
        if not success:
            await report_progress(1, 0, "ERROR: Local dump failed")
            return False, "Local dump failed."

        # 1.5 Generate Checksum
        await report_progress(1, 20, "Generating checksum...")
        checksum = await asyncio.to_thread(_generate_checksum, local_path)
        await asyncio.to_thread(
            lambda: open(local_path + ".sha256", "w").write(checksum)
        )

        # 2. Verify Local Backup
        await report_progress(2, 40, "Verifying backup integrity...")
        v_success, v_msg = await asyncio.to_thread(
            verify_sql_dump,
            local_path,
            db_session,
            checksum,
        )
        health = "RESTORE_SKIPPED" if v_success and "skipped" in str(v_msg).lower() else ("OK" if v_success else f"Issue: {v_msg}")
        if not v_success:
            final_status = "VERIFY_FAILED"
            await report_progress(2, 0, f"ERROR: {v_msg}")
            return False, f"Backup verification failed: {v_msg}"

        # 3. Rotation (Local)
        await report_progress(3, 50, "Rotating old local backups...")
        await asyncio.to_thread(_rotate_backups, LOCAL_DIR, keep=7)

        # 4. USB Mirroring
        await report_progress(4, 70, "Syncing to USB Drive...")
        usb_success = False
        usb_path = await asyncio.to_thread(_find_usb_drive)
        if usb_path:
            def sync_usb():
                usb_dest = os.path.join(usb_path, "MTO_Backups")
                os.makedirs(usb_dest, exist_ok=True)
                shutil.copy2(local_path, os.path.join(usb_dest, filename))
                shutil.copy2(local_path + ".sha256", os.path.join(usb_dest, filename + ".sha256"))
                _rotate_backups(usb_dest, keep=14)
            await asyncio.to_thread(sync_usb)
            usb_success = True

        # 5. Cloud Sync
        await report_progress(5, 90, "Syncing to Cloud...")
        cloud_result = await asyncio.to_thread(_sync_to_cloud, local_path, checksum)
        cloud_success = bool(cloud_result)
        if not cloud_success and cloud_result.code != "DISABLED":
            health = cloud_result.code

        if cloud_success and usb_success:
            final_status = "SYNCED"
        elif cloud_success:
            final_status = "CLOUD_ONLY"
        elif usb_success:
            final_status = "USB_ONLY"
        else:
            final_status = "LOCAL_ONLY"
        await report_progress(6, 100, "Finalizing backup logs...")
        if not cloud_success and cloud_result.code != "DISABLED":
            return True, (
                "Local backup completed, but cloud protection was not updated: "
                f"{cloud_result.message}"
            )
        return True, "Hybrid backup completed successfully."

    except Exception as e:
        log_error_to_file("Hybrid Backup Orchestrator Error", e)
        await report_progress(0, 0, f"CRITICAL ERROR: {str(e)}")
        await asyncio.to_thread(_alert_failure, f"Hybrid Backup Error: {str(e)}", user_name)
        return False, str(e)

    finally:
        # Always release the lock — update the sentinel row with the final result
        try:
            _release_backup_lock(
                lock_id=lock_id,
                final_status=final_status,
                health=health,
                filename=filename,
                file_path=local_path,
                checksum=checksum,
                db_session=db_session,
            )
            mto_logger.info(f"Hybrid Backup finished: status={final_status}", user=user_name)
        except Exception as release_err:
            mto_logger.error(f"Failed to release backup lock: {release_err}")


def _create_local_dump(dest_path):
    """
    Shells out to mysqldump synchronously (called via asyncio.to_thread).

    On timeout or any failure the partial output file is deleted so a
    corrupted dump is never left on disk for the checksum/verify steps
    to silently pass against.
    """
    from utils import log_error_to_file

    dump_path = mto_config.MYSQLDUMP_PATH
    db_user = mto_config.DB_USER
    db_pass = secrets.db_password
    db_name = mto_config.DB_NAME
    db_host = mto_config.DB_HOST
    db_port = mto_config.DB_PORT

    COMMON_DUMP_PATHS = [
        dump_path,
        # Windows (XAMPP, standard MySQL installer, alternate drive)
        r"C:\xampp\mysql\bin\mysqldump.exe",
        r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
        r"C:\Program Files\MySQL\MySQL Server 5.7\bin\mysqldump.exe",
        r"D:\xampp\mysql\bin\mysqldump.exe",
        # Linux / Docker / macOS Homebrew
        "/usr/bin/mysqldump",
        "/usr/local/bin/mysqldump",
        "/opt/homebrew/bin/mysqldump",
        "/usr/local/mysql/bin/mysqldump",
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
        log_error_to_file(
            "Backup Dump Error",
            "Could not locate mysqldump executable in common paths or System PATH.",
        )
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
            # Pass the password via MYSQL_PWD environment variable instead of
            # the command line. Command-line passwords are visible in the process
            # list (ps aux / tasklist) and in Docker inspect output.
            env = dict(os.environ)
            if db_pass:
                env["MYSQL_PWD"] = db_pass

            subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.PIPE,
                check=True,
                timeout=300,
                env=env,
            )
        return True

    except subprocess.TimeoutExpired:
        log_error_to_file("Backup Dump Timeout", "mysqldump exceeded 5-minute limit.")
        # Remove the partial file — a truncated dump must not be treated as valid
        try:
            os.remove(dest_path)
        except OSError:
            pass
        return False

    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.decode("utf-8", errors="ignore") if e.stderr else "No stderr message output."
        log_error_to_file("Backup Dump Process Error", e, extra={"stderr": stderr_msg})
        try:
            os.remove(dest_path)
        except OSError:
            pass
        return False

    except Exception as e:
        log_error_to_file("Backup Dump Error", e)
        try:
            os.remove(dest_path)
        except OSError:
            pass
        return False


def _rotate_backups(directory, keep=7):
    files = sorted(glob.glob(os.path.join(directory, "*.sql")), key=os.path.getmtime)
    while len(files) > keep:
        to_delete = files.pop(0)
        try:
            os.remove(to_delete)
        except OSError:
            pass


def _find_usb_drive():
    """Scans connected local/removable drives without touching mapped network drives."""
    import string

    letters = string.ascii_uppercase[4:]
    if os.name == "nt":
        try:
            import ctypes

            drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
            get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
            # DRIVE_REMOTE (4) can block for a long time when a mapped share is offline.
            letters = [
                letter for letter in letters
                if drive_mask & (1 << (ord(letter) - ord("A")))
                and get_drive_type(f"{letter}:\\") != 4
            ]
        except Exception:
            pass

    for letter in letters:
        drive = f"{letter}:\\"
        if os.path.exists(os.path.join(drive, USB_SECRET_FILE)):
            return drive
        if os.path.exists(os.path.join(drive, "mto_backup_drive.txt")):
            return drive
    return None


def _sync_to_cloud(file_path, plaintext_checksum=None):
    """
    Encrypts and uploads the backup through the quota-bounded cloud workflow.
    Raw SQL is never passed to object storage.
    """
    try:
        from backend.services.cloud_backup_service import sync_encrypted_backup

        return sync_encrypted_backup(file_path, plaintext_checksum)
    except Exception as e:
        from backend.services.cloud_backup_service import CloudSyncResult

        mto_logger.error(f"Cloud backup workflow failed: {e}")
        return CloudSyncResult(False, "CLOUD_UPLOAD_FAILED", str(e))


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
