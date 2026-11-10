"""Synthetic Tax Bill discovery; never uses the production DB, vault or cloud."""

from datetime import date, datetime
import sqlite3
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from backend.database import Base
from backend.models import Payment, Property, PropertyBilling, TaxPolicy
from backend.services import billing_service as billing
from backend.services.tax_bill_search_service import search_tax_bill_properties


@pytest.fixture(params=["YEAR", "VARCHAR(100)", "DATE", "TIMESTAMP"])
def db(request):
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        native_datetime=True,
        connect_args={
            "check_same_thread": False,
            "detect_types": sqlite3.PARSE_DECLTYPES,
        },
    )
    Base.metadata.create_all(engine)
    if request.param in ("DATE", "TIMESTAMP"):
        ddl = str(CreateTable(Property.__table__).compile(engine)).replace(
            "effectivity_date VARCHAR(100)", f"effectivity_date {request.param}"
        )
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE properties"))
            connection.execute(text(ddl))
    effective = "2027-01-01 00:00:00" if request.param == "TIMESTAMP" else "2027-01-01"
    if request.param == "YEAR":
        effective = "2027"
    with Session(engine) as session:
        session.add_all(
            [
                Property(
                    id=10,
                    td_number="SYNTHETIC-TD",
                    owner_name="NEW OWNER",
                    pin="TEST-PIN",
                    lot_number="LOT-X",
                    location="TEST PLACE",
                    effectivity_date=effective,
                    tax_year="2027",
                    assessed_value=100_000,
                ),
                Property(
                    id=20,
                    td_number="SYNTHETIC-TD",
                    owner_name="DIFFERENT OWNER",
                    effectivity_date=effective,
                    tax_year="2027",
                    assessed_value=200_000,
                ),
                Property(
                    id=30,
                    td_number="DELETED-TD",
                    owner_name="NEW OWNER",
                    deleted_at=datetime(2026, 11, 1),
                ),
                Property(id=40, td_number="LITERAL-%_", owner_name="WILDCARD OWNER"),
                # Synthetic configured rates only; no determination of legal entitlement.
                TaxPolicy(
                    tax_year=2027,
                    basic_rate="0.01",
                    sef_rate="0.01",
                    penalty_rate="0.02",
                ),
            ]
        )
        session.commit()
        yield session
        session.rollback()
    engine.dispose()


def test_future_unpaid_declarations_are_searchable_but_not_marked_compliant(db):
    statements = []
    listener = lambda _c, _cu, sql, *_a: statements.append(sql)
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        page = search_tax_bill_properties("synthetic-td", db_session=db)
        assert [r["id"] for r in page["items"]] == [20, 10]
        assert page["has_more"] is False and page["next_cursor"] is None
        for compliant in (
            billing.get_compliant_accounts,
            billing.get_compliant_accounts_v2,
        ):
            for year in (2026, 2027):
                assert compliant(as_of_year=year, db_session=db)["items"] == []
        for pid, assessed in ((10, 100_000), (20, 200_000)):
            result = billing.get_property_tax_bill_data(
                pid, 2027, as_of_date=date(2026, 11, 10), db_session=db
            )
            assert result["id"] == pid and result["tax_year"] == 2027
            assert result["assessed_value"] == assessed
            assert result["calculation_source"] == "VIRTUAL_ADVANCE"
            assert result["billing_record_exists"] is False
            assert result["compliant_through_year"] is None
        assert db.query(PropertyBilling).count() == 0
        assert db.query(Payment).count() == 0
        assert all(
            sql.lstrip().upper().startswith(("SELECT", "PRAGMA")) for sql in statements
        )
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)


@pytest.mark.parametrize("term", ["NEW OWNER", "TEST-PIN", "TEST PLACE", "LOT-X"])
def test_search_does_not_require_a_billing_or_payment_and_omits_deleted(db, term):
    page = search_tax_bill_properties(term, db_session=db)
    assert [r["id"] for r in page["items"]] == [10]
    assert page["items"][0]["effectivity"].startswith("2027")
    assert "or_number" not in page["items"][0]
    assert "assessed_value" not in page["items"][0]


