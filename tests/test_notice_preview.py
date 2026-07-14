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
        "pin": "06-0001-00577",
        "last_payment_date": None,
        "last_or_number": None,
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
    assert "MTO TEST USER" not in document
    assert '<div class="signature-name"></div>' in document


def test_notice_preview_escapes_taxpayer_text(tmp_path):
    data = _statement_data()
    data["owner_name"] = "Owner <script>alert('x')</script>"
    output = Path(generate_delinquency_notice_preview(data, str(tmp_path)))
    document = output.read_text(encoding="utf-8")

    assert "<script>alert" not in document
    assert "&lt;script&gt;" in document


def test_peso_words_includes_centavos():
    assert _peso_words(10603.95) == "Ten Thousand Six Hundred Three Pesos and 95/100 Only"
