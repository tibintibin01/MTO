"""Synthetic regression coverage; no production database or office records."""

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import Payment, PaymentBilling, Property, PropertyBilling
from backend.services import property_service as service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _property(td, year, **kwargs):
    return Property(
        td_number=td,
        owner_name="SYNTHETIC OWNER",
        barangay="LOB BOT TEST",
        location="LOB BOT TEST",
        kind_of_property="AGRICULTURAL",
        assessed_value=100_000,
        effectivity_date=f"{year}-01-01" if year is not None else None,
        tax_year=str(year) if year is not None else None,
        **kwargs,
    )


def _chain(db, *, explicit=True, ids=(30, 20, 10)):
    oldest = _property("TEST-OLDEST", 2023, id=ids[0])
    db.add(oldest)
    db.flush()
    previous = _property(
        "TEST-PREVIOUS",
        2025,
        id=ids[1],
        prev_td_number=oldest.td_number,
        previous_property_id=oldest.id if explicit else None,
    )
    db.add(previous)
    db.flush()
    current = _property(
        "TEST-CURRENT",
        2025,
        id=ids[2],
        prev_td_number=previous.td_number,
        previous_property_id=previous.id if explicit else None,
    )
    db.add(current)
    db.flush()
    db.add(
        PropertyBilling(
            property_id=current.id,
            tax_year=2026,
            assessed_value=100_000,
            penalty=0,
            discount=400,
            amount_paid=1600,
            is_archived=False,
        )
    )
    db.commit()
    return oldest, previous, current


def _snapshot(rows):
    return [
        tuple(getattr(row, column.name) for column in row.__table__.columns)
        for row in rows
    ]


@pytest.mark.parametrize("explicit", [True, False])
@pytest.mark.parametrize("ids", [(30, 20, 10), (10, 30, 20)])
@pytest.mark.parametrize("selected_index", [0, 1, 2])
def test_same_year_successor_uses_lineage_not_id_or_selected_seed(
    db, explicit, ids, selected_index
):
    chain = _chain(db, explicit=explicit, ids=ids)
    selected = chain[selected_index]
    before = _snapshot(db.query(Property).order_by(Property.id).all())

    result = service.resolve_property_for_tax_year(
        selected.td_number, 2027, db, property_id=selected.id
    )

    assert result.id == chain[-1].id
    assert _snapshot(db.query(Property).order_by(Property.id).all()) == before
    assert db.query(PropertyBilling).count() == 1
    assert db.query(Payment).count() == 0


@pytest.mark.parametrize("explicit", [True, False])
def test_2026_existing_billing_and_2027_missing_billing_use_same_account(db, explicit):
    _oldest, _previous, current = _chain(db, explicit=explicit)
    for year in (2026, 2027):
        assert (
            service.resolve_payment_property_for_tax_year(
                current.td_number, year, db, property_id=current.id
            ).id
            == current.id
        )
    assert (
        service.resolve_payment_target(
            current.td_number, 2027, db, property_id=current.id
        )["id"]
        == current.id
    )
    assert db.query(PropertyBilling).count() == 1  # Resolution creates no billing.


def test_more_than_two_same_year_versions_resolve_to_last_successor(db):
    _oldest, _previous, current = _chain(db)
    newer = _property(
        "TEST-NEWER",
        2025,
        previous_property_id=current.id,
        prev_td_number=current.td_number,
    )
    db.add(newer)
    db.commit()
    assert (
        service.resolve_property_for_tax_year(
            current.td_number, 2027, db, property_id=current.id
        ).id
        == newer.id
    )


def test_future_successor_does_not_replace_current_before_its_year(db):
    oldest, previous, current = _chain(db)
    future = _property(
        "TEST-FUTURE",
        2028,
        previous_property_id=current.id,
        prev_td_number=current.td_number,
    )
    db.add(future)
    db.commit()
    for year, expected in (
        (2024, oldest),
        (2025, current),
        (2027, current),
        (2028, future),
    ):
        assert (
            service.resolve_property_for_tax_year(
                previous.td_number, year, db, property_id=previous.id
            ).id
            == expected.id
        )


def test_existing_requested_billing_stays_authoritative(db):
    _oldest, previous, _current = _chain(db)
    db.add(PropertyBilling(property_id=previous.id, tax_year=2027, is_archived=False))
    db.commit()
    assert (
        service.resolve_payment_property_for_tax_year(
            previous.td_number, 2027, db, property_id=previous.id
        ).id
        == previous.id
    )


