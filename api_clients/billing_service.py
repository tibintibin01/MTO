# -*- coding: utf-8 -*-
# Client-side Billing Service (Thin Client)
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from api_clients.api_helper import api_request, api_download_file

# --- Utility Logic (Local) ---


def normalize_tax_years(value):
    raw = str(value or "").replace(";", ",")
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    normalized = []
    for part in parts:
        if "-" in part:
            range_parts = [p.strip() for p in part.split("-") if p.strip()]
            if len(range_parts) == 2:
                start, end = range_parts
                if start.isdigit() and end.isdigit() and len(start) == 4 and len(end) == 4:
                    start_year = int(start)
                    end_year = int(end)
                    if end_year >= start_year and (end_year - start_year) <= 15:
                        for year in range(start_year, end_year + 1):
                            normalized.append(str(year))
                        continue
        normalized.append(part)

    deduped = []
    seen = set()
    for item in normalized:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def format_tax_years(value):
    years = normalize_tax_years(value)
    return ", ".join(years)


def normalize_date_input(value):
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def validate_tax_year_text(value):
    text = str(value or "").strip()
    if not text:
        return {"ok": False, "message": "Please enter at least one Tax Year."}
    parts = [item.strip() for item in text.replace(";", ",").split(",") if item.strip()]
    current_year = datetime.now().year + 5
    for part in parts:
        if "-" in part:
            if not re.fullmatch(r"\d{4}-\d{4}", part):
                return {"ok": False, "message": f"Invalid range: {part}"}
            s, e = [int(x) for x in part.split("-", 1)]
            if e < s:
                return {"ok": False, "message": f"Invalid range: {part}"}
            continue
        if not re.fullmatch(r"\d{4}", part):
            return {"ok": False, "message": f"Invalid year: {part}"}
    return {
        "ok": True,
        "years": normalize_tax_years(text),
        "text": format_tax_years(text),
    }


# --- API Requests ---


def get_property_statement_data(property_id):
    return api_request("GET", f"/properties/{property_id}/statement")


def get_assessment_roll():
    return api_request("GET", "/billing/assessment-roll")


def get_report_details(month="All", year="All", limit=100, cursor=None):
    params = {"month": month, "year": year, "limit": limit}
    if cursor is not None:
        params["cursor"] = cursor
    result = api_request(
        "GET", "/billing/report-details", params=params
    )
    # Return the full paginated dict so the UI can read next_cursor / has_more.
    # Fallback to a wrapped list for any legacy response shape.
    if isinstance(result, dict) and "items" in result:
        return result
    return {"items": result if isinstance(result, list) else [], "has_more": False, "next_cursor": None}


def get_rpt_receivables_summary(year):
    return api_request("GET", "/billing/receivables-summary", params={"year": year})


def get_delinquent_accounts(limit=100, offset=0):
    """Returns the items list from the cursor-paginated delinquent accounts endpoint."""
    result = api_request(
        "GET", "/billing/delinquents", params={"limit": limit}
    )
    # Backend returns {"items": [...], "next_cursor": ..., "has_more": ..., "count": ...}
    # The UI expects a flat list of tuples: (id, td, owner, loc, total_due, total_paid, balance)
    if isinstance(result, dict) and "items" in result:
        items = result["items"]
        return [
            (
                item.get("id"),
                item.get("td_number"),
                item.get("owner_name"),
                item.get("location"),
                item.get("total_due", 0),
                item.get("total_paid", 0),
                item.get("balance", 0),
            )
            for item in items
        ]
    # Fallback if already a list (shouldn't happen but safe)
    return result if isinstance(result, list) else []


def download_computation_pdf(property_id):
    """Triggers the download of a computation PDF and returns the local path."""
    return api_download_file("GET", f"/properties/{property_id}/computation-pdf")


def download_statement_pdf(property_id):
    """Triggers the download of a statement PDF and returns the local path."""
    return api_download_file("GET", f"/properties/{property_id}/statement-pdf")


def download_notice_pdf(property_id):
    """Triggers the download of a delinquency notice PDF and returns the local path."""
    return api_download_file("GET", f"/properties/{property_id}/notice-pdf")


def download_receivables_by_barangay_pdf(year=None, barangay=None):
    """Downloads the Receivables-by-Barangay PDF report and returns the local file path."""
    params = {}
    if year:
        params["year"] = year
    if barangay and barangay != "ALL":
        params["barangay"] = barangay
    return api_download_file(
        "GET", "/reports/receivables-by-barangay-pdf",
        params=params if params else None,
    )


