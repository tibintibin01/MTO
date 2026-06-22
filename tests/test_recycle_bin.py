# -*- coding: utf-8 -*-
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property
from backend.services.property_service import get_deleted_properties, soft_delete_property


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(eng)
    eng.dispose()


def _deleted_property(td_number, owner, deleted_at):
    return Property(
        td_number=td_number,
        owner_name=owner,
        barangay="DINADIAWAN",
        assessed_value=100_000.0,
        deleted_at=deleted_at,
    )


def test_recycle_bin_orders_by_recently_deleted_first(db):
    older_deleted = _deleted_property(
        "TD-OLDER-DELETE",
        "Older Delete",
        datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc),
    )
    newer_deleted = _deleted_property(
        "TD-NEWER-DELETE",
        "Newer Delete",
        datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
    )
    db.add_all([older_deleted, newer_deleted])
    db.commit()

    rows = get_deleted_properties(db_session=db)["items"]

    assert rows[0][1] == "TD-NEWER-DELETE"
    assert rows[0][5] == "2026-06-01 08:00"
    assert rows[1][1] == "TD-OLDER-DELETE"

def test_soft_delete_returns_confirmation_payload(db):
    prop = Property(
        td_number="TD-SOFT-DELETE-CONFIRM",
        owner_name="Delete Confirm Owner",
        barangay="DINADIAWAN",
        assessed_value=50_000.0,
    )
    db.add(prop)
    db.commit()

    result = soft_delete_property(
        prop.id,
        user={"id": 1, "username": "admin", "role": "admin"},
        db_session=db,
    )

    assert result["id"] == prop.id
    assert result["td_number"] == "TD-SOFT-DELETE-CONFIRM"
    assert result["deleted_at"]
    assert db.query(Property).filter(Property.id == prop.id).first().deleted_at is not None


def test_property_delete_client_requires_live_server(monkeypatch):
    import api_clients.property_service as client

    captured = {}

    def fake_api_request(method, endpoint, **kwargs):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured.update(kwargs)
        return {"status": "deleted"}

    monkeypatch.setattr(client, "api_request", fake_api_request)

    result = client.delete_property(123)

    assert result == {"status": "deleted"}
    assert captured["method"] == "DELETE"
    assert captured["endpoint"] == "/properties/123"
    assert captured["queue_offline"] is False

