"""
report_gen.py
=============
PDF generators for management/COA-facing reports:
  - Receivables by Barangay
  - Assessment Roll (full-page tabular report)

Both follow the same ReportLab-based pattern used by soa_gen / computation_gen.
"""

import os
from datetime import datetime, timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from backend.generators.base import (
    BRANDING,
    safe_text,
    safe_filename,
    fmt_currency,
    draw_header,
    draw_seal,
)
from utils.assessment_roll_status import assessment_roll_duplicate_status

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_HEADER_FILL = colors.HexColor("#1F4E78")
_ALT_FILL = colors.HexColor("#EBF0F7")
_BORDER = colors.HexColor("#B0C4DE")
_TEXT_DARK = colors.black
_TEXT_GRAY = colors.HexColor("#555555")
_VERIFIED_DUPLICATE_FILL = colors.HexColor("#FEF3C7")
_VERIFIED_DUPLICATE_TEXT = colors.HexColor("#92400E")


def _fit_cell_text(c, value, max_width, font_name, font_size):
    """Shorten cell text so it cannot overlap the next PDF column."""
    text = str(value or "")
    if c.stringWidth(text, font_name, font_size) <= max_width:
        return text

    suffix = "..."
    suffix_width = c.stringWidth(suffix, font_name, font_size)
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        candidate_width = c.stringWidth(text[:middle], font_name, font_size)
        if candidate_width + suffix_width <= max_width:
            low = middle
        else:
            high = middle - 1
    return f"{text[:low].rstrip()}{suffix}"


def _draw_table_header_row(c, left_x, top_y, columns):
    """Draws a single styled header row for a tabular report section."""
    row_h = 7 * mm
    c.setFillColor(_HEADER_FILL)
    total_w = sum(w for _, w in columns)
    c.rect(left_x, top_y - row_h, total_w, row_h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 7.5)
    cx = left_x
    for label, w in columns:
        c.drawCentredString(cx + w / 2, top_y - 5 * mm, label.upper())
        cx += w
    return top_y - row_h


def _draw_data_row(
    c,
    left_x,
    top_y,
    columns,
    values,
    row_idx,
    fill_color=None,
    text_color=None,
    font_name="Helvetica",
):
    """Draws one data row; alternates fill colour for readability."""
    row_h = 6.5 * mm
    fill = fill_color or (_ALT_FILL if row_idx % 2 == 0 else colors.white)
    total_w = sum(w for _, w in columns)
    c.setFillColor(fill)
    c.rect(left_x, top_y - row_h, total_w, row_h, fill=1, stroke=0)
    # draw border
    c.setStrokeColor(_BORDER)
    c.setLineWidth(0.3)
    c.rect(left_x, top_y - row_h, total_w, row_h, fill=0, stroke=1)
    c.setFillColor(text_color or _TEXT_DARK)
    c.setFont(font_name, 7.5)
    cx = left_x
    for i, (_, w) in enumerate(columns):
        raw_val = str(values[i]) if i < len(values) else ""
        # right-align numeric-looking cells (columns > 0 that are not "Barangay"/"TD")
        try:
            _ = float(raw_val.replace(",", ""))
            c.drawRightString(cx + w - 1.5 * mm, top_y - 4.5 * mm, raw_val)
        except (ValueError, TypeError):
            val = _fit_cell_text(c, raw_val, w - 3 * mm, font_name, 7.5)
            c.drawString(cx + 1.5 * mm, top_y - 4.5 * mm, val)
        cx += w
    return top_y - row_h


def _draw_totals_row(c, left_x, top_y, columns, values):
    """Draws a bold totals/grand-total footer row."""
    row_h = 7 * mm
    total_w = sum(w for _, w in columns)
    c.setFillColor(colors.HexColor("#D0DCF0"))
    c.rect(left_x, top_y - row_h, total_w, row_h, fill=1, stroke=0)
    c.setStrokeColor(_HEADER_FILL)
    c.setLineWidth(0.5)
    c.rect(left_x, top_y - row_h, total_w, row_h, fill=0, stroke=1)
    c.setFillColor(_TEXT_DARK)
    c.setFont("Helvetica-Bold", 7.5)
    cx = left_x
    for i, (_, w) in enumerate(columns):
        val = str(values[i]) if i < len(values) else ""
        try:
            _ = float(str(val).replace(",", ""))
            c.drawRightString(cx + w - 1.5 * mm, top_y - 4.5 * mm, val)
        except (ValueError, TypeError):
            c.drawString(cx + 1.5 * mm, top_y - 4.5 * mm, val)
        cx += w
    return top_y - row_h


# ===========================================================================
# 1. RECEIVABLES BY BARANGAY — Portrait A4
# ===========================================================================


