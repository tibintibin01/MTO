import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from backend.generators.base import (
    BRANDING, safe_text, safe_filename, fmt_currency, draw_field, draw_header
)

def generate_or_receipt(receipt_data, base_dir):
    receipts_dir = os.path.join(base_dir, "receipts")
    os.makedirs(receipts_dir, exist_ok=True)

    or_number = safe_text(receipt_data.get("or_number")) or "NO_OR_NUMBER"
    td_number = safe_text(receipt_data.get("td_number")) or "NO_TD"
    date_part = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"OR_{safe_filename(or_number)}_{safe_filename(td_number)}_{date_part}.pdf"
    output_path = os.path.join(receipts_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin_x = 18 * mm

    # Use Base Header
    draw_header(c, "OFFICIAL RECEIPT", width, height, margin_x)

    current_y = height - 55 * mm
    c.setFillColor(colors.black)
    current_y -= 14 * mm

    # Receipt metadata
    accent_color = colors.HexColor(BRANDING["branding_colors"]["accent"])
    c.setStrokeColor(accent_color)
    c.rect(margin_x, current_y - 18 * mm, width - (2 * margin_x), 20 * mm, fill=0, stroke=1)
    draw_field(c, "OR Number", receipt_data.get("or_number"), margin_x + 5 * mm, current_y - 5 * mm)
    draw_field(c, "Date Paid", receipt_data.get("or_date"), margin_x + 5 * mm, current_y - 12 * mm)
    
    tax_year_label = ", ".join(receipt_data.get("tax_years", [])) if receipt_data.get("tax_years") else receipt_data.get("tax_year")
    draw_field(c, "Tax Year(s)", tax_year_label, width / 2, current_y - 5 * mm, width=55 * mm)
    draw_field(c, "Accountable Officer", receipt_data.get("accountable_officer"), width / 2, current_y - 12 * mm, width=55 * mm)

    current_y -= 30 * mm

    # Property details
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_x, current_y, "Property Details")
    current_y -= 6 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 8 * mm

    draw_field(c, "TD Number", receipt_data.get("td_number"), margin_x, current_y)
    current_y -= 8 * mm
    draw_field(c, "Owner Name", receipt_data.get("owner_name"), margin_x, current_y)
    current_y -= 8 * mm
    draw_field(c, "Kind of Property", receipt_data.get("kind_of_property"), margin_x, current_y)
    current_y -= 8 * mm
    draw_field(c, "Lot Number", receipt_data.get("lot_number"), margin_x, current_y)
    current_y -= 8 * mm
    draw_field(c, "Location", receipt_data.get("location"), margin_x, current_y)

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
                if applied_amount <= 0: continue
                entries.append((f"Applied Payment ({year})", fmt_currency(applied_amount)))
            else:
                entries.extend([
                    (f"Assessed Value ({year})", fmt_currency(item.get("assessed_value", receipt_data.get("assessed_value")))),
                    (f"Basic Tax ({year})", fmt_currency(item.get("basic_amount"))),
                    (f"SEF ({year})", fmt_currency(item.get("sef_amount"))),
                    (f"Penalty ({year})", fmt_currency(item.get("penalty", receipt_data.get("penalty")))),
                ])
    else:
        assessed = float(receipt_data.get("assessed_value") or 0)
        entries = [
            ("Assessed Value", fmt_currency(assessed)),
            ("Basic Tax (1%)", fmt_currency(receipt_data.get("basic") or (assessed * 0.01))),
            ("SEF (1%)", fmt_currency(receipt_data.get("sef") or (assessed * 0.01))),
            ("Penalty", fmt_currency(receipt_data.get("penalty"))),
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
    c.drawRightString(width - margin_x, current_y, fmt_currency(total_paid))

    current_y -= 18 * mm
    c.setFont(BRANDING["fonts"]["body"], 9)
    c.drawString(margin_x, current_y, "Received from:")
    c.setFont(BRANDING["fonts"]["header"], 10)
    c.drawString(margin_x + 28 * mm, current_y, safe_text(receipt_data.get("payor_name") or receipt_data.get("owner_name")))

    current_y -= 18 * mm
    c.setFont(BRANDING["fonts"]["body"], 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawString(margin_x, current_y, BRANDING["footer_text"])

    c.save()
    return output_path
