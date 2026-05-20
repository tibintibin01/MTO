# -*- coding: utf-8 -*-
# Client-side Auth Service (Thin Client)
from api_clients.api_helper import api_request, set_token

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
        return str(user.get("username") or "System")
    return str(user or "System")


def get_user_role(user):
    if isinstance(user, dict):
        return str(user.get("role") or "viewer").lower()
    return str(user or "viewer").lower()


def has_permission(user, permission):
    role = get_user_role(user)
    return permission in ROLE_PERMISSIONS.get(role, set())


def verify_user_login(username, password):
    try:
        payload = {"username": username, "password": password}
        user_info = api_request(
            "POST", "/api/auth/login", data=payload, queue_offline=False
        )
        if user_info and "access_token" in user_info:
            set_token(user_info["access_token"])
            return user_info
        else:
            raise Exception("Login response missing access token.")

    except Exception as e:
        raw = str(e)
        # Extract structured error code from the API response if present.
        # The server now returns {"code": "AUTH_ACCOUNT_LOCKED", "detail": "..."}
        # api_request raises Exception(error_msg) where error_msg may contain
        # the detail string. We also check for the code in the raw exception.
        code = None
        detail = raw

        # Try to parse the JSON body from the exception message
        try:
            import re, json
            # api_request wraps the response detail in "Error: <detail>"
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                body = json.loads(match.group())
                code = body.get("code")
                detail = body.get("detail", raw)
        except Exception:
            pass

        # Raise user-friendly exceptions the login UI can catch by type
        if code == "AUTH_ACCOUNT_LOCKED" or "locked" in detail.lower():
            raise AccountLockedError(detail)
        elif code == "AUTH_ACCOUNT_DISABLED" or "disabled" in detail.lower():
            raise AccountDisabledError(detail)
        elif code in ("AUTH_INVALID_CREDENTIALS", "AUTH_TOKEN_INVALID") or "invalid" in detail.lower():
            raise InvalidCredentialsError(detail)
        else:
            raise Exception(detail)


class InvalidCredentialsError(Exception):
    """Raised when username or password is wrong."""

class AccountLockedError(Exception):
    """Raised when the account is temporarily locked after failed attempts."""

class AccountDisabledError(Exception):
    """Raised when an admin has disabled the account."""



def logout():
    """Clears the global bearer token for client logout/session expiration."""
    set_token(None)


def get_all_users():
    result = api_request("GET", "/users")
    if isinstance(result, dict) and "items" in result:
        return result["items"]
    return result if isinstance(result, list) else []


def update_user(user_id, role=None, is_active=None):
    data = {}
    if role is not None:
        data["role"] = role
    if is_active is not None:
        data["is_active"] = is_active
    return api_request("PATCH", f"/users/{user_id}", data=data)


def reset_user_password(user_id, new_password):
    return api_request(
        "POST", f"/users/{user_id}/reset-password", data={"new_password": new_password}
    )


def create_user(full_name, username, password, role):
    data = {
        "full_name": full_name,
        "username": username,
        "password": password,
        "role": role,
    }
    return api_request("POST", "/users", data=data)


def delete_user(user_id):
    return api_request("DELETE", f"/users/{user_id}")


def get_audit_logs(user_id=None):
    params = {"user_id": user_id} if user_id else {}
    return api_request("GET", "/system/audit-logs", params=params)


def get_current_user():
    try:
        return api_request("GET", "/me")
    except:
        return None


# --- Legacy Compatibility for UI modules not yet migrated to pure API ---
import hashlib
import base64
import secrets

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 200000


def hash_password(password):
    if password is None:
        return ""
    password_text = str(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password_text.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${salt_b64}${digest_b64}"


def verify_password(password, stored_value):
    if not stored_value:
        return False
    stored_text = str(stored_value)
    if not stored_text.startswith(f"{PASSWORD_SCHEME}$"):
        return str(password) == stored_text
    try:
        scheme, iteration_text, salt_b64, digest_b64 = stored_text.split("$", 3)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected_digest = base64.b64decode(digest_b64.encode("ascii"))
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256", str(password).encode("utf-8"), salt, int(iteration_text)
        )
        return secrets.compare_digest(actual_digest, expected_digest)
    except:
        return False
