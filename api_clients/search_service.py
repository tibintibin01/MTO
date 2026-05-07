# -*- coding: utf-8 -*-
# Client-side Search Service (Thin Client)
from api_clients.api_helper import api_request

def global_search(query):
    """Hits the global search API endpoint."""
    return api_request("GET", "/search/global", params={"q": query})

def get_quick_actions():
    """Hits the quick actions API endpoint."""
    # If the endpoint doesn't exist, we can return a hardcoded list for the UI
    # or better, fetch it from a system-config endpoint.
    try:
        return api_request("GET", "/search/quick-actions")
    except:
        # Fallback for the UI if server doesn't support this yet
        return [
            {"title": "➕ Register New Property", "subtitle": "Add a new land or building assessment", "type": "action", "command": "nav:new_property"},
            {"title": "📊 Generate Monthly Report", "subtitle": "View collection summary for this month", "type": "action", "command": "nav:reports"},
            {"title": "🛡️ Trigger Hybrid Backup", "subtitle": "Manual data protection snapshot", "type": "action", "command": "action:backup"},
            {"title": "👥 Manage User Access", "subtitle": "Add or edit system operators", "type": "action", "command": "nav:users"}
        ]
