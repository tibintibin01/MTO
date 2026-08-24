import os
from datetime import datetime, timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from backend.generators.base import (
    BRANDING, safe_text, safe_filename, fmt_currency
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _num_to_words(amount: float) -> str:
    """
    Converts a peso amount to words for the official receipt.
    e.g. 1911.40 → "ONE THOUSAND NINE HUNDRED ELEVEN PESOS AND 40/100"
    Uses a simple implementation — no external library needed.
    """
    ones = ["", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN",
            "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE", "THIRTEEN",
            "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN",
            "NINETEEN"]
    tens = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY",
            "SIXTY", "SEVENTY", "EIGHTY", "NINETY"]

    def _below_thousand(n: int) -> str:
        if n == 0:
            return ""
        elif n < 20:
            return ones[n]
        elif n < 100:
            return tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")
        else:
            rest = _below_thousand(n % 100)
            return ones[n // 100] + " HUNDRED" + (" " + rest if rest else "")

    try:
        pesos = int(amount)
        centavos = round((amount - pesos) * 100)
        if pesos == 0:
            peso_words = "ZERO"
        elif pesos < 1000:
            peso_words = _below_thousand(pesos)
        elif pesos < 1_000_000:
            t = pesos // 1000
            r = pesos % 1000
            peso_words = _below_thousand(t) + " THOUSAND"
            if r:
                peso_words += " " + _below_thousand(r)
        elif pesos < 1_000_000_000:
            m = pesos // 1_000_000
            r = pesos % 1_000_000
            peso_words = _below_thousand(m) + " MILLION"
            if r >= 1000:
                peso_words += " " + _below_thousand(r // 1000) + " THOUSAND"
                r = r % 1000
            if r:
                peso_words += " " + _below_thousand(r)
        else:
            return f"{amount:,.2f}"

        return f"{peso_words} PESOS AND {centavos:02d}/100"
    except Exception:
        return f"{amount:,.2f}"


def _draw_payment_record_header(c, width, height, margin_x):
    """
    Draws a clean official-document header.
    Left: Municipality of Dipaculao seal. Right: Bagong Pilipinas mark.
    The assets are transparent PNGs, so use mask='auto' to avoid white boxes.
    """
    primary = colors.HexColor(BRANDING["branding_colors"]["primary"])
    secondary = colors.HexColor(BRANDING["branding_colors"]["secondary"])
    accent = colors.HexColor(BRANDING["branding_colors"]["accent"])

    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    logo_path = os.path.join(root_dir, BRANDING.get("logo_path", ""))
    seal_path = os.path.join(root_dir, BRANDING.get("seal_path", ""))

    # White paper header with thin official rule lines.
    c.setFillColor(colors.white)
    c.rect(0, height - 50 * mm, width, 50 * mm, fill=1, stroke=0)
    c.setFillColor(primary)
    c.rect(0, height - 4 * mm, width, 4 * mm, fill=1, stroke=0)
    c.setStrokeColor(accent)
    c.setLineWidth(0.8)
    c.line(margin_x, height - 47 * mm, width - margin_x, height - 47 * mm)

    def _draw_png(path, x, y, w, h):
        if not os.path.exists(path):
            return
        try:
            c.drawImage(path, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    # Municipal seal and Bagong Pilipinas mark, both without background boxes.
    _draw_png(logo_path, margin_x, height - 39 * mm, 29 * mm, 29 * mm)
    _draw_png(seal_path, width - margin_x - 25 * mm, height - 35 * mm, 25 * mm, 25 * mm)

    centre_x = width / 2
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 7.5)
    c.drawCentredString(
        centre_x, height - 11 * mm,
        BRANDING.get("republic_header", "Republic of the Philippines")
    )
    c.setFont("Helvetica", 8)
    c.drawCentredString(centre_x, height - 16 * mm, BRANDING.get("province", ""))
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(centre_x, height - 21 * mm, BRANDING.get("municipality", ""))
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(primary)
    c.drawCentredString(
        centre_x, height - 26 * mm,
        BRANDING.get("office_name", "MUNICIPAL TREASURY OFFICE")
    )

    c.setStrokeColor(primary)
    c.setLineWidth(0.7)
    c.line(centre_x - 36 * mm, height - 29 * mm, centre_x + 36 * mm, height - 29 * mm)

    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(primary)
    c.drawCentredString(
        centre_x, height - 37 * mm, "REAL PROPERTY TAX PAYMENT RECORD"
    )
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(secondary)
    c.drawCentredString(
        centre_x, height - 42 * mm, "SYSTEM-GENERATED REFERENCE COPY"
    )

    now = datetime.now()
    c.setFillColor(secondary)
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(
        width - margin_x,
        height - 51 * mm,
        f"Generated on: {now.strftime('%B %d, %Y')}",
    )
    c.setFont("Helvetica", 8)
    c.drawRightString(width - margin_x, height - 56 * mm, now.strftime("%I:%M %p"))


def _draw_section_title(c, title, x, y, width):
    primary = colors.HexColor(BRANDING["branding_colors"]["primary"])
    c.setFillColor(primary)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(x, y, title.upper())
    c.setStrokeColor(primary)
    c.setLineWidth(0.6)
    c.line(x, y - 3 * mm, x + width, y - 3 * mm)


def _draw_wrapped_right(c, text, x_right, y, max_width, font="Helvetica", size=9):
    """
    Draws short wrapped values right-aligned. Keeps long owner names from
    spilling into the left-side labels.
    """
    text = safe_text(text)
    c.setFont(font, size)
    words = text.split()
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
    if not lines:
        lines = [""]
    for offset, line in enumerate(lines[:2]):
        c.drawRightString(x_right, y - (offset * 4.2 * mm), line)
    return len(lines[:2])


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_or_receipt(receipt_data, base_dir):
    receipts_dir = os.path.join(base_dir, "receipts")
    os.makedirs(receipts_dir, exist_ok=True)

    or_number = safe_text(receipt_data.get("or_number")) or "NO_OR_NUMBER"
    td_number = safe_text(receipt_data.get("td_number")) or "NO_TD"
    payment_id = safe_text(receipt_data.get("payment_id")) or "UNASSIGNED"
    file_name = (
        f"RPT_PAYMENT_RECORD_{safe_filename(payment_id)}_"
        f"{safe_filename(or_number)}_{safe_filename(td_number)}.pdf"
    )
    output_path = os.path.join(receipts_dir, file_name)
    working_path = output_path + ".tmp"

    c = canvas.Canvas(working_path, pagesize=A4)
    width, height = A4
    margin_x = 18 * mm

    # ── Watermark seal ────────────────────────────────────────────────────────
    # ── Header ────────────────────────────────────────────────────────────────
    _draw_payment_record_header(c, width, height, margin_x)

    current_y = height - 55 * mm
    c.setFillColor(colors.black)
    current_y -= 10 * mm

    # ── Receipt metadata box ──────────────────────────────────────────────────
    accent = colors.HexColor(BRANDING["branding_colors"]["accent"])
    box_h = 22 * mm
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.setStrokeColor(accent)
    c.setLineWidth(0.8)
    c.rect(margin_x, current_y - box_h, width - 2 * margin_x, box_h,
           fill=1, stroke=1)

    def _lbl(text, x, y):
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
        c.drawString(x, y, text.upper())

    def _val(text, x, y, align="left"):
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.black)
        if align == "right":
            c.drawRightString(x, y, safe_text(text))
        else:
            c.drawString(x, y, safe_text(text))

    col1_x = margin_x + 5 * mm
    col2_x = width / 2 + 5 * mm
    col_right = width - margin_x - 5 * mm

    row1_y = current_y - 7 * mm
    row2_y = current_y - 14 * mm

    _lbl("Source Official Receipt No.", col1_x, row1_y)
    _val(receipt_data.get("or_number"), col1_x + 50 * mm, row1_y)

    tax_year_label = (
        ", ".join(receipt_data.get("tax_years", []))
        if receipt_data.get("tax_years")
        else receipt_data.get("tax_year", "")
    )
    _lbl("Tax Year(s)", col2_x, row1_y)
    _val(tax_year_label, col_right, row1_y, align="right")

    _lbl("Date Paid", col1_x, row2_y)
    _val(receipt_data.get("date_paid"), col1_x + 22 * mm, row2_y)

    ao = safe_text(receipt_data.get("accountable_officer"))
    _lbl("Collecting Officer", col2_x, row2_y)
    _val(ao if ao else "Not recorded", col_right, row2_y, align="right")

    current_y -= box_h + 10 * mm

    # ── Property details ──────────────────────────────────────────────────────
    _draw_section_title(c, "Property Details", margin_x, current_y, width - 2 * margin_x)
    current_y -= 11 * mm

    def _field_row(label, value):
        nonlocal current_y
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
        c.drawString(margin_x, current_y, label.upper())
        c.setFont("Helvetica", 9.2)
        c.setFillColor(colors.black)
        lines = _draw_wrapped_right(
            c, value, width - margin_x, current_y,
            max_width=95 * mm, font="Helvetica", size=9.2
        )
        current_y -= (8 if lines == 1 else 12) * mm

    _field_row("TD Number",       receipt_data.get("td_number"))
    _field_row("Owner Name",      receipt_data.get("owner_name"))
    _field_row("Kind of Property",receipt_data.get("kind_of_property"))
    _field_row("Lot Number",      receipt_data.get("lot_number"))
    _field_row("Location",        receipt_data.get("location"))

    current_y -= 8 * mm

    # ── Payment breakdown ─────────────────────────────────────────────────────
    _draw_section_title(c, "Payment Breakdown", margin_x, current_y, width - 2 * margin_x)
    current_y -= 11 * mm

    c.setFillColor(colors.HexColor("#f1f5f9"))
    c.rect(margin_x, current_y - 5 * mm, width - 2 * margin_x, 9 * mm, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.black)
    c.drawString(margin_x, current_y, "Description")
    c.drawRightString(width - margin_x, current_y, "Amount")
    current_y -= 5 * mm
    c.setStrokeColor(colors.HexColor(BRANDING["branding_colors"]["accent"]))
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 8 * mm

    # Build line items
    line_items = receipt_data.get("line_items") or []
    if line_items:
        partial_mode = any(
            float(item.get("applied_amount", item.get("total_amount", 0)) or 0)
            < float(item.get("total_amount", 0) or 0)
            for item in line_items
        )
        entries = []
        for item in line_items:
            year = item.get("tax_year", "")
            if partial_mode:
                applied = float(item.get("applied_amount", 0) or 0)
                if applied <= 0:
                    continue
                entries.append((f"Applied Payment ({year})", fmt_currency(applied)))
            else:
                entries.extend([
                    (f"Assessed Value ({year})",
                     fmt_currency(item.get("assessed_value",
                                           receipt_data.get("assessed_value")))),
                    (f"Basic Tax 1% ({year})",
                     fmt_currency(item.get("basic_amount"))),
                    (f"SEF 1% ({year})",
                     fmt_currency(item.get("sef_amount"))),
                    (f"Penalty ({year})",
                     fmt_currency(item.get("penalty",
                                           receipt_data.get("penalty")))),
                ])
    else:
        assessed = float(receipt_data.get("assessed_value") or 0)
        entries = [
            ("Assessed Value",
             fmt_currency(assessed)),
            ("Basic Tax (1%)",
             fmt_currency(receipt_data.get("basic") or (assessed * 0.01))),
            ("SEF (1%)",
             fmt_currency(receipt_data.get("sef") or (assessed * 0.01))),
            ("Penalty",
             fmt_currency(receipt_data.get("penalty"))),
        ]

    discount = float(receipt_data.get("discount") or 0)
    if discount > 0:
        entries.append(("Discount", f"- {fmt_currency(discount)}"))

    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    for label, amount in entries:
        c.drawString(margin_x, current_y, label)
        c.drawRightString(width - margin_x, current_y, amount)
        current_y -= 8 * mm
        if current_y < 60 * mm:
            c.showPage()
            current_y = height - 25 * mm
            c.setFont("Helvetica", 10)
            c.setFillColor(colors.black)

    # Total line
    c.setStrokeColor(colors.HexColor(BRANDING["branding_colors"]["primary"]))
    c.setLineWidth(1.2)
    c.line(margin_x, current_y, width - margin_x, current_y)
    current_y -= 9 * mm
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.black)
    c.drawString(margin_x, current_y, "TOTAL AMOUNT PAID")
    total_paid = (receipt_data.get("total")
                  if receipt_data.get("total") is not None
                  else receipt_data.get("amount"))
    c.drawRightString(width - margin_x, current_y, f"PHP {fmt_currency(total_paid)}")

    # ── Amount in words ───────────────────────────────────────────────────────
    current_y -= 9 * mm
    try:
        amount_words = _num_to_words(float(total_paid or 0))
    except Exception:
        amount_words = ""
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawString(margin_x, current_y, "AMOUNT IN WORDS:")
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.black)
    c.drawString(margin_x + 32 * mm, current_y, amount_words)

    # ── Received from ─────────────────────────────────────────────────────────
    current_y -= 12 * mm
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.black)
    c.drawString(margin_x, current_y, "Received from:")
    c.setFont("Helvetica-Bold", 10)
    payor = safe_text(
        receipt_data.get("payor_name") or receipt_data.get("owner_name")
    )
    c.drawString(margin_x + 30 * mm, current_y, payor)

    # ── Reference-copy notice ─────────────────────────────────────────────────
    current_y -= 10 * mm
    notice_h = 20 * mm
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.setStrokeColor(colors.HexColor(BRANDING["branding_colors"]["accent"]))
    c.setLineWidth(0.7)
    c.roundRect(
        margin_x,
        current_y - notice_h,
        width - 2 * margin_x,
        notice_h,
        2 * mm,
        fill=1,
        stroke=1,
    )
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["primary"]))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(margin_x + 4 * mm, current_y - 6 * mm, "REFERENCE COPY ONLY")
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.setFont("Helvetica", 7.5)
    c.drawString(
        margin_x + 4 * mm,
        current_y - 11 * mm,
        "This document summarizes the payment recorded under the Source Official Receipt number shown above.",
    )
    c.drawString(
        margin_x + 4 * mm,
        current_y - 15.5 * mm,
        "It does not replace the original accountable receipt issued by the Municipal Treasurer's Office.",
    )

    # ── Footer ────────────────────────────────────────────────────────────────
    footer_y = 18 * mm
    c.setStrokeColor(colors.HexColor(BRANDING["branding_colors"]["accent"]))
    c.setLineWidth(0.5)
    c.line(margin_x, footer_y + 5 * mm, width - margin_x, footer_y + 5 * mm)

    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawCentredString(
        width / 2,
        footer_y,
        "Payment record generated electronically by the Municipal Revenue System.",
    )
    c.drawCentredString(
        width / 2, footer_y - 5 * mm,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"OR No.: {or_number} | TD No.: {td_number}"
    )

    c.save()
    os.replace(working_path, output_path)
    return output_path
