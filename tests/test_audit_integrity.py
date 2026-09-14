from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import AuditChainState, AuditLog, Property
from backend.services.audit_integrity_service import (
    canonical_snapshot,
    verify_audit_chain,
)
from backend.services.history_service import log_data_change, undo_last_action


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_sealed_events_verify_and_preserve_decimal_text(db):
    log_data_change(
        user_id=7,
        username="auditor",
        table_name="payments",
        record_id=41,
        action="CREATE",
        after={"amount": Decimal("397.42"), "tax_year": 2026},
        db_session=db,
    )
    log_data_change(
        user_id=7,
        username="auditor",
        table_name="payments",
        record_id=41,
        action="UPDATE",
        before={"amount": Decimal("397.42")},
        after={"amount": Decimal("400.00")},
        db_session=db,
    )
    db.commit()

    result = verify_audit_chain(db)
    rows = db.query(AuditLog).order_by(AuditLog.id.asc()).all()

    assert result["status"] == "verified"
    assert result["event_count"] == 2
    assert result["live_event_count"] == 2
    assert rows[0].previous_hash != rows[0].current_hash
    assert rows[1].previous_hash == rows[0].current_hash
    assert '"397.42"' in rows[0].new_values
    assert db.query(AuditChainState).one().head_audit_id == rows[1].id


def test_verifier_detects_raw_database_tampering(db):
    log_data_change(
        user_id=1,
        username="admin",
        table_name="properties",
        record_id=10,
        action="UPDATE",
        before={"barangay": "OLD"},
        after={"barangay": "NEW"},
        db_session=db,
    )
    db.commit()
    audit_id = db.query(AuditLog.id).scalar()

    db.execute(
        text("UPDATE audit_logs SET action='TAMPERED' WHERE id=:audit_id"),
        {"audit_id": audit_id},
    )
    db.commit()

    result = verify_audit_chain(db)

    assert result["status"] == "failed"
    assert {item["code"] for item in result["failures"]} == {"CURRENT_HASH_MISMATCH"}


def test_writer_fails_closed_after_an_unsealed_insert(db):
    log_data_change(
        user_id=1,
        username="admin",
        table_name="properties",
        record_id=10,
        action="CREATE",
        after={"id": 10},
        db_session=db,
    )
    db.commit()
    db.execute(
        text(
            "INSERT INTO audit_logs (username, action, timestamp) "
            "VALUES ('bypass', 'RAW_INSERT', CURRENT_TIMESTAMP)"
        )
    )
    db.commit()

    with pytest.raises(RuntimeError, match="Failed to write audit log"):
        log_data_change(
            user_id=1,
            username="admin",
            table_name="properties",
            record_id=11,
            action="CREATE",
            after={"id": 11},
            db_session=db,
        )


def test_undo_appends_compensating_event_and_keeps_original(db):
    prop = Property(
        td_number="06-0099-00001",
        owner_name="NEW OWNER",
        assessed_value=Decimal("100000.00"),
    )
    db.add(prop)
    db.flush()
    log_data_change(
        user_id=9,
        username="operator",
        table_name="properties",
        record_id=prop.id,
        action="UPDATE",
        before={"owner_name": "OLD OWNER"},
        after={"owner_name": "NEW OWNER"},
        db_session=db,
    )
    db.commit()
    original_id = db.query(AuditLog.id).scalar()

    success, message = undo_last_action(9, db_session=db)
    db.commit()

    events = db.query(AuditLog).order_by(AuditLog.id.asc()).all()
    assert success is True
    assert "Successfully reversed" in message
    assert db.get(Property, prop.id).owner_name == "OLD OWNER"
    assert len(events) == 2
    assert events[0].id == original_id
    assert events[1].compensates_audit_id == original_id
    assert verify_audit_chain(db)["status"] == "verified"


def test_canonical_snapshot_is_order_stable():
    left = canonical_snapshot({"b": 2, "a": Decimal("1.20")})
    right = canonical_snapshot({"a": Decimal("1.20"), "b": 2})

    assert left == right == '{"a":"1.20","b":2}'
