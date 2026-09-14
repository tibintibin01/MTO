# -*- coding: utf-8 -*-
"""Central audit logging and compensating-action support."""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.models import AuditLog, Property
from backend.services.audit_integrity_service import (
    append_audit_event,
    canonical_snapshot,
)


def log_data_change(
    user_id: Optional[int],
    table_name: Optional[str],
    record_id: Optional[int],
    action: str,
    before: Optional[Dict] = None,
    after: Optional[Dict] = None,
    db_session: Session = None,
    username: str = "unknown",
    ip_address: str = None,
    compensates_audit_id: Optional[int] = None,
):
    """Append one sealed audit record inside the caller-owned transaction."""
    if db_session is None:
        raise ValueError("db_session is required for audit logging.")

    diff_before = before
    diff_after = after
    if action == "UPDATE" and before and after:
        changed_keys = {
            key for key in set(before) | set(after) if before.get(key) != after.get(key)
        }
        diff_before = {key: before.get(key) for key in changed_keys}
        diff_after = {key: after.get(key) for key in changed_keys}

    try:
        append_audit_event(
            db_session=db_session,
            user_id=user_id,
            username=username or "unknown",
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_values=canonical_snapshot(diff_before) if diff_before else None,
            new_values=canonical_snapshot(diff_after) if diff_after else None,
            ip_address=ip_address,
            compensates_audit_id=compensates_audit_id,
        )
        return True
    except Exception as exc:
        from utils.logger import mto_logger

        mto_logger.error(
            "CRITICAL: Failed to append sealed audit event",
            action=action,
            table_name=table_name,
            record_id=record_id,
            username=username,
            error_type=type(exc).__name__,
        )
        raise RuntimeError("Failed to write audit log.") from exc


_PROPERTY_UNDO_FIELDS = {
    "owner_name",
    "payor_name",
    "lot_number",
    "block_number",
    "area",
    "location",
    "barangay",
    "kind_of_property",
    "accountable_officer",
    "assessed_value",
    "penalty",
    "discount",
    "pin",
    "prev_td_number",
    "previous_property_id",
    "effectivity_date",
    "archived",
    "is_deleted",
    "deleted_at",
}
_DECIMAL_FIELDS = {"assessed_value", "penalty", "discount"}
_DATE_FIELDS = {"effectivity_date"}
_DATETIME_FIELDS = {"deleted_at"}


def _restore_value(field_name: str, value: Any) -> Any:
    if value is None:
        return None
    if field_name in _DECIMAL_FIELDS:
        return Decimal(str(value))
    if field_name in _DATE_FIELDS and isinstance(value, str):
        return date.fromisoformat(value[:10])
    if field_name in _DATETIME_FIELDS and isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    return value


def undo_last_action(user_id: int, db_session: Session = None):
    """Apply a compensating property event without altering audit history."""
    if db_session is None:
        raise ValueError("db_session is required for undo.")

    candidates = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == user_id,
            AuditLog.action.in_(["UPDATE", "DELETE", "SOFT_DELETE"]),
        )
        .order_by(AuditLog.id.desc())
        .limit(25)
        .all()
    )
    log = next(
        (
            candidate
            for candidate in candidates
            if not db_session.query(AuditLog.id)
            .filter(AuditLog.compensates_audit_id == candidate.id)
            .first()
        ),
        None,
    )
    if not log:
        return False, "No reversible actions found."
    if log.table_name != "properties" or not log.old_values:
        return False, "The latest action does not have a supported property snapshot."

    try:
        before_data = json.loads(log.old_values)
    except (TypeError, json.JSONDecodeError):
        return False, "The stored snapshot cannot be safely restored."
    if not isinstance(before_data, dict):
        return False, "The stored snapshot cannot be safely restored."

    prop = (
        db_session.query(Property)
        .filter(Property.id == log.record_id)
        .with_for_update()
        .one_or_none()
    )
    if prop is None:
        return False, "The property record no longer exists."

    restore_fields = {
        key: value
        for key, value in before_data.items()
        if key in _PROPERTY_UNDO_FIELDS and hasattr(prop, key)
    }
    if log.action in {"DELETE", "SOFT_DELETE"}:
        restore_fields = {"deleted_at": before_data.get("deleted_at")}
    if not restore_fields:
        return False, "The stored snapshot has no safely reversible fields."

    current_values = {key: getattr(prop, key) for key in restore_fields}
    restored_values = {}
    try:
        for key, value in restore_fields.items():
            restored = _restore_value(key, value)
            setattr(prop, key, restored)
            restored_values[key] = restored
        if hasattr(prop, "updated_at"):
            prop.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db_session.flush()
        log_data_change(
            user_id=user_id,
            username=log.username,
            table_name="properties",
            record_id=log.record_id,
            action=f"UNDO_{log.action}",
            before=current_values,
            after=restored_values,
            compensates_audit_id=log.id,
            db_session=db_session,
        )
        return True, f"Successfully reversed {log.action} on properties."
    except Exception as exc:
        db_session.rollback()
        from utils.logger import mto_logger

        mto_logger.error(
            "Compensating property action failed",
            audit_id=log.id,
            error_type=type(exc).__name__,
        )
        return False, "Undo failed. No change was committed."
