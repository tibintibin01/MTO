# -*- coding: utf-8 -*-
# Client-side System Service (Thin Client)
from api_clients.api_helper import api_request


def get_dashboard_summary():
    return api_request("GET", "/billing/summary")


def log_action(user, action):
    # API handles logging on the backend usually, but we can have an endpoint
    try:
        api_request("POST", "/system/logs", data={"action": action})
    except:
        pass


def get_audit_stats():
    return api_request("GET", "/system/audit-stats")


def trigger_backup():
    return api_request("POST", "/system/backup/trigger")


def get_backup_verification_status():
    return api_request("GET", "/system/backup/status")


def get_audit_logs(username=None, search="", date_from=None, date_to=None, limit=100, cursor=None):
    params = {
        "limit": limit,
        "search": search
    }
    if cursor: params["cursor"] = cursor
    if username: params["username"] = username
    if date_from: params["date_from"] = date_from
    if date_to: params["date_to"] = date_to
    
    return api_request("GET", "/system/audit-logs", params=params)


def get_audit_users():
    return api_request("GET", "/system/audit-users")


def validate_import(file_path, mode="property"):
    import os
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        return api_request("POST", f"/system/import/validate?mode={mode}", files=files)


def commit_import(data, mode="property"):
    return api_request("POST", f"/system/import/commit?mode={mode}", data=data)


def restore_backup(file_path):
    return api_request("POST", "/system/restore", data={"file_path": file_path})


def get_system_stats():
    """Fetches real-time DB pool and cache diagnostics from the server."""
    return api_request("GET", "/system/stats")