def test_duplicate_accounts_page_in_stable_id_order_with_no_skips(db):
    first = search_tax_bill_properties("SYNTHETIC", limit=1, db_session=db)
    assert [r["id"] for r in first["items"]] == [20]
    assert first["has_more"] and first["next_cursor"] == 20
    last = search_tax_bill_properties("SYNTHETIC", limit=1, cursor=20, db_session=db)
    assert [r["id"] for r in last["items"]] == [10]
    assert last["has_more"] is False and last["next_cursor"] is None


def test_search_wildcards_are_literal_and_unknown_returns_empty(db):
    assert [
        r["id"] for r in search_tax_bill_properties("%_", db_session=db)["items"]
    ] == [40]
    assert (
        search_tax_bill_properties("not a known declaration", db_session=db)["items"]
        == []
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"search": " "},
        {"search": "X" * 101},
        {"search": "X", "limit": 101},
        {"search": "X", "limit": 0},
        {"search": "X", "cursor": 0},
        {"search": "X", "cursor": True},
        {"search": "X", "limit": True},
    ],
)
def test_search_rejects_unbounded_or_invalid_parameters(db, kwargs):
    with pytest.raises(ValueError):
        search_tax_bill_properties(**kwargs, db_session=db)


def test_advance_bill_still_requires_policy_and_effective_assessment(db):
    with pytest.raises(billing.TaxBillUnavailableError, match="2028 Tax Policy"):
        billing.get_property_tax_bill_data(
            10, 2028, as_of_date=date(2026, 11, 10), db_session=db
        )
    db.add(
        TaxPolicy(
            tax_year=2026, basic_rate="0.01", sef_rate="0.01", penalty_rate="0.02"
        )
    )
    db.commit()
    with pytest.raises(
        billing.TaxBillUnavailableError, match="No assessment is effective"
    ):
        billing.get_property_tax_bill_data(
            10, 2026, as_of_date=date(2025, 11, 10), db_session=db
        )
    assert db.query(PropertyBilling).count() == 0


def test_replaced_account_cannot_get_an_invented_future_bill_or_be_silently_retargeted(
    db,
):
    successor = db.get(Property, 20)
    successor.previous_property_id = 10
    db.commit()
    with pytest.raises(billing.TaxBillUnavailableError, match="explicitly select"):
        billing.get_property_tax_bill_data(
            10, 2027, as_of_date=date(2026, 11, 10), db_session=db
        )
    result = billing.get_property_tax_bill_data(
        20, 2027, as_of_date=date(2026, 11, 10), db_session=db
    )
    assert result["id"] == 20 and result["assessed_value"] == 200_000
    assert db.query(PropertyBilling).count() == 0


def test_deleted_account_has_no_tax_bill(db):
    assert (
        billing.get_property_tax_bill_data(
            30, 2027, as_of_date=date(2026, 11, 10), db_session=db
        )
        is None
    )


def test_authenticated_route_is_not_swallowed_by_property_id_route(db):
    from backend.routes.properties import router, get_current_user, get_db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {
        "username": "synthetic",
        "role": "viewer",
    }
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        result = client.get(
            "/properties/tax-bill-candidates",
            params={"search": "SYNTHETIC", "limit": 1},
        )
        assert result.status_code == 200
        assert [r["id"] for r in result.json()["items"]] == [20]
        assert (
            client.get(
                "/properties/tax-bill-candidates", params={"search": " ", "limit": 1}
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/properties/tax-bill-candidates", params={"search": "X", "limit": 101}
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/properties/tax-bill-candidates", params={"search": "X", "cursor": 0}
            ).status_code
            == 422
        )
        app.dependency_overrides.pop(get_current_user)
        assert (
            client.get(
                "/properties/tax-bill-candidates", params={"search": "X"}
            ).status_code
            == 401
        )


def test_client_search_is_fresh_without_compliance_or_effectivity_filter():
    from api_clients import property_service

    with (
        patch.object(property_service, "api_request", return_value={}) as request,
        patch.object(property_service, "api_request_with_cache") as cached,
    ):
        property_service.search_tax_bill_properties(" SYNTHETIC ", cursor=21)
        request.assert_called_once_with(
            "GET",
            "/properties/tax-bill-candidates",
            params={"search": "SYNTHETIC", "limit": 50, "cursor": 21},
        )
        cached.assert_not_called()
