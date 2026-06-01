# -*- coding: utf-8 -*-
from backend.models import User, RefreshToken, AuditLog
from sqlalchemy.orm import Session
from utils import log_error_to_file, hash_password, verify_password, needs_rehash
from datetime import datetime, timedelta, timezone

from functools import wraps
from fastapi import HTTPException


def require_permission(permission: str):
    """
    Decorator to enforce Role-Based Access Control (RBAC) at the service level.
    It expects a 'current_user' or 'user' object in the function arguments.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Locate user object in arguments
            user = kwargs.get("current_user") or kwargs.get("user")
            if not user and args:
                # Many services pass user as the first or last argument
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

            return func(*args, **kwargs)

        return wrapper

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


def verify_user_login(username, password, db_session: Session):
    from datetime import datetime, timedelta, timezone
    user = db_session.query(User).filter(User.username == username, User.deleted_at == None).first()
    if not user:
        return None

    # 1. Check if account is manually disabled
    if not user.is_active:
        raise ValueError("DISABLED:Account is disabled. Please contact the administrator.")

    # 2. Check for active security lockout.
    # lockout_until is written as a naive UTC datetime (datetime.utcnow() /
    # datetime.now(timezone.utc).replace(tzinfo=None)) so we compare against
    # datetime.utcnow() here — both sides are naive UTC, no offset error.
    # Using datetime.now() (local time) would be wrong on any server not in UTC,
    # including Docker containers which default to UTC while the OS may be UTC+8.
    _now_utc_naive = datetime.utcnow()
    if user.lockout_until and user.lockout_until > _now_utc_naive:
        diff = user.lockout_until - _now_utc_naive
        minutes = int(diff.total_seconds() // 60) + 1
        raise ValueError(f"LOCKED:{minutes}")

    match = verify_password(password, user.password)

    if not match:
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= 5:
            # Write naive UTC so the comparison in the lockout check above
            # (datetime.utcnow()) stays on the same naive-UTC basis.
            user.lockout_until = datetime.utcnow() + timedelta(minutes=5)
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
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "id": user.id},
        expires_delta=timedelta(minutes=60) # 1-hour access token
    )
    
    refresh_token = create_refresh_token(user.id, db_session)

    return {
        "id": user.id, 
        "username": user.username, 
        "role": user.role,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

def create_refresh_token(user_id: int, db_session: Session):
    """Generates a long-lived refresh token and stores it in the DB."""
    import secrets
    from datetime import datetime, timedelta, timezone
    
    token = secrets.token_urlsafe(64)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    
    new_token = RefreshToken(
        user_id=user_id,
        token=token,
        expires_at=expires_at
    )
    db_session.add(new_token)
    db_session.commit()
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
        db_session.commit()


def refresh_access_token(refresh_token_str: str, db_session: Session):
    """Validates a refresh token and generates a new access token."""
    from backend.deps import create_access_token
    from datetime import datetime, timedelta, timezone
    
    token_record = db_session.query(RefreshToken).filter(
        RefreshToken.token == refresh_token_str,
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.now(timezone.utc)
    ).first()
    
    if not token_record:
        raise ValueError("Invalid or expired refresh token.")
        
    user = db_session.query(User).filter(User.id == token_record.user_id).first()
    if not user:
        raise ValueError("User not found.")
        
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "id": user.id},
        expires_delta=timedelta(minutes=60)
    )
    
    return {"access_token": access_token, "token_type": "bearer"}



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
    # Use UTC naive to match datetime.utcfromtimestamp(iat) in get_current_user.
    # datetime.now() would give local time (UTC+8 in Philippines), causing the
    # iat comparison to incorrectly reject fresh tokens after a password reset.
    user.password_changed_at = datetime.utcnow()

    # Revoke all existing refresh tokens — the user must log in again
    # with the new password to get a fresh token pair.
    db_session.query(RefreshToken).filter(
        RefreshToken.user_id == user_id
    ).update({RefreshToken.is_revoked: True}, synchronize_session=False)

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
    db_session.query(RefreshToken).filter(RefreshToken.user_id == user_id).update({RefreshToken.is_revoked: True}, synchronize_session=False)
    
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
