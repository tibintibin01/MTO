from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Payment, Property, ReceiptHistory
from backend.services.payment_service import save_receipt_record


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _fk(connection, _):
        connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _payment(db):
    prop = Property(
        td_number="TD-RECEIPT", owner_name="Receipt Test", assessed_value=100_000
    )
    db.add(prop)
    db.flush()
    payment = Payment(
        property_id=prop.id,
        amount=2_000,
        or_number="OR-RECEIPT",
        tax_year="2026",
        date_paid=datetime(2026, 1, 1),
    )
    db.add(payment)
    db.flush()
    return prop, payment


def test_client_controlled_old_path_is_never_deleted(db, tmp_path, monkeypatch):
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    outside_file = tmp_path / "outside.pdf"
    outside_file.write_bytes(b"must remain")
    prop, payment = _payment(db)
    db.add(
        ReceiptHistory(
            property_id=prop.id,
            payment_id=payment.id,
            or_number=payment.or_number,
            amount=payment.amount,
            file_path=str(outside_file),
            generated_by="cashier",
            generated_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    monkeypatch.setattr(
        "backend.services.payment_service._LOCAL_RECEIPT_ROOTS",
        (trusted_root.resolve(),),
    )

    save_receipt_record(
        prop.id,
        payment.id,
        {"or_number": payment.or_number},
        "C:/attacker/next.pdf",
        "cashier",
        current_user={"username": "cashier", "role": "cashier"},
        db_session=db,
    )

    assert outside_file.read_bytes() == b"must remain"


def test_server_receipt_cleanup_stays_inside_trusted_directory(
    db, tmp_path, monkeypatch
):
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    old_file = trusted_root / "old.pdf"
    new_file = trusted_root / "new.pdf"
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")
    prop, payment = _payment(db)
    db.add(
        ReceiptHistory(
            property_id=prop.id,
            payment_id=payment.id,
            or_number=payment.or_number,
            amount=payment.amount,
            file_path=str(old_file),
            generated_by="cashier",
            generated_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    monkeypatch.setattr(
        "backend.services.payment_service._LOCAL_RECEIPT_ROOTS",
        (trusted_root.resolve(),),
    )

    save_receipt_record(
        prop.id,
        payment.id,
        {"or_number": payment.or_number},
        str(new_file),
        "cashier",
        current_user={"username": "cashier", "role": "cashier"},
        db_session=db,
    )

    assert not old_file.exists()
    assert new_file.exists()


def test_receipt_property_must_match_payment(db, tmp_path):
    prop, payment = _payment(db)
    other = Property(td_number="TD-OTHER", owner_name="Other", assessed_value=100_000)
    db.add(other)
    db.commit()

    with pytest.raises(ValueError, match="does not match"):
        save_receipt_record(
            other.id,
            payment.id,
            {"or_number": payment.or_number},
            str(tmp_path / "receipt.pdf"),
            "cashier",
            current_user={"username": "cashier", "role": "cashier"},
            db_session=db,
        )

    assert prop.id != other.id
