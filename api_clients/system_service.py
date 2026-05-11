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
