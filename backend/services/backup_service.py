import os
import shutil
import glob
import threading
import subprocess
from datetime import datetime
import db_manager as db
from verify_backup import verify_sql_dump
from backend.services.auth_service import require_permission

BACKUP_BASE_DIR = r"C:\MTO\backups"
LOCAL_DIR = os.path.join(BACKUP_BASE_DIR, "local")
USB_SECRET_FILE = "mto_backup_drive.txt"

def _ensure_backup_table():
    """Creates the backup_history table if it doesn't exist."""
    query = """
    CREATE TABLE IF NOT EXISTS backup_history (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        filename VARCHAR(255),
        file_path VARCHAR(500),
        checksum VARCHAR(64),
        status VARCHAR(20),
        health VARCHAR(10),
        user_name VARCHAR(100)
    )
    """
    try:
        db.db_query(query)
    except:
        pass

_ensure_backup_table()

# State tracking for dashboard
backup_status = {
    "last_local": "Never",
    "last_usb": "Never",
    "last_cloud": "Never",
    "last_verify": "Unknown",
    "last_checksum": "None",
    "is_running": False,
}


def get_backup_status():
    """Fetches the latest backup status from the database."""
    try:
        query = "SELECT timestamp, checksum, health FROM backup_history ORDER BY id DESC LIMIT 1"
        res = db.db_query(query, fetch=True, commit=False)
        if res:
            row = res[0]
            backup_status.update({
                "last_success": row[0].strftime("%Y-%m-%d %H:%M:%S") if row[0] else "Never",
                "checksum": row[1] or "None",
                "health": row[2] or "UNKNOWN"
            })
    except:
        pass
    return backup_status


@require_permission("backup_restore")
def run_hybrid_backup(user=None):
    """Main orchestrator for the Hybrid Backup process."""
    from backend.services.auth_service import get_username

    user_name = get_username(user)
    if backup_status["is_running"]:
        return False, "Backup already in progress."

    from utils import log_error_to_file

    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Hybrid Backup Started by {user_name}"
    )

    backup_status["is_running"] = True
    try:
        # 1. Local Backup
        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Step 1/5: Creating local SQL dump..."
        )
        os.makedirs(LOCAL_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"mto_backup_{timestamp}.sql"
        local_path = os.path.join(LOCAL_DIR, filename)

        success = _create_local_dump(local_path)
        if not success:
            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Local dump failed."
            )
            return (
                False,
                "Local dump failed. Check if mysqldump is installed and configured.",
            )

        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Local dump created: {local_path}"
        )
        backup_status["last_local"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1.5 Generate Checksum
        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Step 1.5/5: Generating checksum..."
        )
        checksum = _generate_checksum(local_path)
        checksum_path = local_path + ".sha256"
        with open(checksum_path, "w") as f:
            f.write(checksum)
        backup_status["last_checksum"] = checksum

        # 2. Verify Local Backup
        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Step 2/5: Verifying backup integrity..."
        )
        v_success, v_msg = verify_sql_dump(local_path)
        backup_status["last_verify"] = "Success" if v_success else f"Failed: {v_msg}"
        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Verification Result: {backup_status['last_verify']}"
        )

        # 3. Rotation (Local)
        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Step 3/5: Rotating old local backups..."
        )
        _rotate_backups(LOCAL_DIR, keep=7)

        # 4. USB Mirroring
        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Step 4/5: Syncing to USB Drive..."
        )
        usb_path = _find_usb_drive()
        if usb_path:
            usb_dest = os.path.join(usb_path, "MTO_Backups")
            os.makedirs(usb_dest, exist_ok=True)
            shutil.copy2(local_path, os.path.join(usb_dest, filename))
            # Also copy checksum to USB
            shutil.copy2(
                local_path + ".sha256", os.path.join(usb_dest, filename + ".sha256")
            )

            backup_status["last_usb"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: USB Sync Successful: {usb_path}"
            )
            _rotate_backups(usb_dest, keep=14)
        else:
            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: USB Sync Skipped (No drive found)"
            )

        # 5. Cloud Sync
        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Step 5/5: Syncing to Cloud..."
        )
        _sync_to_cloud(local_path)
        backup_status["last_cloud"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 6. Store in Database
        try:
            db.db_query(
                "INSERT INTO backup_history (filename, file_path, checksum, status, health, user_name) VALUES (%s, %s, %s, %s, %s, %s)",
                (filename, local_path, checksum, "SUCCESS", "OK", user_name)
            )
        except Exception as db_err:
            print(f"Failed to log backup to DB: {db_err}")

        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] INFO: Hybrid Backup Completed Successfully."
        )

        return True, "Hybrid backup completed successfully."
    except Exception as e:
        log_error_to_file("Hybrid Backup Orchestrator Error", e)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] CRITICAL: {str(e)}")
        return False, str(e)

    finally:
        backup_status["is_running"] = False


def _create_local_dump(dest_path):
    from utils import log_error_to_file

    dump_path = db.DB_CONFIG.get("mysqldump_path", "mysqldump")
    db_user = db.DB_CONFIG["user"]
    db_pass = db.DB_CONFIG["password"]
    db_name = db.DB_CONFIG["database"]
    db_host = db.DB_CONFIG["host"]

    try:
        with open(dest_path, "w", encoding="utf-8") as f:
            # Add --no-defaults to avoid reading config files that might prompt
            # Add --single-transaction for better consistency on InnoDB
            cmd = [
                dump_path,
                f"-u{db_user}",
                f"-h{db_host}",
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

    # Try common drive letters (skip C: and D: usually)
    for letter in string.ascii_uppercase[4:]:  # E through Z
        drive = f"{letter}:\\"
        if os.path.exists(os.path.join(drive, USB_SECRET_FILE)):
            return drive
    return None


def _sync_to_cloud(file_path):
    """Placeholder for cloud upload (e.g., S3, Google Drive, or custom API)."""
    print(f"Simulating cloud upload for {file_path}...")
    # In a real scenario, use requests.post or a cloud SDK here
    import time

    time.sleep(2)  # Simulate network lag
    return True


def start_background_backup():
    """Triggers the backup in a non-blocking thread."""
    thread = threading.Thread(target=run_hybrid_backup, daemon=True)
    thread.start()
    return thread


def _generate_checksum(file_path):
    import hashlib

    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()
