import os
from datetime import datetime, date
import calendar
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from backend.generators.base import (
    BRANDING, safe_text, safe_filename, fmt_currency, draw_field, draw_header, draw_seal
)
from utils.currency_helper import amount_to_words

def generate_custom_computation_pdf(computation_data, base_dir):
    """
    Generates a professional consolidated computation PDF mimicking the official MTO format.
    """
    output_dir = os.path.join(base_dir, "computations")
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"DELINQUENCY_NOTICE_{timestamp}.pdf"
    output_path = os.path.join(output_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin_x = 18 * mm

    # 1. Background Seal (Watermark)
    draw_seal(c, width, height)

    # 2. Header & Branding
    draw_header(c, "NOTICE OF REAL PROPERTY TAX DELINQUENCY", width, height, margin_x)

    # 3. Property Information Block
    current_y = height - 52 * mm
    c.setFont("Helvetica", 9)
    
    properties = computation_data.get("properties", [])
    if not properties: return None
    
    p = properties[0]
    lp = p.get("last_payment", {})

    c.drawRightString(width - margin_x, current_y + 8*mm, f"Date:  {datetime.now().strftime('%B %d, %Y')}")

    draw_field(c, "Name", p.get("owner_name"), margin_x, current_y, width=100*mm)
    draw_field(c, "Address", p.get("location"), margin_x, current_y - 8 * mm, width=100*mm)
    
    current_y -= 22 * mm
    c.setFont("Helvetica", 9)
    c.drawString(margin_x, current_y, "Dear Sir/ Madam:")
    current_y -= 5 * mm
    c.setFont("Helvetica", 9)
    msg = "In compliance to the requirement of Sec. 254 R. A. 7160 (Local Government Code of 1991) you are hereby informed of the tax delinquency on your property described as follows:"
    # Simple wrap
    c.drawString(margin_x + 5*mm, current_y, msg[:95])
    c.drawString(margin_x, current_y - 4*mm, msg[95:])
    
    current_y -= 10 * mm
    c.rect(margin_x, current_y - 32*mm, width - 2*margin_x, 38*mm, fill=0, stroke=1)
    
    row_y = current_y
    draw_field(c, "Classification", p.get("kind_of_property"), margin_x + 2*mm, row_y, width=70*mm)
    draw_field(c, "PIN/TDN", p.get("td_number"), margin_x + 2*mm, row_y - 7 * mm, width=70*mm)
    draw_field(c, "Location", p.get("location"), margin_x + 2*mm, row_y - 14 * mm, width=70*mm)
    draw_field(c, "Assessed Value", fmt_currency(p.get("assessed_value")), margin_x + 2*mm, row_y - 21 * mm, width=70*mm)
    draw_field(c, "Last Payment", str(lp.get("year", "N/A")), margin_x + 2*mm, row_y - 28 * mm, width=70*mm)

    col2_x = width/2 + 10 * mm
    draw_field(c, "Lot No.", p.get("lot_no", "N/A"), col2_x, row_y, width=65*mm)
    draw_field(c, "Block No.", p.get("block_no", "N/A"), col2_x, row_y - 7 * mm, width=65*mm)
    draw_field(c, "Area", str(p.get("area", "N/A")), col2_x, row_y - 14 * mm, width=65*mm)
    draw_field(c, "Date", str(lp.get("date", "N/A")), col2_x, row_y - 21 * mm, width=65*mm)
    draw_field(c, "OR No.", str(lp.get("or_number", "N/A")), col2_x, row_y - 28 * mm, width=65*mm)

    current_y -= 42 * mm
    
    # Year Range Line
    years_text = f"For the year(s) {p['rows'][0]['year_from']} to {p['rows'][-1]['year_to']}"
    c.setFont("Helvetica", 10)
    c.drawString(margin_x + 10*mm, current_y, years_text)
    c.drawRightString(width - margin_x - 5*mm, current_y, f"Total amount of Php {fmt_currency(computation_data.get('grand_total', 0))}")
    
    current_y -= 10 * mm
    
    # 4. Computation Table
    c.setFont("Helvetica-Bold", 8)
    cols = [
        ("Assessed Value", 30 * mm),
        ("Tax Year", 25 * mm),
        ("QTR", 12 * mm),
        ("Basic Tax", 25 * mm),
        ("SEF Tax", 25 * mm),
        ("Penalty", 25 * mm),
        ("Total Tax Due", 32 * mm)
    ]
    
    # Draw Table Box
    c.rect(margin_x, current_y - 65*mm, width - 2*margin_x, 72*mm, fill=0, stroke=1)
    
    temp_x = margin_x
    for label, col_width in cols:
        c.drawString(temp_x + 2*mm, current_y, label)
        c.line(temp_x, current_y + 4*mm, temp_x, current_y - 65*mm)
        temp_x += col_width
    c.line(width - margin_x, current_y + 4*mm, width - margin_x, current_y - 65*mm)

    c.line(margin_x, current_y - 2*mm, width - margin_x, current_y - 2*mm)
    
    c.setFont("Helvetica", 8)
    current_y -= 6 * mm
    
    for row in p["rows"]:
        temp_x = margin_x
        year_display = str(row["year_from"])
        if row["year_from"] != row["year_to"]:
            year_display += f" - {row['year_to']}"
            
        c.drawString(margin_x + 2*mm, current_y, fmt_currency(row["assessed_value"]))
        c.drawString(margin_x + 32*mm, current_y, year_display)
        c.drawString(margin_x + 57*mm, current_y, "1-4")
        
        c.drawRightString(margin_x + 92*mm, current_y, fmt_currency(row["basic"]))
        c.drawRightString(margin_x + 117*mm, current_y, fmt_currency(row["sef"]))
        
        penalty_val = row["penalty"]
        penalty_text = fmt_currency(penalty_val) if penalty_val > 0 else "AMNESTY"
        c.drawRightString(margin_x + 142*mm, current_y, penalty_text)
        
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(margin_x + 174*mm, current_y, fmt_currency(row["total"]))
        c.setFont("Helvetica", 8)
        current_y -= 6 * mm

    # 5. Footer Summary
    current_y = row_y - 94 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 4 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin_x + 2*mm, current_y, f"COMPUTATION AS OF {computation_data.get('date_computed', 'MAY 2026')}")
    
    total_basic = sum(row["basic"] for row in p["rows"])
    total_sef = sum(row["sef"] for row in p["rows"])
    total_penalty = sum(row["penalty"] for row in p["rows"])
    
    c.drawRightString(margin_x + 92*mm, current_y, fmt_currency(total_basic))
    c.drawRightString(margin_x + 117*mm, current_y, fmt_currency(total_sef))
    c.drawRightString(margin_x + 142*mm, current_y, fmt_currency(total_penalty))
    c.drawRightString(margin_x + 174*mm, current_y, fmt_currency(computation_data.get("grand_total", 0)))

    # Words Total
    current_y -= 12 * mm
    c.setFont("Helvetica-BoldOblique", 11)
    words = amount_to_words(computation_data.get("grand_total", 0))
    c.drawCentredString(width/2, current_y, words)
    
    # 6. Bottom Text Block
    current_y -= 12 * mm
    c.setFont("Helvetica", 8)
    msg2 = "If after fifteen (15) days from your receipt hereof, you failed to remit or pay the said amount, the remedies provided for under the law for the collection of delinquent taxes shall be applied to enforce collection."
    # Wrap msg2
    c.drawString(margin_x, current_y, msg2[:105])
    c.drawString(margin_x, current_y - 4*mm, msg2[105:])
    
    current_y -= 12 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(width/2, current_y, "Kindly DISREGARD THIS NOTICE if settlement of your real property tax due has been made.")

    # 7. Signature Block (Final Form)
    current_y -= 25 * mm
    c.setFont("Helvetica", 10)
    c.drawString(margin_x, current_y, "Prepared by:")
    c.drawString(width/2 + 20*mm, current_y, "Very truly yours,")
    
    current_y -= 12 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin_x, current_y, "KEVIN JOSEPH M. MACALINAO")
    c.drawString(width/2 + 20*mm, current_y, "MARIA ELENA P. CHAVEZ")
    
    current_y -= 4 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(margin_x + 5*mm, current_y, "Admin Assistant")
    c.drawString(width/2 + 25*mm, current_y, "Municipal Treasurer")
    
    # 8. Acknowledgement Block
    current_y -= 25 * mm
    c.setLineWidth(1)
    c.line(margin_x, current_y, width - margin_x, current_y)
    
    current_y -= 5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin_x, current_y, "ACKNOWLEDGMENT:")
    c.drawString(width/2 + 10*mm, current_y, "To be filled-out by MTO personnel:")
    
    c.line(width/2 + 8*mm, current_y + 5*mm, width/2 + 8*mm, current_y - 25*mm)
    
    c.setFont("Helvetica", 9)
    current_y -= 6 * mm
    c.drawString(margin_x, current_y, "Received by: ____________________________")
    c.drawString(margin_x, current_y - 6*mm, "Name and Signature: ______________________")
    c.drawString(margin_x, current_y - 12*mm, "Date: __________________________________")
    
    c.rect(width/2 + 25*mm, current_y - 2*mm, 15*mm, 8*mm)
    c.drawString(width/2 + 45*mm, current_y + 1*mm, "Served")
    
    c.rect(width/2 + 25*mm, current_y - 12*mm, 15*mm, 8*mm)
    c.drawString(width/2 + 45*mm, current_y - 9*mm, "Unserved")
    
    c.drawString(width/2 + 10*mm, current_y - 20*mm, "Reason: ________________________________")

    c.save()
    return output_path
