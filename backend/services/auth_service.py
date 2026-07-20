# -*- coding: utf-8 -*-
from backend.models import User, RefreshToken, AuditLog
from sqlalchemy.orm import Session
from utils import log_error_to_file, hash_password, verify_password, needs_rehash
from datetime import datetime, timedelta, timezone

import inspect
from functools import wraps
from fastapi import HTTPException


def require_permission(permission: str):
    """
    Decorator to enforce Role-Based Access Control (RBAC) at the service level.
    It expects a 'current_user' or 'user' object in the function arguments.
    """

    def _require_user(args, kwargs):
        user = kwargs.get("current_user") or kwargs.get("user")
        if not user and args:
            for arg in args:
                if isinstance(arg, dict) and ("role" in arg or "username" in arg):
                    user = arg
                    break

        if not user:
            raise HTTPException(
                status_code=401, detail="Authentication required for this operation"
            )

        if not has_permission(user, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Access Denied: Missing required permission '{permission}'",
            )

    def decorator(func):

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            _require_user(args, kwargs)
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            _require_user(args, kwargs)
            return func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator



ROLE_ALIASES = {

    "staff": "cashier",
}

ROLE_PERMISSIONS = {
    "admin": {
        "account_self_service",
        "property_view",
        "property_edit",
        "property_delete",
        "payment_post",
        "payment_delete",
        "receipt_view",
        "receipt_generate",
        "ledger_view",
        "report_view",
        "manage_users",
        "view_logs",
        "recycle_manage",
        "import_data",
        "backup_restore",
    },
    "cashier": {
        "account_self_service",
        "property_view",
        "payment_post",
        "receipt_view",
        "receipt_generate",
        "ledger_view",
        "report_view",
    },
    "encoder": {
        "account_self_service",
        "property_view",
        "property_edit",
        "payment_post",
        "receipt_view",
        "receipt_generate",
        "ledger_view",
        "report_view",
    },
    "viewer": {
        "account_self_service",
        "property_view",
        "receipt_view",
        "ledger_view",
        "report_view",
    },
}


def get_username(user):
    if isinstance(user, dict):
        return str(
            user.get("username") or user.get("full_name") or user.get("id") or "System"
        )
    return str(user or "System")


def normalize_role(role_value):
    role_text = str(role_value or "").strip().lower()
    role_text = ROLE_ALIASES.get(role_text, role_text)
    return role_text or "viewer"


def get_user_role(user):
    if isinstance(user, dict):
        return normalize_role(user.get("role"))
    return normalize_role(user)


def has_permission(user, permission):
    role = get_user_role(user)
    return permission in ROLE_PERMISSIONS.get(role, set())





def get_user_by_username(username, db_session: Session):
    u = db_session.query(User).filter(User.username == username, User.deleted_at == None).first()
    if not u:
        return None
    return {"id": u.id, "username": u.username, "role": u.role}


