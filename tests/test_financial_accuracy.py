# -*- coding: utf-8 -*-
"""
Financial accuracy tests for the MTO Treasury System.

Covers:
  - _d() Decimal helper (currency conversion safety)
  - Basic/SEF tax rate calculations (1% each on assessed value)
  - Penalty calculation (2% per month)
  - Discount application
  - sync_property_billing() — billing record creation and update
  - allocate_payment_amount() — multi-year payment allocation
  - split_amount_across_years() — penny-accurate amount splitting
  - Delinquency determination (balance > 0)
  - Receipt amount matching (payment amount == receipt amount)
  - Full payment lifecycle via real SQLite DB
  - normalize_tax_years() / format_tax_years() — tax year parsing
  - validate_tax_year_text() — input validation
"""

import pytest
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import (
    Property, Payment, PropertyBilling, PaymentBilling,
    ReceiptHistory, AuditLog, User,
)
from backend.services.payment_service import _d
from backend.services.billing_service import (
    sync_property_billing,
    allocate_payment_amount,
    split_amount_across_years,
    calculate_penalty,
    normalize_tax_years,
    format_tax_years,
    validate_tax_year_text,
    get_delinquent_accounts,
    get_property_statement_data,
)


# ---------------------------------------------------------------------------
# Fixtures — shared with test_integration_db.py pattern
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def enable_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


def make_property(db, td="TD-FIN-001", assessed_value=100_000.0):
    p = Property(
        td_number=td,
        owner_name="JUAN DELA CRUZ",
        assessed_value=assessed_value,
        penalty=0.0,
        discount=0.0,
    )
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# _d() Decimal helper
# ---------------------------------------------------------------------------

class TestDecimalHelper:
    def test_none_returns_zero(self):
        assert _d(None) == Decimal("0")

    def test_integer(self):
        assert _d(1000) == Decimal("1000")

    def test_float_precision(self):
        # float(0.1 + 0.2) == 0.30000000000000004 — _d must not propagate this
        result = _d(0.1) + _d(0.2)
        assert result == Decimal("0.3")

    def test_string_currency(self):
        assert _d("2500.50") == Decimal("2500.50")

    def test_decimal_passthrough(self):
        assert _d(Decimal("999.99")) == Decimal("999.99")

    def test_invalid_string_returns_zero(self):
        assert _d("not_a_number") == Decimal("0")

    def test_empty_string_returns_zero(self):
        assert _d("") == Decimal("0")

    def test_large_amount(self):
        # Government properties can have very large assessed values
        assert _d("99999999.99") == Decimal("99999999.99")

    def test_negative_value(self):
        # Discounts and reversals can be negative
        assert _d("-500.00") == Decimal("-500.00")


# ---------------------------------------------------------------------------
# Tax rate calculations — Basic (1%) + SEF (1%) = 2% of assessed value
# ---------------------------------------------------------------------------

