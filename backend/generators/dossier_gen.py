import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from backend.generators.base import (
    BRANDING, safe_text, safe_filename, fmt_currency, draw_field, draw_header
)

def generate_property_dossier(dossier_data, base_dir):
    dossiers_dir = os.path.join(base_dir, "dossiers")
    os.makedirs(dossiers_dir, exist_ok=True)

    m = dossier_data.get("master", {})
    td_number = safe_text(m.get("td_number")) or "NO_TD"
    date_part = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"DOSSIER_{safe_filename(td_number)}_{date_part}.pdf"
    output_path = os.path.join(dossiers_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin_x = 20 * mm
    
    draw_header(c, "PROPERTY HISTORY DOSSIER", width, height, margin_x)

    current_y = height - 45 * mm
    primary_color = colors.HexColor(BRANDING["branding_colors"]["primary"])
    c.setFillColor(colors.black)

    # Section 1: Property Specifications
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
        ("Assessed Value", f"P {fmt_currency(m.get('assessed_value'))}"),
        ("Effectivity Date", m.get("effectivity_date") or "---")
    ]

    for label, val in specs:
        c.setFont(BRANDING["fonts"]["header"], 9)
        c.setFillColor(colors.HexColor("#546e7a"))
        c.drawString(margin_x, current_y, label.upper())
        c.setFont(BRANDING["fonts"]["body"], 10)
        c.setFillColor(colors.black)
        c.drawRightString(width - margin_x, current_y, safe_text(val))
        current_y -= 8 * mm

    current_y -= 10 * mm

    # Section 2: Ownership Genealogy
    c.setFont(BRANDING["fonts"]["header"], 12)
    c.drawString(margin_x, current_y, "II. OWNERSHIP GENEALOGY (ANCESTRY)")
    current_y -= 5 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 10 * mm

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

    # Section 3: Payment History
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
            c.drawString(margin_x + 2 * mm, current_y, safe_text(p[0]))
            c.drawString(margin_x + 35 * mm, current_y, safe_text(p[1]))
            c.drawString(margin_x + 75 * mm, current_y, safe_text(p[2]))
            c.drawRightString(width - margin_x - 2 * mm, current_y, f"P {fmt_currency(p[6])}")
            current_y -= 7 * mm

    current_y -= 15 * mm

    # Section 4: Administrative Audit
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
        c.drawString(margin_x, current_y, safe_text(log.get("action")))
        current_y -= 8 * mm

    c.setFont(BRANDING["fonts"]["body"], 7)
    c.setFillColor(colors.HexColor("#90a4ae"))
    c.drawCentredString(width/2, 15 * mm, BRANDING["footer_text"])

    c.save()
    return output_path