def download_assessment_roll_pdf(barangay=None, year_start=None, year_end=None):
    """Downloads the Assessment Roll PDF report and returns the local file path."""
    params = {}
    if barangay and barangay != "ALL":
        params["barangay"] = barangay
    if year_start:
        params["year_start"] = year_start
    if year_end:
        params["year_end"] = year_end
    return api_download_file(
        "GET", "/reports/assessment-roll-pdf",
        params=params if params else None,
    )


def export_report_excel(report_type, month="All", year="All", barangay=None, year_start=None, year_end=None):
    """Downloads an Excel (.xlsx) export and returns the local file path.

    The backend ExportReportRequest expects a JSON body, so we use the
    api_request helper (raw_response=True) and then stream-save like
    api_download_file does internally.
    """
    import tempfile, os
    from api_clients.api_helper import (
        BASE_URL, _SESSION_TOKEN, is_token_expired, _try_refresh,
        CERT_PATH
    )
    import requests as _req, urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if _SESSION_TOKEN and is_token_expired(_SESSION_TOKEN):
        if not _try_refresh():
            raise Exception("Session expired. Please log in again.")

    headers = {"X-Requested-With": "XMLHttpRequest"}
    if _SESSION_TOKEN:
        headers["Authorization"] = f"Bearer {_SESSION_TOKEN}"

    body = {"report_type": report_type, "month": month, "year": year}
    if barangay and barangay != "ALL":
        body["barangay"] = barangay
    if year_start:
        body["year_start"] = year_start
    if year_end:
        body["year_end"] = year_end
    verify_param = str(CERT_PATH) if CERT_PATH.exists() else False
    resp = _req.post(
        f"{BASE_URL}/billing/export/excel",
        json=body, headers=headers, timeout=180, verify=verify_param, stream=True,
    )
    resp.raise_for_status()

    suffix = ".xlsx"
    if "content-disposition" in resp.headers:
        cd = resp.headers["content-disposition"]
        if "filename=" in cd:
            fn = cd.split("filename=")[1].strip('"')
            if "." in fn:
                suffix = "." + fn.split(".")[-1]

    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as tmp:
        for chunk in resp.iter_content(chunk_size=8192):
            tmp.write(chunk)
    return path


def _get_compliant_accounts_first_page(barangay=None, limit=100):
    """
    Returns properties with zero outstanding balance across all billing years.
    Optionally filtered by barangay.
    Returns a flat list of tuples for the treeview:
      (id, td_number, owner_name, barangay, kind, total_paid, years_covered, last_or, last_paid)
    """
    params = {"limit": limit}
    if barangay and barangay != "ALL":
        params["barangay"] = barangay

    result = api_request("GET", "/billing/compliant", params=params)
    if isinstance(result, dict) and "items" in result:
        return [
            (
                item.get("id"),
                item.get("td_number"),
                item.get("owner_name"),
                item.get("barangay", "—"),
                item.get("kind_of_property", "—"),
                item.get("total_paid", 0),
                item.get("years_covered", 0),
                item.get("last_or") or "—",
                item.get("last_paid") or "—",
            )
            for item in result["items"]
        ]
    return []


def get_compliant_accounts(barangay=None, limit=200):
    """
    Returns all compliant properties, following the backend cursor pages.
    The UI expects tuples:
      (id, td_number, owner_name, barangay, kind, total_paid, years_covered, last_or, last_paid)
    """
    rows = []
    cursor = None

    while True:
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if barangay and barangay != "ALL":
            params["barangay"] = barangay

        result = api_request("GET", "/billing/compliant", params=params)
        if not isinstance(result, dict) or "items" not in result:
            break

        rows.extend(
            (
                item.get("id"),
                item.get("td_number"),
                item.get("owner_name"),
                item.get("barangay", "-"),
                item.get("kind_of_property", "-"),
                item.get("total_paid", 0),
                item.get("years_covered", 0),
                item.get("last_or") or "-",
                item.get("last_paid") or "-",
            )
            for item in result["items"]
        )

        cursor = result.get("next_cursor")
        if not result.get("has_more") or not cursor:
            break

    return rows


def get_compliant_summary():
    """
    Returns per-barangay compliance summary.
    Each item: {barangay, total_properties, compliant_count, delinquent_count,
                compliance_rate, collected_from_compliant}
    """
    result = api_request("GET", "/billing/compliant/summary")
    return result if isinstance(result, list) else []

