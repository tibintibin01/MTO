import os
from datetime import datetime, date, timezone
import calendar
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from backend.generators.base import (
    BRANDING, safe_text, safe_filename, fmt_currency, draw_field, draw_header, draw_seal
)

def generate_delinquency_computation(statement_data, base_dir):
    """
    Generates a professional 'Computation of Delinquencies' form.
    This is used as a pre-payment breakdown for taxpayers.
    """
    output_dir = os.path.join(base_dir, "computations")
    os.makedirs(output_dir, exist_ok=True)

    td_number = safe_text(statement_data.get("td_number")) or "NO_TD"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_name = f"COMP_{safe_filename(td_number)}_{timestamp}.pdf"
    output_path = os.path.join(output_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin_x = 18 * mm

    # 1. Background Seal (Watermark)
    draw_seal(c, width, height)

    # 2. Header
    draw_header(c, "COMPUTATION OF DELINQUENCIES", width, height, margin_x)

    # 2. Property & Taxpayer Info
    current_y = height - 52 * mm
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.black)
    c.drawString(margin_x, current_y, "PROPERTY INFORMATION")
    current_y -= 4 * mm
    c.setStrokeColor(colors.HexColor(BRANDING["branding_colors"]["primary"]))
    c.setLineWidth(0.5)
    c.line(margin_x, current_y, width - margin_x, current_y)
    
    current_y -= 10 * mm
    draw_field(c, "TD Number", statement_data.get("td_number"), margin_x, current_y)
    draw_field(c, "Owner Name", statement_data.get("owner_name"), margin_x, current_y - 8 * mm, width=87*mm)
    draw_field(c, "Location", statement_data.get("location"), margin_x, current_y - 16 * mm)
    
    draw_field(c, "Kind of Property", statement_data.get("kind_of_property"), width/2 + 5*mm, current_y, width=82*mm)
    draw_field(c, "Assessed Value", fmt_currency(statement_data.get("assessed_value")), width/2 + 5*mm, current_y - 8*mm, width=82*mm)
    
    # 3. Computation Table
    current_y -= 32 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin_x, current_y, "TAX COMPUTATION DETAILS")
    current_y -= 4 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    
    columns = [
        ("Year", 18 * mm), 
        ("Basic (1%)", 28 * mm), 
        ("SEF (1%)", 28 * mm),
        ("Penalty", 28 * mm), 
        ("Subtotal", 32 * mm)
    ]
    
    current_y -= 8 * mm
    # Draw Table Header
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["accent"]))
    c.rect(margin_x, current_y - 2*mm, width - 2*margin_x, 8*mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8)
    
    temp_x = margin_x + 2*mm
    for label, col_width in columns:
        if label == "Year":
            c.drawString(temp_x, current_y, label)
        else:
            c.drawRightString(temp_x + col_width - 4*mm, current_y, label)
        temp_x += col_width

    current_y -= 8 * mm
    c.setFont("Helvetica", 9)
    
    billing_rows = statement_data.get("billing_rows", [])
    total_basic = 0
    total_sef = 0
    total_penalties = 0
    
    for row in billing_rows:
        # Only show rows with balance
        if float(row.get("balance_amount", 0)) <= 0:
            continue
            
        if current_y < 50 * mm:
            c.showPage()
            current_y = height - 30 * mm # Minimal header on next page
            # Redraw Table Header logic would go here if needed
            
        temp_x = margin_x + 2*mm
        
        basic = float(row.get("basic_amount", 0))
        sef = float(row.get("sef_amount", 0))
        penalty = float(row.get("penalty", 0))
        subtotal = basic + sef + penalty
        
        total_basic += basic
        total_sef += sef
        total_penalties += penalty
        
        for label, col_width in columns:
            if label == "Year":
                c.drawString(temp_x, current_y, str(row.get("tax_year")))
            else:
                val = ""
                if "Basic" in label: val = fmt_currency(basic)
                elif "SEF" in label: val = fmt_currency(sef)
                elif "Penalty" in label: val = fmt_currency(penalty)
                elif "Subtotal" in label: 
                    val = fmt_currency(subtotal)
                    c.setFont("Helvetica-Bold", 9)
                
                c.drawRightString(temp_x + col_width - 4*mm, current_y, val)
                c.setFont("Helvetica", 9)
            temp_x += col_width
        
        current_y -= 7 * mm
        c.setStrokeColor(colors.lightgrey)
        c.line(margin_x, current_y + 1*mm, width - margin_x, current_y + 1*mm)

    # 4. Summary & Total
    current_y -= 10 * mm
    if current_y < 60 * mm:
        c.showPage()
        current_y = height - 40 * mm

    c.setStrokeColor(colors.black)
    c.roundRect(width - 85 * mm, current_y - 30 * mm, 67 * mm, 35 * mm, 2, stroke=1, fill=0)
    
    summary_x = width - 80 * mm
    c.setFont("Helvetica", 9)
    c.drawString(summary_x, current_y, "Total Basic:")
    c.drawRightString(width - margin_x - 5*mm, current_y, fmt_currency(total_basic))
    
    current_y -= 6 * mm
    c.drawString(summary_x, current_y, "Total SEF:")
    c.drawRightString(width - margin_x - 5*mm, current_y, fmt_currency(total_sef))
    
    current_y -= 6 * mm
    c.drawString(summary_x, current_y, "Total Penalties:")
    c.drawRightString(width - margin_x - 5*mm, current_y, fmt_currency(total_penalties))
    
    current_y -= 8 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(summary_x, current_y, "GRAND TOTAL")
    c.drawRightString(width - margin_x - 5*mm, current_y, fmt_currency(total_basic + total_sef + total_penalties))

    # 5. Validity & Signatures
    current_y -= 25 * mm
    today = datetime.now(timezone.utc).date()
    last_day = calendar.monthrange(today.year, today.month)[1]
    valid_until = date(today.year, today.month, last_day).strftime("%B %d, %Y")
    
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["danger"]))
    c.drawString(margin_x, current_y, f"Note: This computation is valid only until {valid_until}.")
    
    current_y -= 25 * mm
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    c.drawString(margin_x, current_y, "Prepared by:")
    c.drawString(width/2 + 10*mm, current_y, "Approved by:")
    
    current_y -= 15 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin_x, current_y, statement_data.get("accountable_officer", "__________________________"))
    c.drawString(width/2 + 10*mm, current_y, "__________________________")
    
    current_y -= 4 * mm
    c.setFont("Helvetica", 8)
    c.drawString(margin_x, current_y, "Revenue Officer / Deputy")
    c.drawString(width/2 + 10*mm, current_y, "Municipal Treasurer")

    # Footer
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.grey)
    c.drawRightString(width - margin_x, 10 * mm, BRANDING["footer_text"])

    c.save()
    return output_path