def test_archived_billing_does_not_override_same_year_successor(db):
    _oldest, previous, current = _chain(db)
    db.add(PropertyBilling(property_id=previous.id, tax_year=2027, is_archived=True))
    db.commit()
    assert (
        service.resolve_payment_property_for_tax_year(
            previous.td_number, 2027, db, property_id=previous.id
        ).id
        == current.id
    )


def _payment_payload(current):
    return {
        "TD Number": current.td_number,
        "Owner Name": current.owner_name,
        "Barangay": current.barangay,
        "Location": current.location,
        "Kind of Property": current.kind_of_property,
        "Assessed Value": "100000",
        "Tax Year": "2027",
        "OR Number": "TEST20270001",
        "OR Date": "2026-11-05",
        "Penalty": "0",
        "Discount": "400",
        "Amount Paid": "1600",
    }


@pytest.mark.parametrize("explicit", [True, False])
def test_new_payment_keeps_old_td_history_and_old_financial_rows(
    db, monkeypatch, explicit
):
    _oldest, _previous, current = _chain(db, explicit=explicit)
    old_billing = db.query(PropertyBilling).one()
    old_payment = Payment(
        property_id=current.id,
        amount=1600,
        penalty=0,
        discount=400,
        tax_year="2026",
        or_number="TEST20260001",
        date_paid=datetime(2025, 11, 5),
    )
    db.add(old_payment)
    db.flush()
    db.add(
        PaymentBilling(
            payment_id=old_payment.id,
            billing_id=old_billing.id,
            tax_year=2026,
            amount_paid=1600,
        )
    )
    db.commit()
    before_properties = _snapshot(db.query(Property).order_by(Property.id).all())
    before_billing = _snapshot([old_billing])
    before_payment = _snapshot([old_payment])
    before_link = _snapshot(db.query(PaymentBilling).all())
    monkeypatch.setattr(
        service, "_refresh_dashboard_stats_after_payment", lambda _db: None
    )

    result = service.save_property(
        _payment_payload(current),
        editing_id=current.id,
        user={"id": 1, "username": "synthetic-tester", "role": "admin"},
        db_session=db,
    )

    assert result["payment_only"] is True
    assert result["target_changed"] is False
    assert result["property_id"] == current.id
    assert (
        _snapshot(db.query(Property).order_by(Property.id).all()) == before_properties
    )
    assert _snapshot([db.get(PropertyBilling, old_billing.id)]) == before_billing
    assert _snapshot([db.get(Payment, old_payment.id)]) == before_payment
    assert (
        _snapshot(
            db.query(PaymentBilling)
            .filter(PaymentBilling.payment_id == old_payment.id)
            .all()
        )
        == before_link
    )
    new_payment = db.query(Payment).filter(Payment.tax_year == "2027").one()
    new_billing = (
        db.query(PropertyBilling).filter(PropertyBilling.tax_year == 2027).one()
    )
    new_link = (
        db.query(PaymentBilling)
        .filter(PaymentBilling.payment_id == new_payment.id)
        .one()
    )
    assert new_payment.property_id == new_billing.property_id == current.id
    assert (
        float(new_payment.amount)
        == float(new_billing.amount_paid)
        == float(new_link.amount_paid)
        == 1600
    )
    assert float(new_payment.discount) == float(new_billing.discount) == 400
    assert float(new_payment.penalty) == float(new_billing.penalty) == 0


@pytest.mark.parametrize(
    "problem", ["branch", "cycle", "self", "conflict", "reverse_year", "unknown_bridge"]
)
def test_unsafe_lineage_never_resolves_by_sort_order(db, problem):
    oldest, previous, current = _chain(db)
    if problem == "branch":
        db.add(
            _property(
                "TEST-SIBLING",
                2025,
                previous_property_id=previous.id,
                prev_td_number=previous.td_number,
            )
        )
    elif problem == "cycle":
        previous.previous_property_id = current.id
        previous.prev_td_number = current.td_number
    elif problem == "self":
        current.previous_property_id = current.id
        current.prev_td_number = current.td_number
    elif problem == "conflict":
        current.prev_td_number = "TEST-DISAGREES-WITH-PARENT-ID"
    elif problem == "reverse_year":
        oldest.effectivity_date = "2025-01-01"
        previous.effectivity_date = "2024-01-01"
    else:
        oldest.effectivity_date = "2025-01-01"
        previous.effectivity_date = None
        previous.tax_year = None
    db.commit()
    before = _snapshot(db.query(Property).order_by(Property.id).all())
    with pytest.raises(service.AmbiguousPropertyError):
        service.resolve_property_for_tax_year(
            current.td_number, 2027, db, property_id=current.id
        )
    assert _snapshot(db.query(Property).order_by(Property.id).all()) == before
    assert db.query(Payment).count() == 0


