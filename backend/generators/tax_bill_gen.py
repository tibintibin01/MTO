"""Generate a current-year or advance real property Tax Bill PDF."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone

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


def _display_date(value):
    text = safe_text(value) or date.today().isoformat()
    try:
        return date.fromisoformat(text).strftime("%B %d, %Y")
    except ValueError:
        return text


def tax_bill_lot_block_reference(tax_bill_data):
    """Return a concise taxpayer-facing Lot/Block property reference."""
    missing_values = {"", "-", "N/A", "NA", "NONE", "NULL"}
    lot_number = safe_text(tax_bill_data.get("lot_number")).strip()
    block_number = safe_text(tax_bill_data.get("block_number")).strip()
    references = []

    if lot_number.upper() not in missing_values:
        references.append(f"Lot {lot_number}")
    if block_number.upper() not in missing_values:
        references.append(f"Block {block_number}")

    return " / ".join(references) or "N/A"


def tax_bill_computation_basis(tax_bill_data):
    """Classify whether the bill computes a full or partially paid year."""
    amount_paid = float(tax_bill_data.get("amount_paid", 0) or 0)
    amount_payable = float(tax_bill_data.get("amount_payable", 0) or 0)
    return "PARTIAL" if amount_paid > 0.005 and amount_payable > 0.005 else "FULL"


def tax_bill_letter_text(tax_bill_data):
    """Return the formal taxpayer-facing introduction for the Tax Bill."""
    tax_year = int(tax_bill_data["tax_year"])
    report_date = _display_date(tax_bill_data.get("report_as_of_date"))
    gross_tax = float(tax_bill_data.get("basic_amount", 0) or 0) + float(
        tax_bill_data.get("sef_amount", 0) or 0
    )
    amount_payable = fmt_currency(tax_bill_data.get("amount_payable"))
    discount = float(tax_bill_data.get("discount", 0) or 0)

    amount_paid = float(tax_bill_data.get("amount_paid", 0) or 0)
    if discount > 0:
        discount_label = (
            safe_text(tax_bill_data.get("discount_label"))
            or "eligible payment discount"
        )
        if amount_paid > 0.005:
            payable_clause = (
                f"the amount payable after applying the {discount_label} and "
                "deducting the posted payment of "
                f"PHP {fmt_currency(amount_paid)} is PHP {amount_payable}"
            )
        else:
            payable_clause = (
                f"the amount payable after the {discount_label} is PHP "
                f"{amount_payable}"
            )
    elif amount_paid > 0.005:
        payable_clause = (
            "the amount payable after deducting the posted payment of "
            f"PHP {fmt_currency(amount_paid)} is PHP {amount_payable}"
        )
    else:
        payable_clause = f"the amount payable is PHP {amount_payable}"

    return (
        "This is to respectfully inform you that, based on the records of this "
        "Office, the real property tax for the property described below for Tax "
        f"Year {tax_year} has been computed at PHP {fmt_currency(gross_tax)}. As of "
        f"{report_date}, {payable_clause}, subject to verification when payment is "
        "posted."
    )


def tax_bill_notes(tax_bill_data):
    """Return concise, legally conditional notes for a non-delinquency Tax Bill."""
    deadline_text = (
        _display_date(tax_bill_data.get("discount_valid_until"))
        if tax_bill_data.get("discount_valid_until")
        else ""
    )

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


def _draw_tax_row(c, x, y, columns, values, accent, centered_columns=()):
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.rect(
        x, y - 4.5 * mm, sum(width for _, width in columns), 8 * mm, fill=1, stroke=0
    )
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 7.8)
    centered_columns = set(centered_columns)
    cursor = x
    for index, value in enumerate(values):
        column_width = columns[index][1]
        if index == 0:
            c.drawString(cursor + 2 * mm, y, safe_text(value))
        elif index in centered_columns:
            c.drawCentredString(cursor + column_width / 2, y, safe_text(value))
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
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(margin_x, current_y, "Dear Sir/Madam:")
    current_y -= 7 * mm

    letter_font = "Helvetica"
    letter_size = 9
    letter_leading = 5 * mm
    letter_lines = _wrapped_lines(
        c,
        tax_bill_letter_text(tax_bill_data),
        letter_font,
        letter_size,
        content_w,
    )
    c.setFont(letter_font, letter_size)
    for line in letter_lines:
        c.drawString(margin_x, current_y, line)
        current_y -= letter_leading
    current_y -= 4 * mm

    _section_title(
        c, "Property and Taxpayer Information", margin_x, current_y, content_w
    )
    current_y -= 10 * mm

    box_h = 50 * mm
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
    _kv(
        c,
        "Lot / Block No.",
        tax_bill_lot_block_reference(tax_bill_data),
        right_x,
        row_y,
        cell_w,
    )
    row_y -= 11 * mm
    _kv(
        c,
        "Owner Name",
        tax_bill_data.get("owner_name"),
        left_x,
        row_y,
        full_w,
        value_size=8.8,
    )
    row_y -= 11 * mm
    _kv(c, "Location", tax_bill_data.get("location"), left_x, row_y, full_w)
    row_y -= 11 * mm
    _kv(
        c,
        "Kind of Property",
        tax_bill_data.get("kind_of_property"),
        left_x,
        row_y,
        cell_w,
    )
    _kv(c, "Assessment for Tax Year", tax_year, right_x, row_y, cell_w)

    current_y -= box_h + 9 * mm
    _section_title(c, "Tax Computation", margin_x, current_y, content_w)
    current_y -= 11 * mm
    columns = [
        ("Year", 18 * mm),
        ("Assessed Value", 31 * mm),
        ("Basic", 27 * mm),
        ("SEF", 27 * mm),
        ("Discount", 25 * mm),
        ("Computation", 25 * mm),
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
            tax_bill_computation_basis(tax_bill_data),
            fmt_currency(tax_bill_data.get("amount_payable")),
        ],
        accent,
        centered_columns={5},
    )

    current_y -= 18 * mm
    summary_w = 77 * mm
    summary_x = width - margin_x - summary_w
    posted_payment = float(tax_bill_data.get("amount_paid", 0) or 0)
    summary_h = (39 if posted_payment > 0.005 else 33) * mm
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
    if posted_payment > 0.005:
        sy -= 6 * mm
        _draw_summary_line(
            c,
            "Less Posted Payment",
            posted_payment,
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
    signature_y = 24 * mm
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
