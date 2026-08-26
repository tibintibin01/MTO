# -*- coding: utf-8 -*-
"""
Integration tests against a real SQLite in-memory database.

These tests verify what the unit tests with MagicMock cannot:
  - SQLAlchemy queries produce correct SQL and return real rows
  - Schema constraints (UNIQUE, FK, NOT NULL) are enforced by the DB engine
  - Multi-step financial operations (payment post, billing sync, payment delete)
    leave the database in a consistent state
  - Soft-delete filters work correctly at the query level
  - Audit log immutability events fire correctly

The in-memory SQLite database is created fresh for every test function via
the `db` fixture, so tests are fully isolated with no shared state.

No external services (MySQL, Redis) are required — this runs in CI with
zero infrastructure.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import (
    User,
    Property,
    Payment,
    PropertyBilling,
    PaymentBilling,
    AuditLog,
    RefreshToken,
    ReceiptHistory,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    """
    Creates a fresh SQLite in-memory engine for each test.

    SQLite does not enforce FK constraints by default — enable them so the
    tests catch the same constraint violations that MariaDB would raise.
    """
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
    """Provides a transactional session that is rolled back after each test."""
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(db, username="cashier1", role="cashier", password="hashed_pw"):
    u = User(username=username, full_name="Test User", password=password, role=role)
    db.add(u)
    db.flush()
    return u


def make_property(db, td="TD-TEST-001", assessed_value=100_000.0):
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


def make_billing(db, property_id, tax_year="2024", assessed_value=100_000.0):
    b = PropertyBilling(
        property_id=property_id,
        tax_year=tax_year,
        assessed_value=assessed_value,
        penalty=0.0,
        discount=0.0,
        amount_paid=0.0,
    )
    db.add(b)
    db.flush()
    return b


def make_payment(db, property_id, amount=2_000.0, or_number="OR-000001", tax_year="2024"):
    p = Payment(
        property_id=property_id,
        amount=amount,
        penalty=0.0,
        discount=0.0,
        or_number=or_number,
        tax_year=tax_year,
        date_paid=datetime.now(timezone.utc),
        posted_by="cashier1",
    )
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# Schema / constraint tests
# ---------------------------------------------------------------------------

class TestSchemaConstraints:
    def test_user_username_unique(self, db):
        """UNIQUE constraint on users.username must be enforced."""
        make_user(db, username="alice")
        db.commit()

        with pytest.raises(Exception):
            make_user(db, username="alice")
            db.commit()

    def test_property_td_number_can_store_separate_internal_accounts(self, db):
        """Approved duplicate TD exceptions remain separate by property ID.

        The admin authorization gate is covered by the duplicate-TD service
        tests; the database intentionally permits the resulting two rows.
        """
        first = make_property(db, td="TD-CONTROLLED-DUPLICATE")
        db.commit()
        second = make_property(db, td="TD-CONTROLLED-DUPLICATE")
        db.commit()

        assert first.id != second.id
        assert (
            db.query(Property)
            .filter(Property.td_number == "TD-CONTROLLED-DUPLICATE")
            .count()
            == 2
        )

    def test_payment_requires_existing_property(self, db):
        """FK constraint: payment.property_id must reference a real property."""
        with pytest.raises(Exception):
            p = Payment(
                property_id=99999,  # does not exist
                amount=1000.0,
                penalty=0.0,
                discount=0.0,
                or_number="OR-ORPHAN",
                tax_year="2024",
                date_paid=datetime.now(timezone.utc),
            )
            db.add(p)
            db.commit()

    def test_user_not_null_fields(self, db):
        """NOT NULL constraint on users.username must be enforced."""
        with pytest.raises(Exception):
            u = User(username=None, full_name="No Name", password="pw", role="viewer")
            db.add(u)
            db.commit()

    def test_property_billing_fk(self, db):
        """FK constraint: property_billings.property_id must reference a real property."""
        with pytest.raises(Exception):
            b = PropertyBilling(
                property_id=99999,
                tax_year="2024",
                assessed_value=50000.0,
                penalty=0.0,
                discount=0.0,
                amount_paid=0.0,
            )
            db.add(b)
            db.commit()


# ---------------------------------------------------------------------------
# Query correctness tests
# ---------------------------------------------------------------------------

class TestQueryCorrectness:
    def test_soft_delete_filter(self, db):
        """
        Properties with deleted_at set must not appear in active queries.
        This verifies the ORM filter `Property.deleted_at == None` works
        correctly at the SQL level — MagicMock cannot catch a missing filter.
        """
        active = make_property(db, td="TD-ACTIVE-001")
        deleted = make_property(db, td="TD-DELETED-001")
        deleted.deleted_at = datetime.now(timezone.utc)
        db.commit()

        results = db.query(Property).filter(Property.deleted_at == None).all()
        td_numbers = [p.td_number for p in results]

        assert "TD-ACTIVE-001" in td_numbers
        assert "TD-DELETED-001" not in td_numbers

    def test_payment_join_to_property(self, db):
        """Payment → Property join returns the correct owner name."""
        prop = make_property(db, td="TD-JOIN-001")
        pay = make_payment(db, property_id=prop.id, or_number="OR-JOIN-001")
        db.commit()

        row = (
            db.query(Payment, Property)
            .join(Property, Property.id == Payment.property_id)
            .filter(Payment.id == pay.id)
            .first()
        )
        assert row is not None
        payment, property_ = row
        assert property_.owner_name == "JUAN DELA CRUZ"
        assert payment.or_number == "OR-JOIN-001"

    def test_billing_amount_paid_update(self, db):
        """
        Updating PropertyBilling.amount_paid persists correctly and is
        readable back from the database.
        """
        prop = make_property(db)
        billing = make_billing(db, property_id=prop.id, assessed_value=100_000.0)
        db.commit()

        billing.amount_paid = Decimal("2000.00")
        db.commit()

        refreshed = db.query(PropertyBilling).filter(PropertyBilling.id == billing.id).first()
        assert float(refreshed.amount_paid) == pytest.approx(2000.0)

    def test_refresh_token_lookup(self, db):
        """RefreshToken can be looked up by token string and expiry."""
        user = make_user(db)
        db.commit()

        token_str = "secure_random_token_abc123"
        rt = RefreshToken(
            user_id=user.id,
            token=token_str,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            is_revoked=False,
        )
        db.add(rt)
        db.commit()

        found = db.query(RefreshToken).filter(
            RefreshToken.token == token_str,
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc),
        ).first()

        assert found is not None
        assert found.user_id == user.id

    def test_revoked_token_not_returned(self, db):
        """A revoked refresh token must not be returned by the active token query."""
        user = make_user(db)
        db.commit()

        rt = RefreshToken(
            user_id=user.id,
            token="revoked_token_xyz",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            is_revoked=True,
        )
        db.add(rt)
        db.commit()

        found = db.query(RefreshToken).filter(
            RefreshToken.token == "revoked_token_xyz",
            RefreshToken.is_revoked == False,
        ).first()

        assert found is None


# ---------------------------------------------------------------------------
# Financial operation integrity tests
# ---------------------------------------------------------------------------

class TestFinancialIntegrity:
    def test_payment_post_updates_billing_balance(self, db):
        """
        Posting a payment and updating the billing balance leaves the DB in
        a consistent state: amount_paid reflects the payment, balance is correct.
        """
        prop = make_property(db, assessed_value=100_000.0)
        billing = make_billing(db, property_id=prop.id, assessed_value=100_000.0)
        db.commit()

        # Total due = basic (1%) + SEF (1%) = 2,000
        total_due = Decimal("2000.00")
        payment_amount = Decimal("2000.00")

        pay = make_payment(db, property_id=prop.id, amount=float(payment_amount))

        # Simulate billing sync
        billing.amount_paid = payment_amount
        db.commit()

        refreshed_billing = db.query(PropertyBilling).filter(
            PropertyBilling.property_id == prop.id,
            PropertyBilling.tax_year == "2024",
        ).first()

        balance = total_due - Decimal(str(refreshed_billing.amount_paid))
        assert balance == Decimal("0.00")

    def test_payment_delete_reverses_billing(self, db):
        """
        Deleting a payment must reverse the billing balance.
        This is the core financial integrity check — a MagicMock test cannot
        verify that the DB actually reflects the reversal.
        """
        prop = make_property(db, assessed_value=100_000.0)
        billing = make_billing(db, property_id=prop.id, assessed_value=100_000.0)
        pay = make_payment(db, property_id=prop.id, amount=2_000.0)

        # Post the payment
        billing.amount_paid = Decimal("2000.00")
        db.commit()

        # Now delete the payment and reverse the billing
        amt = Decimal(str(pay.amount))
        billing.amount_paid = max(Decimal("0"), Decimal(str(billing.amount_paid)) - amt)
        db.delete(pay)
        db.commit()

        refreshed = db.query(PropertyBilling).filter(
            PropertyBilling.id == billing.id
        ).first()
        assert float(refreshed.amount_paid) == pytest.approx(0.0)

        deleted_pay = db.query(Payment).filter(Payment.id == pay.id).first()
        assert deleted_pay is None

    def test_payment_billing_link_cascade_delete(self, db):
        """
        Deleting a Payment must cascade-delete its PaymentBilling links.
        Verifies the cascade="all, delete-orphan" on the ORM relationship
        actually works at the DB level.
        """
        prop = make_property(db)
        billing = make_billing(db, property_id=prop.id)
        pay = make_payment(db, property_id=prop.id)

        link = PaymentBilling(
            payment_id=pay.id,
            billing_id=billing.id,
            tax_year="2024",
            amount_paid=Decimal("2000.00"),
        )
        db.add(link)
        db.commit()

        link_id = link.id
        db.delete(pay)
        db.commit()

        orphan = db.query(PaymentBilling).filter(PaymentBilling.id == link_id).first()
        assert orphan is None

    def test_duplicate_or_number_detection(self, db):
        """
        Two payments with the same OR number for the same property and tax year
        can be detected by query — this is the duplicate payment guard.
        """
        from sqlalchemy import func

        prop = make_property(db)
        make_payment(db, property_id=prop.id, or_number="OR-DUP-001", tax_year="2024")
        db.commit()

        duplicate = db.query(Payment).filter(
            Payment.property_id == prop.id,
            Payment.or_number == "OR-DUP-001",
            func.coalesce(Payment.tax_year, "") == "2024",
        ).first()

        assert duplicate is not None

    def test_partial_payment_balance(self, db):
        """
        A partial payment leaves a non-zero balance on the billing record.
        """
        prop = make_property(db, assessed_value=100_000.0)
        billing = make_billing(db, property_id=prop.id, assessed_value=100_000.0)
        db.commit()

        # Pay only half
        billing.amount_paid = Decimal("1000.00")
        db.commit()

        total_due = Decimal("2000.00")  # 1% basic + 1% SEF
        balance = total_due - Decimal(str(billing.amount_paid))
        assert balance == Decimal("1000.00")


# ---------------------------------------------------------------------------
# Audit log immutability tests
# ---------------------------------------------------------------------------

class TestAuditLogImmutability:
    def test_audit_log_insert_succeeds(self, db):
        """Audit logs can be inserted (append-only)."""
        log = AuditLog(
            username="admin",
            action="TEST_ACTION",
            table_name="properties",
            record_id=1,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(log)
        db.commit()

        found = db.query(AuditLog).filter(AuditLog.action == "TEST_ACTION").first()
        assert found is not None

    def test_audit_log_update_raises(self, db):
        """
        Updating an audit log must raise ValueError due to the SQLAlchemy
        before_update event listener on the AuditLog model.
        """
        log = AuditLog(
            username="admin",
            action="ORIGINAL_ACTION",
            table_name="properties",
            record_id=1,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(log)
        db.commit()

        with pytest.raises(ValueError, match="immutable"):
            log.action = "TAMPERED_ACTION"
            db.commit()

    def test_audit_log_delete_raises(self, db):
        """
        Deleting an audit log must raise ValueError due to the SQLAlchemy
        before_delete event listener on the AuditLog model.
        """
        log = AuditLog(
            username="admin",
            action="DELETE_ME",
            table_name="properties",
            record_id=1,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(log)
        db.commit()

        with pytest.raises(ValueError, match="immutable"):
            db.delete(log)
            db.commit()


# ---------------------------------------------------------------------------
# User lifecycle tests
# ---------------------------------------------------------------------------

class TestUserLifecycle:
    def test_soft_delete_user_revokes_tokens(self, db):
        """
        Soft-deleting a user should allow their refresh tokens to be revoked.
        Verifies the query pattern used in auth_service.delete_user works
        against a real DB.
        """
        user = make_user(db, username="to_delete")
        db.commit()

        rt = RefreshToken(
            user_id=user.id,
            token="token_to_revoke",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            is_revoked=False,
        )
        db.add(rt)
        db.commit()

        # Simulate delete_user: revoke tokens, soft-delete
        db.query(RefreshToken).filter(RefreshToken.user_id == user.id).update(
            {RefreshToken.is_revoked: True}, synchronize_session=False
        )
        user.deleted_at = datetime.now(timezone.utc)
        user.is_active = False
        db.commit()

        # Token must now be revoked
        token = db.query(RefreshToken).filter(
            RefreshToken.token == "token_to_revoke"
        ).first()
        assert token.is_revoked is True

        # User must not appear in active user queries
        active = db.query(User).filter(
            User.username == "to_delete",
            User.deleted_at == None,
        ).first()
        assert active is None

    def test_lockout_query(self, db):
        """
        A user with lockout_until in the future must be detected by the
        lockout check query used in verify_user_login.
        """
        user = make_user(db, username="locked_user")
        user.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.commit()

        locked = db.query(User).filter(
            User.username == "locked_user",
            User.lockout_until > datetime.now(timezone.utc),
        ).first()

        assert locked is not None

    def test_expired_lockout_not_blocked(self, db):
        """
        A user whose lockout_until is in the past must not be blocked.
        """
        user = make_user(db, username="unlocked_user")
        user.lockout_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

        still_locked = db.query(User).filter(
            User.username == "unlocked_user",
            User.lockout_until > datetime.now(timezone.utc),
        ).first()

        assert still_locked is None


# ---------------------------------------------------------------------------
# Cursor-based pagination tests
# ---------------------------------------------------------------------------

class TestCursorPagination:
    def test_assessment_roll_cursor_pagination(self, db):
        """
        Cursor-based pagination on properties returns correct pages and
        has_more flag — verifies the query logic works against real data.
        """
        # Insert 5 properties
        for i in range(1, 6):
            p = Property(
                td_number=f"TD-PAGE-{i:03d}",
                owner_name=f"Owner {i}",
                assessed_value=50_000.0 * i,
                penalty=0.0,
                discount=0.0,
            )
            db.add(p)
        db.commit()

        # Page 1: limit=3, no cursor
        page1 = (
            db.query(Property)
            .filter(Property.deleted_at == None)
            .order_by(Property.id.asc())
            .limit(4)  # limit+1 to detect has_more
            .all()
        )
        has_more = len(page1) > 3
        items = page1[:3]
        assert has_more is True
        assert len(items) == 3

        # Page 2: cursor = last id from page 1
        cursor = items[-1].id
        page2 = (
            db.query(Property)
            .filter(Property.deleted_at == None, Property.id > cursor)
            .order_by(Property.id.asc())
            .limit(4)
            .all()
        )
        has_more_p2 = len(page2) > 3
        items_p2 = page2[:3]
        assert has_more_p2 is False
        assert len(items_p2) == 2  # only 2 remaining

        # No overlap between pages
        page1_ids = {p.id for p in items}
        page2_ids = {p.id for p in items_p2}
        assert page1_ids.isdisjoint(page2_ids)
