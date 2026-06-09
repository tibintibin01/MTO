# -*- coding: utf-8 -*-
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Payment, Property, PropertyBilling
from backend.services.portal_publish_service import _snapshot_checksum, generate_portal_snapshot


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


def test_generate_portal_snapshot_is_sanitized_and_checksummed(db):
    prop = Property(
        td_number="06-0012-01379",
        owner_name="JUAN DELA CRUZ",
        pin="1234567890",
        barangay="DINADIAWAN",
        location="DINADIAWAN",
        kind_of_property="RESIDENTIAL LOT",
        assessed_value=100_000,
    )
    db.add(prop)
    db.flush()
    db.add(PropertyBilling(
        property_id=prop.id,
        tax_year=2024,
        assessed_value=100_000,
        penalty=0,
        discount=0,
        amount_paid=2_000,
    ))
    db.add(Payment(
        property_id=prop.id,
        amount=2_000,
        or_number="7812345",
        date_paid=datetime(2026, 1, 15, tzinfo=timezone.utc),
        tax_year="2024",
    ))
    db.commit()

    snapshot = generate_portal_snapshot(db)
    record = snapshot["properties"][0]

    assert snapshot["record_count"] == 1
    assert snapshot["checksum"] == _snapshot_checksum({k: v for k, v in snapshot.items() if k != "checksum"})
    assert record["owner_name"] == "J*** D*** C***"
    assert record["pin_masked"] == "1234****7890"
    assert record["payment_history"][0]["or_number"] == "781****"
    assert "JUAN DELA CRUZ" not in str(snapshot)
    assert "7812345" not in str(snapshot)
