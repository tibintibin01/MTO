# -*- coding: utf-8 -*-
# Client-side Payment Service (Thin Client)
from api_clients.api_helper import api_request


def get_recent_payments(limit=8):
    return api_request("GET", "/payments/recent", params={"limit": limit})


def get_payment_receipt_records(term):
    return api_request("GET", "/payments/records", params={"term": term})


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
