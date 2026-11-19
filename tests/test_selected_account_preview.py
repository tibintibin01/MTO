"""An existing obligation selects one parcel, not its sibling successors."""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import Payment, PaymentBilling, Property, PropertyBilling
from backend.routes.compute import ComputePaymentRequest, compute_payment
from backend.services import property_service as service


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _property(account_id, td, year, **kwargs):
    return Property(
        id=account_id,
        td_number=td,
        owner_name="SYNTHETIC OWNER",
        assessed_value=100000,
        effectivity_date=f"{year}-01-01",
        **kwargs,
    )


def _split(db, *, explicit=True, billing_state="active", ids=None):
    ids = ids or [70, 30, 90, 10, 80, 20, 60, 40, 50]
    parent = _property(1, "TEST-PARENT", 2020)
    children = [
        _property(
            account_id,
            f"TEST-CHILD-{i}",
            2027,
            previous_property_id=parent.id if explicit else None,
            prev_td_number=parent.td_number,
        )
        for i, account_id in enumerate(ids)
    ]
    db.add_all([parent, *children])
    db.flush()
    if billing_state != "missing":
        db.add_all(
            [
                PropertyBilling(
                    property_id=child.id,
                    tax_year=2027,
                    assessed_value=100000,
                    is_archived=billing_state == "archived",
                )
                for child in children
            ]
        )
    db.commit()
    return parent, children


def _snapshot(db):
    return {
        model.__tablename__: [
            tuple(getattr(row, col.name) for col in model.__table__.columns)
            for row in db.query(model).order_by(model.id).all()
        ]
        for model in (Property, PropertyBilling, Payment, PaymentBilling)
    }


@pytest.mark.parametrize("explicit", [True, False])
@pytest.mark.parametrize("selected_index", [0, 3, 8])
@pytest.mark.parametrize("reverse_ids", [False, True])
def test_preview_reads_only_selected_parcel_and_ancestors(
    db, explicit, selected_index, reverse_ids
):
    ids = list(range(10, 19))
    parent, children = _split(
        db, explicit=explicit, ids=ids[::-1] if reverse_ids else ids
    )
    chosen = children[selected_index]
    before = _snapshot(db)
    result = service.resolve_payment_target(
        chosen.td_number, 2027, db, property_id=chosen.id
    )
    assert result["id"] == chosen.id
    assert result["chain_scope"] == "selected_account_ancestors"
    assert [row["id"] for row in result["chain"]] == [parent.id, chosen.id]
    assert _snapshot(db) == before
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize("billing_state", ["missing", "archived"])
def test_without_active_selected_year_obligation_branch_stays_blocked(
    db, billing_state
):
    _parent, children = _split(db, billing_state=billing_state)
    chosen = children[0]
    sibling_billing = (
        db.query(PropertyBilling)
        .filter(
            PropertyBilling.property_id == children[1].id,
            PropertyBilling.tax_year == 2027,
        )
        .first()
    )
    if sibling_billing is None:
        db.add(
            PropertyBilling(
                property_id=children[1].id, tax_year=2027, is_archived=False
            )
        )
    else:
        sibling_billing.is_archived = False
    db.commit()
    before = _snapshot(db)
    with pytest.raises(service.AmbiguousPropertyError):
        service.resolve_payment_target(
            chosen.td_number, 2027, db, property_id=chosen.id
        )
    assert _snapshot(db) == before


@pytest.mark.parametrize("tax_year", [2026, 2028])
def test_other_year_billing_does_not_select_between_siblings(db, tax_year):
    _parent, children = _split(db)
    chosen = children[0]
    with pytest.raises(service.AmbiguousPropertyError):
        service.resolve_payment_target(
            chosen.td_number, tax_year, db, property_id=chosen.id
        )


def test_searching_shared_parent_does_not_guess_a_child(db):
    parent, _children = _split(db)
    with pytest.raises(service.AmbiguousPropertyError):
        service.resolve_payment_target(
            parent.td_number, 2027, db, property_id=parent.id
        )


def test_without_explicit_account_id_the_complete_branch_stays_blocked(db):
    _parent, children = _split(db)
    with pytest.raises(service.AmbiguousPropertyError):
        service.resolve_payment_target(children[0].td_number, 2027, db)


def test_deleted_account_does_not_fall_back_to_a_different_record(db):
    from datetime import datetime, timezone

    _parent, children = _split(db)
    chosen = children[0]
    chosen.deleted_at = datetime.now(timezone.utc)
    db.commit()
    before = _snapshot(db)
    assert (
        service.resolve_payment_target(
            chosen.td_number, 2027, db, property_id=chosen.id
        )
        is None
    )
    assert _snapshot(db) == before


@pytest.mark.parametrize("selection", [None, 777777])
def test_duplicate_td_still_requires_exact_existing_account(db, selection):
    _parent, children = _split(db)
    children[1].td_number = children[0].td_number
    db.commit()
    if selection is None:
        with pytest.raises(service.AmbiguousPropertyError):
            service.resolve_payment_target(children[0].td_number, 2027, db)
    else:
        assert (
            service.resolve_payment_target(
                children[0].td_number, 2027, db, property_id=selection
            )
            is None
        )
    for chosen in children[:2]:
        result = service.resolve_payment_target(
            chosen.td_number, 2027, db, property_id=chosen.id
        )
        assert result["id"] == chosen.id


def test_mismatched_td_and_explicit_id_never_selects_an_account(db):
    _parent, children = _split(db)
    before = _snapshot(db)
    with pytest.raises(HTTPException) as rejected:
        service.resolve_payment_target(
            children[0].td_number, 2027, db, property_id=children[1].id
        )
    assert rejected.value.status_code == 409
    assert _snapshot(db) == before


