# -*- coding: utf-8 -*-
from api_clients.api_helper import api_request, api_download_file

def log_bank_deposit(date_deposited: str, bank_name: str, reference_number: str, amount: float):
    """Logs a new bank deposit slip to the backend."""
    payload = {
        "date_deposited": date_deposited,
        "bank_name": bank_name,
        "reference_number": reference_number,
        "amount": amount
    }
    return api_request("POST", "/reports/deposits", data=payload, queue_offline=False)

def list_bank_deposits(start_date: str, end_date: str):
    """Retrieves list of logged bank deposits within date range."""
    params = {"start_date": start_date, "end_date": end_date}
    return api_request("GET", "/reports/deposits", params=params)

def delete_bank_deposit(deposit_id: int):
    """Deletes a bank deposit record."""
    return api_request("DELETE", f"/reports/deposits/{deposit_id}", queue_offline=False)

def download_coa_rcd(start_date: str, end_date: str, liquidating_officer: str, treasurer: str):
    """Generates the COA RCD Excel sheet and returns local file path."""
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "liquidating_officer": liquidating_officer,
        "treasurer": treasurer
    }
    return api_download_file("GET", "/reports/rcd", params=params)
