# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Payment, PaymentBilling, Property, PropertyAssessmentHistory, PropertyBilling
from backend.services.portal_publish_service import (
    _owner_lookup_hash,
    _snapshot_checksum,
    generate_portal_snapshot,
    portal_snapshot_directory,
    save_portal_snapshot,
)


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


def test_generate_portal_snapshot_is_sanitized_and_checksummed(db, monkeypatch):
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

    monkeypatch.setattr(
        "backend.services.portal_publish_service.mto_config.PORTAL_LOOKUP_SECRET",
        "test-lookup-secret",
    )

    snapshot = generate_portal_snapshot(db)
    record = snapshot["properties"][0]

    assert snapshot["schema_version"] == 2
    assert snapshot["record_count"] == 1
    assert snapshot["checksum"] == _snapshot_checksum({k: v for k, v in snapshot.items() if k != "checksum"})
    assert record["owner_name"] == "J*** D*** C***"
    assert record["pin_masked"] == "1234****7890"
    assert record["td_lookup_hash"]
    assert record["pin_lookup_hash"]
    assert record["payment_history"][0]["or_number"] == "781****"
    assert _owner_lookup_hash("JUAN", "test-lookup-secret") in snapshot["owner_lookup_index"]
    assert snapshot["owner_lookup_index"][_owner_lookup_hash("JUAN", "test-lookup-secret")] == [0]
    assert "JUAN DELA CRUZ" not in str(snapshot)
    assert "7812345" not in str(snapshot)


def test_save_portal_snapshot_uses_configured_directory_and_atomic_files(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.services.portal_publish_service.mto_config.PORTAL_SNAPSHOT_DIR",
        str(tmp_path),
    )
    snapshot = {
        "schema_version": 2,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "record_count": 0,
        "properties": [],
        "owner_lookup_index": {},
        "checksum": "test",
    }

    result = save_portal_snapshot(snapshot)

    assert portal_snapshot_directory() == str(tmp_path.resolve())
    assert result["latest_path"] == str(tmp_path / "portal_snapshot_latest.json")
    assert result["latest_gzip_path"] == str(tmp_path / "portal_snapshot_latest.json.gz")
    assert json.loads((tmp_path / "portal_snapshot_latest.json").read_text(encoding="utf-8")) == snapshot
    assert not list(tmp_path.glob(".portal_snapshot_*"))


def test_snapshot_uses_current_year_assessment_and_labels_future_revaluation(db, monkeypatch):
    current_year = datetime.now(timezone.utc).year
    prop = Property(
        td_number="06-0012-02561",
        owner_name="AGRI COMPONENT CORPORATION",
        barangay="DINADIAWAN",
        assessed_value=7_098_520,
        effectivity_date=f"{current_year + 1}-01-01",
    )
    db.add(prop)
    db.flush()
    db.add(PropertyAssessmentHistory(
        property_id=prop.id,
        td_number=prop.td_number,
        assessed_value=60_080,
        tax_year=str(current_year - 3),
        change_reason="Historical assessment correction",
    ))
    db.add(PropertyBilling(
        property_id=prop.id,
        tax_year=current_year,
        assessed_value=60_080,
        penalty=0,
        discount=0,
        amount_paid=0,
    ))
    db.add(PropertyBilling(
        property_id=prop.id,
        tax_year=current_year + 1,
        assessed_value=7_098_520,
        penalty=0,
        discount=0,
        amount_paid=0,
    ))
    db.commit()

    monkeypatch.setattr(
        "backend.services.portal_publish_service.mto_config.PORTAL_LOOKUP_SECRET",
        "test-lookup-secret",
    )

    record = generate_portal_snapshot(db)["properties"][0]

    assert record["assessed_value"] == 60_080
    assert record["assessment_as_of_year"] == current_year
    assert record["future_assessment"] == {
        "assessed_value": 7_098_520,
        "effective_year": current_year + 1,
    }
    assert [row["tax_year"] for row in record["billing_breakdown"]] == [current_year]


def test_snapshot_keeps_cross_year_credit_unapplied(db, monkeypatch):
    prop = Property(
        td_number="06-0010-00257",
        owner_name="VERIFICATION ACCOUNT",
        barangay="DIBUTUNAN",
        assessed_value=36_900,
    )
    db.add(prop)
    db.flush()
    db.add_all([
        PropertyBilling(
            property_id=prop.id,
            tax_year=2023,
            assessed_value=36_900,
            penalty=0,
            discount=0,
            amount_paid=0,
        ),
        PropertyBilling(
            property_id=prop.id,
            tax_year=2024,
            assessed_value=36_900,
            penalty=0,
            discount=0,
            amount_paid=792,
        ),
    ])
    db.commit()
    monkeypatch.setattr(
        "backend.services.portal_publish_service.mto_config.PORTAL_LOOKUP_SECRET",
        "test-lookup-secret",
    )

    record = generate_portal_snapshot(db)["properties"][0]

    assert record["balance"] == 1269.36
    assert record["total_credit"] == 54.0
    assert record["billing_breakdown"][0]["penalty"] == 531.36
    assert record["billing_breakdown"][1]["credit"] == 54.0


def test_snapshot_uses_single_year_receipt_when_allocation_is_stale(db, monkeypatch):
    prop = Property(
        td_number="06-0010-00999",
        owner_name="PAYMENT TEST",
        barangay="DIBUTUNAN",
        assessed_value=39_600,
    )
    db.add(prop)
    db.flush()
    billing = PropertyBilling(
        property_id=prop.id,
        tax_year=datetime.now(timezone.utc).year,
        assessed_value=39_600,
        penalty=0,
        discount=0,
        amount_paid=738,
    )
    db.add(billing)
    db.flush()
    payment = Payment(
        property_id=prop.id,
        amount=871,
        penalty=79,
        discount=0,
        or_number="8330002",
        tax_year=str(datetime.now(timezone.utc).year),
    )
    db.add(payment)
    db.flush()
    db.add(PaymentBilling(
        payment_id=payment.id,
        billing_id=billing.id,
        tax_year=datetime.now(timezone.utc).year,
        amount_paid=738,
    ))
    db.commit()
    monkeypatch.setattr(
        "backend.services.portal_publish_service.mto_config.PORTAL_LOOKUP_SECRET",
        "test-lookup-secret",
    )

    record = generate_portal_snapshot(db)["properties"][0]
    year = record["billing_breakdown"][0]

    assert year["penalty"] == 79.0
    assert year["total_due"] == 871.0
    assert year["amount_paid"] == 871.0
    assert year["balance"] == 0.0
