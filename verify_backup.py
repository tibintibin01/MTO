import os
import subprocess
import db_manager as db

def verify_sql_dump(sql_file_path):
    """
    Verifies a SQL dump by importing it into a temporary database.
    Returns (True, "Success") or (False, "Error Message").
    """
    if not os.path.exists(sql_file_path):
        return False, "SQL file not found."

    test_db_name = "mto_test_restore"
    mysql_path = db.DB_CONFIG.get('mysql_path', 'mysql')
    db_user = db.DB_CONFIG['user']
    db_pass = db.DB_CONFIG['password']
    db_host = db.DB_CONFIG['host']

    try:
        # 1. Create temporary database
        print(f"Creating test database: {test_db_name}")
        create_cmd = [mysql_path, f"-u{db_user}", f"-h{db_host}"]
        if db_pass: create_cmd.insert(2, f"-p{db_pass}")
        
        subprocess.run(create_cmd, input=f"CREATE DATABASE IF NOT EXISTS {test_db_name};", text=True, check=True, timeout=180)

        # 2. Import the SQL file
        print(f"Importing {sql_file_path} into {test_db_name}...")
        import_cmd = [mysql_path, f"-u{db_user}", f"-h{db_host}", test_db_name]
        if db_pass: import_cmd.insert(2, f"-p{db_pass}")
        
        with open(sql_file_path, "r", encoding="utf-8", errors="ignore") as f:
            subprocess.run(import_cmd, stdin=f, check=True, timeout=180)

        # 3. Verify data presence
        print("Verifying data integrity...")
        verify_cmd = [mysql_path, f"-u{db_user}", f"-h{db_host}", test_db_name, "-e", "SELECT COUNT(*) FROM properties;"]
        if db_pass: verify_cmd.insert(2, f"-p{db_pass}")
        
        result = subprocess.run(verify_cmd, capture_output=True, text=True, check=True, timeout=180)
        count_output = result.stdout.strip()
        print(f"Verification Query Result: {count_output}")

        # 4. Clean up
        print(f"Cleaning up {test_db_name}...")
        subprocess.run(create_cmd, input=f"DROP DATABASE {test_db_name};", text=True, check=True, timeout=180)

        return True, "Backup verified successfully."

    except subprocess.TimeoutExpired:
        return False, "Verification timed out after 3 minutes."
    except subprocess.CalledProcessError as e:
        return False, f"Verification failed: {e.stderr if hasattr(e, 'stderr') else str(e)}"
    except Exception as e:
        return False, f"Unexpected verification error: {str(e)}"

if __name__ == "__main__":
    # Test with the latest backup if any
    import glob
    backup_dir = os.path.join(os.path.dirname(__file__), "backups", "local")
    backups = sorted(glob.glob(os.path.join(backup_dir, "*.sql")), reverse=True)
    if backups:
        print(f"Testing latest backup: {backups[0]}")
        success, msg = verify_sql_dump(backups[0])
        print(f"Result: {success} - {msg}")
    else:
        print("No local backups found to verify.")
