from pathlib import Path

from backend.generators.receipt_gen import generate_or_receipt
from backend.services.payment_service import receipt_pdf_status


def _sample_payment():
    return {
        "payment_id": 42,
        "or_number": "3183715",
        "td_number": "06-0025-00265",
        "date_paid": "2024-08-08",
        "tax_year": "2024",
        "owner_name": "GIMENA, Carlo De Leon (Single)",
        "payor_name": "GIMENA, Carlo De Leon (Single)",
        "lot_number": "80-FL",
        "location": "TOYTOYAN",
        "kind_of_property": "RESIDENTIAL LOT",
        "assessed_value": 5040.0,
        "basic": 50.40,
        "sef": 50.40,
        "penalty": 3.02,
        "discount": 0.0,
        "amount": 103.82,
    }


def test_payment_record_pdf_is_a_reference_copy_and_uses_one_stable_file(tmp_path):
    first_path = Path(generate_or_receipt(_sample_payment(), str(tmp_path)))
    second_path = Path(generate_or_receipt(_sample_payment(), str(tmp_path)))

    assert first_path == second_path
    assert first_path.name.startswith("RPT_PAYMENT_RECORD_42_")
    assert list(first_path.parent.glob("*.pdf")) == [first_path]

    assert first_path.read_bytes().startswith(b"%PDF-")


def test_payment_record_status_is_resolved_on_the_server(tmp_path, monkeypatch):
    trusted_root = tmp_path / "receipts"
    trusted_root.mkdir()
    retained_pdf = trusted_root / "payment.pdf"
    monkeypatch.setattr(
        "backend.services.payment_service._LOCAL_RECEIPT_ROOTS",
        (trusted_root.resolve(),),
    )

    assert receipt_pdf_status(None) == "NOT_GENERATED"
    assert receipt_pdf_status(retained_pdf) == "MISSING"

    retained_pdf.write_bytes(b"%PDF-1.4\n")
    assert receipt_pdf_status(retained_pdf) == "READY"
    assert receipt_pdf_status("receipts/payment.pdf") == "READY"
    assert receipt_pdf_status(tmp_path / "outside.pdf") == "MISSING"
