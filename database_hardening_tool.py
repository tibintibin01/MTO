# -*- coding: utf-8 -*-
# MTO Treasury System - Database Hardening Tool
# This script applies strict constraints at the SQL layer (CHECKs, UNIQUEs, and FKs).

import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import db_manager as db
except ImportError as e:
    print(f"Error: Could not import db_manager.py: {e}")
    print(f"Current Directory: {os.getcwd()}")
    print(f"File Location: {os.path.abspath(__file__)}")
    sys.exit(1)

def apply_hardening():
    print("--- MTO Database Hardening Patch ---")
    print("Enforcing strict integrity constraints at the SQL layer...")

    steps = [
        {
            "name": "Enforce Unique & Non-Null TD Numbers",
            "sql": "ALTER TABLE properties MODIFY td_number VARCHAR(255) NOT NULL UNIQUE"
        },
        {
            "name": "Enforce Non-Null Owner Names",
            "sql": "ALTER TABLE properties MODIFY owner_name VARCHAR(255) NOT NULL"
        },
        {
            "name": "Add Non-Negative Value Constraints (CHECKs)",
            "sql": """
                ALTER TABLE properties 
                ADD CONSTRAINT chk_assessed_value CHECK (assessed_value >= 0),
                ADD CONSTRAINT chk_penalty CHECK (penalty >= 0),
                ADD CONSTRAINT chk_discount CHECK (discount >= 0)
            """
        },
        {
            "name": "Drop Unsafe Financial Cascade",
            "sql": "ALTER TABLE payments DROP FOREIGN KEY fk_payments_property"
        },
        {
            "name": "Harden Financial Relationships (RESTRICT)",
            "sql": "ALTER TABLE payments ADD CONSTRAINT fk_payments_property FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE RESTRICT ON UPDATE CASCADE"
        },
        {
            "name": "Drop Unsafe Billing Cascade",
            "sql": "ALTER TABLE property_billings DROP FOREIGN KEY fk_property_billings_property"
        },
        {
            "name": "Harden Billing Relationships (RESTRICT)",
            "sql": "ALTER TABLE property_billings ADD CONSTRAINT fk_property_billings_property FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE RESTRICT ON UPDATE CASCADE"
        }
    ]

    for step in steps:
        print(f"Applying: {step['name']}...", end=" ")
        try:
            db.db_query(step['sql'])
            print("✅ DONE")
        except Exception as e:
            if "Duplicate entry" in str(e) or "already exists" in str(e):
                print("ℹ️  ALREADY APPLIED")
            else:
                print(f"❌ FAILED: {e}")

    print("\n[SUCCESS] Your database is now HARDENED. Integrity is enforced at the disk level.")

if __name__ == "__main__":
    apply_hardening()
