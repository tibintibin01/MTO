import os
import subprocess
import db_manager as db

def verify_sql_dump(file_path):
    """
    Performs a multi-point integrity check on a MySQL dump file.
    1. Shallow Check: File presence and completion marker.
    2. Deep Check: Automated Restore Test into a temp database.
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

    # 2. Deep Check: Automated Restore Test
    return perform_restore_test(file_path)


def perform_restore_test(file_path):
    """
    Verifies that the backup can actually be restored by performing
    a dry-run restore into a temporary validation database.
    """
    # Create a safe temp name (sanitize filename to be a valid DB name)
    base_name = os.path.basename(file_path).split('.')[0]
    safe_name = "".join([c if c.isalnum() else "_" for c in base_name])
    temp_db_name = f"mto_verify_{safe_name}"
    
    mysql_path = db.DB_CONFIG.get("mysql_path", "mysql")
    db_user = db.DB_CONFIG["user"]
    db_pass = db.DB_CONFIG["password"]
    db_host = db.DB_CONFIG["host"]

    try:
        # 1. Create temporary database
        db.db_query(f"CREATE DATABASE IF NOT EXISTS {temp_db_name}")
        
        # 2. Restore the dump
        cmd = [
            mysql_path,
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
        res = db.db_query(f"SELECT COUNT(*) FROM {temp_db_name}.properties", fetch=True)
        count = res[0][0] if res else 0
        
        # 4. Cleanup
        db.db_query(f"DROP DATABASE {temp_db_name}")
        
        if count > 0:
            return True, f"Restore Test Passed: {count} records verified."
        else:
            return False, "Restore Test Failed: Database is empty after restoration."

    except Exception as e:
        # Cleanup on failure if DB was created
        try:
            db.db_query(f"DROP DATABASE IF EXISTS {temp_db_name}")
        except:
            pass
        return False, f"Restore Test Failed: {str(e)}"
