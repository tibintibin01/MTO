# -*- coding: utf-8 -*-
# Client-side Auth Service (Thin Client)
from services.api_helper import api_request, set_token

ROLE_PERMISSIONS = {
    "admin": {
        "account_self_service", "property_view", "property_edit", "property_delete",
        "payment_post", "receipt_view", "receipt_generate", "ledger_view",
        "report_view", "manage_users", "view_logs", "recycle_manage",
        "import_data", "backup_restore",
    },
    "cashier": {
        "account_self_service", "property_view", "payment_post", "receipt_view",
        "receipt_generate", "ledger_view", "report_view",
    },
    "encoder": {
        "account_self_service", "property_view", "property_edit", "payment_post",
        "receipt_view", "receipt_generate", "ledger_view", "report_view",
    },
    "viewer": {
        "account_self_service", "property_view", "receipt_view", "ledger_view", "report_view",
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
        # FastAPI OAuth2 uses form data for /token
        import requests
        from services.api_helper import API_BASE_URL
        response = requests.post(f"{API_BASE_URL}/token", data=payload)
        if response.status_code == 200:
            token_data = response.json()
            set_token(token_data["access_token"])
            # Get user info
            user_info = api_request("GET", "/me")
            return user_info
        return None
    except Exception as e:
        print(f"Login failed: {e}")
        return None

def get_all_users():
    return api_request("GET", "/users")

def update_user(user_id, role=None, is_active=None):
    data = {}
    if role is not None: data["role"] = role
    if is_active is not None: data["is_active"] = is_active
    return api_request("PATCH", f"/users/{user_id}", data=data)

def reset_user_password(user_id, new_password):
    return api_request("POST", f"/users/{user_id}/reset-password", data={"new_password": new_password})

def create_user(full_name, username, password, role):
    data = {
        "full_name": full_name,
        "username": username,
        "password": password,
        "role": role
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
    if password is None: return ""
    password_text = str(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password_text.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${salt_b64}${digest_b64}"

def verify_password(password, stored_value):
    if not stored_value: return False
    stored_text = str(stored_value)
    if not stored_text.startswith(f"{PASSWORD_SCHEME}$"): return str(password) == stored_text
    try:
        scheme, iteration_text, salt_b64, digest_b64 = stored_text.split("$", 3)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected_digest = base64.b64decode(digest_b64.encode("ascii"))
        actual_digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, int(iteration_text))
        return secrets.compare_digest(actual_digest, expected_digest)
    except: return False
