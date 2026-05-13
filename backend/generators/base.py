from datetime import datetime
import os
import re
import json
from reportlab.lib import colors
from reportlab.lib.units import mm

# Load branding configuration
BRANDING_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "branding.json")

try:
    with open(BRANDING_FILE, "r") as f:
        BRANDING = json.load(f)
except:
    # Fallback to defaults if file missing
    BRANDING = {
        "office_name": "MUNICIPAL TREASURY OFFICE",
        "branding_colors": {
            "primary": "#1f538d", 
            "secondary": "#7f8c8d", 
            "accent": "#d9e2f3", 
            "danger": "#c0392b", 
            "success": "#27ae60"
        },
        "fonts": {"header": "Helvetica-Bold", "body": "Helvetica"},
        "footer_text": "This document was generated electronically by the MTO System."
    }

def safe_text(value):
    return str(value).strip() if value is not None else ""

def safe_filename(value):
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', "_", safe_text(value))
    return cleaned.strip("_") or "document"

def fmt_currency(value):
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return "0.00"

def draw_field(c, label, value, x, y, width=78 * mm):
    c.setFont(BRANDING["fonts"]["header"], 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawString(x, y, label.upper())
    
    text = safe_text(value)
    font_size = 10
    # Dynamic scaling for long text
    if len(text) > 30 and width < 90 * mm:
        font_size = 8
    elif len(text) > 45:
        font_size = 7
        
    c.setFont(BRANDING["fonts"]["body"], font_size)
    c.setFillColor(colors.black)
    c.drawRightString(x + width, y, text)

def draw_header(c, title, width, height, margin_x, color=None):
    primary_color = color or colors.HexColor(BRANDING["branding_colors"]["primary"])
    c.setStrokeColor(primary_color)
    c.setFillColor(primary_color)
    c.rect(0, height - 40 * mm, width, 40 * mm, fill=1, stroke=0)
    
    c.setFillColor(colors.white)
    c.setFont(BRANDING["fonts"]["header"], 22)
    c.drawString(margin_x, height - 20 * mm, title.upper())
    c.setFont(BRANDING["fonts"]["body"], 10)
    c.drawString(margin_x, height - 26 * mm, BRANDING["office_name"])
    
    c.drawRightString(width - margin_x, height - 20 * mm, datetime.now().strftime("%B %d, %Y"))
    c.drawRightString(width - margin_x, height - 26 * mm, datetime.now().strftime("%I:%M %p"))
