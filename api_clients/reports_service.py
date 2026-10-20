# -*- coding: utf-8 -*-
from api_clients.api_helper import api_request, api_download_file


def log_bank_deposit(
    date_deposited: str, bank_name: str, reference_number: str, amount: float
):
    """Logs a new bank deposit slip to the backend."""
    payload = {
        "date_deposited": date_deposited,
        "bank_name": bank_name,
        "reference_number": reference_number,
        "amount": amount,
    }
    return api_request("POST", "/reports/deposits", data=payload, queue_offline=False)


def list_bank_deposits(start_date: str, end_date: str):
    """Retrieves list of logged bank deposits within date range."""
    params = {"start_date": start_date, "end_date": end_date}
    return api_request("GET", "/reports/deposits", params=params)


def delete_bank_deposit(deposit_id: int):
    """Deletes a bank deposit record."""
    return api_request("DELETE", f"/reports/deposits/{deposit_id}", queue_offline=False)


def download_coa_rcd(
    start_date: str,
    end_date: str,
    liquidating_officer: str,
    treasurer: str,
    *,
    report_number: str = "",
    accountable_officer: str = "",
    report_date: str | None = None,
):
    """Generates the COA RCD Excel sheet and returns local file path."""
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "liquidating_officer": liquidating_officer,
        "treasurer": treasurer,
        "report_number": report_number,
        "accountable_officer": accountable_officer,
    }
    if report_date is not None:
        params["report_date"] = report_date
    return api_download_file("GET", "/reports/rcd", params=params)


def get_rcd_register():
    return api_request("GET", "/reports/rcd/register")


def register_rcd_officer(name):
    return api_request(
        "POST", "/reports/rcd/officers", data={"name": name}, queue_offline=False
    )


def register_rcd_booklet(collector_id, first_or, last_or, issued_on):
    return api_request(
        "POST",
        "/reports/rcd/booklets",
        data={
            "collector_id": collector_id,
            "first_or": first_or,
            "last_or": last_or,
            "issued_on": issued_on,
        },
        queue_offline=False,
    )


def get_daily_rcd(collector_id, report_date):
    return api_request(
        "GET",
        "/reports/rcd/daily",
        params={"collector_id": collector_id, "report_date": report_date},
    )


def download_daily_rcd(
    collector_id, report_date, report_number, expected_signature, *, review=None
):
    if review is not None:
        return api_download_file(
            "POST",
            "/reports/rcd/daily/excel",
            json_body={
                "collector_id": collector_id,
                "report_date": report_date,
                "report_number": report_number,
                "expected_signature": expected_signature,
                "review": review,
            },
        )
    return api_download_file(
        "GET",
        "/reports/rcd/daily/excel",
        params={
            "collector_id": collector_id,
            "report_date": report_date,
            "report_number": report_number,
            "expected_signature": expected_signature,
        },
    )
