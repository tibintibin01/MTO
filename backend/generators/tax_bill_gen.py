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


def _wrapped_lines(c, text, font_name, font_size, max_width):
    words = safe_text(text).split()
    if not words:
        return [""]

    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if c.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_numbered_note(c, number, text, x, y, width, text_color):
    font_name = "Helvetica"
    font_size = 7.2
    number_width = 7 * mm
    leading = 3.6 * mm
    lines = _wrapped_lines(
        c,
        text,
        font_name,
        font_size,
        width - number_width,
    )

    c.setFillColor(text_color)
    c.setFont(font_name, font_size)
    c.drawString(x, y, f"{number}.")
    line_y = y
    for line in lines:
        c.drawString(x + number_width, line_y, line)
        line_y -= leading
    return line_y - 0.8 * mm


def tax_bill_notes(tax_bill_data):
    """Return concise, legally conditional notes for a non-delinquency Tax Bill."""
    deadline_text = safe_text(tax_bill_data.get("discount_valid_until"))
    if deadline_text:
        try:
            deadline_text = date.fromisoformat(deadline_text).strftime("%B %d, %Y")
        except ValueError:
            pass

    if float(tax_bill_data.get("discount", 0) or 0) > 0 and deadline_text:
        payment_note = (
            f"The discounted amount shown is valid for payment through {deadline_text}; "
            "eligibility will be rechecked when payment is posted."
        )
    else:
        payment_note = (
            "The amount shown remains subject to payment-date verification, including "
            "any applicable discount or interest."
        )

    return [
        "Please report any error or omission in this Bill to the Municipal "
        "Treasurer's Office.",
        "Please present this Bill to the Municipal Treasurer's Office when making "
        "payment.",
        payment_note,
        "If these taxes remain unpaid after they become due and delinquent, the "
        "Municipality may use the collection remedies under Section 256 of "
        "Republic Act No. 7160.",
        "Please disregard this Bill if the taxes shown were already paid, subject "
        "to verification of the Official Receipt.",
        "Prior payment / Official Receipt details (if applicable): "
        "____________________.",
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
    secondary = colors.HexColor(BRANDING["branding_colors"]["secondary"])

    title = "REAL PROPERTY TAX BILL"
    _draw_header(c, title, width, height, margin_x)

    current_y = height - 64 * mm
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
        "Less Eligible Discount",
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
    c.drawString(margin_x, current_y - 3 * mm, "NOTES")
    notes_width = content_w - summary_w - 8 * mm
    note_y = current_y - 9 * mm
    for number, note in enumerate(tax_bill_notes(tax_bill_data), start=1):
        note_y = _draw_numbered_note(
            c, number, note, margin_x, note_y, notes_width, secondary
        )

    signature_x = summary_x
    signature_y = current_y - summary_h - 11 * mm
    c.setStrokeColor(colors.black)
    c.setFillColor(secondary)
    c.setFont("Helvetica", 8)
    c.drawString(signature_x, signature_y + 8 * mm, "Very truly yours,")
    c.line(signature_x, signature_y, signature_x + summary_w, signature_y)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 8)
    c.drawCentredString(
        signature_x + summary_w / 2,
        signature_y - 5 * mm,
        "Municipal Treasurer",
    )

    footer_y = 9 * mm
    c.setStrokeColor(accent)
    c.line(margin_x, footer_y + 5 * mm, width - margin_x, footer_y + 5 * mm)
    c.setFont("Helvetica", 7)
    c.setFillColor(secondary)
    c.drawCentredString(
        width / 2,
        footer_y,
        "This is a system-generated Tax Bill. Please present it when making payment.",
    )

    c.save()
    return output_path