def verify_user_login(
    username,
    password,
    db_session: Session,
    client_ip=None,
    user_agent=None,
    device_name=None,
):
    from datetime import datetime, timedelta, timezone
    user = db_session.query(User).filter(User.username == username, User.deleted_at == None).first()
    if not user:
        return None

    # 1. Check if account is manually disabled
    if not user.is_active:
        raise ValueError("DISABLED:Account is disabled. Please contact the administrator.")

    # 2. Check for active security lockout.
    # lockout_until is written as a naive UTC datetime, so compare against a
    # naive UTC "now" here. Both sides stay on the same clock basis.
    # Using datetime.now() (local time) would be wrong on any server not in UTC,
    # including Docker containers which default to UTC while the OS may be UTC+8.
    _now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    if user.lockout_until and user.lockout_until > _now_utc_naive:
        diff = user.lockout_until - _now_utc_naive
        minutes = int(diff.total_seconds() // 60) + 1
        raise ValueError(f"LOCKED:{minutes}")

    match = verify_password(password, user.password)

    if not match:
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= 5:
            # Write naive UTC so the comparison in the lockout check above
            # stays on the same naive-UTC basis.
            user.lockout_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
            db_session.commit()
            raise ValueError("LOCKED:5")
        else:
            db_session.commit()
            remaining = 5 - user.failed_attempts
            raise ValueError(f"INVALID:{remaining}")

    # 3. Successful login - Reset security counters
    user.last_login = datetime.now(timezone.utc)
    user.failed_attempts = 0
    user.lockout_until = None
    
    # Auto-upgrade legacy PBKDF2 hash to bcrypt on successful login.
    # needs_rehash() returns True only for PBKDF2 hashes — bcrypt hashes
    # are already current and are left untouched.
    if user.password and needs_rehash(user.password):
        user.password = hash_password(password)
        
    db_session.commit()

    # 4. Generate tokens
    from backend.deps import create_access_token
    refresh_token, session_id = create_refresh_token(
        user.id,
        db_session,
        client_ip=client_ip,
        user_agent=user_agent,
        device_name=device_name,
        return_session_id=True,
    )
    access_token = create_access_token(
        data={
            "sub": user.username,
            "role": user.role,
            "id": user.id,
            "sid": session_id,
        },
        expires_delta=timedelta(minutes=60),  # 1-hour access token
    )

    return {
        "id": user.id, 
        "username": user.username, 
        "role": user.role,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

def create_refresh_token(
    user_id: int,
    db_session: Session,
    client_ip=None,
    user_agent=None,
    device_name=None,
    return_session_id=False,
):
    """Generates a long-lived refresh token and stores it in the DB."""
    import secrets
    from datetime import datetime, timedelta, timezone
    
    token = secrets.token_urlsafe(64)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires_at = now + timedelta(days=7)
    
    new_token = RefreshToken(
        user_id=user_id,
        token=token,
        expires_at=expires_at,
        client_ip=str(client_ip or "")[:45] or None,
        user_agent=str(user_agent or "")[:500] or None,
        device_name=str(device_name or "")[:128] or None,
        last_used_at=now,
    )
    db_session.add(new_token)
    db_session.commit()
    db_session.refresh(new_token)
    if return_session_id:
        return token, new_token.id
    return token

def revoke_refresh_token(refresh_token_str: str, db_session: Session):
    """
    Marks a single refresh token as revoked.
    Called on logout so a stolen token cannot generate new access tokens.
    """
    token_record = db_session.query(RefreshToken).filter(
        RefreshToken.token == refresh_token_str
    ).first()
    if token_record and not token_record.is_revoked:
        token_record.is_revoked = True
        token_record.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db_session.commit()


def refresh_access_token(refresh_token_str: str, db_session: Session):
    """Validates a refresh token and generates a new access token."""
    from backend.deps import create_access_token
    from datetime import datetime, timedelta, timezone
    
    token_record = db_session.query(RefreshToken).filter(
        RefreshToken.token == refresh_token_str,
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)
    ).first()
    
    if not token_record:
        raise ValueError("Invalid or expired refresh token.")
        
    user = db_session.query(User).filter(
        User.id == token_record.user_id,
        User.deleted_at == None,
        User.is_active == True,
    ).first()
    if not user:
        raise ValueError("User not found.")
        
    token_record.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.commit()

    access_token = create_access_token(
        data={
            "sub": user.username,
            "role": user.role,
            "id": user.id,
            "sid": token_record.id,
        },
        expires_delta=timedelta(minutes=60)
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


def get_active_sessions(user_id: int, current_user: dict, db_session: Session):
    """Return safe session metadata without exposing refresh-token secrets."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = (
        db_session.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id,
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > now,
        )
        .order_by(RefreshToken.created_at.desc())
        .all()
    )
    current_session_id = current_user.get("session_id")
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "device_name": row.device_name or "Unknown workstation",
            "client_ip": row.client_ip or "Unknown",
            "user_agent": row.user_agent or "",
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "is_current": row.id == current_session_id,
        }
        for row in rows
    ]


def revoke_managed_session(
    session_id: int, current_user: dict, db_session: Session
):
    row = db_session.query(RefreshToken).filter(RefreshToken.id == session_id).first()
    if not row:
        raise ValueError("Session not found.")
    if row.id == current_user.get("session_id"):
        raise ValueError("Use Log Out to close your current session.")
    if not row.is_revoked:
        row.is_revoked = True
        row.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db_session.commit()
        from backend.services.history_service import log_data_change
        log_data_change(
            user_id=current_user.get("id", 0),
            username=get_username(current_user),
            table_name="refresh_tokens",
            record_id=row.id,
            action="REVOKE_SESSION",
            before={"user_id": row.user_id, "is_revoked": False},
            after={"user_id": row.user_id, "is_revoked": True},
            db_session=db_session,
        )
    return row.user_id


def revoke_other_user_sessions(
    user_id: int, current_user: dict, db_session: Session
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    query = db_session.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > now,
    )
    if int(user_id) == int(current_user.get("id")) and current_user.get("session_id"):
        query = query.filter(RefreshToken.id != current_user["session_id"])
    rows = query.all()
    for row in rows:
        row.is_revoked = True
        row.revoked_at = now
    db_session.commit()
    if rows:
        from backend.services.history_service import log_data_change
        log_data_change(
            user_id=current_user.get("id", 0),
            username=get_username(current_user),
            table_name="refresh_tokens",
            record_id=user_id,
            action="REVOKE_OTHER_SESSIONS",
            before={"active_sessions": len(rows)},
            after={"active_sessions": 0},
            db_session=db_session,
        )
    return len(rows)



def create_user(username, full_name, password, role, admin_user, db_session: Session):
    """Securely creates a new system user with hashed password."""
    # 1. Validate password complexity first
    from backend.services.validation_service import validate_password_complexity
    validate_password_complexity(password)

    # 2. Check for duplicates
    if db_session.query(User).filter(User.username == username, User.deleted_at == None).first():
        raise Exception(f"Username '{username}' is already taken.")

    # 3. Hash password
    hashed = hash_password(password)

    try:
        # 4. Insert user — flush to get the auto-generated ID for the audit record
        new_user = User(
            username=username,
            full_name=full_name,
            password=hashed,
            role=normalize_role(role),
            is_active=True
        )
        db_session.add(new_user)
        db_session.flush()

        # 5. Audit log staged in the same transaction — user + audit commit atomically
        import json
        audit_log = AuditLog(
            username=get_username(admin_user),
            action=f"Created new user: {username} ({full_name})",
            table_name="users",
            record_id=new_user.id,
            new_values=json.dumps({"username": username, "role": role}),
            timestamp=datetime.now(timezone.utc)
        )
        db_session.add(audit_log)
        db_session.commit()
        return new_user.id

    except Exception:
        db_session.rollback()
        raise


# --- User Management (Admin) ---


def get_all_users(limit=50, cursor=None, db_session: Session = None):
    """Returns users using cursor-based pagination ordered by username."""
    safe_limit = min(max(1, int(limit)), 200)

    query = db_session.query(User).filter(User.deleted_at == None)
    if cursor:
        # cursor is the last seen User.id
        query = query.filter(User.id > int(cursor))

    rows = query.order_by(User.id.asc()).limit(safe_limit + 1).all()

    has_more = len(rows) > safe_limit
    items = rows[:safe_limit]
    next_cursor = items[-1].id if has_more and items else None

    return {
        "items": [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name,
                "role": u.role,
                "is_active": u.is_active,
                "last_login": u.last_login,
                "created_at": u.created_at,
            }
            for u in items
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items),
    }


def update_user_role(user_id, new_role, admin_user, db_session: Session):
    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    
    old_role = user.role
    user.role = new_role
    db_session.commit()
    
    from backend.services.history_service import log_data_change
    log_data_change(
        user_id=admin_user.get("id") if isinstance(admin_user, dict) else 0,
        username=get_username(admin_user),
        table_name="users",
        record_id=user_id,
        action="UPDATE_ROLE",
        before={"role": old_role},
        after={"role": new_role},
        db_session=db_session
    )
    return True


def update_user_status(user_id, is_active, admin_user, db_session: Session):
    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    
    old_status = user.is_active
    user.is_active = is_active
    db_session.commit()
    
    from backend.services.history_service import log_data_change
    log_data_change(
        user_id=admin_user.get("id") if isinstance(admin_user, dict) else 0,
        username=get_username(admin_user),
        table_name="users",
        record_id=user_id,
        action="UPDATE_STATUS",
        before={"is_active": old_status},
        after={"is_active": is_active},
        db_session=db_session
    )
    return True


def reset_user_password(user_id, new_password, admin_user, db_session: Session):
    # Validate complexity before any DB operation
    from backend.services.validation_service import validate_password_complexity
    validate_password_complexity(new_password)

    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return False

    user.password = hash_password(new_password)
    user.failed_attempts = 0
    user.lockout_until = None
    # Use naive UTC to match the token issued-at comparison in get_current_user.
    # datetime.now() would give local time (UTC+8 in Philippines), causing the
    # iat comparison to incorrectly reject fresh tokens after a password reset.
    user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Revoke all existing refresh tokens — the user must log in again
    # with the new password to get a fresh token pair.
    revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.query(RefreshToken).filter(
        RefreshToken.user_id == user_id
    ).update(
        {RefreshToken.is_revoked: True, RefreshToken.revoked_at: revoked_at},
        synchronize_session=False,
    )

    db_session.commit()

    from backend.services.history_service import log_data_change
    log_data_change(
        user_id=admin_user.get("id") if isinstance(admin_user, dict) else 0,
        username=get_username(admin_user),
        table_name="users",
        record_id=user_id,
        action="RESET_PASSWORD",
        before=None,
        after=None,
        db_session=db_session
    )
    return True


def delete_user(user_id, admin_user, db_session: Session):
    """Soft removes a user from the system by setting deleted_at."""
    user = db_session.query(User).filter(User.id == user_id, User.deleted_at == None).first()
    if not user:
        return False
        
    username = user.username
    old_data = {"deleted_at": None, "is_active": user.is_active}
    
    # Revoke all their refresh tokens immediately to end active sessions
    revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.query(RefreshToken).filter(RefreshToken.user_id == user_id).update(
        {RefreshToken.is_revoked: True, RefreshToken.revoked_at: revoked_at},
        synchronize_session=False,
    )
    
    user.deleted_at = datetime.now(timezone.utc)
    user.is_active = False # Deactivate deleted users
    db_session.commit()
    
    from backend.services.history_service import log_data_change
    log_data_change(
        user_id=admin_user.get("id") if isinstance(admin_user, dict) else 0,
        username=get_username(admin_user),
        table_name="users",
        record_id=user_id,
        action="SOFT_DELETE",
        before=old_data,
        after={"deleted_at": user.deleted_at.isoformat() if hasattr(user.deleted_at, "isoformat") else str(user.deleted_at), "is_active": False},
        db_session=db_session
    )
    return True
