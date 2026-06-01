# -*- coding: utf-8 -*-
"""
Tests for the public taxpayer inquiry endpoint logic.

Verifies the core Phase-1 promise: the portal computes a real outstanding
balance and per-year breakdown from PropertyBilling, derives status from
that balance (not a payment-year heuristic), and masks PII correctly.

Uses a real SQLite in-memory database so the SQLAlchemy queries in
_compute_billing_breakdown run exactly as they would against MariaDB.
"""

import pytest
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property, Payment, PropertyBilling, TaxPolicy
from backend.routes.public import (
    _compute_billing_breakdown,
    _derive_status,
    _mask_owner_name,
    _mask_pin,
    _mask_td_tail,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def enable_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(eng)
    eng.dispose()


def _make_property(db, td="06-0012-01379", assessed=100_000.0, owner="JUAN DELA CRUZ", pin="123-45-678-00-001"):
    p = Property(
        td_number=td,
        owner_name=owner,
        pin=pin,
        assessed_value=assessed,
        penalty=0.0,
        discount=0.0,
    )
    db.add(p)
    db.flush()
    return p


def _make_billing(db, property_id, tax_year, assessed=100_000.0, penalty=0.0, discount=0.0, paid=0.0):
    b = PropertyBilling(
        property_id=property_id,
        tax_year=tax_year,
        assessed_value=assessed,
        penalty=penalty,
        discount=discount,
        amount_paid=paid,
    )
    db.add(b)
    db.flush()
    return b


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------

class TestMasking:
    def test_owner_name_masks_each_word(self):
        assert _mask_owner_name("JUAN DELA CRUZ") == "J*** D*** C***"

    def test_owner_name_short_name_not_revealed(self):
        # A 3-char name must not be substantially exposed
        assert _mask_owner_name("ROD") == "R***"

    def test_owner_name_empty_falls_back(self):
        assert _mask_owner_name("") == "Taxpayer"
        assert _mask_owner_name(None) == "Taxpayer"

    def test_pin_masks_middle(self):
        assert _mask_pin("123456789012") == "1234****9012"

    def test_pin_short_uses_placeholder(self):
        assert _mask_pin("123") == "PIN-****"
        assert _mask_pin(None) == "PIN-****"

    def test_td_tail(self):
        assert _mask_td_tail("06-0012-01379") == "…1379"


# ---------------------------------------------------------------------------
# Balance computation
# ---------------------------------------------------------------------------

class TestBillingBreakdown:
    def test_no_billing_returns_zero_and_pending(self, db):
        prop = _make_property(db)
        bd = _compute_billing_breakdown(prop.id, db)
        assert bd["years"] == []
        assert bd["balance"] == 0.0
        assert _derive_status(bd) == "PENDING"

    def test_unpaid_billing_is_delinquent_with_balance(self, db):
        prop = _make_property(db, assessed=100_000.0)
        # 100k * (1% + 1%) = 2,000 due, nothing paid
        _make_billing(db, prop.id, 2024, assessed=100_000.0, paid=0.0)
        bd = _compute_billing_breakdown(prop.id, db)
        assert bd["total_due"] == 2_000.0
        assert bd["balance"] == 2_000.0
        assert _derive_status(bd) == "DELINQUENT"

    def test_fully_paid_billing_is_updated(self, db):
        prop = _make_property(db, assessed=100_000.0)
        _make_billing(db, prop.id, 2024, assessed=100_000.0, paid=2_000.0)
        bd = _compute_billing_breakdown(prop.id, db)
        assert bd["balance"] == 0.0
        assert _derive_status(bd) == "UPDATED"

    def test_partial_payment_still_delinquent(self, db):
        prop = _make_property(db, assessed=100_000.0)
        _make_billing(db, prop.id, 2024, assessed=100_000.0, paid=500.0)
        bd = _compute_billing_breakdown(prop.id, db)
        assert bd["balance"] == 1_500.0
        assert _derive_status(bd) == "DELINQUENT"

    def test_multi_year_balance_sums(self, db):
        prop = _make_property(db, assessed=100_000.0)
        _make_billing(db, prop.id, 2023, assessed=100_000.0, paid=2_000.0)  # paid
        _make_billing(db, prop.id, 2024, assessed=100_000.0, paid=0.0)      # unpaid
        _make_billing(db, prop.id, 2025, assessed=100_000.0, paid=0.0)      # unpaid
        bd = _compute_billing_breakdown(prop.id, db)
        assert bd["total_due"] == 6_000.0
        assert bd["total_paid"] == 2_000.0
        assert bd["balance"] == 4_000.0
        assert len(bd["years"]) == 3
        assert _derive_status(bd) == "DELINQUENT"

    def test_penalty_and_discount_in_balance(self, db):
        prop = _make_property(db, assessed=100_000.0)
        # due = 2000 + 300 penalty - 100 discount = 2200
        _make_billing(db, prop.id, 2024, assessed=100_000.0, penalty=300.0, discount=100.0, paid=0.0)
        bd = _compute_billing_breakdown(prop.id, db)
        assert bd["balance"] == 2_200.0

    def test_uses_tax_policy_rate_when_present(self, db):
        prop = _make_property(db, assessed=100_000.0)
        # Custom policy: 1.5% basic + 0.5% SEF = 2% total, but split differs
        db.add(TaxPolicy(tax_year=2024, basic_rate=0.015, sef_rate=0.005, penalty_rate=0.02))
        db.flush()
        _make_billing(db, prop.id, 2024, assessed=100_000.0, paid=0.0)
        bd = _compute_billing_breakdown(prop.id, db)
        year = bd["years"][0]
        assert year["basic"] == 1_500.0   # 100k * 1.5%
        assert year["sef"] == 500.0       # 100k * 0.5%
        assert bd["balance"] == 2_000.0

    def test_overpayment_floors_balance_at_zero(self, db):
        prop = _make_property(db, assessed=100_000.0)
        _make_billing(db, prop.id, 2024, assessed=100_000.0, paid=5_000.0)  # overpaid
        bd = _compute_billing_breakdown(prop.id, db)
        assert bd["balance"] == 0.0
        assert _derive_status(bd) == "UPDATED"
