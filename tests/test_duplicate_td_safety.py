import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import AuditLog, Payment, Property, PropertyBilling
from backend.routes.admin_tools import td_number_audit
from backend.routes.public import _find_unique_public_property
from backend.services.payment_service import get_payment_ledger
from backend.services.property_service import (
    AmbiguousPropertyError,
    _one_active_property_by_td,
    save_property,
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


def _duplicate_payload(td_number="06-0017-00249"):
    return {
        "TD Number": td_number,
        "Owner Name": "SECOND OWNER",
        "Barangay": "LIPIT",
        "Location": "LIPIT",
        "Kind of Property": "RESIDENTIAL LOT",
        "Assessed Value": "120000.00",
        "Effectivity Date": "2026",
    }


def test_duplicate_creation_remains_blocked_when_feature_is_disabled(db):
    db.add(_property("06-0017-00249", "FIRST OWNER"))
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        save_property(
            _duplicate_payload(),
            user={"id": 2, "username": "admin", "role": "admin"},
            db_session=db,
        )

    assert exc_info.value.status_code == 409
    assert db.query(Property).count() == 1


def test_only_admin_can_authorize_duplicate_td(db, monkeypatch):
    monkeypatch.setenv("MTO_ENABLE_VERIFIED_DUPLICATE_TD", "1")
    db.add(_property("06-0017-00249", "FIRST OWNER"))
    db.commit()
    payload = _duplicate_payload()
    payload.update({
        "Verified Duplicate TD": True,
        "Assessor Reference": "ARP-2026-001",
        "Duplicate TD Reason": "Confirmed separate active assessment record.",
        "Duplicate TD Confirmation": "06-0017-00249",
    })

    with pytest.raises(HTTPException) as exc_info:
        save_property(
            payload,
            user={"id": 3, "username": "encoder", "role": "encoder"},
            db_session=db,
        )

    assert exc_info.value.status_code == 403


def test_pilot_mode_blocks_every_other_duplicate_td(db, monkeypatch):
    monkeypatch.setenv("MTO_ENABLE_VERIFIED_DUPLICATE_TD", "1")
    monkeypatch.setenv("MTO_VERIFIED_DUPLICATE_TD_PILOT_TD", "06-0017-00999")
    db.add(_property("06-0017-00249", "FIRST OWNER"))
    db.commit()
    payload = _duplicate_payload()
    payload.update({
        "Verified Duplicate TD": True,
        "Assessor Reference": "ARP-2026-001",
        "Duplicate TD Reason": "Confirmed separate active assessment record.",
        "Duplicate TD Confirmation": "06-0017-00249",
    })

    with pytest.raises(HTTPException) as exc_info:
        save_property(
            payload,
            user={"id": 1, "username": "admin", "role": "admin"},
            db_session=db,
        )

    assert exc_info.value.status_code == 409
    assert "pilot mode" in exc_info.value.detail
    assert db.query(Property).count() == 1


def test_admin_authorization_marks_group_and_audits_every_record(db, monkeypatch):
    monkeypatch.setenv("MTO_ENABLE_VERIFIED_DUPLICATE_TD", "1")
    first = _property("06-0017-00249", "FIRST OWNER")
    db.add(first)
    db.commit()
    payload = _duplicate_payload()
    payload.update({
        "Verified Duplicate TD": True,
        "Assessor Reference": "ARP-2026-001",
        "Duplicate TD Reason": "Confirmed separate active assessment record.",
        "Duplicate TD Confirmation": "06-0017-00249",
    })

    result = save_property(
        payload,
        user={"id": 1, "username": "admin", "role": "admin"},
        db_session=db,
    )

    rows = db.query(Property).order_by(Property.id.asc()).all()
    assert result["verified_duplicate_td"] is True
    assert result["duplicate_group_size"] == 2
    assert len(rows) == 2
    assert all(row.duplicate_td_verified for row in rows)
    assert all(row.duplicate_td_reference == "ARP-2026-001" for row in rows)
    actions = {row.action for row in db.query(AuditLog).all()}
    assert "MARK_VERIFIED_DUPLICATE_TD" in actions
    assert "CREATE_VERIFIED_DUPLICATE_TD" in actions
    billed_property_ids = {
        row[0]
        for row in db.query(PropertyBilling.property_id)
        .filter(PropertyBilling.tax_year == 2026)
        .all()
    }
    assert billed_property_ids == {row.id for row in rows}


def test_ambiguous_previous_td_requires_explicit_property_id(db, monkeypatch):
    first = _property("06-0017-00249", "FIRST OWNER")
    second = _property("06-0017-00249", "SECOND OWNER")
    first.duplicate_td_verified = True
    second.duplicate_td_verified = True
    db.add_all([first, second])
    db.commit()
    payload = _duplicate_payload("06-0017-00999")
    payload["Previous TD Number"] = "06-0017-00249"

    with pytest.raises(HTTPException) as exc_info:
        save_property(
            payload,
            user={"id": 1, "username": "admin", "role": "admin"},
            db_session=db,
        )
    assert exc_info.value.status_code == 422
    assert "Select the exact Previous Property" in exc_info.value.detail

    payload["Previous Property ID"] = first.id
    result = save_property(
        payload,
        user={"id": 1, "username": "admin", "role": "admin"},
        db_session=db,
    )
    child = db.get(Property, result["property_id"])
    assert child.previous_property_id == first.id


def test_integrity_audit_separates_verified_duplicate_group(db):
    first = _property("06-0017-00249", "FIRST OWNER")
    second = _property("06-0017-00249", "SECOND OWNER")
    for item in (first, second):
        item.duplicate_td_verified = True
        item.duplicate_td_reference = "ARP-2026-001"
        item.duplicate_td_reason = "Confirmed separate active assessment record."
        item.duplicate_td_approved_by = "admin"
    db.add_all([first, second])
    db.commit()

    result = asyncio.run(
        td_number_audit(current_user={"username": "tester"}, db_session=db)
    )

    assert result["duplicate_td_count"] == 0
    assert result["verified_duplicate_td_count"] == 2
    assert result["duplicate_tds"] == []