@pytest.mark.parametrize(
    "problem", ["cycle", "self", "wrong_parent_text", "ambiguous_legacy_parent"]
)
def test_selected_ancestry_is_still_validated_with_an_existing_obligation(db, problem):
    parent, children = _split(db)
    chosen = children[0]
    if problem == "cycle":
        parent.previous_property_id = chosen.id
        parent.prev_td_number = chosen.td_number
    elif problem == "self":
        chosen.previous_property_id = chosen.id
        chosen.prev_td_number = chosen.td_number
    elif problem == "wrong_parent_text":
        chosen.prev_td_number = "WRONG-PARENT-TEXT"
    else:
        chosen.previous_property_id = None
        db.add(_property(99, parent.td_number, 2020))
    db.commit()
    before = _snapshot(db)
    with pytest.raises(service.AmbiguousPropertyError):
        service.resolve_payment_target(
            chosen.td_number, 2027, db, property_id=chosen.id
        )
    assert _snapshot(db) == before


def test_preview_endpoint_accepts_exact_obligation_but_not_unselected_branch(db):
    from backend.routes.properties import get_current_user, get_db, router

    parent, children = _split(db)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "synthetic-test",
        "role": "admin",
    }
    app.dependency_overrides[get_db] = lambda: db
    before = _snapshot(db)
    with TestClient(app, raise_server_exceptions=False) as client:
        accepted = client.get(
            "/properties/payment-target",
            params={
                "td_number": children[0].td_number,
                "property_id": children[0].id,
                "tax_year": 2027,
            },
        )
        blocked = client.get(
            "/properties/payment-target",
            params={
                "td_number": parent.td_number,
                "property_id": parent.id,
                "tax_year": 2027,
            },
        )
    assert accepted.status_code == 200
    assert accepted.json()["id"] == children[0].id
    assert accepted.json()["chain_scope"] == "selected_account_ancestors"
    assert blocked.status_code == 409
    assert _snapshot(db) == before


@pytest.mark.asyncio
async def test_existing_client_can_calculate_after_selecting_exact_obligation(db):
    _parent, children = _split(db)
    before = _snapshot(db)
    chosen = children[0]
    target = service.resolve_payment_target(
        chosen.td_number, 2027, db, property_id=chosen.id
    )
    result = await compute_payment(
        ComputePaymentRequest(
            assessed_value=100000,
            tax_year=2027,
            date_paid="2026-11-18",
            property_id=target["id"],
        ),
        current_user={"id": 1, "username": "synthetic-test"},
        db_session=db,
    )
    assert result["assessed_value_source"] == "effective_year"
    assert result["net_amount_due"] == pytest.approx(1600)
    assert _snapshot(db) == before


def test_genuine_posting_uses_only_selected_billing_and_preserves_siblings(
    db, monkeypatch
):
    from datetime import datetime

    _parent, children = _split(db)
    chosen = children[0]
    sibling_billing = (
        db.query(PropertyBilling)
        .filter(
            PropertyBilling.property_id == children[1].id,
            PropertyBilling.tax_year == 2027,
        )
        .one()
    )
    previous_payment = Payment(
        property_id=children[1].id,
        amount=1600,
        penalty=0,
        discount=400,
        or_number="SYNTHETIC-PRIOR-OR",
        date_paid=datetime(2026, 11, 1),
        tax_year="2027",
    )
    db.add(previous_payment)
    db.flush()
    db.add(
        PaymentBilling(
            payment_id=previous_payment.id,
            billing_id=sibling_billing.id,
            tax_year=2027,
            amount_paid=1600,
        )
    )
    sibling_billing.amount_paid = 1600
    sibling_billing.discount = 400
    db.commit()
    sibling_before = _snapshot(db)
    monkeypatch.setattr(
        service, "_refresh_dashboard_stats_after_payment", lambda _db: None
    )
    payload = {
        "TD Number": chosen.td_number,
        "Owner Name": chosen.owner_name,
        "Assessed Value": "100000",
        "Tax Year": "2027",
        "OR Number": "SYNTHETIC-OR-001",
        "OR Date": "2026-11-18",
        "Penalty": "0",
        "Discount": "400",
        "Amount Paid": "1600",
    }
    result = service.save_property(
        payload,
        editing_id=chosen.id,
        user={"id": 1, "username": "synthetic-test", "role": "admin"},
        db_session=db,
    )
    assert result["ok"] is True
    assert result["property_id"] == chosen.id
    posted = db.query(Payment).filter(Payment.property_id == chosen.id).one()
    allocated = (
        db.query(PaymentBilling).filter(PaymentBilling.payment_id == posted.id).one()
    )
    billing = (
        db.query(PropertyBilling)
        .filter(PropertyBilling.id == allocated.billing_id)
        .one()
    )
    assert posted.property_id == billing.property_id == chosen.id
    assert allocated.payment_id == posted.id
    assert float(posted.amount) == float(allocated.amount_paid) == 1600
    assert _snapshot(db)["properties"] == sibling_before["properties"]
    assert [
        row for row in _snapshot(db)["property_billings"] if row[1] != chosen.id
    ] == [row for row in sibling_before["property_billings"] if row[1] != chosen.id]
    assert [
        row for row in _snapshot(db)["payments"] if row[0] != posted.id
    ] == sibling_before["payments"]
    assert [
        row for row in _snapshot(db)["payment_billings"] if row[0] != allocated.id
    ] == sibling_before["payment_billings"]