def generate_receivables_by_barangay_pdf(rows, year_label, base_dir):
    """
    Generate a PDF report for Receivables by Barangay.

    Parameters
    ----------
    rows : list of list/tuple
        Each row: [barangay, assessed, due, penalty, discount, collected, receivable]
    year_label : str
        Human-readable year string, e.g. "2025" or "All Years"
    base_dir : str
        Root directory of the project (used to resolve temp_docs/).

    Returns
    -------
    str  – absolute path to the generated PDF file.
    """
    out_dir = os.path.join(base_dir, "temp_docs")
    os.makedirs(out_dir, exist_ok=True)
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_name = f"Receivables_by_Barangay_{date_part}.pdf"
    output_path = os.path.join(out_dir, file_name)

    width, height = A4
    margin_x = 15 * mm
    c = canvas.Canvas(output_path, pagesize=A4)

    columns = [
        ("Barangay", 48 * mm),
        ("Assessed\nValue", 26 * mm),
        ("Total Due", 26 * mm),
        ("Penalty", 22 * mm),
        ("Discount", 22 * mm),
        ("Collected", 26 * mm),
        ("Total\nReceivable", 27 * mm),
    ]

    def new_page():
        draw_seal(c, width, height)
        draw_header(c, "RECEIVABLES BY BARANGAY", width, height, margin_x)
        # Sub-title
        sub_y = height - 47 * mm
        c.setFont("Helvetica", 9)
        c.setFillColor(_TEXT_GRAY)
        c.drawString(margin_x, sub_y, f"Report Year: {year_label}")
        generated = datetime.now(timezone.utc).strftime("%B %d, %Y — %I:%M %p UTC")
        c.drawRightString(width - margin_x, sub_y, f"Generated: {generated}")
        c.setStrokeColor(_BORDER)
        c.line(margin_x, sub_y - 2 * mm, width - margin_x, sub_y - 2 * mm)
        return sub_y - 10 * mm

    cur_y = new_page()
    cur_y = _draw_table_header_row(c, margin_x, cur_y, columns)

    grand_total = 0.0
    for i, row in enumerate(rows or []):
        if cur_y < 30 * mm:
            c.showPage()
            cur_y = new_page()
            cur_y = _draw_table_header_row(c, margin_x, cur_y, columns)

        values = [
            safe_text(row[0]),  # Barangay
            fmt_currency(row[1]),  # Assessed
            fmt_currency(row[2]),  # Due
            fmt_currency(row[3]),  # Penalty
            fmt_currency(row[4]),  # Discount
            fmt_currency(row[5]),  # Collected
            fmt_currency(row[6]),  # Receivable
        ]
        try:
            grand_total += float(row[6] or 0)
        except (TypeError, ValueError, IndexError):
            pass

        cur_y = _draw_data_row(c, margin_x, cur_y, columns, values, i)

    # Totals row
    if cur_y < 20 * mm:
        c.showPage()
        cur_y = new_page()
    blank_vals = ["GRAND TOTAL", "", "", "", "", "", fmt_currency(grand_total)]
    _draw_totals_row(c, margin_x, cur_y, columns, blank_vals)

    # Footer
    c.setFont("Helvetica", 7.5)
    c.setFillColor(_TEXT_GRAY)
    c.drawString(margin_x, 10 * mm, BRANDING.get("footer_text", ""))

    c.save()
    return output_path


# ===========================================================================
# 2. ASSESSMENT ROLL — Landscape A4 (wide table)
# ===========================================================================


