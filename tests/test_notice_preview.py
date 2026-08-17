from datetime import datetime
from pathlib import Path

from backend.generators.notice_gen import (
    _peso_words,
    generate_delinquency_notice_preview,
)


def _statement_data():
    return {
        "td_number": "06-0001-00577",
        "owner_name": "ABERO, MAURICIO married to RIVERA, PATRICIA",
        "barangay": "NORTH POBLACION",
        "location": "NORTH POBLACION",
        "kind_of_property": "RESIDENTIAL LOT",
        "assessed_value": 112330,
        "lot_number": None,
        "block_number": None,
        "area": "0 sqm",
        "pin": "03-140-1001",
        "last_payment_date": datetime(2026, 7, 29),
        "last_or_number": "8169531Y",
        "prepared_by": "MTO Test User",
        "billing_rows": [
            {
                "tax_year": 2023,
                "assessed_value": 112330,
                "basic_amount": 1123.30,
                "sef_amount": 1123.30,
                "penalty": 1617.55,
                "balance_amount": 3864.15,
            },
            {
                "tax_year": 2024,
                "assessed_value": 112330,
                "basic_amount": 1123.30,
                "sef_amount": 1123.30,
                "penalty": 1392.89,
                "balance_amount": 3639.49,
            },
            {
                "tax_year": 2025,
                "assessed_value": 112330,
                "basic_amount": 1123.30,
                "sef_amount": 1123.30,
                "penalty": 853.71,
                "balance_amount": 3100.31,
            },
            {
                "tax_year": 2026,
                "assessed_value": 112330,
                "basic_amount": 1123.30,
                "sef_amount": 1123.30,
                "penalty": 0,
                "balance_amount": 0,
            },
        ],
    }


def test_notice_preview_is_self_contained_folio_document(tmp_path):
    output = Path(generate_delinquency_notice_preview(_statement_data(), str(tmp_path)))
    document = output.read_text(encoding="utf-8")

    assert output.suffix == ".html"
    assert "NOTICE OF REAL PROPERTY TAX DELINQUENCY" in document
    assert "size:8.5in 13in" in document
    assert "Sec. 254, R.A. 7160" in document
    assert "2023 to 2025" in document
    assert "10,603.95" in document
    assert "Save PDF" in document
    assert "Print Document" in document
    assert "data:image/png;base64," in document
    assert "ABERO, MAURICIO MARRIED TO RIVERA, PATRICIA" in document
    assert "BRGY. NORTH POBLACION, DIPACULAO, AURORA" in document
    assert "<strong>TDN:</strong><span>06-0001-00577</span>" in document
    assert "03-140-1001" not in document
    assert "JUL 29, 2026 / OR NO. 8169531Y" in document
    assert "<strong>Date:</strong><span>JUL 29, 2026</span>" in document
    assert "<strong>OR No.:</strong><span>8169531Y</span>" in document
    assert '<div class="signature-name">MTO TEST USER</div>' in document
    assert '<div class="signature-name">MARIA ELENA P. CHAVEZ</div>' in document
    assert "<td>FULL</td>" in document


def test_notice_preview_escapes_taxpayer_text(tmp_path):
    data = _statement_data()
    data["owner_name"] = "Owner <script>alert('x')</script>"
    output = Path(generate_delinquency_notice_preview(data, str(tmp_path)))
    document = output.read_text(encoding="utf-8")

    assert "<script>alert" not in document
    assert "&lt;SCRIPT&gt;" in document


def test_peso_words_includes_centavos():
    assert _peso_words(10603.95) == "Ten Thousand Six Hundred Three Pesos and 95/100 Only"