def test_duplicate_td_accounts_still_require_selection_and_stay_separate(db):
    first = _property("TEST-DUPLICATE", 2025)
    second = _property("TEST-DUPLICATE", 2025)
    db.add_all([first, second])
    db.commit()
    with pytest.raises(
        service.AmbiguousPropertyError, match="2 active properties use TD"
    ):
        service.resolve_property_for_tax_year(first.td_number, 2027, db)
    for selected in (first, second):
        assert (
            service.resolve_property_for_tax_year(
                selected.td_number, 2027, db, property_id=selected.id
            ).id
            == selected.id
        )


def test_ambiguous_legacy_parent_is_not_disambiguated_by_effectivity_year(db):
    first = _property("TEST-DUPLICATE", 2025)
    second = _property("TEST-DUPLICATE", 2025)
    child = _property("TEST-CHILD", 2025, prev_td_number=first.td_number)
    db.add_all([first, second, child])
    db.commit()
    with pytest.raises(service.AmbiguousPropertyError):
        service.resolve_property_for_tax_year(
            child.td_number, 2027, db, property_id=child.id
        )


def test_branch_save_returns_conflict_and_rolls_back_without_creating_payment(db):
    _oldest, previous, current = _chain(db)
    db.add(
        _property(
            "TEST-SIBLING",
            2025,
            previous_property_id=previous.id,
            prev_td_number=previous.td_number,
        )
    )
    db.commit()
    with pytest.raises(HTTPException) as failure:
        service.save_property(
            _payment_payload(current),
            editing_id=current.id,
            user={"id": 1, "username": "synthetic-tester", "role": "admin"},
            db_session=db,
        )
    assert failure.value.status_code == 409
    assert "history" in str(failure.value.detail).lower()
    assert "active properties use TD" not in str(failure.value.detail)
    assert db.query(Payment).count() == 0
    assert (
        db.query(PropertyBilling).filter(PropertyBilling.tax_year == 2027).count() == 0
    )


def test_payment_target_endpoint_reports_history_conflict_without_duplicate_claim(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.routes.properties import get_current_user, get_db, router

    _oldest, previous, current = _chain(db)
    db.add(
        _property(
            "TEST-SIBLING",
            2025,
            previous_property_id=previous.id,
            prev_td_number=previous.td_number,
        )
    )
    db.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "synthetic-tester",
        "role": "admin",
    }
    app.dependency_overrides[get_db] = lambda: db
    # The sync endpoint uses a worker thread; the fixture shares one isolated
    # in-memory connection rather than connecting to an application database.
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/properties/payment-target",
            params={
                "td_number": current.td_number,
                "tax_year": 2027,
                "property_id": current.id,
            },
        )
    assert response.status_code == 409
    message = response.json()["detail"]["message"]
    assert "history" in message.lower()
    assert "active properties use TD" not in message
    assert db.query(Payment).count() == 0


def test_same_year_tie_does_not_follow_ambiguous_legacy_child_of_duplicate_parent(db):
    first = _property("TEST-DUPLICATE", 2025)
    second = _property("TEST-DUPLICATE", 2025)
    child = _property("TEST-CHILD", 2025, prev_td_number=first.td_number)
    db.add_all([first, second, child])
    db.commit()
    with pytest.raises(service.AmbiguousPropertyError):
        service.resolve_property_for_tax_year(
            first.td_number, 2027, db, property_id=first.id
        )


def test_explicit_same_year_parent_link_preserves_duplicate_account_isolation(db):
    first = _property("TEST-DUPLICATE", 2025)
    second = _property("TEST-DUPLICATE", 2025)
    db.add_all([first, second])
    db.flush()
    child = _property(
        "TEST-CHILD",
        2025,
        previous_property_id=first.id,
        prev_td_number=first.td_number,
    )
    db.add(child)
    db.commit()
    assert (
        service.resolve_property_for_tax_year(
            child.td_number, 2027, db, property_id=child.id
        ).id
        == child.id
    )
    assert (
        service.resolve_property_for_tax_year(
            second.td_number, 2027, db, property_id=second.id
        ).id
        == second.id
    )