def generate_assessment_roll_pdf(
    items, base_dir, barangay_filter=None, as_of_year=None
):
    """
    Generate a PDF for the Assessment Roll.

    Parameters
    ----------
    items : list of list/tuple
        Each item from the assessment roll; expected indices:
          0=id, 1=td, 2=owner, 4=lot, 6=loc, 7=kind, 9=av,
          18=pin, 19=blk, 20=prev, 21=eff, 22=brgy,
          23=verified duplicate TD
        OR dict with keys td_number, owner_name, barangay, kind_of_property,
           assessed_value, tax_year.
    base_dir : str
    barangay_filter : str or None

    Returns
    -------
    str  – absolute path to the generated PDF file.
    """
    out_dir = os.path.join(base_dir, "temp_docs")
    os.makedirs(out_dir, exist_ok=True)
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_name = f"Assessment_Roll_{date_part}.pdf"
    output_path = os.path.join(out_dir, file_name)

    width, height = landscape(A4)  # wider page for more columns
    margin_x = 12 * mm
    c = canvas.Canvas(output_path, pagesize=landscape(A4))

    columns = [
        ("TD NO.", 25 * mm),
        ("PIN", 28 * mm),
        ("LOT & BLK", 21 * mm),
        ("PROPERTY OWNER", 41 * mm),
        ("LOCATION", 25 * mm),
        ("CLASSIFICATION", 24 * mm),
        ("ASSESSED VALUE", 26 * mm),
        ("PREVIOUS TD", 24 * mm),
        ("EFFECTIVITY", 16 * mm),
        ("STATUS", 35 * mm),
    ]

    filter_label = (
        f"Barangay: {barangay_filter}" if barangay_filter else "All Barangays"
    )
    if as_of_year:
        filter_label += f" | Active As Of: {as_of_year}"

    def new_page():
        draw_seal(c, width, height)
        draw_header(c, "ASSESSMENT ROLL", width, height, margin_x)
        sub_y = height - 47 * mm
        c.setFont("Helvetica", 9)
        c.setFillColor(_TEXT_GRAY)
        c.drawString(margin_x, sub_y, filter_label)
        generated = datetime.now(timezone.utc).strftime("%B %d, %Y — %I:%M %p UTC")
        c.drawRightString(width - margin_x, sub_y, f"Generated: {generated}")
        legend_y = sub_y - 7 * mm
        c.setFillColor(_VERIFIED_DUPLICATE_FILL)
        c.rect(margin_x, legend_y - 2.5 * mm, 4 * mm, 4 * mm, fill=1, stroke=0)
        c.setFillColor(_VERIFIED_DUPLICATE_TEXT)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(
            margin_x + 6 * mm,
            legend_y - 1.3 * mm,
            "VERIFIED DUPLICATE = Assessor-authorized duplicate TD account",
        )
        c.setStrokeColor(_BORDER)
        c.line(margin_x, legend_y - 4 * mm, width - margin_x, legend_y - 4 * mm)
        return legend_y - 11 * mm

    cur_y = new_page()
    cur_y = _draw_table_header_row(c, margin_x, cur_y, columns)

    total_av = 0.0
    for i, item in enumerate(items or []):
        if cur_y < 25 * mm:
            c.showPage()
            cur_y = new_page()
            cur_y = _draw_table_header_row(c, margin_x, cur_y, columns)

        if isinstance(item, dict):
            td = safe_text(item.get("td_number"))
            pin = safe_text(item.get("pin", ""))
            lot = safe_text(item.get("lot_number", ""))
            block = safe_text(item.get("block_number", ""))
            lot_blk = f"{lot} / {block}" if lot and block else (lot or block)
            owner = safe_text(item.get("owner_name"))
            brgy = safe_text(item.get("barangay") or item.get("location", ""))
            kind = safe_text(item.get("kind_of_property"))
            av_raw = item.get("assessed_value", 0)
            prev = safe_text(item.get("prev_td_number", ""))
            eff = safe_text(item.get("effectivity_date") or item.get("tax_year", ""))
        else:
            # tuple/list from search_properties
            td = safe_text(item[1] if len(item) > 1 else "")
            pin = safe_text(item[18] if len(item) > 18 else "")
            lot = safe_text(item[4] if len(item) > 4 else "")
            block = safe_text(item[19] if len(item) > 19 else "")
            lot_blk = f"{lot} / {block}" if lot and block else (lot or block)
            owner = safe_text(item[2] if len(item) > 2 else "")
            brgy = safe_text(
                item[22]
                if len(item) > 22 and item[22]
                else (item[6] if len(item) > 6 else "")
            )
            kind = safe_text(item[7] if len(item) > 7 else "")
            av_raw = item[9] if len(item) > 9 else 0
            prev = safe_text(item[20] if len(item) > 20 else "")
            eff = safe_text(item[21] if len(item) > 21 else "")
        if eff and len(eff) >= 4:
            eff = eff[:4]
        duplicate_status = assessment_roll_duplicate_status(item)

        try:
            av_val = float(av_raw or 0)
            total_av += av_val
        except (TypeError, ValueError):
            av_val = 0.0

        values = [
            td,
            pin,
            lot_blk,
            owner,
            brgy,
            kind,
            fmt_currency(av_val),
            prev,
            eff,
            duplicate_status,
        ]
        cur_y = _draw_data_row(
            c,
            margin_x,
            cur_y,
            columns,
            values,
            i,
            fill_color=(_VERIFIED_DUPLICATE_FILL if duplicate_status else None),
            text_color=(_VERIFIED_DUPLICATE_TEXT if duplicate_status else None),
            font_name="Helvetica-Bold" if duplicate_status else "Helvetica",
        )

    # Grand total row
    if cur_y < 20 * mm:
        c.showPage()
        cur_y = new_page()
    blank = [
        "TOTAL ASSESSED VALUE",
        "",
        "",
        f"{len(items or [])} Records",
        "",
        "",
        fmt_currency(total_av),
        "",
        "",
        "",
    ]
    _draw_totals_row(c, margin_x, cur_y, columns, blank)

    # Footer
    c.setFont("Helvetica", 7.5)
    c.setFillColor(_TEXT_GRAY)
    c.drawString(margin_x, 8 * mm, BRANDING.get("footer_text", ""))

    c.save()
    return output_path
