import base64
import html
import os
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from backend.generators.base import BRANDING, safe_text, safe_filename, fmt_currency

MUNICIPAL_TREASURER_NAME = "MARIA ELENA P. CHAVEZ"


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
    c.drawCentredString(sig_x + 35 * mm, current_y + 2 * mm, MUNICIPAL_TREASURER_NAME)
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawCentredString(sig_x + 35 * mm, current_y - 5 * mm, "Municipal Treasurer")

    footer_y = 15 * mm
    c.setStrokeColor(accent)
    c.line(margin_x, footer_y + 5 * mm, width - margin_x, footer_y + 5 * mm)
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor(BRANDING["branding_colors"]["secondary"]))
    c.drawCentredString(width / 2, footer_y, BRANDING["footer_text"])

    c.save()
    return output_path


_ONES = (
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _whole_number_words(value):
    value = int(value)
    if value < 20:
        return _ONES[value]
    if value < 100:
        return f"{_TENS[value // 10]} {_ONES[value % 10]}".strip()
    if value < 1000:
        return f"{_ONES[value // 100]} Hundred {_whole_number_words(value % 100)}".strip()
    for divisor, label in ((1_000_000_000, "Billion"), (1_000_000, "Million"), (1000, "Thousand")):
        if value >= divisor:
            lead, remainder = divmod(value, divisor)
            return f"{_whole_number_words(lead)} {label} {_whole_number_words(remainder)}".strip()
    return ""


def _peso_words(value):
    amount = max(0.0, float(value or 0))
    whole = int(amount)
    centavos = int(round((amount - whole) * 100))
    if centavos == 100:
        whole += 1
        centavos = 0
    words = _whole_number_words(whole) or "Zero"
    return f"{words} Pesos and {centavos:02d}/100 Only"


def _asset_data_uri(key):
    path = _asset_path(key)
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    extension = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    media_type = "jpeg" if extension in ("jpg", "jpeg") else extension
    return f"data:image/{media_type};base64,{encoded}"


def _html_text(value, fallback="N/A"):
    text = safe_text(value).strip()
    return html.escape(text if text else fallback)


def _html_upper(value, fallback="N/A"):
    text = safe_text(value).strip()
    return html.escape((text if text else fallback).upper())


def _municipal_address(value):
    """Return a consistent full municipal address from a barangay value."""
    barangay = " ".join(safe_text(value).strip().upper().split())
    barangay = barangay.split(",", 1)[0].strip()
    for prefix in ("BARANGAY ", "BRGY. ", "BRGY "):
        if barangay.startswith(prefix):
            barangay = barangay[len(prefix):].strip()
            break
    if not barangay or barangay in {"N/A", "NONE", "NULL"}:
        return "DIPACULAO, AURORA"
    return f"BRGY. {barangay}, DIPACULAO, AURORA"


def _notice_date(value):
    if not value:
        return "N/A"
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y")
    text = safe_text(value).strip()
    try:
        return datetime.fromisoformat(text[:10]).strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return text or "N/A"


def generate_delinquency_notice_preview(statement_data, base_dir):
    """Create a self-contained Folio print preview using authoritative billing rows."""
    statements_dir = os.path.join(base_dir, "statements")
    os.makedirs(statements_dir, exist_ok=True)

    td_number = safe_text(statement_data.get("td_number")).strip() or "NO_TD"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(
        statements_dir,
        f"NOTICE_PREVIEW_{safe_filename(td_number)}_{timestamp}.html",
    )

    delinquent_rows = [
        row for row in statement_data.get("billing_rows", [])
        if float(row.get("balance_amount", 0) or 0) > 0.005
    ]
    delinquent_rows.sort(key=lambda row: str(row.get("tax_year") or ""))
    total_balance = sum(float(row.get("balance_amount", 0) or 0) for row in delinquent_rows)
    first_year = delinquent_rows[0].get("tax_year") if delinquent_rows else "N/A"
    last_year = delinquent_rows[-1].get("tax_year") if delinquent_rows else "N/A"
    year_range = str(first_year) if first_year == last_year else f"{first_year} to {last_year}"

    table_rows = []
    for row in delinquent_rows:
        table_rows.append(
            "<tr>"
            f"<td>{fmt_currency(row.get('assessed_value'))}</td>"
            f"<td>{_html_text(row.get('tax_year'))}</td>"
            "<td>FULL</td>"
            f"<td>{fmt_currency(row.get('basic_amount'))}</td>"
            f"<td>{fmt_currency(row.get('sef_amount'))}</td>"
            f"<td class=\"penalty\">+ {fmt_currency(row.get('penalty'))}</td>"
            f"<td class=\"due\">{fmt_currency(row.get('balance_amount'))}</td>"
            "</tr>"
        )
    if not table_rows:
        table_rows.append('<tr><td colspan="7" class="empty">No outstanding billing rows found.</td></tr>')

    prepared_by = _html_upper(
        statement_data.get("prepared_by"),
        "AUTHORIZED MTO PERSONNEL",
    )
    owner_name = _html_upper(statement_data.get("owner_name"))
    property_address = _html_text(
        _municipal_address(
            statement_data.get("barangay") or statement_data.get("location")
        )
    )
    last_payment = _html_upper(_notice_date(statement_data.get("last_payment_date")))
    last_or = _html_upper(statement_data.get("last_or_number"))
    if last_payment == "N/A" and last_or == "N/A":
        last_payment_summary = "NO PAYMENT ON RECORD"
    else:
        last_payment_summary = f"{last_payment} / OR NO. {last_or}"
    accountable = _html_upper(
        statement_data.get("accountable_officer"),
        "MUNICIPAL TREASURER",
    )
    current_assessed = float(statement_data.get("assessed_value", 0) or 0)
    logo_uri = _asset_data_uri("logo_path")
    seal_uri = _asset_data_uri("seal_path")
    today = datetime.now().strftime("%b %d, %Y").upper()

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Notice of RPT Delinquency - {_html_text(td_number)}</title>
<style>
  :root {{ color-scheme: light; --ink:#111827; --line:#111827; --muted:#475569; --blue:#1d4f7a; --red:#c62828; }}
  * {{ box-sizing:border-box; }}
  html, body {{ margin:0; min-height:100%; font-family:Arial, Helvetica, sans-serif; color:var(--ink); background:#e9eef5; }}
  .toolbar {{ height:46px; display:flex; align-items:center; justify-content:space-between; gap:18px; padding:0 24px; background:#f8fafc; border-bottom:1px solid #cbd5e1; position:sticky; top:0; z-index:20; }}
  .toolbar-note {{ font-size:12px; color:#475569; }}
  .toolbar-actions {{ display:flex; gap:10px; }}
  button {{ border:0; border-radius:4px; padding:9px 18px; font-weight:700; cursor:pointer; font-size:12px; }}
  .save {{ background:#e8eef6; color:#18324d; }}
  .print {{ background:#2563eb; color:white; }}
  .preview {{ padding:8px 24px 32px; overflow:auto; }}
  .sheet {{ width:8.5in; min-height:13in; margin:0 auto; background:#fff; padding:.38in .46in .34in; box-shadow:0 10px 28px rgba(15,23,42,.18); font-size:10.5px; line-height:1.38; display:flex; flex-direction:column; }}
  .letterhead {{ display:grid; grid-template-columns:1.12in 1fr 1.12in; align-items:center; min-height:1in; }}
  .letterhead img {{ width:.86in; height:.86in; object-fit:contain; justify-self:center; }}
  .gov {{ text-align:center; font-weight:700; font-size:9.3px; line-height:1.2; text-transform:uppercase; }}
  .office-script {{ display:block; margin-top:7px; color:#164d8c; font-family:Georgia, 'Times New Roman', serif; font-style:italic; font-size:18px; text-transform:none; }}
  .double-rule {{ border-top:3px double #222; margin:6px 0 11px; }}
  h1 {{ margin:0 0 13px; text-align:center; font-size:15px; letter-spacing:.1px; }}
  .date-row {{ display:flex; justify-content:flex-end; align-items:flex-end; gap:10px; margin-bottom:10px; }}
  .date-line {{ width:1.55in; border-bottom:1px solid #111; padding:0 5px 3px; text-align:center; }}
  .identity {{ display:grid; grid-template-columns:.76in 1fr; gap:7px 10px; margin-bottom:11px; }}
  .fill-line {{ border-bottom:1px solid #111; min-height:19px; padding:0 5px 3px; font-weight:700; text-transform:uppercase; }}
  .fill-line.address {{ font-weight:400; }}
  .salutation {{ font-weight:700; margin:11px 0 7px; }}
  .legal {{ margin:0 0 11px; text-align:justify; }}
  .property-grid {{ display:grid; grid-template-columns:1fr 1fr; column-gap:30px; margin:7px 0 11px; }}
  .detail {{ display:grid; grid-template-columns:.96in 1fr; align-items:end; min-height:25px; }}
  .detail strong {{ font-size:9px; }}
  .detail span {{ border-bottom:1px solid #111; padding:0 5px 3px; min-height:18px; text-transform:uppercase; }}
  .summary-sentence {{ margin:11px 0 8px; }}
  .summary-sentence b {{ color:var(--red); }}
  table {{ width:100%; border-collapse:collapse; table-layout:fixed; font-size:8.8px; }}
  th, td {{ border:1px solid #111; padding:6px 4px; text-align:right; vertical-align:middle; }}
  th {{ text-align:center; font-weight:700; background:#f8fafc; text-transform:uppercase; }}
  th:nth-child(1), td:nth-child(1) {{ width:18%; }}
  th:nth-child(2), td:nth-child(2) {{ width:10%; text-align:center; }}
  th:nth-child(3), td:nth-child(3) {{ width:9%; text-align:center; }}
  .penalty {{ color:var(--red); }}
  .due {{ font-weight:700; }}
  .empty {{ text-align:center; padding:12px; color:#64748b; }}
  .total-row td {{ font-weight:700; background:#f3f4f6; }}
  .total-row td:first-child {{ text-align:center; }}
  .total-row .amount {{ color:var(--red); font-size:10.5px; }}
  .body-note {{ margin:10px 0 0; text-align:justify; font-size:9px; }}
  .amount-words {{ text-align:center; font-weight:700; font-style:italic; text-decoration:underline; margin:8px 0; font-size:9.5px; }}
  .warning {{ text-align:center; font-size:9px; margin-top:8px; }}
  .signature-space {{ flex:1 1 auto; min-height:1.7in; max-height:2.25in; display:flex; align-items:flex-end; }}
  .signatures {{ width:100%; display:grid; grid-template-columns:1fr 1fr; gap:.72in; text-align:center; }}
  .signature-label {{ text-align:left; margin-bottom:22px; }}
  .signature-name {{ border-bottom:1px solid #111; font-weight:700; min-height:18px; text-transform:uppercase; }}
  .signature-title {{ font-size:7.8px; margin-top:3px; text-transform:uppercase; }}
  .service-rule {{ border-top:1px solid #9ca3af; margin-top:8px; }}
  .service {{ display:grid; grid-template-columns:1.35fr .9fr; gap:14px; padding-top:8px; }}
  .ack-title, .service-title {{ font-weight:700; font-size:8px; margin-bottom:6px; }}
  .ack-line {{ display:grid; grid-template-columns:1.02in 1fr; margin:4px 0; }}
  .ack-line span:last-child {{ border-bottom:1px solid #111; min-height:14px; }}
  .service-box {{ border:1px solid #111; padding:8px; min-height:.82in; }}
  .check {{ display:inline-block; width:11px; height:11px; border:1px solid #111; vertical-align:-1px; margin:0 4px 0 8px; }}
  .reason {{ margin-top:12px; border-bottom:1px solid #111; min-height:15px; }}
  @page {{ size:8.5in 13in; margin:0; }}
  @media print {{
    html, body {{ background:white; }}
    .toolbar {{ display:none !important; }}
    .preview {{ padding:0; overflow:visible; }}
    .sheet {{ margin:0; width:8.5in; height:13in; min-height:13in; box-shadow:none; page-break-after:always; }}
  }}
</style>
</head>
<body>
  <div class="toolbar">
    <div class="toolbar-note">Print Preview: set paper size to <b>8.5 x 13</b> or <b>Folio</b>, with Portrait orientation.</div>
    <div class="toolbar-actions">
      <button class="save" onclick="window.print()">Save PDF</button>
      <button class="print" onclick="window.print()">Print Document</button>
    </div>
  </div>
  <main class="preview">
    <article class="sheet">
      <header class="letterhead">
        <img src="{logo_uri}" alt="Municipality of Dipaculao seal">
        <div class="gov">
          Republic of the Philippines<br>
          Province of Aurora<br>
          Municipality of Dipaculao<br>
          o0o
          <span class="office-script">Office of the Municipal Treasurer</span>
        </div>
        <img src="{seal_uri}" alt="Bagong Pilipinas seal">
      </header>
      <div class="double-rule"></div>
      <h1>NOTICE OF REAL PROPERTY TAX DELINQUENCY</h1>
      <div class="date-row"><b>Date:</b><span class="date-line">{today}</span></div>
      <section class="identity">
        <b>Name:</b><span class="fill-line">{owner_name}</span>
        <b>Address:</b><span class="fill-line address">{property_address}</span>
      </section>
      <div class="salutation">Dear Sir / Madam:</div>
      <p class="legal">In compliance with the requirement of Sec. 254, R.A. 7160 (Local Government Code of 1991), you are hereby informed of the tax delinquency on your property described as follows:</p>
      <section class="property-grid">
        <div>
          <div class="detail"><strong>Classification:</strong><span>{_html_upper(statement_data.get('kind_of_property'))}</span></div>
          <div class="detail"><strong>TDN:</strong><span>{_html_upper(td_number)}</span></div>
          <div class="detail"><strong>Location:</strong><span>{property_address}</span></div>
          <div class="detail"><strong>Assessed Value:</strong><span>PHP {fmt_currency(current_assessed)}</span></div>
          <div class="detail"><strong>Last Payment:</strong><span>{last_payment_summary}</span></div>
          <div class="detail"><strong>Collector:</strong><span>{accountable}</span></div>
        </div>
        <div>
          <div class="detail"><strong>Lot No.:</strong><span>{_html_upper(statement_data.get('lot_number'))}</span></div>
          <div class="detail"><strong>Block No.:</strong><span>{_html_upper(statement_data.get('block_number'))}</span></div>
          <div class="detail"><strong>TCT No.:</strong><span>N/A</span></div>
          <div class="detail"><strong>Area:</strong><span>{_html_upper(statement_data.get('area'), '0 SQM')}</span></div>
          <div class="detail"><strong>Date:</strong><span>{last_payment}</span></div>
          <div class="detail"><strong>OR No.:</strong><span>{last_or}</span></div>
        </div>
      </section>
      <p class="summary-sentence">For the year(s) <b>{year_range}</b>, the total outstanding amount is <b>PHP {fmt_currency(total_balance)}</b>, including applicable penalties and less posted payments and discounts, computed as follows:</p>
      <table aria-label="Delinquent real property tax computation">
        <thead><tr><th>Assessed Value</th><th>Tax Year</th><th>QTR</th><th>Basic Tax</th><th>SEF Tax</th><th>Penalty</th><th>Total Tax Due</th></tr></thead>
        <tbody>{''.join(table_rows)}
          <tr class="total-row"><td colspan="6">COMPUTATION AS OF {today.upper()}</td><td class="amount">{fmt_currency(total_balance)}</td></tr>
        </tbody>
      </table>
      <p class="body-note">If any of the taxes stated above have already been paid, please furnish this office with the number of the Official Receipt and the date of payment, or a clear copy thereof; otherwise, the amount stated above shall remain due and demandable.</p>
      <div class="amount-words">{_html_text(_peso_words(total_balance))}</div>
      <p class="body-note">If, after fifteen (15) days from your receipt hereof, you fail to remit or pay the stated amount, the remedies provided by law for the collection of delinquent taxes shall be applied to enforce collection.</p>
      <div class="warning">Kindly <b>DISREGARD THIS NOTICE</b> if settlement of your real property tax due has already been made.</div>
      <div class="signature-space">
        <section class="signatures">
          <div><div class="signature-label">Prepared by:</div><div class="signature-name">{prepared_by}</div><div class="signature-title">Revenue Collection Clerk / Authorized Personnel</div></div>
          <div><div class="signature-label">Very truly yours,</div><div class="signature-name">{MUNICIPAL_TREASURER_NAME}</div><div class="signature-title">Municipal Treasurer</div></div>
        </section>
      </div>
      <div class="service-rule"></div>
      <section class="service">
        <div>
          <div class="ack-title">ACKNOWLEDGEMENT:</div>
          <div class="ack-line"><span>Received by:</span><span></span></div>
          <div class="ack-line"><span>Name &amp; Signature:</span><span></span></div>
          <div class="ack-line"><span>Position/Designation:</span><span></span></div>
          <div class="ack-line"><span>Date:</span><span></span></div>
          <div class="ack-line"><span>Telephone No.:</span><span></span></div>
        </div>
        <div class="service-box">
          <div class="service-title">TO BE FILLED OUT BY MTO PERSONNEL:</div>
          <span class="check"></span>Served <span class="check"></span>Unserved
          <div class="reason">Reason:</div>
        </div>
      </section>
    </article>
  </main>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as output_file:
        output_file.write(document)
    return output_path
