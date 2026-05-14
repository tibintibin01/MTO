import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from backend.generators.base import (
    BRANDING, safe_text, safe_filename, fmt_currency, draw_field, draw_header, draw_seal
)

def _draw_soa_table_header(c, left_x, top_y, columns):
    table_width = sum(item[1] for item in columns)
    c.setStrokeColor(colors.HexColor("#b7c9e2"))
    c.setFillColor(colors.HexColor("#d9e2f3"))
    c.rect(left_x, top_y - 7 * mm, table_width, 8 * mm, fill=1, stroke=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8)
    current_x = left_x
    for index, (label, width) in enumerate(columns):
        if index == 0:
            c.drawString(current_x + 2 * mm, top_y - 4.5 * mm, label)
        else:
            c.drawRightString(current_x + width - 2 * mm, top_y - 4.5 * mm, label)
        current_x += width
    return top_y - 10 * mm

def _draw_soa_page(c, statement_data, width, height, margin_x):
    draw_seal(c, width, height)
    draw_header(c, "STATEMENT OF ACCOUNT", width, height, margin_x)

    current_y = height - 55 * mm
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_x, current_y, "MTO Property Tax Account Summary")
    current_y -= 7 * mm
    c.setFont("Helvetica", 9)
    c.drawString(margin_x, current_y, "Printable breakdown of outstanding balances by tax year")

    current_y -= 14 * mm
    c.setStrokeColor(colors.HexColor("#d9e2f3"))
    c.rect(margin_x, current_y - 26 * mm, width - (2 * margin_x), 28 * mm, fill=0, stroke=1)
    draw_field(c, "TD Number", statement_data.get("td_number"), margin_x + 4 * mm, current_y - 5 * mm)
    draw_field(c, "Owner Name", statement_data.get("owner_name"), margin_x + 4 * mm, current_y - 12 * mm)
    draw_field(c, "Payor", statement_data.get("payor_name"), margin_x + 4 * mm, current_y - 19 * mm)
    draw_field(c, "Location", statement_data.get("location"), width / 2, current_y - 5 * mm, width=55 * mm)
    draw_field(c, "Kind of Property", statement_data.get("kind_of_property"), width / 2, current_y - 12 * mm, width=55 * mm)
    draw_field(c, "Accountable Officer", statement_data.get("accountable_officer"), width / 2, current_y - 19 * mm, width=55 * mm)

    current_y -= 36 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_x, current_y, "Outstanding Balance by Tax Year")
    current_y -= 6 * mm
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 8 * mm

    columns = [
        ("Year", 16 * mm), ("Assessed", 29 * mm), ("Basic", 21 * mm),
        ("SEF", 21 * mm), ("Penalty", 21 * mm), ("Total", 23 * mm),
        ("Paid", 21 * mm), ("Balance", 24 * mm),
    ]
    table_width = sum(item[1] for item in columns)

    current_y = _draw_soa_table_header(c, margin_x, current_y, columns)
    c.setFont("Helvetica", 8)
    c.setStrokeColor(colors.HexColor("#d9e2f3"))

    for row in statement_data.get("billing_rows", []):
        if current_y < 35 * mm:
            c.showPage()
            current_y = height - 55 * mm
            current_y = _draw_soa_table_header(c, margin_x, current_y, columns)
            c.setFont("Helvetica", 8)
            c.setStrokeColor(colors.HexColor("#d9e2f3"))

        row_top = current_y + 2.5 * mm
        c.rect(margin_x, row_top - 7 * mm, table_width, 8 * mm, fill=0, stroke=1)

        current_x = margin_x
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
        for index, value in enumerate(values):
            width_value = columns[index][1]
            if index > 0:
                c.line(current_x, row_top - 7 * mm, current_x, row_top + 1 * mm)
            if index == 0:
                c.drawString(current_x + 2 * mm, current_y, value)
            else:
                c.drawRightString(current_x + width_value - 2 * mm, current_y, value)
            current_x += width_value
        current_y -= 8 * mm

    current_y -= 8 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin_x, current_y, "Grand Total Due")
    c.drawRightString(width - margin_x, current_y, fmt_currency(statement_data.get("grand_total")))

    current_y -= 16 * mm
    c.setFont(BRANDING["fonts"]["body"], 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawString(margin_x, current_y, BRANDING["footer_text"])

def generate_statement_of_account(statement_data, base_dir):
    statements_dir = os.path.join(base_dir, "statements")
    os.makedirs(statements_dir, exist_ok=True)
    td_number = safe_text(statement_data.get("td_number")) or "NO_TD"
    date_part = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"SOA_{safe_filename(td_number)}_{date_part}.pdf"
    output_path = os.path.join(statements_dir, file_name)
    c = canvas.Canvas(output_path, pagesize=A4)
    _draw_soa_page(c, statement_data, A4[0], A4[1], 15 * mm)
    c.save()
    return output_path

def bulk_generate_soa(data_list, base_dir, filename_prefix="BULK_SOA"):
    statements_dir = os.path.join(base_dir, "statements")
    os.makedirs(statements_dir, exist_ok=True)
    date_part = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{filename_prefix}_{date_part}.pdf"
    output_path = os.path.join(statements_dir, file_name)
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    for index, statement_data in enumerate(data_list):
        if index > 0: c.showPage()
        _draw_soa_page(c, statement_data, width, height, 15 * mm)
    c.save()
    return output_path
