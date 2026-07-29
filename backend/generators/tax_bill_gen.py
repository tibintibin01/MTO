"""Generate a current-year or advance real property Tax Bill PDF."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from backend.generators.base import BRANDING, fmt_currency, safe_filename, safe_text
from backend.generators.computation_gen import (
    _draw_header,
    _draw_summary_line,
    _kv,
    _section_title,
    _table_header,
)


MONEY = Decimal("0.01")


def split_installments(amount) -> list[Decimal]:
    """Split an annual amount into four cent-exact installment amounts."""
    total = Decimal(str(amount or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)
    total_cents = int(total * 100)
    base_cents, remainder = divmod(total_cents, 4)
    return [
        (Decimal(base_cents + (1 if index < remainder else 0)) / 100).quantize(MONEY)
        for index in range(4)
    ]


def _draw_tax_row(c, x, y, columns, values, accent):
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.rect(
        x, y - 4.5 * mm, sum(width for _, width in columns), 8 * mm, fill=1, stroke=0
    )
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 7.8)
    cursor = x
    for index, value in enumerate(values):
        column_width = columns[index][1]
        if index == 0:
            c.drawString(cursor + 2 * mm, y, safe_text(value))
        else:
            c.drawRightString(cursor + column_width - 2 * mm, y, safe_text(value))
        cursor += column_width
    c.setStrokeColor(accent)
    c.line(x, y - 5 * mm, x + sum(width for _, width in columns), y - 5 * mm)


def generate_tax_bill(tax_bill_data, base_dir):
    """Create a non-delinquency Tax Bill for exactly one tax year."""
    output_dir = os.path.join(base_dir, "tax_bills")
    os.makedirs(output_dir, exist_ok=True)

    td_number = safe_text(tax_bill_data.get("td_number")) or "NO_TD"
    tax_year = int(tax_bill_data["tax_year"])
    is_advance = tax_bill_data.get("document_type") == "ADVANCE"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = "ADVANCE_TAX_BILL" if is_advance else "TAX_BILL"
    file_name = f"{prefix}_{safe_filename(td_number)}_{tax_year}_{timestamp}.pdf"
    output_path = os.path.join(output_dir, file_name)

    c = canvas.Canvas(output_path, pagesize=A4)
    c.setTitle(
        f"{'Advance ' if is_advance else ''}Real Property Tax Bill - {td_number} - {tax_year}"
    )
    width, height = A4
    margin_x = 15 * mm
    content_w = width - 2 * margin_x
    accent = colors.HexColor(BRANDING["branding_colors"]["accent"])
    primary = colors.HexColor(BRANDING["branding_colors"]["primary"])
    success = colors.HexColor(BRANDING["branding_colors"].get("success", "#059669"))
    secondary = colors.HexColor(BRANDING["branding_colors"]["secondary"])

    title = "REAL PROPERTY TAX BILL"
    _draw_header(c, title, width, height, margin_x)

    current_y = height - 64 * mm
    status_text = (
        f"TAX YEAR {tax_year} - ADVANCE COMPUTATION - NOT DELINQUENT"
        if is_advance
        else f"TAX YEAR {tax_year} - CURRENT TAX BILL"
    )
    c.setFillColor(colors.HexColor("#ecfdf5"))
    c.setStrokeColor(success)
    c.roundRect(
        margin_x, current_y - 11 * mm, content_w, 11 * mm, 2 * mm, fill=1, stroke=1
    )
    c.setFillColor(success)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(width / 2, current_y - 7 * mm, status_text)

    current_y -= 20 * mm
    _section_title(
        c, "Property and Taxpayer Information", margin_x, current_y, content_w
    )
    current_y -= 10 * mm

    box_h = 48 * mm
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.setStrokeColor(accent)
    c.roundRect(margin_x, current_y - box_h, content_w, box_h, 2 * mm, fill=1, stroke=1)
    gap = 8 * mm
    cell_w = (content_w - 10 * mm - gap) / 2
    left_x = margin_x + 5 * mm
    right_x = left_x + cell_w + gap
    full_w = content_w - 10 * mm
    row_y = current_y - 8 * mm
    _kv(c, "TD Number", tax_bill_data.get("td_number"), left_x, row_y, cell_w)
    _kv(c, "PIN", tax_bill_data.get("pin"), right_x, row_y, cell_w)
    row_y -= 12 * mm
    _kv(
        c,
        "Owner Name",
        tax_bill_data.get("owner_name"),
        left_x,
        row_y,
        full_w,
        value_size=8.8,
    )
    row_y -= 12 * mm
    _kv(c, "Location", tax_bill_data.get("location"), left_x, row_y, full_w)
    row_y -= 12 * mm
    _kv(
        c,
        "Kind of Property",
        tax_bill_data.get("kind_of_property"),
        left_x,
        row_y,
        cell_w,
    )
    _kv(c, "Assessment for Tax Year", tax_year, right_x, row_y, cell_w)

    current_y -= box_h + 11 * mm
    _section_title(c, "Tax Computation", margin_x, current_y, content_w)
    current_y -= 11 * mm
    columns = [
        ("Year", 18 * mm),
        ("Assessed", 31 * mm),
        ("Basic", 27 * mm),
        ("SEF", 27 * mm),
        ("Discount", 25 * mm),
        ("Paid", 25 * mm),
        ("Payable", 27 * mm),
    ]
    current_y = _table_header(c, margin_x, current_y, columns)
    _draw_tax_row(
        c,
        margin_x,
        current_y,
        columns,
        [
            tax_year,
            fmt_currency(tax_bill_data.get("assessed_value")),
            fmt_currency(tax_bill_data.get("basic_amount")),
            fmt_currency(tax_bill_data.get("sef_amount")),
            fmt_currency(tax_bill_data.get("discount")),
            fmt_currency(tax_bill_data.get("amount_paid")),
            fmt_currency(tax_bill_data.get("amount_payable")),
        ],
        accent,
    )

    current_y -= 15 * mm
    _section_title(c, "Quarterly Payment Guide", margin_x, current_y, content_w)
    current_y -= 10 * mm
    schedule_columns = [
        ("Installment", 42 * mm),
        ("Due Date", 52 * mm),
        ("Scheduled Amount", 48 * mm),
        ("Classification", 38 * mm),
    ]
    current_y = _table_header(c, margin_x, current_y, schedule_columns)
    scheduled_amounts = split_installments(
        tax_bill_data.get("annual_tax_after_discount")
    )
    due_dates = [
        date(tax_year, 3, 31),
        date(tax_year, 6, 30),
        date(tax_year, 9, 30),
        date(tax_year, 12, 31),
    ]
    for index, (amount, due_date) in enumerate(
        zip(scheduled_amounts, due_dates), start=1
    ):
        values = [
            f"Quarter {index}",
            due_date.strftime("%B %d, %Y"),
            fmt_currency(amount),
            "UPCOMING" if is_advance else "SCHEDULED",
        ]
        _draw_tax_row(c, margin_x, current_y, schedule_columns, values, accent)
        current_y -= 8 * mm

    current_y -= 8 * mm
    summary_w = 77 * mm
    summary_x = width - margin_x - summary_w
    summary_h = 33 * mm
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.setStrokeColor(accent)
    c.roundRect(
        summary_x, current_y - summary_h, summary_w, summary_h, 2 * mm, fill=1, stroke=1
    )
    sy = current_y - 8 * mm
    _draw_summary_line(
        c,
        "Annual Basic",
        tax_bill_data.get("basic_amount"),
        summary_x + 5 * mm,
        sy,
        summary_w - 10 * mm,
    )
    sy -= 6 * mm
    _draw_summary_line(
        c,
        "Annual SEF",
        tax_bill_data.get("sef_amount"),
        summary_x + 5 * mm,
        sy,
        summary_w - 10 * mm,
    )
    sy -= 6 * mm
    _draw_summary_line(
        c,
        "Less Discount",
        tax_bill_data.get("discount"),
        summary_x + 5 * mm,
        sy,
        summary_w - 10 * mm,
    )
    sy -= 8 * mm
    c.setStrokeColor(primary)
    c.line(summary_x + 5 * mm, sy + 3 * mm, summary_x + summary_w - 5 * mm, sy + 3 * mm)
    _draw_summary_line(
        c,
        "AMOUNT PAYABLE",
        tax_bill_data.get("amount_payable"),
        summary_x + 5 * mm,
        sy,
        summary_w - 10 * mm,
        bold=True,
    )

    c.setFillColor(primary)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin_x, current_y - 3 * mm, "IMPORTANT")
    c.setFillColor(secondary)
    c.setFont("Helvetica", 8)
    note_lines = [
        "This document is a Tax Bill, not a notice of delinquency.",
        f"The computation uses the assessment and tax policy recorded for {tax_year}.",
        "Amounts remain subject to verification when payment is posted.",
    ]
    if is_advance:
        note_lines.insert(1, f"Tax year {tax_year} begins on January 1, {tax_year}.")
    prior_balance = float(tax_bill_data.get("prior_balance", 0) or 0)
    if prior_balance > 0:
        note_lines.append(
            f"Prior-year outstanding balance detected: PHP {prior_balance:,.2f}."
        )
    line_y = current_y - 9 * mm
    for line in note_lines:
        c.drawString(margin_x, line_y, line)
        line_y -= 5 * mm

    signature_y = current_y - max(summary_h, 33 * mm) - 17 * mm
    prepared_x = margin_x
    approved_x = width / 2 + 12 * mm
    c.setStrokeColor(colors.black)
    c.line(prepared_x, signature_y, prepared_x + 65 * mm, signature_y)
    c.line(approved_x, signature_y, approved_x + 65 * mm, signature_y)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(
        prepared_x + 32.5 * mm,
        signature_y + 2 * mm,
        safe_text(tax_bill_data.get("prepared_by")),
    )
    c.setFont("Helvetica", 8)
    c.setFillColor(secondary)
    c.drawCentredString(prepared_x + 32.5 * mm, signature_y - 5 * mm, "Prepared by")
    c.drawCentredString(
        approved_x + 32.5 * mm, signature_y - 5 * mm, "Municipal Treasurer"
    )

    footer_y = 15 * mm
    c.setStrokeColor(accent)
    c.line(margin_x, footer_y + 5 * mm, width - margin_x, footer_y + 5 * mm)
    c.setFont("Helvetica", 7)
    c.setFillColor(secondary)
    c.drawCentredString(width / 2, footer_y, BRANDING["footer_text"])

    c.save()
    return output_path
