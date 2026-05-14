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
    return api_request(
        "GET", "/billing/report-details", params={"month": month, "year": year}
    )


def get_rpt_receivables_summary(year):
    return api_request("GET", "/billing/receivables-summary", params={"year": year})


def get_delinquent_accounts(limit=100, offset=0):
    return api_request(
        "GET", "/billing/delinquents", params={"limit": limit, "offset": offset}
    )


def download_computation_pdf(property_id):
    """Triggers the download of a computation PDF and returns the local path."""
    return api_download_file("GET", f"/properties/{property_id}/computation-pdf")


def download_statement_pdf(property_id):
    """Triggers the download of a statement PDF and returns the local path."""
    return api_download_file("GET", f"/properties/{property_id}/statement-pdf")


def download_notice_pdf(property_id):
    """Triggers the download of a delinquency notice PDF and returns the local path."""
    return api_download_file("GET", f"/properties/{property_id}/notice-pdf")

def get_custom_computation_preview(property_ids, penalty_rate=0.02, discount_rate=0.0, amnesty_year=None, last_payment_year=None, project_until=None):
    """Fetches a preview of the computation with overrides."""
    return api_request("POST", "/billing/compute/preview", data={
        "property_ids": property_ids,
        "penalty_rate": penalty_rate,
        "discount_rate": discount_rate,
        "amnesty_year": amnesty_year,
        "last_payment_year": last_payment_year,
        "project_until": project_until
    })

def export_custom_computation(property_ids, penalty_rate=0.02, discount_rate=0.0, amnesty_year=None, last_payment_year=None, project_until=None):
    """Downloads the professional PDF for the custom computation."""
    # Using raw_response=True because we want the binary file stream
    response = api_request("POST", "/billing/compute/export", data={
        "property_ids": property_ids,
        "penalty_rate": penalty_rate,
        "discount_rate": discount_rate,
        "amnesty_year": amnesty_year,
        "last_payment_year": last_payment_year,
        "project_until": project_until
    }, raw_response=True)


    
    if response:
        import os
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        filename = f"Delinquency_Computation_{timestamp}.pdf"
        save_path = os.path.join(downloads_dir, filename)
        
        with open(save_path, "wb") as f:
            f.write(response.content)
        return save_path
    return None


