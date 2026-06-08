import os
from datetime import datetime, timezone

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
    danger = colors.HexColor(BRANDING["branding_colors"]["danger"])
    secondary = colors.HexColor(BRANDING["branding_colors"]["secondary"])
    accent = colors.HexColor(BRANDING["branding_colors"]["accent"])
    centre_x = width / 2

    c.setFillColor(colors.white)
    c.rect(0, height - 50 * mm, width, 50 * mm, fill=1, stroke=0)
    c.setFillColor(danger)
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
    c.setFillColor(danger)
    c.drawCentredString(centre_x, height - 38 * mm, title)

    now = datetime.now()
    c.setFillColor(secondary)
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(width - margin_x, height - 51 * mm, now.strftime("%B %d, %Y"))
    c.setFont("Helvetica", 8)
    c.drawRightString(width - margin_x, height - 56 * mm, now.strftime("%I:%M %p"))


def _section_title(c, title, x, y, w, color=None):
    color = color or colors.HexColor(BRANDING["branding_colors"]["primary"])
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(x, y, title.upper())
    c.setStrokeColor(color)
    c.setLineWidth(0.6)
    c.line(x, y - 3 * mm, x + w, y - 3 * mm)


def _wrap_text(c, text, x, y, max_width, font="Helvetica", size=9, leading=4.5 * mm):
    c.setFont(font, size)
    words = safe_text(text).split()
    lines = []
    current = ""
    for word in words:
        probe = f"{current} {word}".strip()
        if c.stringWidth(probe, font, size) <= max_width or not current:
            current = probe
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    for idx, line in enumerate(lines):
        c.drawString(x, y - idx * leading, line)
    return y - max(1, len(lines)) * leading


def _info_cell(c, label, value, x, y, width, value_size=9):
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
        if c.stringWidth(probe, font, value_size) <= width or not current:
            current = probe
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if not lines:
        lines = ["-"]

    max_lines = 2
    for idx, line in enumerate(lines[:max_lines]):
        c.drawString(x, y - (5 + idx * 4.2) * mm, line)


def _table_header(c, x, y, columns, color):
    c.setFillColor(color)
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


def generate_delinquency_notice(statement_data, base_dir):
    statements_dir = os.path.join(base_dir, "statements")
    os.makedirs(statements_dir, exist_ok=True)

    td_number = safe_text(statement_data.get("td_number")) or "NO_TD"
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_name = f"NOTICE_{safe_filename(td_number)}_{date_part}.pdf"
    output_path = os.path.join(statements_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin_x = 15 * mm
    content_w = width - 2 * margin_x
    danger = colors.HexColor(BRANDING["branding_colors"]["danger"])
    accent = colors.HexColor(BRANDING["branding_colors"]["accent"])

    _draw_header(c, "NOTICE OF DELINQUENCY", width, height, margin_x)

    current_y = height - 67 * mm
    c.setFillColor(colors.black)
    notice_text = (
        "This serves as formal notice that, based on the records of the Municipal Treasury Office, "
        "the real property account listed below has outstanding real property tax obligations. "
        "Please settle the stated balance promptly to avoid additional penalties and appropriate collection action."
    )
    current_y = _wrap_text(c, notice_text, margin_x, current_y, content_w, size=9.5)

    current_y -= 6 * mm
    box_h = 43 * mm
    c.setFillColor(colors.HexColor("#fff7f7"))
    c.setStrokeColor(colors.HexColor("#f3b3b3"))
    c.roundRect(margin_x, current_y - box_h, content_w, box_h, 2 * mm, fill=1, stroke=1)
    cell_gap = 8 * mm
    cell_w = (content_w - (10 * mm) - cell_gap) / 2
    left_x = margin_x + 5 * mm
    right_x = left_x + cell_w + cell_gap
    full_w = content_w - 10 * mm

    row_y = current_y - 8 * mm
    _info_cell(c, "TD Number", statement_data.get("td_number"), left_x, row_y, cell_w)
    _info_cell(c, "Total Balance", fmt_currency(statement_data.get("total_balance")), right_x, row_y, cell_w)
    row_y -= 13 * mm
    _info_cell(c, "Owner Name", statement_data.get("owner_name"), left_x, row_y, full_w, value_size=8.8)
    row_y -= 13 * mm
    _info_cell(c, "Location", statement_data.get("location"), left_x, row_y, cell_w)
    _info_cell(c, "Kind", statement_data.get("kind_of_property"), right_x, row_y, cell_w)

    current_y -= box_h + 12 * mm
    _section_title(c, "Delinquent Balance Details", margin_x, current_y, content_w, danger)
    current_y -= 11 * mm

    columns = [
        ("Year", 15 * mm), ("Assessed", 26 * mm), ("Basic", 22 * mm),
        ("SEF", 22 * mm), ("Penalty", 24 * mm), ("Due", 25 * mm),
        ("Paid", 22 * mm), ("Balance", 24 * mm),
    ]
    current_y = _table_header(c, margin_x, current_y, columns, danger)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.black)
    c.setStrokeColor(accent)

    delinquent_rows = [r for r in statement_data.get("billing_rows", []) if float(r.get("balance_amount", 0) or 0) > 0]
    for idx, row in enumerate(delinquent_rows):
        if current_y < 52 * mm:
            c.showPage()
            _draw_header(c, "NOTICE OF DELINQUENCY", width, height, margin_x)
            current_y = height - 65 * mm
            current_y = _table_header(c, margin_x, current_y, columns, danger)
            c.setFont("Helvetica", 7.5)
            c.setFillColor(colors.black)

        if idx % 2 == 0:
            c.setFillColor(colors.HexColor("#f8fafc"))
            c.rect(margin_x, current_y - 4.5 * mm, sum(w for _, w in columns), 7.5 * mm, fill=1, stroke=0)
            c.setFillColor(colors.black)

        values = [
            safe_text(row.get("tax_year")),
            fmt_currency(row.get("assessed_value")),
            fmt_currency(row.get("basic_amount")),
            fmt_currency(row.get("sef_amount")),
            fmt_currency(row.get("penalty")),
            fmt_currency(row.get("total_amount")),
            fmt_currency(row.get("amount_paid")),
            fmt_currency(row.get("balance_amount")),
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

    current_y -= 5 * mm
    c.setStrokeColor(danger)
    c.setLineWidth(1)
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 8 * mm
    c.setFillColor(danger)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin_x, current_y, "TOTAL DELINQUENT BALANCE")
    c.drawRightString(width - margin_x, current_y, f"PHP {fmt_currency(statement_data.get('total_balance'))}")

    current_y -= 16 * mm
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    current_y = _wrap_text(
        c,
        "Kindly present this notice when making payment at the Municipal Treasury Office. "
        "For questions or verification, please bring the latest tax declaration and official receipt records.",
        margin_x,
        current_y,
        content_w,
        size=9,
    )

    current_y -= 20 * mm
    sig_x = width - margin_x - 70 * mm
    c.setStrokeColor(colors.black)
    c.line(sig_x, current_y, width - margin_x, current_y)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(sig_x + 35 * mm, current_y + 2 * mm, safe_text(statement_data.get("accountable_officer")) or "")
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawCentredString(sig_x + 35 * mm, current_y - 5 * mm, "Municipal Treasurer / Authorized Representative")

    footer_y = 15 * mm
    c.setStrokeColor(accent)
    c.line(margin_x, footer_y + 5 * mm, width - margin_x, footer_y + 5 * mm)
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawCentredString(width / 2, footer_y, BRANDING["footer_text"])

    c.save()
    return output_path
