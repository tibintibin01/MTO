import calendar
import os
from datetime import date, datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from backend.generators.base import BRANDING, safe_text, safe_filename, fmt_currency


def _asset_path(key):
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root_dir, BRANDING.get(key, ""))


def _draw_png(c, path, x, y, w, h):
    if not os.path.exists(path):
        return
    try:
        c.drawImage(path, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")
    except Exception:
        pass


def _draw_header(c, title, width, height, margin_x):
    primary = colors.HexColor(BRANDING["branding_colors"]["primary"])
    secondary = colors.HexColor(BRANDING["branding_colors"]["secondary"])
    accent = colors.HexColor(BRANDING["branding_colors"]["accent"])
    centre_x = width / 2

    c.setFillColor(colors.white)
    c.rect(0, height - 50 * mm, width, 50 * mm, fill=1, stroke=0)
    c.setFillColor(primary)
    c.rect(0, height - 4 * mm, width, 4 * mm, fill=1, stroke=0)
    c.setStrokeColor(accent)
    c.setLineWidth(0.8)
    c.line(margin_x, height - 47 * mm, width - margin_x, height - 47 * mm)

    _draw_png(c, _asset_path("logo_path"), margin_x, height - 39 * mm, 29 * mm, 29 * mm)
    _draw_png(c, _asset_path("seal_path"), width - margin_x - 32 * mm, height - 40 * mm, 32 * mm, 32 * mm)

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 7.5)
    c.drawCentredString(centre_x, height - 11 * mm, BRANDING.get("republic_header", "Republic of the Philippines"))
    c.setFont("Helvetica", 8)
    c.drawCentredString(centre_x, height - 16 * mm, BRANDING.get("province", ""))
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(centre_x, height - 21 * mm, BRANDING.get("municipality", ""))
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(primary)
    c.drawCentredString(centre_x, height - 26 * mm, BRANDING.get("office_name", "MUNICIPAL TREASURY OFFICE"))
    c.setStrokeColor(primary)
    c.setLineWidth(0.7)
    c.line(centre_x - 38 * mm, height - 29 * mm, centre_x + 38 * mm, height - 29 * mm)

    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(primary)
    c.drawCentredString(centre_x, height - 38 * mm, title)

    now = datetime.now()
    c.setFillColor(secondary)
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(width - margin_x, height - 51 * mm, now.strftime("%B %d, %Y"))
    c.setFont("Helvetica", 8)
    c.drawRightString(width - margin_x, height - 56 * mm, now.strftime("%I:%M %p"))


def _section_title(c, title, x, y, w):
    primary = colors.HexColor(BRANDING["branding_colors"]["primary"])
    c.setFillColor(primary)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(x, y, title.upper())
    c.setStrokeColor(primary)
    c.setLineWidth(0.6)
    c.line(x, y - 3 * mm, x + w, y - 3 * mm)


def _kv(c, label, value, x, y, w, value_size=9):
    secondary = colors.HexColor(BRANDING["branding_colors"]["secondary"])
    c.setFillColor(secondary)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x, y, label.upper())

    text = safe_text(value) or "-"
    font = "Helvetica"
    c.setFillColor(colors.black)
    c.setFont(font, value_size)

    words = text.split()
    lines = []
    current = ""
    for word in words:
        probe = f"{current} {word}".strip()
        if c.stringWidth(probe, font, value_size) <= w or not current:
            current = probe
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if not lines:
        lines = ["-"]

    for idx, line in enumerate(lines[:2]):
        c.drawString(x, y - (5 + idx * 4.2) * mm, line)


def _table_header(c, x, y, columns):
    primary = colors.HexColor(BRANDING["branding_colors"]["primary"])
    c.setFillColor(primary)
    c.rect(x, y - 5 * mm, sum(w for _, w in columns), 8 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 7.5)
    cursor = x
    for idx, (label, w) in enumerate(columns):
        if idx == 0:
            c.drawString(cursor + 2 * mm, y, label)
        else:
            c.drawRightString(cursor + w - 2 * mm, y, label)
        cursor += w
    return y - 8 * mm


