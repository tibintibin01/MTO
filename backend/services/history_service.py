# -*- coding: utf-8 -*-
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.models import AuditLog, Property
from backend.database import SessionLocal


def _make_json_serializable(value: Any) -> Any:
    """Convert Decimal and other non-serializable types to JSON-compatible types."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _make_json_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_serializable(v) for v in value]
    return value


def _calculate_audit_hash(prev_hash: str, data: str) -> str:
    import hashlib

    combined = f"{prev_hash or ''}{data}".encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def log_data_change(
    user_id: int,
    table_name: str,
    record_id: int,
    action: str,
    before: Optional[Dict] = None,
    after: Optional[Dict] = None,
    db_session: Session = None,
    username: str = "unknown",
    ip_address: str = None,
):
    """
    Records a detailed audit trail including before/after state snapshots.
    Uses hash-chaining for security. The caller owns the transaction: this
    function flushes the audit record but never commits independently.
    """
    if db_session is None:
        raise ValueError("db_session is required for audit logging.")

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
        if not d:
            return d
        proc = _make_json_serializable(d)
        return {
            k: (v[:2000] + "... [TRUNC]" if isinstance(v, str) and len(v) > 2000 else v)
            for k, v in proc.items()
        }

    before_json = json.dumps(clean(diff_before)) if diff_before else None
    after_json = json.dumps(clean(diff_after)) if diff_after else None

    try:
        # Serialize concurrent writers where the database supports row locks.
        latest_log = (
            db_session.query(AuditLog)
            .order_by(AuditLog.id.desc())
            .with_for_update()
            .first()
        )
        prev_hash = (
            getattr(latest_log, "current_hash", None) if latest_log else "INITIAL_SEED"
        )

        event_time = datetime.now(timezone.utc)

        # Combine all data for current hash
        current_data = f"{user_id}{table_name}{record_id}{action}{before_json}{after_json}{event_time.isoformat()}"
        cur_hash = _calculate_audit_hash(prev_hash, current_data)

        log_data = dict(
            user_id=user_id,
            username=username,
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_values=before_json,
            new_values=after_json,
            ip_address=ip_address,
            timestamp=event_time,
        )
        if hasattr(AuditLog, "previous_hash"):
            log_data["previous_hash"] = prev_hash
        if hasattr(AuditLog, "current_hash"):
            log_data["current_hash"] = cur_hash

        log = AuditLog(**log_data)
        db_session.add(log)
        db_session.flush()
        return True
    except Exception as e:
        from utils.logger import mto_logger

        mto_logger.error(
            f"CRITICAL: Failed to write audit log — action={action}, "
            f"table={table_name}, record_id={record_id}, user={username}: {e}"
        )
        raise RuntimeError("Failed to write audit log.") from e


def undo_last_action(user_id: int, db_session: Session = None):
    """
    Reverses the last action performed by the user by restoring the 'before' state.
    """
    # 1. Find the last reversible action
    log = (
        db_session.query(AuditLog)
        .filter(AuditLog.user_id == user_id, AuditLog.action.in_(["UPDATE", "DELETE"]))
        .order_by(AuditLog.timestamp.desc())
        .first()
    )

    if not log:
        return False, "No reversible actions found."

    if not log.before_value:
        return (
            False,
            f"Action '{log.action}' on {log.table_name} cannot be undone (no state snapshot).",
        )

    before_data = json.loads(log.before_value)
    table = log.table_name
    rec_id = log.record_id
    action = log.action

    try:
        if action == "DELETE":
            if table == "properties":
                prop = db_session.query(Property).filter(Property.id == rec_id).first()
                if prop:
                    prop.deleted_at = None
                    prop.updated_at = datetime.now(timezone.utc)
            else:
                return False, f"Undo not supported for deletion on table {table}"

        elif action == "UPDATE":
            if table == "properties":
                prop = db_session.query(Property).filter(Property.id == rec_id).first()
                if prop:
                    for k, v in before_data.items():
                        db_col = k.lower().replace(" ", "_")
                        if hasattr(prop, db_col):
                            if k in ("assessed_value", "penalty", "discount"):
                                v = Decimal(str(v)) if v is not None else None
                            setattr(prop, db_col, v)
                    prop.updated_at = datetime.now(timezone.utc)
            else:
                return False, f"Undo update not yet supported for {table}"

        # Log the UNDO action itself
        undo_log = AuditLog(
            user_id=user_id,
            table_name=table,
            record_id=rec_id,
            action=f"UNDO_{action}",
            timestamp=datetime.now(timezone.utc),
        )
        db_session.add(undo_log)

        # Delete the original log so we don't undo the same thing twice in a row
        db_session.delete(log)
        db_session.commit()
        return True, f"Successfully reversed {action} on {table}."

    except Exception as e:
        db_session.rollback()
        return False, f"Undo failed: {str(e)}"
