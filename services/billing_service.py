# -*- coding: utf-8 -*-
# Client-side Billing Service (Thin Client)
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from services.api_helper import api_request

# --- Utility Logic (Local) ---

def normalize_tax_years(value):
    raw = str(value or "").replace(";", ",")
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    normalized = []
    for part in parts:
        if "-" in part and len(part) == 9:
            start, end = part.split("-", 1)
            if start.isdigit() and end.isdigit():
                start_year = int(start)
                end_year = int(end)
                if end_year >= start_year and (end_year - start_year) <= 10:
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
    if not text: return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try: return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError: continue
    return None

def validate_tax_year_text(value):
    text = str(value or "").strip()
    if not text: return {"ok": False, "message": "Please enter at least one Tax Year."}
    parts = [item.strip() for item in text.replace(";", ",").split(",") if item.strip()]
    current_year = datetime.now().year + 5
    for part in parts:
        if "-" in part:
            if not re.fullmatch(r"\d{4}-\d{4}", part): return {"ok": False, "message": f"Invalid range: {part}"}
            s, e = [int(x) for x in part.split("-", 1)]
            if e < s: return {"ok": False, "message": f"Invalid range: {part}"}
            continue
        if not re.fullmatch(r"\d{4}", part): return {"ok": False, "message": f"Invalid year: {part}"}
    return {"ok": True, "years": normalize_tax_years(text), "text": format_tax_years(text)}

# --- API Requests ---

def get_property_statement_data(property_id):
    return api_request("GET", f"/properties/{property_id}/statement")

def get_assessment_roll():
    return api_request("GET", "/billing/assessment-roll")

def get_report_details(month="All", year="All"):
    return api_request("GET", "/billing/report-details", params={"month": month, "year": year})

def get_rpt_receivables_summary(year):
    return api_request("GET", "/billing/receivables-summary", params={"year": year})
