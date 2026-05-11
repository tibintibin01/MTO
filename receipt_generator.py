from datetime import datetime
import os
import re
import json

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


# Load branding configuration
BRANDING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "branding.json")
try:
    with open(BRANDING_FILE, "r") as f:
        BRANDING = json.load(f)
except:
    # Fallback to defaults if file missing
    BRANDING = {
        "office_name": "MUNICIPAL TREASURY OFFICE",
        "branding_colors": {"primary": "#1f538d", "secondary": "#7f8c8d", "accent": "#d9e2f3", "danger": "#c0392b", "success": "#27ae60"},
        "fonts": {"header": "Helvetica-Bold", "body": "Helvetica"},
        "footer_text": "This document was generated electronically by the MTO System."
    }


def _safe_text(value):
    return str(value).strip() if value is not None else ""


def _safe_filename(value):
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', "_", _safe_text(value))
    return cleaned.strip("_") or "receipt"


def _fmt_currency(value):
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return "0.00"


def _draw_field(c, label, value, x, y, width=78 * mm):
    c.setFont(BRANDING["fonts"]["header"], 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawString(x, y, label.upper())
    c.setFont(BRANDING["fonts"]["body"], 10)
    c.setFillColor(colors.black)
    c.drawRightString(x + width, y, _safe_text(value))


def generate_or_receipt(receipt_data, base_dir):
    receipts_dir = os.path.join(base_dir, "receipts")
    os.makedirs(receipts_dir, exist_ok=True)

    or_number = _safe_text(receipt_data.get("or_number")) or "NO_OR_NUMBER"
    td_number = _safe_text(receipt_data.get("td_number")) or "NO_TD"
    date_part = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"OR_{_safe_filename(or_number)}_{_safe_filename(td_number)}_{date_part}.pdf"
    output_path = os.path.join(receipts_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4

    margin_x = 18 * mm
    current_y = height - 22 * mm

    # Header with Branding
    primary_color = colors.HexColor(BRANDING["branding_colors"]["primary"])
    c.setStrokeColor(primary_color)
    c.setFillColor(primary_color)
    c.rect(0, height - 40 * mm, width, 40 * mm, fill=1, stroke=0)
    
    c.setFillColor(colors.white)
    c.setFont(BRANDING["fonts"]["header"], 22)
    c.drawString(margin_x, height - 20 * mm, "OFFICIAL RECEIPT")
    c.setFont(BRANDING["fonts"]["body"], 10)
    c.drawString(margin_x, height - 26 * mm, BRANDING["office_name"])
    
    c.drawRightString(width - margin_x, height - 20 * mm, datetime.now().strftime("%B %d, %Y"))
    c.drawRightString(width - margin_x, height - 26 * mm, datetime.now().strftime("%I:%M %p"))

    current_y = height - 55 * mm
    c.setFillColor(colors.black)

    current_y -= 14 * mm

    # Receipt metadata
    accent_color = colors.HexColor(BRANDING["branding_colors"]["accent"])
    c.setStrokeColor(accent_color)
    c.rect(margin_x, current_y - 18 * mm, width - (2 * margin_x), 20 * mm, fill=0, stroke=1)
    _draw_field(c, "OR Number", receipt_data.get("or_number"), margin_x + 5 * mm, current_y - 5 * mm)
    _draw_field(c, "Date Paid", receipt_data.get("or_date"), margin_x + 5 * mm, current_y - 12 * mm)
    tax_year_label = ", ".join(receipt_data.get("tax_years", [])) if receipt_data.get("tax_years") else receipt_data.get("tax_year")
    _draw_field(c, "Tax Year(s)", tax_year_label, width / 2, current_y - 5 * mm, width=55 * mm)
    _draw_field(c, "Accountable Officer", receipt_data.get("accountable_officer"), width / 2, current_y - 12 * mm, width=55 * mm)

    current_y -= 30 * mm

    # Property details
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_x, current_y, "Property Details")
    current_y -= 6 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 8 * mm

    _draw_field(c, "TD Number", receipt_data.get("td_number"), margin_x, current_y)
    current_y -= 8 * mm
    _draw_field(c, "Owner Name", receipt_data.get("owner_name"), margin_x, current_y)
    current_y -= 8 * mm
    _draw_field(c, "Kind of Property", receipt_data.get("kind_of_property"), margin_x, current_y)
    current_y -= 8 * mm
    _draw_field(c, "Lot Number", receipt_data.get("lot_number"), margin_x, current_y)
    current_y -= 8 * mm
    _draw_field(c, "Location", receipt_data.get("location"), margin_x, current_y)

    current_y -= 16 * mm

    # Payment breakdown
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_x, current_y, "Payment Breakdown")
    current_y -= 6 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 8 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin_x, current_y, "Description")
    c.drawRightString(width - margin_x, current_y, "Amount")
    current_y -= 5 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 8 * mm

    line_items = receipt_data.get("line_items") or []
    if line_items:
        partial_mode = any(float(item.get("applied_amount", item.get("total_amount", 0)) or 0) < float(item.get("total_amount", 0) or 0) for item in line_items)
        entries = []
        for item in line_items:
            year = item.get("tax_year", "")
            if partial_mode:
                applied_amount = float(item.get("applied_amount", 0) or 0)
                if applied_amount <= 0:
                    continue
                entries.append((f"Applied Payment ({year})", _fmt_currency(applied_amount)))
            else:
                entries.extend(
                    [
                        (f"Assessed Value ({year})", _fmt_currency(item.get("assessed_value", receipt_data.get("assessed_value")))),
                        (f"Basic Tax ({year})", _fmt_currency(item.get("basic_amount"))),
                        (f"SEF ({year})", _fmt_currency(item.get("sef_amount"))),
                        (f"Penalty ({year})", _fmt_currency(item.get("penalty", receipt_data.get("penalty")))),
                    ]
                )
    else:
        # Fallback calculations if specific amounts missing
        assessed = float(receipt_data.get("assessed_value") or 0)
        basic = receipt_data.get("basic") if receipt_data.get("basic") is not None else (assessed * 0.01)
        sef = receipt_data.get("sef") if receipt_data.get("sef") is not None else (assessed * 0.01)
        
        entries = [
            ("Assessed Value", _fmt_currency(assessed)),
            ("Basic Tax (1%)", _fmt_currency(basic)),
            ("SEF (1%)", _fmt_currency(sef)),
            ("Penalty", _fmt_currency(receipt_data.get("penalty"))),
        ]

    c.setFont("Helvetica", 10)
    for label, amount in entries:
        c.drawString(margin_x, current_y, label)
        c.drawRightString(width - margin_x, current_y, amount)
        current_y -= 8 * mm

        if current_y < 45 * mm:
            c.showPage()
            current_y = height - 25 * mm
            c.setFont("Helvetica", 10)

    c.setStrokeColor(colors.HexColor("#1f4e78"))
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 9 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin_x, current_y, "TOTAL PAID")
    
    total_paid = receipt_data.get("total") if receipt_data.get("total") is not None else receipt_data.get("amount")
    c.drawRightString(width - margin_x, current_y, _fmt_currency(total_paid))

    current_y -= 18 * mm
    c.setFont(BRANDING["fonts"]["body"], 9)
    c.drawString(margin_x, current_y, "Received from:")
    c.setFont(BRANDING["fonts"]["header"], 10)
    c.drawString(margin_x + 28 * mm, current_y, _safe_text(receipt_data.get("payor_name") or receipt_data.get("owner_name")))

    current_y -= 18 * mm
    c.setFont(BRANDING["fonts"]["body"], 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawString(margin_x, current_y, BRANDING["footer_text"])
    current_y -= 5 * mm

    c.save()
    return output_path


def _draw_soa_table_header(c, left_x, top_y, columns):
    table_width = sum(item[1] for item in columns)
    c.setStrokeColor(colors.HexColor("#b7c9e2"))
    c.setFillColor(colors.HexColor("#d9e2f3"))
    c.rect(left_x, top_y - 7 * mm, table_width, 8 * mm, fill=1, stroke=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8)
    current_x = left_x
    for index, (label, width) in enumerate(columns):
        if index == 0:
            c.drawString(current_x + 2 * mm, top_y - 4.5 * mm, label)
        else:
            c.drawRightString(current_x + width - 2 * mm, top_y - 4.5 * mm, label)
        current_x += width
    return top_y - 10 * mm


    c.save()
    return output_path


def _draw_soa_page(c, statement_data, width, height, margin_x):
    current_y = height - 20 * mm

    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["primary"]))
    c.rect(margin_x, current_y - 12 * mm, width - (2 * margin_x), 14 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(BRANDING["fonts"]["header"], 16)
    c.drawString(margin_x + 5 * mm, current_y - 3 * mm, "STATEMENT OF ACCOUNT")
    c.setFont("Helvetica", 9)
    c.drawRightString(width - margin_x - 5 * mm, current_y - 2 * mm, datetime.now().strftime("%B %d, %Y %I:%M %p"))

    current_y -= 24 * mm
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_x, current_y, "MTO Property Tax Account Summary")
    current_y -= 7 * mm
    c.setFont("Helvetica", 9)
    c.drawString(margin_x, current_y, "Printable breakdown of outstanding balances by tax year")

    current_y -= 14 * mm
    c.setStrokeColor(colors.HexColor("#d9e2f3"))
    c.rect(margin_x, current_y - 26 * mm, width - (2 * margin_x), 28 * mm, fill=0, stroke=1)
    _draw_field(c, "TD Number", statement_data.get("td_number"), margin_x + 4 * mm, current_y - 5 * mm)
    _draw_field(c, "Owner Name", statement_data.get("owner_name"), margin_x + 4 * mm, current_y - 12 * mm)
    _draw_field(c, "Payor", statement_data.get("payor_name"), margin_x + 4 * mm, current_y - 19 * mm)
    _draw_field(c, "Location", statement_data.get("location"), width / 2, current_y - 5 * mm, width=55 * mm)
    _draw_field(c, "Kind of Property", statement_data.get("kind_of_property"), width / 2, current_y - 12 * mm, width=55 * mm)
    _draw_field(c, "Accountable Officer", statement_data.get("accountable_officer"), width / 2, current_y - 19 * mm, width=55 * mm)

    current_y -= 36 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_x, current_y, "Outstanding Balance by Tax Year")
    current_y -= 6 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 8 * mm

    columns = [
        ("Year", 16 * mm),
        ("Assessed", 29 * mm),
        ("Basic", 21 * mm),
        ("SEF", 21 * mm),
        ("Penalty", 21 * mm),
        ("Total", 23 * mm),
        ("Paid", 21 * mm),
        ("Balance", 24 * mm),
    ]
    table_width = sum(item[1] for item in columns)

    def draw_table_header(y_pos):
        c.setFont("Helvetica", 8)
        return _draw_soa_table_header(c, margin_x, y_pos, columns)

    current_y = draw_table_header(current_y)
    c.setFont("Helvetica", 8)
    c.setStrokeColor(colors.HexColor("#d9e2f3"))

    for row in statement_data.get("billing_rows", []):
        if current_y < 35 * mm:
            c.showPage()
            current_y = height - 20 * mm
            current_y = draw_table_header(current_y)
            c.setFont("Helvetica", 8)
            c.setStrokeColor(colors.HexColor("#d9e2f3"))

        row_top = current_y + 2.5 * mm
        c.rect(margin_x, row_top - 7 * mm, table_width, 8 * mm, fill=0, stroke=1)

        current_x = margin_x
        values = [
            _safe_text(row.get("tax_year")),
            _fmt_currency(row.get("assessed_value")),
            _fmt_currency(row.get("basic_amount")),
            _fmt_currency(row.get("sef_amount")),
            _fmt_currency(row.get("penalty")),
            _fmt_currency(row.get("total_amount")),
            _fmt_currency(row.get("amount_paid")),
            _fmt_currency(row.get("balance_amount")),
        ]
        for index, value in enumerate(values):
            width_value = columns[index][1]
            if index > 0:
                c.line(current_x, row_top - 7 * mm, current_x, row_top + 1 * mm)
            if index == 0:
                c.drawString(current_x + 2 * mm, current_y, value)
            else:
                c.drawRightString(current_x + width_value - 2 * mm, current_y, value)
            current_x += width_value
        current_y -= 8 * mm

    current_y -= 1 * mm
    c.line(margin_x, current_y, margin_x + table_width, current_y)
    current_y -= 8 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin_x, current_y, "Grand Total Outstanding")
    c.drawRightString(width - margin_x, current_y, _fmt_currency(statement_data.get("total_balance")))

    current_y -= 8 * mm
    c.drawString(margin_x, current_y, "Grand Total Paid")
    c.drawRightString(width - margin_x, current_y, _fmt_currency(statement_data.get("total_paid")))

    current_y -= 8 * mm
    c.drawString(margin_x, current_y, "Grand Total Due")
    c.drawRightString(width - margin_x, current_y, _fmt_currency(statement_data.get("grand_total")))

    current_y -= 16 * mm
    c.setFont(BRANDING["fonts"]["body"], 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawString(margin_x, current_y, BRANDING["footer_text"])
    return current_y


def generate_statement_of_account(statement_data, base_dir):
    statements_dir = os.path.join(base_dir, "statements")
    os.makedirs(statements_dir, exist_ok=True)

    td_number = _safe_text(statement_data.get("td_number")) or "NO_TD"
    date_part = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"SOA_{_safe_filename(td_number)}_{date_part}.pdf"
    output_path = os.path.join(statements_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    _draw_soa_page(c, statement_data, A4[0], A4[1], 15 * mm)
    c.save()
    return output_path


def bulk_generate_soa(data_list, base_dir, filename_prefix="BULK_SOA"):
    """Generates multiple SOAs into a single PDF file for high-speed printing."""
    statements_dir = os.path.join(base_dir, "statements")
    os.makedirs(statements_dir, exist_ok=True)

    date_part = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{filename_prefix}_{date_part}.pdf"
    output_path = os.path.join(statements_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin_x = 15 * mm

    for index, statement_data in enumerate(data_list):
        if index > 0:
            c.showPage()
        _draw_soa_page(c, statement_data, width, height, margin_x)

    c.save()
    return output_path

def generate_delinquency_notice(statement_data, base_dir):
    statements_dir = os.path.join(base_dir, "statements")
    os.makedirs(statements_dir, exist_ok=True)

    td_number = _safe_text(statement_data.get("td_number")) or "NO_TD"
    date_part = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"NOTICE_{_safe_filename(td_number)}_{date_part}.pdf"
    output_path = os.path.join(statements_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin_x = 15 * mm
    current_y = height - 20 * mm

    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["danger"]))
    c.rect(margin_x, current_y - 12 * mm, width - (2 * margin_x), 14 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(BRANDING["fonts"]["header"], 16)
    c.drawString(margin_x + 5 * mm, current_y - 3 * mm, "NOTICE OF DELINQUENCY")
    c.setFont("Helvetica", 9)
    c.drawRightString(width - margin_x - 5 * mm, current_y - 2 * mm, datetime.now().strftime("%B %d, %Y %I:%M %p"))

    current_y -= 24 * mm
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 11)
    
    notice_text = (
        "Our records show that the property listed below has an outstanding balance. "
        "Please settle your account immediately to avoid further penalties and legal action."
    )
    c.drawString(margin_x, current_y, notice_text)
    
    current_y -= 14 * mm
    c.setStrokeColor(colors.HexColor("#f5c6cb"))
    c.rect(margin_x, current_y - 26 * mm, width - (2 * margin_x), 28 * mm, fill=0, stroke=1)
    _draw_field(c, "TD Number", statement_data.get("td_number"), margin_x + 4 * mm, current_y - 5 * mm)
    _draw_field(c, "Owner Name", statement_data.get("owner_name"), margin_x + 4 * mm, current_y - 12 * mm)
    _draw_field(c, "Location", statement_data.get("location"), margin_x + 4 * mm, current_y - 19 * mm)
    
    current_y -= 36 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_x, current_y, "Delinquent Balances")
    current_y -= 6 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 8 * mm

    columns = [
        ("Year", 16 * mm),
        ("Assessed", 29 * mm),
        ("Basic", 21 * mm),
        ("SEF", 21 * mm),
        ("Penalty", 21 * mm),
        ("Total", 23 * mm),
        ("Paid", 21 * mm),
        ("Balance", 24 * mm),
    ]
    table_width = sum(item[1] for item in columns)

    def draw_page_header(y_pos):
        c.setFont("Helvetica", 8)
        return _draw_soa_table_header(c, margin_x, y_pos, columns)

    current_y = draw_page_header(current_y)
    c.setFont("Helvetica", 8)
    c.setStrokeColor(colors.HexColor("#f5c6cb"))

    for row in statement_data.get("billing_rows", []):
        if float(row.get("balance_amount", 0)) <= 0:
            continue
            
        if current_y < 35 * mm:
            c.showPage()
            current_y = height - 20 * mm
            current_y = draw_page_header(current_y)
            c.setFont("Helvetica", 8)
            c.setStrokeColor(colors.HexColor("#f5c6cb"))

        row_top = current_y + 2.5 * mm
        c.rect(margin_x, row_top - 7 * mm, table_width, 8 * mm, fill=0, stroke=1)

        current_x = margin_x
        values = [
            _safe_text(row.get("tax_year")),
            _fmt_currency(row.get("assessed_value")),
            _fmt_currency(row.get("basic_amount")),
            _fmt_currency(row.get("sef_amount")),
            _fmt_currency(row.get("penalty")),
            _fmt_currency(row.get("total_amount")),
            _fmt_currency(row.get("amount_paid")),
            _fmt_currency(row.get("balance_amount")),
        ]
        for index, value in enumerate(values):
            width_value = columns[index][1]
            if index > 0:
                c.line(current_x, row_top - 7 * mm, current_x, row_top + 1 * mm)
            if index == 0:
                c.drawString(current_x + 2 * mm, current_y, value)
            else:
                c.drawRightString(current_x + width_value - 2 * mm, current_y, value)
            current_x += width_value
        current_y -= 8 * mm

    current_y -= 1 * mm
    c.line(margin_x, current_y, margin_x + table_width, current_y)
    current_y -= 8 * mm
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor("#c0392b"))
    c.drawString(margin_x, current_y, "TOTAL DELINQUENT BALANCE")
    c.drawRightString(width - margin_x, current_y, _fmt_currency(statement_data.get("total_balance")))

    current_y -= 16 * mm
    c.setFont(BRANDING["fonts"]["body"], 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawString(margin_x, current_y, BRANDING["footer_text"])

    c.save()
    return output_path


def generate_property_dossier(dossier_data, base_dir):
    dossiers_dir = os.path.join(base_dir, "dossiers")
    os.makedirs(dossiers_dir, exist_ok=True)

    m = dossier_data.get("master", {})
    td_number = _safe_text(m.get("td_number")) or "NO_TD"
    date_part = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"DOSSIER_{_safe_filename(td_number)}_{date_part}.pdf"
    output_path = os.path.join(dossiers_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin_x = 20 * mm
    current_y = height - 25 * mm

    # --- TOP BRANDING HEADER ---
    primary_color = colors.HexColor(BRANDING["branding_colors"]["primary"])
    c.setFillColor(primary_color)
    c.rect(0, height - 35 * mm, width, 35 * mm, fill=1, stroke=0)
    
    c.setFillColor(colors.white)
    c.setFont(BRANDING["fonts"]["header"], 18)
    c.drawString(margin_x, height - 15 * mm, "PROPERTY HISTORY DOSSIER")
    c.setFont(BRANDING["fonts"]["body"], 10)
    c.drawString(margin_x, height - 21 * mm, BRANDING["office_name"])
    
    c.drawRightString(width - margin_x, height - 15 * mm, "OFFICIAL RECORD")
    c.setFont(BRANDING["fonts"]["body"], 8)
    c.drawRightString(width - margin_x, height - 21 * mm, f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}")

    current_y = height - 45 * mm
    c.setFillColor(colors.black)

    # --- SECTION 1: MASTER PROPERTY DETAILS ---
    c.setFont(BRANDING["fonts"]["header"], 12)
    c.drawString(margin_x, current_y, "I. PROPERTY SPECIFICATIONS")
    current_y -= 5 * mm
    c.setStrokeColor(primary_color)
    c.setLineWidth(0.5)
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 10 * mm

    specs = [
        ("Tax Declaration No.", m.get("td_number")),
        ("Property Index No. (PIN)", m.get("pin") or "Not Assigned"),
        ("Current Owner", m.get("owner_name")),
        ("Location / Barangay", f"{m.get('location') or '---'} / {m.get('barangay') or '---'}"),
        ("Lot & Block No.", f"{m.get('lot_number') or '---'} / {m.get('block_number') or '---'}"),
        ("Total Land Area", f"{m.get('area')} SQM"),
        ("Property Kind", m.get("kind_of_property")),
        ("Assessed Value", f"P {_fmt_currency(m.get('assessed_value'))}"),
        ("Effectivity Date", m.get("effectivity_date") or "---")
    ]

    c.setFont(BRANDING["fonts"]["body"], 10)
    for label, val in specs:
        c.setFont(BRANDING["fonts"]["header"], 9)
        c.setFillColor(colors.HexColor("#546e7a"))
        c.drawString(margin_x, current_y, label.upper())
        c.setFont(BRANDING["fonts"]["body"], 10)
        c.setFillColor(colors.black)
        c.drawRightString(width - margin_x, current_y, _safe_text(val))
        current_y -= 8 * mm

    current_y -= 10 * mm

    # --- SECTION 2: OWNERSHIP GENEALOGY ---
    c.setFont(BRANDING["fonts"]["header"], 12)
    c.drawString(margin_x, current_y, "II. OWNERSHIP GENEALOGY (ANCESTRY)")
    current_y -= 5 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 10 * mm

    c.setFont(BRANDING["fonts"]["body"], 10)
    if dossier_data.get("ancestry"):
        for parent in dossier_data["ancestry"]:
            c.setFont(BRANDING["fonts"]["header"], 10)
            c.drawString(margin_x + 5 * mm, current_y, f"Derived From TD: {parent.get('td_number')}")
            current_y -= 5 * mm
            c.setFont(BRANDING["fonts"]["body"], 9)
            c.drawString(margin_x + 5 * mm, current_y, f"Previous Owner: {parent.get('owner_name')}")
            current_y -= 10 * mm
    else:
        c.setFont(BRANDING["fonts"]["body"], 9)
        c.setFillColor(colors.HexColor("#90a4ae"))
        c.drawString(margin_x + 5 * mm, current_y, "No further ancestry links found for this record.")
        c.setFillColor(colors.black)
        current_y -= 10 * mm

    current_y -= 10 * mm

    # --- SECTION 3: PAYMENT HISTORY ---
    c.setFont(BRANDING["fonts"]["header"], 12)
    c.drawString(margin_x, current_y, "III. COMPLETE PAYMENT TIMELINE")
    current_y -= 5 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 10 * mm

    # Table Header
    c.setFillColor(colors.HexColor("#f1f4f9"))
    c.rect(margin_x, current_y - 2 * mm, width - 2 * margin_x, 8 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont(BRANDING["fonts"]["header"], 9)
    c.drawString(margin_x + 2 * mm, current_y + 3 * mm, "DATE PAID")
    c.drawString(margin_x + 35 * mm, current_y + 3 * mm, "OR NUMBER")
    c.drawString(margin_x + 75 * mm, current_y + 3 * mm, "TAX YEAR")
    c.drawRightString(width - margin_x - 2 * mm, current_y + 3 * mm, "AMOUNT PAID")
    current_y -= 10 * mm

    c.setFont(BRANDING["fonts"]["body"], 9)
    payments = dossier_data.get("payments", [])
    if not payments:
        c.drawCentredString(width/2, current_y - 10 * mm, "No payment history recorded.")
        current_y -= 25 * mm
    else:
        for p in payments:
            if current_y < 40 * mm:
                c.showPage()
                current_y = height - 30 * mm
                c.setFont(BRANDING["fonts"]["body"], 9)

            c.drawString(margin_x + 2 * mm, current_y, _safe_text(p[0]))
            c.drawString(margin_x + 35 * mm, current_y, _safe_text(p[1]))
            c.drawString(margin_x + 75 * mm, current_y, _safe_text(p[2]))
            c.drawRightString(width - margin_x - 2 * mm, current_y, f"P {_fmt_currency(p[6])}")
            current_y -= 7 * mm

    current_y -= 15 * mm

    # --- SECTION 4: ADMINISTRATIVE AUDIT ---
    if current_y < 60 * mm:
        c.showPage()
        current_y = height - 30 * mm

    c.setFont(BRANDING["fonts"]["header"], 12)
    c.drawString(margin_x, current_y, "IV. ADMINISTRATIVE ACTIVITY TRACE")
    current_y -= 5 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 10 * mm

    logs = dossier_data.get("audit_summary", [])
    for log in logs[:10]:
        if current_y < 30 * mm:
            c.showPage()
            current_y = height - 30 * mm

        c.setFont(BRANDING["fonts"]["header"], 8)
        c.setFillColor(colors.HexColor("#455a64"))
        c.drawString(margin_x, current_y, f"{log.get('timestamp')} - {log.get('username')}")
        current_y -= 4 * mm
        c.setFont(BRANDING["fonts"]["body"], 9)
        c.setFillColor(colors.black)
        c.drawString(margin_x, current_y, _safe_text(log.get("action")))
        current_y -= 8 * mm

    # Footer
    c.setFont(BRANDING["fonts"]["body"], 7)
    c.setFillColor(colors.HexColor("#90a4ae"))
    c.drawCentredString(width/2, 15 * mm, BRANDING["footer_text"])

    c.save()
    return output_path

