# -*- coding: utf-8 -*-
import json
import db_manager as db
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional


def _make_json_serializable(value: Any) -> Any:
    """Convert Decimal and other non-serializable types to JSON-compatible types."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _make_json_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_serializable(v) for v in value]
    return value


def log_data_change(user_id: int, table_name: str, record_id: int, action: str, before: Optional[Dict] = None, after: Optional[Dict] = None):
    """
    Records a detailed audit trail including before/after state snapshots.
    Used for both accountability and Undo functionality.
    """
    query = """
        INSERT INTO audit_logs (user_id, table_name, record_id, action, before_value, after_value, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """

    # Calculate Delta
    diff_before = {}
    diff_after = {}
    if action == "UPDATE" and before and after:
        for k in set(before.keys()) | set(after.keys()):
            if before.get(k) != after.get(k):
                diff_before[k] = before.get(k)
                diff_after[k] = after.get(k)
    else:
        diff_before, diff_after = before, after

    def clean(d):
        if not d: return d
        proc = _make_json_serializable(d)
        return {k: (v[:2000] + "... [TRUNC]" if isinstance(v, str) and len(v) > 2000 else v) for k, v in proc.items()}

    before_json = json.dumps(clean(diff_before)) if diff_before else None
    after_json = json.dumps(clean(diff_after)) if diff_after else None
    
    try:
        db.db_query(query, (user_id, table_name, record_id, action, before_json, after_json))
        return True
    except Exception as e:
        print(f"FAILED TO LOG AUDIT DATA: {e}")
        return False

def undo_last_action(user_id: int):
    """
    Reverses the last action performed by the user by restoring the 'before' state.
    """
    # 1. Find the last reversible action
    query = """
        SELECT id, table_name, record_id, action, before_value 
        FROM audit_logs 
        WHERE user_id = %s AND action IN ('UPDATE', 'DELETE')
        ORDER BY timestamp DESC LIMIT 1
    """
    res = db.db_query(query, (user_id,), fetch=True, commit=False)
    if not res:
        return False, "No reversible actions found."
    
    log_id, table, rec_id, action, before_json = res[0]
    
    if not before_json:
        return False, f"Action '{action}' on {table} cannot be undone (no state snapshot)."

    before_data = json.loads(before_json)
    
    def perform_undo(cur):
        if action == 'DELETE':
            # Restore the record (assuming soft-delete was used, we just unset is_deleted)
            if table == 'properties':
                cur.execute("UPDATE properties SET is_deleted = 0, updated_at = NOW() WHERE id = %s", (rec_id,))
            else:
                return False, f"Undo not supported for deletion on table {table}"
        
        elif action == 'UPDATE':
            # This is more complex, we'd need to map the keys back to SQL columns
            # For simplicity in this hardening phase, we'll focus on Property restores
            if table == 'properties':
                # Dynamically build update query from the 'before' snapshot
                cols = []
                params = []
                for k, v in before_data.items():
                    # Map common UI fields to DB columns if necessary
                    db_col = k.lower().replace(" ", "_")
                    # Convert float back to Decimal for precision-sensitive fields
                    if k in ('assessed_value', 'penalty', 'discount'):
                        v = Decimal(str(v)) if v is not None else None
                    cols.append(f"{db_col} = %s")
                    params.append(v)
                
                params.append(rec_id)
                q = f"UPDATE properties SET {', '.join(cols)}, updated_at = NOW() WHERE id = %s"
                cur.execute(q, tuple(params))
            else:
                return False, f"Undo update not yet supported for {table}"
        
        # Log the UNDO action itself
        cur.execute(
            "INSERT INTO audit_logs (user_id, table_name, record_id, action, timestamp) VALUES (%s, %s, %s, %s, NOW())",
            (user_id, table, rec_id, f"UNDO_{action}")
        )
        # Delete the original log so we don't undo the same thing twice in a row
        cur.execute("DELETE FROM audit_logs WHERE id = %s", (log_id,))
        return True, f"Successfully reversed {action} on {table}."

    return db.execute_transaction(perform_undo)
