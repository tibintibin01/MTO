import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import AuditLog, Property, User
from backend.services.auth_service import update_user_role
from backend.services.history_service import log_data_change


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_audit_log_does_not_commit_the_callers_transaction(db):
    property_record = Property(
        td_number="06-0099-00001",
        owner_name="TRANSACTION TEST",
        assessed_value=100_000,
    )
    db.add(property_record)
    db.flush()

    log_data_change(
        user_id=1,
        username="admin",
        table_name="properties",
        record_id=property_record.id,
        action="CREATE",
        after={"td_number": property_record.td_number},
        db_session=db,
    )

    db.rollback()

    assert db.query(Property).count() == 0
    assert db.query(AuditLog).count() == 0


def test_user_change_rolls_back_when_audit_write_fails(db, monkeypatch):
    user = User(
        full_name="Transaction User",
        username="transaction-user",
        password="already-hashed",
        role="viewer",
        is_active=True,
    )
    db.add(user)
    db.commit()

    def fail_audit(*args, **kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr("backend.services.history_service.log_data_change", fail_audit)

    with pytest.raises(RuntimeError, match="simulated audit failure"):
        update_user_role(
            user.id,
            "admin",
            {"id": 99, "username": "system-admin"},
            db,
        )

    db.expire_all()
    unchanged_user = db.query(User).filter(User.id == user.id).one()
    assert unchanged_user.role == "viewer"
    assert db.query(AuditLog).count() == 0


def test_user_change_and_audit_commit_together(db):
    user = User(
        full_name="Audited User",
        username="audited-user",
        password="already-hashed",
        role="viewer",
        is_active=True,
    )
    db.add(user)
    db.commit()

    assert update_user_role(
        user.id,
        "assessor",
        {"id": 99, "username": "system-admin"},
        db,
    ) is True

    db.expire_all()
    updated_user = db.query(User).filter(User.id == user.id).one()
    audit = db.query(AuditLog).filter(AuditLog.record_id == user.id).one()
    assert updated_user.role == "assessor"
    assert audit.action == "UPDATE_ROLE"
    assert audit.username == "system-admin"
