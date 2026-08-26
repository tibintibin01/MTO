import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Payment, Property
from backend.routes.admin_tools import td_number_audit
from backend.routes.public import _find_unique_public_property
from backend.services.payment_service import get_payment_ledger
from backend.services.property_service import (
    AmbiguousPropertyError,
    _one_active_property_by_td,
)
from backend.services.search_service import global_search


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _property(td_number, owner):
    return Property(
        td_number=td_number,
        owner_name=owner,
        barangay="LIPIT",
        assessed_value=100_000,
        tax_year="2026",
    )


def test_payment_ledger_is_scoped_to_internal_property_id(db):
    first = _property("06-0017-00249", "FIRST OWNER")
    second = _property("06-0017-00250", "SECOND OWNER")
    db.add_all([first, second])
    db.flush()
    db.add_all(
        [
            Payment(
                property_id=first.id,
                amount=100,
                or_number="SAME-OR",
                tax_year="2026",
                date_paid=datetime(2026, 8, 26),
            ),
            Payment(
                property_id=second.id,
                amount=200,
                or_number="SAME-OR",
                tax_year="2026",
                date_paid=datetime(2026, 8, 26),
            ),
        ]
    )
    db.commit()

    rows = get_payment_ledger(first.id, db_session=db)

    assert len(rows) == 1
    assert float(rows[0][7]) == 100.0


def test_integrity_audit_does_not_merge_same_or_across_properties(db):
    first = _property("06-0017-00249", "FIRST OWNER")
    second = _property("06-0017-00250", "SECOND OWNER")
    db.add_all([first, second])
    db.flush()
    db.add_all(
        [
            Payment(property_id=first.id, amount=100, or_number="12345", tax_year="2026"),
            Payment(property_id=second.id, amount=200, or_number="12345", tax_year="2026"),
        ]
    )
    db.commit()

    result = asyncio.run(
        td_number_audit(current_user={"username": "tester"}, db_session=db)
    )

    assert result["duplicate_payment_count"] == 0
    assert result["duplicate_payments"] == []


def test_integrity_audit_flags_repeat_within_same_property(db):
    prop = _property("06-0017-00249", "FIRST OWNER")
    db.add(prop)
    db.flush()
    db.add_all(
        [
            Payment(property_id=prop.id, amount=100, or_number="12345", tax_year="2026"),
            Payment(property_id=prop.id, amount=100, or_number="12345", tax_year="2026"),
        ]
    )
    db.commit()

    result = asyncio.run(
        td_number_audit(current_user={"username": "tester"}, db_session=db)
    )

    assert result["duplicate_payment_count"] == 1
    assert result["duplicate_payments"][0]["property_id"] == prop.id


def test_public_lookup_refuses_to_guess_between_two_accounts():
    db_session = MagicMock()
    query = db_session.query.return_value
    query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        SimpleNamespace(id=10, td_number="06-0017-00249"),
        SimpleNamespace(id=20, td_number="06-0017-00249"),
    ]

    with pytest.raises(HTTPException) as exc_info:
        _find_unique_public_property("06-0017-00249", db_session)

    assert exc_info.value.status_code == 409


def test_exact_td_resolver_raises_when_account_is_ambiguous(monkeypatch):
    import backend.services.property_service as property_service

    matches = [
        SimpleNamespace(id=10, td_number="06-0017-00249"),
        SimpleNamespace(id=20, td_number="06-0017-00249"),
    ]
    monkeypatch.setattr(
        property_service,
        "get_active_properties_by_td",
        lambda *_args, **_kwargs: matches,
    )

    with pytest.raises(AmbiguousPropertyError):
        _one_active_property_by_td("06-0017-00249", MagicMock())


def test_global_search_uses_property_id_as_navigation_identifier(db):
    prop = _property("06-0017-00249", "FIRST OWNER")
    db.add(prop)
    db.commit()

    result = global_search("00249", db_session=db)

    property_result = next(item for item in result if item["type"] == "property")
    assert property_result["identifier"] == prop.id


def test_command_palette_client_unwraps_results_envelope(monkeypatch):
    import api_clients.search_service as client_search

    expected = [{"type": "property", "identifier": 42}]
    monkeypatch.setattr(
        client_search,
        "api_request",
        lambda *_args, **_kwargs: {"results": expected},
    )

    assert client_search.global_search("00249") == expected
