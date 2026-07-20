# -*- coding: utf-8 -*-
# Client-side Payment Service (Thin Client)
from api_clients.api_helper import api_request


def get_recent_payments(limit=8):
    return api_request("GET", "/payments/recent", params={"limit": limit})


def get_payment_receipt_records(term):
    result = api_request("GET", "/payments/records", params={"term": term})
    if isinstance(result, dict) and "items" in result:
        return result["items"]
    return result if isinstance(result, list) else []


def get_payment_receipt_details(payment_id):
    # This might need an endpoint
    return api_request("GET", f"/payments/{payment_id}/details")


# Placeholder for others
def find_duplicate_payment(property_id, or_number, tax_year_text):
    return None


def get_payment_ledger(term):
    return api_request("GET", "/payments/ledger", params={"term": term})


def get_unified_payment_history(term):
    return api_request("GET", "/payments/ledger", params={"term": term})


def get_next_or_number():
    return api_request("GET", "/payments/next-or")


def get_monthly_collection_trend(months=6):
    return api_request("GET", "/analytics/trends", params={"months": months})


def get_barangay_breakdown():
    return api_request("GET", "/analytics/barangay-breakdown")


def get_analytics_kpis():
    return api_request("GET", "/analytics/kpis")


def get_operational_analytics(year=None, barangay=None):
    params = {}
    if year not in (None, ""):
        params["year"] = int(year)
    if barangay and str(barangay).upper() != "ALL":
        params["barangay"] = str(barangay)
    return api_request("GET", "/analytics/operational", params=params)


def save_receipt_record(property_id, payment_id, details, file_path, user_name):
    data = {
        "property_id": property_id,
        "payment_id": payment_id,
        "details": details,
        "file_path": file_path,
        "user_name": str(user_name),
    }
    return api_request("POST", "/payments/receipt-record", data=data)


def update_receipt_history(history_id, file_path, user_name):
    data = {"file_path": file_path, "user_name": str(user_name)}
    return api_request(
        "POST", f"/payments/receipt-history/{history_id}/update", data=data
    )

def update_payment(payment_id, data):
    return api_request("PUT", f"/payments/{payment_id}", data=data)


def delete_payment(payment_id):
    return api_request("DELETE", f"/payments/{payment_id}")


def generate_receipt_pdf(payment_id) -> str:
    """
    Calls the backend to generate a receipt PDF and saves it to a temp file.
    Returns the local path to the downloaded PDF.
    """
    from api_clients.api_helper import api_download_file
    return api_download_file("POST", f"/payments/{payment_id}/receipt-pdf")


def batch_delete_preview(or_numbers: list):
    """Preview which payments match the given OR numbers before deleting."""
    return api_request("POST", "/payments/batch-delete/preview",
                       data={"or_numbers": or_numbers})


def batch_delete_preview_by_ids(payment_ids: list):
    """Preview payments by exact Payment IDs — safer for targeting specific duplicates."""
    return api_request("POST", "/payments/batch-delete/preview-by-ids",
                       data={"payment_ids": payment_ids})

def get_cleanup_candidates(year=2026, limit=500):
    """Load suspicious payment rows for review before cleanup/re-import."""
    return api_request("GET", "/payments/cleanup-candidates",
                       params={"year": year, "limit": limit})


def batch_delete_commit(payment_ids: list):
    """Delete the confirmed payment IDs and reverse their billing balances."""
    return api_request("POST", "/payments/batch-delete/commit",
                       data={"payment_ids": payment_ids})