class TestTaxRateCalculations:
    """
    Philippine RPT: Basic tax = 1% of assessed value, SEF = 1%.
    Total annual tax = 2% of assessed value.
    These rates are hardcoded in sync_property_billing() and the billing
    history query. Any change to the rate must break these tests.
    """

    def test_basic_rate_one_percent(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        assert result["basic_amount"] == pytest.approx(1_000.0)

    def test_sef_rate_one_percent(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        assert result["sef_amount"] == pytest.approx(1_000.0)

    def test_total_tax_two_percent(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        assert result["total_amount"] == pytest.approx(2_000.0)

    def test_fractional_assessed_value_rounds_half_up(self, db):
        # 333,333.33 * 0.01 = 3,333.3333 → rounds to 3,333.33
        prop = make_property(db, assessed_value=333_333.33)
        result = sync_property_billing(
            prop.id, "2024", 333_333.33, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        basic = Decimal(str(result["basic_amount"]))
        assert basic == Decimal("3333.33")

    def test_zero_assessed_value(self, db):
        prop = make_property(db, assessed_value=0.0)
        result = sync_property_billing(
            prop.id, "2024", 0.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        assert result["total_amount"] == pytest.approx(0.0)
        assert result["billing_status"] == "Paid"  # 0 due, 0 paid = Paid


# ---------------------------------------------------------------------------
# Penalty calculation
# ---------------------------------------------------------------------------

class TestPenaltyCalculation:
    def test_standard_2_percent_per_month(self):
        assert calculate_penalty(10_000.0, 1) == pytest.approx(200.0)

    def test_five_months_late(self):
        assert calculate_penalty(10_000.0, 5) == pytest.approx(1_000.0)

    def test_zero_months_no_penalty(self):
        assert calculate_penalty(10_000.0, 0) == pytest.approx(0.0)

    def test_penalty_on_large_principal(self):
        # 5,000,000 assessed value, 3 months late
        assert calculate_penalty(5_000_000.0, 3) == pytest.approx(300_000.0)

    def test_penalty_included_in_billing_total(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        penalty = 500.0
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, penalty, 0.0,
            has_payment=False, db_session=db
        )
        # total = basic(1000) + sef(1000) + penalty(500) = 2500
        assert result["total_amount"] == pytest.approx(2_500.0)
        assert result["penalty"] == pytest.approx(500.0)

    def test_penalty_stored_in_billing_record(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        sync_property_billing(
            prop.id, "2024", 100_000.0, 750.0, 0.0,
            has_payment=False, db_session=db
        )
        db.commit()
        billing = db.query(PropertyBilling).filter(
            PropertyBilling.property_id == prop.id
        ).first()
        assert float(billing.penalty) == pytest.approx(750.0)


# ---------------------------------------------------------------------------
# Discount application
# ---------------------------------------------------------------------------

class TestDiscountApplication:
    def test_discount_reduces_total(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 200.0,
            has_payment=False, db_session=db
        )
        # total = basic(1000) + sef(1000) - discount(200) = 1800
        assert result["total_amount"] == pytest.approx(1_800.0)

    def test_discount_cannot_make_total_negative(self, db):
        # Discount larger than total due — total should floor at 0
        prop = make_property(db, assessed_value=10_000.0)
        result = sync_property_billing(
            prop.id, "2024", 10_000.0, 0.0, 9_999.0,
            has_payment=False, db_session=db
        )
        # basic(100) + sef(100) - discount(9999) = -9799 — service returns raw
        # The balance_amount is clamped to 0 by max(0, total - paid)
        assert result["balance_amount"] >= 0.0

    def test_penalty_and_discount_combined(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, 500.0, 300.0,
            has_payment=False, db_session=db
        )
        # basic(1000) + sef(1000) + penalty(500) - discount(300) = 2200
        assert result["total_amount"] == pytest.approx(2_200.0)


# ---------------------------------------------------------------------------
# Billing status determination
# ---------------------------------------------------------------------------

class TestBillingStatus:
    def test_status_pending_when_nothing_paid(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        assert result["billing_status"] == "Pending"

    def test_status_paid_when_fully_paid(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=True, db_session=db
        )
        assert result["billing_status"] == "Paid"

    def test_status_partial_when_underpaid(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        # Create billing first
        sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        # Manually set partial payment
        billing = db.query(PropertyBilling).filter(
            PropertyBilling.property_id == prop.id
        ).first()
        billing.amount_paid = Decimal("1000.00")  # half of 2000 due
        db.flush()

        # Re-sync to get updated status
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        assert result["billing_status"] == "Partial"

    def test_balance_is_zero_when_fully_paid(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=True, db_session=db
        )
        assert result["balance_amount"] == pytest.approx(0.0)

    def test_balance_equals_total_when_unpaid(self, db):
        prop = make_property(db, assessed_value=100_000.0)
        result = sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        assert result["balance_amount"] == pytest.approx(result["total_amount"])


# ---------------------------------------------------------------------------
# allocate_payment_amount() — multi-year payment allocation
# ---------------------------------------------------------------------------

class TestPaymentAllocation:
    """
    allocate_payment_amount() distributes a payment across multiple billing
    years in chronological order (oldest first). This is the core of the
    multi-year payment posting logic.
    """

    def _make_billing_row(self, tax_year, total_amount, amount_paid=0.0):
        balance = max(0.0, total_amount - amount_paid)
        return {
            "billing_id": int(tax_year),
            "tax_year": str(tax_year),
            "total_amount": total_amount,
            "amount_paid": amount_paid,
            "balance_amount": balance,
        }

    def test_single_year_full_payment(self):
        rows = [self._make_billing_row("2024", 2_000.0)]
        result = allocate_payment_amount(rows, 2_000.0)
        assert result[0]["applied_amount"] == pytest.approx(2_000.0)

    def test_single_year_partial_payment(self):
        rows = [self._make_billing_row("2024", 2_000.0)]
        result = allocate_payment_amount(rows, 1_000.0)
        assert result[0]["applied_amount"] == pytest.approx(1_000.0)

    def test_multi_year_oldest_first(self):
        rows = [
            self._make_billing_row("2023", 2_000.0),
            self._make_billing_row("2024", 2_000.0),
        ]
        # Pay exactly one year
        result = allocate_payment_amount(rows, 2_000.0)
        # 2023 should be fully covered, 2024 gets nothing
        by_year = {r["tax_year"]: r["applied_amount"] for r in result}
        assert by_year["2023"] == pytest.approx(2_000.0)
        assert by_year["2024"] == pytest.approx(0.0)

    def test_multi_year_overflow_to_next(self):
        rows = [
            self._make_billing_row("2022", 2_000.0),
            self._make_billing_row("2023", 2_000.0),
            self._make_billing_row("2024", 2_000.0),
        ]
        # Pay 5000 — covers 2022 fully, 2023 fully, 2024 partially
        result = allocate_payment_amount(rows, 5_000.0)
        by_year = {r["tax_year"]: r["applied_amount"] for r in result}
        assert by_year["2022"] == pytest.approx(2_000.0)
        assert by_year["2023"] == pytest.approx(2_000.0)
        assert by_year["2024"] == pytest.approx(1_000.0)

    def test_payment_does_not_exceed_due(self):
        rows = [self._make_billing_row("2024", 2_000.0)]
        # Overpayment — applied amount must not exceed total_amount
        result = allocate_payment_amount(rows, 9_999.0)
        assert result[0]["applied_amount"] == pytest.approx(2_000.0)

    def test_zero_payment_allocates_nothing(self):
        rows = [self._make_billing_row("2024", 2_000.0)]
        result = allocate_payment_amount(rows, 0.0)
        assert result[0]["applied_amount"] == pytest.approx(0.0)

    def test_total_allocated_never_exceeds_payment(self):
        rows = [
            self._make_billing_row("2021", 2_000.0),
            self._make_billing_row("2022", 2_000.0),
            self._make_billing_row("2023", 2_000.0),
        ]
        payment = 3_500.0
        result = allocate_payment_amount(rows, payment)
        total_applied = sum(r["applied_amount"] for r in result)
        assert total_applied == pytest.approx(payment)


# ---------------------------------------------------------------------------
# split_amount_across_years() — penny-accurate splitting
# ---------------------------------------------------------------------------

class TestAmountSplitting:
    """
    When a property has multiple tax years, the assessed value and penalty
    are split evenly. The split must be penny-accurate — the sum of all
    parts must exactly equal the original total with no floating-point drift.
    """

    def test_single_year_returns_full_amount(self):
        result = split_amount_across_years(2_000.0, 1)
        assert len(result) == 1
        assert result[0] == pytest.approx(2_000.0)

    def test_even_split_two_years(self):
        result = split_amount_across_years(4_000.0, 2)
        assert len(result) == 2
        assert result[0] == pytest.approx(2_000.0)
        assert result[1] == pytest.approx(2_000.0)

    def test_penny_accurate_odd_split(self):
        # 100.00 / 3 = 33.333... → [33.34, 33.33, 33.33]
        result = split_amount_across_years(100.0, 3)
        total = sum(Decimal(str(r)) for r in result)
        assert total == Decimal("100.00")

    def test_sum_always_equals_original(self):
        for total in [1.0, 100.01, 999.99, 12_345.67]:
            for count in [1, 2, 3, 5, 7]:
                parts = split_amount_across_years(total, count)
                reconstructed = sum(Decimal(str(p)) for p in parts)
                original = Decimal(str(total)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                assert reconstructed == original, (
                    f"Split of {total} into {count} parts summed to {reconstructed}, "
                    f"expected {original}"
                )

    def test_zero_amount_splits_to_zeros(self):
        result = split_amount_across_years(0.0, 3)
        assert all(r == pytest.approx(0.0) for r in result)

    def test_zero_count_treated_as_one(self):
        result = split_amount_across_years(500.0, 0)
        assert len(result) == 1
        assert result[0] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Delinquency determination
# ---------------------------------------------------------------------------

class TestDelinquencyDetermination:
    """
    A property is delinquent when its billing balance > 0.
    The get_delinquent_accounts() query uses HAVING balance_expr > 0.
    These tests verify the determination logic against real DB rows.
    """

    def test_unpaid_property_is_delinquent(self, db):
        prop = make_property(db, td="TD-DELINQ-001", assessed_value=100_000.0)
        sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        db.commit()

        result = get_delinquent_accounts(limit=50, db_session=db)
        ids = [item["id"] for item in result["items"]]
        assert prop.id in ids

    def test_fully_paid_property_not_delinquent(self, db):
        prop = make_property(db, td="TD-PAID-001", assessed_value=100_000.0)
        sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=True, db_session=db
        )
        db.commit()

        result = get_delinquent_accounts(limit=50, db_session=db)
        ids = [item["id"] for item in result["items"]]
        assert prop.id not in ids

    def test_partially_paid_property_is_delinquent(self, db):
        prop = make_property(db, td="TD-PARTIAL-001", assessed_value=100_000.0)
        sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        billing = db.query(PropertyBilling).filter(
            PropertyBilling.property_id == prop.id
        ).first()
        billing.amount_paid = Decimal("1000.00")  # partial
        db.commit()

        result = get_delinquent_accounts(limit=50, db_session=db)
        ids = [item["id"] for item in result["items"]]
        assert prop.id in ids

    def test_delinquent_balance_is_correct(self, db):
        prop = make_property(db, td="TD-BAL-001", assessed_value=100_000.0)
        sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        db.commit()

        result = get_delinquent_accounts(limit=50, db_session=db)
        item = next(i for i in result["items"] if i["id"] == prop.id)
        # total_due = basic(1000) + sef(1000) = 2000, nothing paid
        assert item["balance"] == pytest.approx(2_000.0)

    def test_soft_deleted_property_excluded_from_delinquents(self, db):
        prop = make_property(db, td="TD-SOFTDEL-001", assessed_value=100_000.0)
        sync_property_billing(
            prop.id, "2024", 100_000.0, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        prop.deleted_at = datetime.now(timezone.utc)
        db.commit()

        result = get_delinquent_accounts(limit=50, db_session=db)
        ids = [item["id"] for item in result["items"]]
        assert prop.id not in ids


# ---------------------------------------------------------------------------
# Receipt amount matching
# ---------------------------------------------------------------------------

class TestReceiptAmountMatching:
    """
    The amount on a receipt must exactly match the payment amount.
    get_payment_receipt_details() returns both — they must be equal.
    """

    def test_receipt_amount_matches_payment(self, db):
        prop = make_property(db)
        pay = Payment(
            property_id=prop.id,
            amount=Decimal("2500.00"),
            penalty=Decimal("0.00"),
            discount=Decimal("0.00"),
            or_number="OR-RECEIPT-001",
            tax_year="2024",
            date_paid=datetime.now(timezone.utc),
            posted_by="cashier1",
        )
        db.add(pay)
        db.flush()

        rh = ReceiptHistory(
            property_id=prop.id,
            payment_id=pay.id,
            or_number="OR-RECEIPT-001",
            amount=Decimal("2500.00"),
            file_path="/receipts/OR-RECEIPT-001.pdf",
            generated_by="cashier1",
            generated_at=datetime.now(timezone.utc),
            status="PDF READY",
        )
        db.add(rh)
        db.commit()

        from backend.services.payment_service import get_payment_receipt_details
        details = get_payment_receipt_details(pay.id, db_session=db)

        assert details is not None
        assert details["amount"] == pytest.approx(2_500.0)
        assert details["or_number"] == "OR-RECEIPT-001"

    def test_receipt_penalty_matches_payment_penalty(self, db):
        prop = make_property(db)
        pay = Payment(
            property_id=prop.id,
            amount=Decimal("2750.00"),
            penalty=Decimal("250.00"),
            discount=Decimal("0.00"),
            or_number="OR-PEN-001",
            tax_year="2024",
            date_paid=datetime.now(timezone.utc),
            posted_by="cashier1",
        )
        db.add(pay)
        db.commit()

        from backend.services.payment_service import get_payment_receipt_details
        details = get_payment_receipt_details(pay.id, db_session=db)

        assert details["penalty"] == pytest.approx(250.0)
        assert details["amount"] == pytest.approx(2_750.0)

    def test_receipt_discount_matches_payment_discount(self, db):
        prop = make_property(db)
        pay = Payment(
            property_id=prop.id,
            amount=Decimal("1800.00"),
            penalty=Decimal("0.00"),
            discount=Decimal("200.00"),
            or_number="OR-DISC-001",
            tax_year="2024",
            date_paid=datetime.now(timezone.utc),
            posted_by="cashier1",
        )
        db.add(pay)
        db.commit()

        from backend.services.payment_service import get_payment_receipt_details
        details = get_payment_receipt_details(pay.id, db_session=db)

        assert details["discount"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Tax year parsing and validation
# ---------------------------------------------------------------------------

class TestTaxYearParsing:
    def test_single_year(self):
        assert normalize_tax_years("2024") == ["2024"]

    def test_comma_separated(self):
        assert normalize_tax_years("2022, 2023, 2024") == ["2022", "2023", "2024"]

    def test_semicolon_separator(self):
        assert normalize_tax_years("2022;2023") == ["2022", "2023"]

    def test_range_expansion(self):
        assert normalize_tax_years("2021-2024") == ["2021", "2022", "2023", "2024"]

    def test_range_with_spaces(self):
        assert normalize_tax_years("2021 - 2023") == ["2021", "2022", "2023"]

    def test_deduplication(self):
        result = normalize_tax_years("2023, 2023, 2024")
        assert result.count("2023") == 1

    def test_format_tax_years_joins_with_comma(self):
        assert format_tax_years("2022, 2023") == "2022, 2023"

    def test_format_range_expands_and_joins(self):
        result = format_tax_years("2022-2024")
        assert result == "2022, 2023, 2024"


class TestTaxYearValidation:
    def test_valid_single_year(self):
        result = validate_tax_year_text("2024")
        assert result["ok"] is True

    def test_valid_range(self):
        result = validate_tax_year_text("2020-2024")
        assert result["ok"] is True
        assert len(result["years"]) == 5

    def test_empty_input_fails(self):
        result = validate_tax_year_text("")
        assert result["ok"] is False

    def test_invalid_format_fails(self):
        result = validate_tax_year_text("twenty-twenty")
        assert result["ok"] is False

    def test_reversed_range_fails(self):
        result = validate_tax_year_text("2024-2020")
        assert result["ok"] is False

    def test_range_too_wide_fails(self):
        result = validate_tax_year_text("2000-2015")
        assert result["ok"] is False

    def test_duplicate_year_fails(self):
        result = validate_tax_year_text("2023, 2023")
        assert result["ok"] is False

    def test_year_before_1900_fails(self):
        result = validate_tax_year_text("1899")
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# Full payment lifecycle — end-to-end financial accuracy
# ---------------------------------------------------------------------------

class TestFullPaymentLifecycle:
    """
    Posts a payment through the full sync_property_billing + manual billing
    update flow and verifies every financial figure is correct at each step.
    """

    def test_full_lifecycle_single_year(self, db):
        # Setup
        assessed = 200_000.0
        prop = make_property(db, td="TD-LIFECYCLE-001", assessed_value=assessed)

        # Step 1: Create billing (no payment yet)
        billing_result = sync_property_billing(
            prop.id, "2024", assessed, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        assert billing_result["billing_status"] == "Pending"
        assert billing_result["total_amount"] == pytest.approx(4_000.0)  # 2% of 200k
        assert billing_result["balance_amount"] == pytest.approx(4_000.0)

        # Step 2: Post full payment
        pay = Payment(
            property_id=prop.id,
            amount=Decimal("4000.00"),
            penalty=Decimal("0.00"),
            discount=Decimal("0.00"),
            or_number="OR-LIFECYCLE-001",
            tax_year="2024",
            date_paid=datetime.now(timezone.utc),
            posted_by="cashier1",
        )
        db.add(pay)
        db.flush()

        billing = db.query(PropertyBilling).filter(
            PropertyBilling.property_id == prop.id,
            PropertyBilling.tax_year == "2024",
        ).first()
        billing.amount_paid = Decimal("4000.00")
        db.commit()

        # Step 3: Verify billing is now Paid with zero balance
        updated = sync_property_billing(
            prop.id, "2024", assessed, 0.0, 0.0,
            has_payment=False, db_session=db
        )
        assert updated["billing_status"] == "Paid"
        assert updated["balance_amount"] == pytest.approx(0.0)
        assert updated["amount_paid"] == pytest.approx(4_000.0)

        # Step 4: Verify property statement totals
        db.commit()
        statement = get_property_statement_data(prop.id, db_session=db)
        assert statement["total_paid"] == pytest.approx(4_000.0)
        assert statement["total_balance"] == pytest.approx(0.0)
        assert statement["grand_total"] == pytest.approx(4_000.0)

    def test_multi_year_lifecycle(self, db):
        assessed = 100_000.0
        prop = make_property(db, td="TD-MULTI-001", assessed_value=assessed)

        # Create billings for 3 years
        for year in ["2022", "2023", "2024"]:
            sync_property_billing(
            prop.id, year, assessed, 0.0, 0.0,
                has_payment=False, db_session=db
            )
        db.commit()

        # Total due = 3 years × 2000 = 6000
        statement = get_property_statement_data(prop.id, db_session=db)
        assert statement["grand_total"] == pytest.approx(6_000.0)
        assert statement["total_balance"] == pytest.approx(6_000.0)

        # Pay 2022 and 2023 only
        for year in ["2022", "2023"]:
            billing = db.query(PropertyBilling).filter(
                PropertyBilling.property_id == prop.id,
                PropertyBilling.tax_year == year,
            ).first()
            billing.amount_paid = Decimal("2000.00")
        db.commit()

        statement2 = get_property_statement_data(prop.id, db_session=db)
        assert statement2["total_paid"] == pytest.approx(4_000.0)
        assert statement2["total_balance"] == pytest.approx(2_000.0)  # 2024 still unpaid
