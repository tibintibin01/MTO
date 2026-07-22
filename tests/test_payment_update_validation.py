import pytest
from pydantic import ValidationError

from backend.routes.payments import PaymentUpdateRequest
from backend.services.payment_service import looks_like_valid_or_number


def test_payment_service_or_number_validator_is_available():
    assert looks_like_valid_or_number("OR-VALID")
    assert not looks_like_valid_or_number("<script>")


@pytest.mark.parametrize("amount", [0, -1])
def test_payment_update_schema_rejects_nonpositive_amount(amount):
    with pytest.raises(ValidationError):
        PaymentUpdateRequest(
            or_number="OR-VALID",
            date_paid="2026-01-01",
            tax_year="2026",
            amount=amount,
        )


@pytest.mark.parametrize("field", ["penalty", "discount"])
def test_payment_update_schema_rejects_negative_adjustments(field):
    values = {
        "or_number": "OR-VALID",
        "date_paid": "2026-01-01",
        "tax_year": "2026",
        "amount": 100,
        field: -1,
    }
    with pytest.raises(ValidationError):
        PaymentUpdateRequest(**values)
