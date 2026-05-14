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
        "office_name": "MUNICIPAL REVENUE OFFICE",
        "branding_colors": {
            "primary": "#1f538d", 
            "secondary": "#7f8c8d", 
            "accent": "#d9e2f3", 
            "danger": "#c0392b", 
            "success": "#27ae60"
        },
        "fonts": {"header": "Helvetica-Bold", "body": "Helvetica"},
        "footer_text": "This document was generated electronically by the Municipal Revenue System."
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

def draw_field(c, label, value, x, y, width=80 * mm):
    c.setFont(BRANDING["fonts"]["header"], 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawString(x, y, label.upper())
    
    text = safe_text(value)
    # Even more dynamic scaling for very long text
    text_len = len(text)
    if text_len > 50:
        font_size = 6
    elif text_len > 35:
        font_size = 7
    elif text_len > 20:
        font_size = 8
    else:
        font_size = 9
        
    c.setFont(BRANDING["fonts"]["body"], font_size)
    c.setFillColor(colors.black)
    # Ensure value is drawn at the right boundary of the specified width
    c.drawRightString(x + width, y, text)

def draw_header(c, title, width, height, margin_x, color=None):
    primary_color = color or colors.HexColor(BRANDING["branding_colors"]["primary"])
    c.setStrokeColor(primary_color)
    c.setFillColor(primary_color)
    c.rect(0, height - 40 * mm, width, 40 * mm, fill=1, stroke=0)
    
    # Draw Logo if exists
    logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), BRANDING.get("logo_path", ""))
    logo_drawn = False
    if os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, margin_x, height - 35 * mm, width=25 * mm, height=25 * mm, mask='auto')
            logo_drawn = True
        except:
            pass

    text_offset = 30 * mm if logo_drawn else 0
    
    c.setFillColor(colors.white)
    c.setFont(BRANDING["fonts"]["header"], 18) # Reduced from 22
    c.drawString(margin_x + text_offset, height - 18 * mm, title.upper())
    c.setFont(BRANDING["fonts"]["body"], 10)
    c.drawString(margin_x + text_offset, height - 24 * mm, BRANDING["office_name"])
    
    c.setFont(BRANDING["fonts"]["header"], 9)
    c.drawRightString(width - margin_x, height - 18 * mm, datetime.now().strftime("%B %d, %Y"))
    c.setFont(BRANDING["fonts"]["body"], 9)
    c.drawRightString(width - margin_x, height - 24 * mm, datetime.now().strftime("%I:%M %p"))

def draw_seal(c, width, height):
    """Draws a faded background seal if configured."""
    seal_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), BRANDING.get("seal_path", ""))
    if os.path.exists(seal_path):
        try:
            c.saveState()
            c.setFillAlpha(0.05) # Very subtle watermark
            c.drawImage(seal_path, (width - 120 * mm) / 2, (height - 120 * mm) / 2, width=120 * mm, height=120 * mm, mask='auto')
            c.restoreState()
        except:
            pass
