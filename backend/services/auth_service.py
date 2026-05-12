# -*- coding: utf-8 -*-
import base64
import hashlib
import secrets
import binascii
import db_manager as db
from utils import log_error_to_file
from functools import wraps
from fastapi import HTTPException
import asyncio


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


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 200000

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


def hash_password(password):
    if password is None:
        raise ValueError("Password is required.")
    password_text = str(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password_text.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${salt_b64}${digest_b64}"


def is_password_hashed(password_value):
    return str(password_value).startswith(f"{PASSWORD_SCHEME}$")


def verify_password(password, stored_value):
    if stored_value is None:
        return False
    stored_text = str(stored_value)
    if not is_password_hashed(stored_text):
        return str(password) == stored_text
    try:
        scheme, iteration_text, salt_b64, digest_b64 = stored_text.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected_digest = base64.b64decode(digest_b64.encode("ascii"))
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(password).encode("utf-8"),
            salt,
            int(iteration_text),
        )
        return secrets.compare_digest(actual_digest, expected_digest)
    except (ValueError, binascii.Error, TypeError):
        return False
    except Exception as e:
        log_error_to_file("Unexpected error during password verification", e)
        return False


def acquire_user_lock(user_id, user_name, stale_minutes=30):
    return db._acquire_named_lock(
        "user_edit_locks", "user_id", user_id, user_name, stale_minutes
    )


def release_user_lock(user_id, user_name):
    db._release_named_lock("user_edit_locks", "user_id", user_id, user_name)


def release_all_user_locks(user_name):
    db._release_all_named_locks("user_edit_locks", user_name)


def get_user_by_username(username):
    rows = db.db_query(
        "SELECT id, username, role FROM users WHERE username=%s AND is_deleted=0 LIMIT 1",
        (username,),
        fetch=True,
        commit=False,
    )
    if not rows:
        return None
    r = rows[0]
    return {"id": r[0], "username": r[1], "role": r[2]}


def verify_user_login(username, password):
    rows = db.db_query(
        "SELECT id, username, password, role, is_active FROM users WHERE username=%s AND is_deleted=0 LIMIT 1",
        (username,),
        fetch=True,
        commit=False,
    )
    if not rows:
        return None

    user_id, stored_username, stored_password, role, is_active = rows[0]

    if not bool(is_active):
        raise ValueError("Account is disabled. Please contact the administrator.")

    match = verify_password(password, stored_password)

    if not match:
        return None

    # Update last login
    db.db_query("UPDATE users SET last_login=NOW() WHERE id=%s", (user_id,))

    if stored_password and not is_password_hashed(stored_password):
        upgraded_hash = hash_password(password)
        db.db_query(
            "UPDATE users SET password=%s WHERE id=%s", (upgraded_hash, user_id)
        )

    # Import locally to avoid circular dependencies
    import backend.services.property_service as prop_service

    try:
        prop_service.release_all_property_locks(stored_username)
    except Exception as e:
        log_error_to_file("Failed to clear orphaned locks on login", error=e)
        
    return {"id": user_id, "username": stored_username, "role": role}


def create_user(username, full_name, password, role, admin_user):
    """Securely creates a new system user with hashed password."""

    def operation(cur):
        # 1. Check for duplicates
        cur.execute(
            "SELECT id FROM users WHERE username=%s AND is_deleted=0", (username,)
        )
        if cur.fetchone():
            raise Exception(f"Username '{username}' is already taken.")

        # 2. Hash password
        hashed = hash_password(password)

        # 3. Insert
        cur.execute(
            """
            INSERT INTO users (username, full_name, password, role, is_active, is_deleted)
            VALUES (%s, %s, %s, %s, 1, 0)
            """,
            (username, full_name, hashed, normalize_role(role)),
        )
        user_id = cur.lastrowid

        # 4. Audit
        db.record_audit_log_with_cur(
            cur,
            admin_user,
            f"Created new user: {username} ({full_name})",
            table_name="users",
            record_id=user_id,
            new_values={"username": username, "role": role},
        )
        return user_id

    return db.execute_transaction(operation)


# --- User Management (Admin) ---


def get_all_users(limit=50, offset=0):
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))
    rows = db.db_query(
        f"SELECT id, username, full_name, role, is_active, last_login, created_at FROM users WHERE is_deleted=0 ORDER BY username ASC LIMIT {safe_limit} OFFSET {safe_offset}",
        fetch=True,
        commit=False,
    )
    return [
        {
            "id": r[0],
            "username": r[1],
            "full_name": r[2],
            "role": r[3],
            "is_active": bool(r[4]),
            "last_login": r[5],
            "created_at": r[6],
        }
        for r in rows
    ]


def update_user_role(user_id, new_role, admin_user):
    def operation(cur):
        # Audit old value
        cur.execute("SELECT role FROM users WHERE id=%s", (user_id,))
        old_role = cur.fetchone()[0]

        cur.execute("UPDATE users SET role=%s WHERE id=%s", (new_role, user_id))

        db.record_audit_log_with_cur(
            cur,
            admin_user,
            f"Changed role for user ID {user_id}",
            table_name="users",
            record_id=user_id,
            old_values={"role": old_role},
            new_values={"role": new_role},
        )
        return True

    return db.execute_transaction(operation)


def update_user_status(user_id, is_active, admin_user):
    def operation(cur):
        cur.execute("SELECT is_active FROM users WHERE id=%s", (user_id,))
        old_status = bool(cur.fetchone()[0])

        cur.execute(
            "UPDATE users SET is_active=%s WHERE id=%s", (int(is_active), user_id)
        )

        db.record_audit_log_with_cur(
            cur,
            admin_user,
            f"{'Enabled' if is_active else 'Disabled'} user ID {user_id}",
            table_name="users",
            record_id=user_id,
            old_values={"is_active": old_status},
            new_values={"is_active": is_active},
        )
        return True

    return db.execute_transaction(operation)


def reset_user_password(user_id, new_password, admin_user):
    def operation(cur):
        hashed = hash_password(new_password)
        cur.execute("UPDATE users SET password=%s WHERE id=%s", (hashed, user_id))

        db.record_audit_log(
            admin_user,
            f"Force password reset for user ID {user_id}",
            table_name="users",
            record_id=user_id,
        )
        return True

    return db.execute_transaction(operation)
