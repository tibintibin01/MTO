"""Conserved receipt adjustments under the existing equal-share convention.

Payment.amount is cash, including penalty and net of discount. Older records
do not store a year-specific adjustment. Split once across the linked billing
rows, in tax-year/id order, instead of repeating the receipt total on every row.
These helpers read existing receipts; they never backfill or repair history.
"""

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Integer, Numeric, and_, case, cast, func, or_
from sqlalchemy.orm import aliased

from backend.models import PaymentBilling

CENT = Decimal("0.01")


def equal_adjustment_shares(amount, count):
    """Match split_amount_across_years, retaining every cent."""
    if count < 1:
        raise ValueError("A receipt adjustment requires at least one allocation.")
    total = Decimal(str(amount or 0)).quantize(CENT, rounding=ROUND_HALF_UP)
    base = (total / count).quantize(CENT, rounding=ROUND_HALF_UP)
    shares = [base] * count
    remainder = int((total - base * count) / CENT)
    for index in range(abs(remainder)):
        shares[index] += CENT if remainder > 0 else -CENT
    return shares


def allocated_adjustment_expr(db_session, amount_column):
    """SQL equivalent of equal_adjustment_shares for the current link row.

    Correlated indexed lookups avoid requiring new columns or a DB migration.
    Integer cents plus deterministic remainder distribution preserve the
    receipt total even for three-way and odd-cent splits.
    """
    sibling = aliased(PaymentBilling)
    count = (
        db_session.query(func.count(sibling.id))
        .filter(sibling.payment_id == PaymentBilling.payment_id)
        .correlate(PaymentBilling)
        .scalar_subquery()
    )
    rank = (
        db_session.query(func.count(sibling.id))
        .filter(
            sibling.payment_id == PaymentBilling.payment_id,
            or_(
                sibling.tax_year < PaymentBilling.tax_year,
                and_(
                    sibling.tax_year == PaymentBilling.tax_year,
                    sibling.id < PaymentBilling.id,
                ),
            ),
        )
        .correlate(PaymentBilling)
        .scalar_subquery()
    )
    cents = cast(func.round(func.coalesce(amount_column, 0) * 100, 0), Integer)
    base = cast(func.round(cents / cast(count, Numeric(20, 8)), 0), Integer)
    remainder = cents - base * count
    extra = case(
        (and_(remainder > 0, rank < remainder), 1),
        (and_(remainder < 0, rank < -remainder), -1),
        else_=0,
    )
    return cast(base + extra, Numeric(20, 2)) / 100
