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


def get_report_details(month="All", year="All"):
    result = api_request(
        "GET", "/billing/report-details", params={"month": month, "year": year}
    )
    # Backend now returns {"items": [...], "next_cursor": ..., "has_more": ..., "count": ...}
    if isinstance(result, dict) and "items" in result:
        return result["items"]
    # Fallback for any legacy response shape
    return result if isinstance(result, list) else []


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


def get_compliant_accounts(barangay=None, limit=100):
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


def get_compliant_summary():
    """
    Returns per-barangay compliance summary.
    Each item: {barangay, total_properties, compliant_count, delinquent_count,
                compliance_rate, collected_from_compliant}
    """
    result = api_request("GET", "/billing/compliant/summary")
    return result if isinstance(result, list) else []