def _draw_summary_line(c, label, value, x, y, w, bold=False):
    c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
    c.setFillColor(colors.black)
    c.drawString(x, y, label)
    c.drawRightString(x + w, y, fmt_currency(value))


def generate_delinquency_computation(statement_data, base_dir):
    """
    Generates an official computation of delinquent real property taxes.
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
    margin_x = 15 * mm
    content_w = width - 2 * margin_x
    accent = colors.HexColor(BRANDING["branding_colors"]["accent"])
    primary = colors.HexColor(BRANDING["branding_colors"]["primary"])

    _draw_header(c, "COMPUTATION OF DELINQUENCIES", width, height, margin_x)

    current_y = height - 66 * mm
    _section_title(c, "Property and Taxpayer Information", margin_x, current_y, content_w)
    current_y -= 10 * mm

    box_h = 55 * mm
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.setStrokeColor(accent)
    c.roundRect(margin_x, current_y - box_h, content_w, box_h, 2 * mm, fill=1, stroke=1)
    cell_gap = 8 * mm
    cell_w = (content_w - (10 * mm) - cell_gap) / 2
    left_x = margin_x + 5 * mm
    right_x = left_x + cell_w + cell_gap
    full_w = content_w - 10 * mm
    row_y = current_y - 8 * mm
    _kv(c, "TD Number", statement_data.get("td_number"), left_x, row_y, cell_w)
    _kv(c, "Total Balance", fmt_currency(statement_data.get("total_balance")), right_x, row_y, cell_w)
    row_y -= 13 * mm
    _kv(c, "Owner Name", statement_data.get("owner_name"), left_x, row_y, full_w, value_size=8.8)
    row_y -= 13 * mm
    _kv(c, "Location", statement_data.get("location"), left_x, row_y, full_w)
    row_y -= 13 * mm
    _kv(c, "Kind of Property", statement_data.get("kind_of_property"), left_x, row_y, cell_w)
    _kv(c, "Assessed Value", fmt_currency(statement_data.get("assessed_value")), right_x, row_y, cell_w)

    current_y -= box_h + 12 * mm
    _section_title(c, "Tax Computation Details", margin_x, current_y, content_w)
    current_y -= 11 * mm

    columns = [
        ("Year", 18 * mm), ("Assessed", 30 * mm), ("Basic", 26 * mm),
        ("SEF", 26 * mm), ("Penalty", 28 * mm), ("Paid", 26 * mm),
        ("Balance", 26 * mm),
    ]
    current_y = _table_header(c, margin_x, current_y, columns)
    c.setFont("Helvetica", 7.8)
    c.setFillColor(colors.black)

    billing_rows = [r for r in statement_data.get("billing_rows", []) if float(r.get("balance_amount", 0) or 0) > 0]
    total_basic = 0.0
    total_sef = 0.0
    total_penalties = 0.0
    total_paid = 0.0
    total_balance = 0.0

    for idx, row in enumerate(billing_rows):
        if current_y < 58 * mm:
            c.showPage()
            _draw_header(c, "COMPUTATION OF DELINQUENCIES", width, height, margin_x)
            current_y = height - 65 * mm
            current_y = _table_header(c, margin_x, current_y, columns)
            c.setFont("Helvetica", 7.8)
            c.setFillColor(colors.black)

        assessed = float(row.get("assessed_value", 0) or 0)
        basic = float(row.get("basic_amount", 0) or 0)
        sef = float(row.get("sef_amount", 0) or 0)
        penalty = float(row.get("penalty", 0) or 0)
        paid = float(row.get("amount_paid", 0) or 0)
        balance = float(row.get("balance_amount", 0) or 0)

        total_basic += basic
        total_sef += sef
        total_penalties += penalty
        total_paid += paid
        total_balance += balance

        if idx % 2 == 0:
            c.setFillColor(colors.HexColor("#f8fafc"))
            c.rect(margin_x, current_y - 4.5 * mm, sum(w for _, w in columns), 7.5 * mm, fill=1, stroke=0)
            c.setFillColor(colors.black)

        values = [
            safe_text(row.get("tax_year")),
            fmt_currency(assessed),
            fmt_currency(basic),
            fmt_currency(sef),
            fmt_currency(penalty),
            fmt_currency(paid),
            fmt_currency(balance),
        ]
        cursor = margin_x
        for col_idx, value in enumerate(values):
            col_w = columns[col_idx][1]
            if col_idx == 0:
                c.drawString(cursor + 2 * mm, current_y, value)
            else:
                c.drawRightString(cursor + col_w - 2 * mm, current_y, value)
            cursor += col_w
        c.setStrokeColor(accent)
        c.line(margin_x, current_y - 5 * mm, margin_x + sum(w for _, w in columns), current_y - 5 * mm)
        current_y -= 7.5 * mm

    current_y -= 8 * mm
    if current_y < 70 * mm:
        c.showPage()
        _draw_header(c, "COMPUTATION OF DELINQUENCIES", width, height, margin_x)
        current_y = height - 70 * mm

    summary_w = 77 * mm
    summary_x = width - margin_x - summary_w
    summary_h = 40 * mm
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.setStrokeColor(accent)
    c.roundRect(summary_x, current_y - summary_h, summary_w, summary_h, 2 * mm, fill=1, stroke=1)
    sy = current_y - 8 * mm
    _draw_summary_line(c, "Total Basic", total_basic, summary_x + 5 * mm, sy, summary_w - 10 * mm)
    sy -= 6 * mm
    _draw_summary_line(c, "Total SEF", total_sef, summary_x + 5 * mm, sy, summary_w - 10 * mm)
    sy -= 6 * mm
    _draw_summary_line(c, "Total Penalties", total_penalties, summary_x + 5 * mm, sy, summary_w - 10 * mm)
    sy -= 6 * mm
    _draw_summary_line(c, "Total Paid", total_paid, summary_x + 5 * mm, sy, summary_w - 10 * mm)
    sy -= 8 * mm
    c.setStrokeColor(primary)
    c.line(summary_x + 5 * mm, sy + 3 * mm, summary_x + summary_w - 5 * mm, sy + 3 * mm)
    _draw_summary_line(c, "BALANCE DUE", total_balance, summary_x + 5 * mm, sy, summary_w - 10 * mm, bold=True)

    today = datetime.now(timezone.utc).date()
    last_day = calendar.monthrange(today.year, today.month)[1]
    valid_until = date(today.year, today.month, last_day).strftime("%B %d, %Y")

    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["danger"]))
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(margin_x, current_y - 8 * mm, f"Note: This computation is valid only until {valid_until}.")
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.setFont("Helvetica", 8)
    c.drawString(margin_x, current_y - 15 * mm, "Amounts are subject to verification upon actual payment posting.")

    current_y -= 58 * mm
    prepared_x = margin_x
    approved_x = width / 2 + 12 * mm
    c.setStrokeColor(colors.black)
    c.line(prepared_x, current_y, prepared_x + 65 * mm, current_y)
    c.line(approved_x, current_y, approved_x + 65 * mm, current_y)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(prepared_x + 32.5 * mm, current_y + 2 * mm, safe_text(statement_data.get("accountable_officer")) or "")
    c.drawCentredString(approved_x + 32.5 * mm, current_y + 2 * mm, "")
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawCentredString(prepared_x + 32.5 * mm, current_y - 5 * mm, "Prepared by")
    c.drawCentredString(approved_x + 32.5 * mm, current_y - 5 * mm, "Municipal Treasurer")

    footer_y = 15 * mm
    c.setStrokeColor(accent)
    c.line(margin_x, footer_y + 5 * mm, width - margin_x, footer_y + 5 * mm)
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawCentredString(width / 2, footer_y, BRANDING["footer_text"])

    c.save()
    return output_path
