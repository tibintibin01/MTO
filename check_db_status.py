import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import db_manager as db

try:
    cols = db.db_query("DESCRIBE users", fetch=True, commit=False)
    print("Table Structure for 'users':")
    for col in cols:
        print(col)
        
    versions = db.db_query("SELECT * FROM schema_versions", fetch=True, commit=False)
    print("\nApplied Migrations:")
    for v in versions:
        print(v)
except Exception as e:
    print(f"Error: {e}")
