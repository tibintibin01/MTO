# -*- coding: utf-8 -*-
# MTO Treasury System - Automated Migration Manager
# This script handles version tracking and execution of SQL-based migrations.

import os
import sys
import re

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import db_manager as db
except ImportError as e:
    print(f"Error: Could not import db_manager.py: {e}")
    sys.exit(1)

MIGRATIONS_DIR = "migrations"

def init_migration_table():
    """Ensures the tracking table exists and has the correct columns."""
    # 1. Create table if totally missing
    db.db_query("""
        CREATE TABLE IF NOT EXISTS schema_versions (
            version_name VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)
    
    # 2. Check for column existence (Auto-Heal)
    try:
        # If this fails, we try to add the column
        db.db_query("SELECT version_name FROM schema_versions LIMIT 1")
    except:
        print("ℹ️  Repairing schema_versions table structure...")
        try:
            # Try to rename or add. For simplicity, we just ensure version_name exists.
            db.db_query("ALTER TABLE schema_versions ADD COLUMN version_name VARCHAR(255) FIRST")
            db.db_query("ALTER TABLE schema_versions ADD PRIMARY KEY (version_name)")
        except: pass

def get_applied_versions():
    """Returns a set of versions already in the database."""
    res = db.db_query("SELECT version_name FROM schema_versions", fetch=True)
    return {row[0] for row in res} if res else set()

def execute_sql_file(file_path):
    """Reads and executes SQL from a file, handling multiple statements."""
    with open(file_path, 'r', encoding='utf-8') as f:
        sql = f.read()
    
    # Simple split by semicolon (caution: doesn't handle semicolons inside strings/triggers)
    # For standard MTO migrations, this is usually sufficient.
    statements = [s.strip() for s in sql.split(';') if s.strip()]
    
    for statement in statements:
        db.db_query(statement)

def run_migrations():
    print("--- MTO Automated Migration Manager ---")
    
    # 1. Setup
    try:
        init_migration_table()
    except Exception as e:
        print(f"CRITICAL: Could not initialize version tracking: {e}")
        return

    # 2. Discover Migrations
    if not os.path.exists(MIGRATIONS_DIR):
        print(f"Error: Migrations directory '{MIGRATIONS_DIR}' not found.")
        return

    all_files = [f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql")]
    all_files.sort() # Numerical order: 001, 002, 003...

    applied = get_applied_versions()
    
    print(f"Found {len(all_files)} total migrations. {len(applied)} already applied.\n")

    new_migrations = [f for f in all_files if f not in applied]

    if not new_migrations:
        print("✅ System is up to date. No pending migrations.")
        return

    # 3. Apply New Migrations
    for filename in new_migrations:
        file_path = os.path.join(MIGRATIONS_DIR, filename)
        print(f"Applying [{filename}]...", end=" ", flush=True)
        
        try:
            execute_sql_file(file_path)
            # Record success
            db.db_query("INSERT INTO schema_versions (version_name) VALUES (%s)", (filename,))
            print("🚀 SUCCESS")
        except Exception as e:
            err_msg = str(e)
            # Catch "Duplicate column", "Table already exists", "Duplicate key", etc.
            if any(msg in err_msg for msg in ["1060", "1050", "1061", "1062", "already exists"]):
                print("ℹ️  ALREADY IN SYNC")
                try:
                    db.db_query("INSERT INTO schema_versions (version_name) VALUES (%s)", (filename,))
                except: pass
            else:
                print(f"❌ FAILED\n\nERROR in {filename}: {e}")
                print("\nStopping migration process to prevent data corruption.")
                break

    print("\n[FINISH] Migration cycle complete.")

if __name__ == "__main__":
    run_migrations()
