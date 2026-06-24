import pytest

from backend.routes.compute import ComputePaymentRequest, compute_payment


class _NoPolicyQuery:
    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return None


class _NoPolicySession:
    def query(self, *_args, **_kwargs):
        return _NoPolicyQuery()


@pytest.mark.asyncio
async def test_compute_payment_uses_office_penalty_month_count():
    result = await compute_payment(
        ComputePaymentRequest(
            assessed_value=480_210.0,
            tax_year=2024,
            date_paid="2026-06-20",
        ),
        current_user={"id": 1, "username": "test"},
        db_session=_NoPolicySession(),
    )

    assert result["basic_tax"] == pytest.approx(4802.10)
    assert result["sef_tax"] == pytest.approx(4802.10)
    assert result["total_tax"] == pytest.approx(9604.20)
    assert result["penalty_months"] == 23
    assert result["penalty_amount"] == pytest.approx(4417.93)
    assert result["net_amount_due"] == pytest.approx(14022.13)
