# -*- coding: utf-8 -*-
import db_manager as db
from datetime import datetime, timedelta
from typing import List, Dict, Any

def get_retention_summary():
    """Calculates how much data is eligible for archival based on a 10-year policy."""
    ten_years_ago = (datetime.now() - timedelta(days=3650)).strftime("%Y-%m-%d")
    
    query = """
        SELECT 
            (SELECT COUNT(*) FROM properties WHERE created_at < %s AND is_deleted = 0) as properties_to_archive,
            (SELECT COUNT(*) FROM payments WHERE date_paid < %s) as payments_to_archive
    """
    res = db.db_query(query, (ten_years_ago, ten_years_ago), fetch=True, commit=False)
    if res:
        return {
            "eligible_properties": res[0][0],
            "eligible_payments": res[0][1],
            "cutoff_date": ten_years_ago
        }
    return {}

def run_archival_policy(user="SYSTEM"):
    """
    Moves data older than 10 years to archive tables to maintain performance.
    """
    cutoff_date = (datetime.now() - timedelta(days=3650)).strftime("%Y-%m-%d")
    
    def archive_operation(cur):
        # 1. Ensure Archive Tables Exist
        cur.execute("CREATE TABLE IF NOT EXISTS properties_archive LIKE properties")
        cur.execute("CREATE TABLE IF NOT EXISTS payments_archive LIKE payments")
        
        # 2. Archive Old Properties
        cur.execute("""
            INSERT INTO properties_archive 
            SELECT * FROM properties WHERE created_at < %s
        """, (cutoff_date,))
        prop_count = cur.rowcount
        
        cur.execute("DELETE FROM properties WHERE created_at < %s", (cutoff_date,))
        
        # 3. Archive Old Payments
        cur.execute("""
            INSERT INTO payments_archive 
            SELECT * FROM payments WHERE date_paid < %s
        """, (cutoff_date,))
        pay_count = cur.rowcount
        
        cur.execute("DELETE FROM payments WHERE date_paid < %s", (cutoff_date,))
        
        # 4. Log the policy enforcement
        cur.execute(
            "INSERT INTO audit_logs (user_id, table_name, action, timestamp) VALUES (0, 'SYSTEM', %s, NOW())",
            (f"RETENTION_POLICY_ENFORCED: {prop_count} properties, {pay_count} payments archived.",)
        )
        
        return {
            "archived_properties": prop_count,
            "archived_payments": pay_count,
            "status": "success"
        }

    return db.execute_transaction(archive_operation)
