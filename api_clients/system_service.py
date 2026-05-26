# -*- coding: utf-8 -*-
# Client-side System Service (Thin Client)
from api_clients.api_helper import api_request


def get_dashboard_summary():
    return api_request("GET", "/billing/summary")


def log_action(user, action):
    # API handles logging on the backend usually, but we can have an endpoint
    try:
        api_request("POST", "/system/logs", data={"action": action})
    except Exception:
        # Fire-and-forget — a logging failure must never crash the caller.
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


def restart_server():
    """Sends a graceful restart command to the backend server. Admin only."""
    return api_request("POST", "/system/restart")


def get_api_version():
    """
    Returns the server's API version info.
    Called on desktop app startup to detect server/client version mismatches.
    """
    try:
        return api_request("GET", "/api/v1/version")
    except Exception:
        # Server may be an older version without this endpoint — not fatal
        return None


def check_version_compatibility(client_version: str = "1.0") -> dict:
    """
    Checks if this client version is compatible with the running server.
    Returns {"compatible": True/False, "server_version": "x.y", "message": "..."}
    """
    info = get_api_version()
    if not info:
        return {"compatible": True, "server_version": "unknown", "message": ""}

    server_version = info.get("api_version", "1.0")
    min_client = info.get("min_client_version", "1.0")

    # Simple major.minor comparison
    def _ver(v):
        parts = str(v).split(".")
        return tuple(int(x) for x in parts[:2])

    compatible = _ver(client_version) >= _ver(min_client)
    message = (
        ""
        if compatible
        else (
            f"This client (v{client_version}) is outdated. "
            f"The server requires client v{min_client} or newer. "
            "Please update the desktop app."
        )
    )
    return {
        "compatible": compatible,
        "server_version": server_version,
        "min_client_version": min_client,
        "message": message,
    }


def sync_billing_years(dry_run: bool = False):
    """
    Syncs missing PropertyBilling records for all active properties.
    Set dry_run=True to preview without writing to the database.
    """
    return api_request(
        "POST",
        f"/system/sync-billing-years{'?dry_run=true' if dry_run else ''}",
    )


def get_job_status(job_id: str):
    """Polls the status of a background job."""
    try:
        return api_request("GET", f"/jobs/{job_id}")
    except Exception:
        return None


def get_tax_policies():
    """Returns all configured tax policies ordered by tax year descending."""
    result = api_request("GET", "/system/tax-policy")
    return result if isinstance(result, list) else []


def update_tax_policy(tax_year: int, basic_rate: float, sef_rate: float, penalty_rate: float):
    """Creates or updates the tax policy for a given tax year. Admin only."""
    return api_request(
        "PUT",
        f"/system/tax-policy/{tax_year}",
        data={
            "basic_rate": basic_rate,
            "sef_rate": sef_rate,
            "penalty_rate": penalty_rate,
        },
    )


def sync_billing_years(dry_run=False):
    """Syncs missing billing year records. dry_run=True for preview."""
    return api_request(
        "POST",
        f"/system/sync-billing-years?dry_run={'true' if dry_run else 'false'}"
    )


def get_job_status(job_id: str):
    """Polls a background job for its current status and result."""
    return api_request("GET", f"/jobs/{job_id}")


def audit_td_numbers():
    """
    Scans all active properties and returns those whose TD number
    does not match the format DD-DDDD-DDDDD (e.g. 06-0014-00239).
    """
    return api_request("GET", "/system/td-number-audit")


def fix_td_numbers(dry_run: bool = True):
    """
    Auto-fixes malformed TD numbers using three rules:
      1. Third segment has 6 digits → remove the first zero
         e.g. 06-0014-000239 → 06-0014-00239
      2. Second segment has 3 digits → add a leading zero
         e.g. 06-014-00239 → 06-0014-00239
      3. First two segments merged (no dash after position 2)
         e.g. 060014-00239 → 06-0014-00239
    dry_run=True returns a preview without saving.
    dry_run=False applies the fixes.
    """
    return api_request(
        "POST",
        f"/system/td-number-fix?dry_run={'true' if dry_run else 'false'}"
    )

def compute_payment(assessed_value: float, tax_year: int, date_paid: str,
                    payment_type: str = "annual", quarter: int = 0):
    """
    Smart payment computation.
    Returns discount and penalty amounts based on date_paid vs tax_year deadline.

    Discount rules (Basic + SEF only):
      - Paid before Jan 1 of tax_year  → 20% advance discount
      - Paid Jan 1 – Mar 31 of tax_year → 10% prompt payment discount
      - Paid Apr 1 onwards              → 0%

    Penalty rules (annual deadline = Jan 31 of tax_year):
      - Paid on/before Jan 31 or within discount period → no penalty
      - Paid after Jan 31 → 2%/month × months late

    Args:
        assessed_value: property assessed value
        tax_year:       the tax year being paid
        date_paid:      payment date as YYYY-MM-DD string
        payment_type:   "annual" (default) or "quarterly"
        quarter:        1-4, only used for quarterly

    Returns dict with: basic_tax, sef_tax, total_tax, discount_rate,
        discount_amount, discount_label, penalty_months, penalty_amount,
        penalty_label, net_amount_due, breakdown
    """
    return api_request("POST", "/system/compute-payment", data={
        "assessed_value": assessed_value,
        "tax_year":       tax_year,
        "date_paid":      date_paid,
        "payment_type":   payment_type,
        "quarter":        quarter,
    })
