import threading
import time
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.models import IdempotencyKey
from backend.services.idempotency_service import begin_financial_operation


def _operation(session, key, payload=None, user_id=7):
    return begin_financial_operation(
        db_session=session,
        idempotency_key=key,
        current_user={"id": user_id, "username": f"user-{user_id}"},
        method="POST",
        path="/payments/batch-delete/commit",
        payload=payload or {"payment_ids": [11, 12]},
    )


@pytest.fixture()
def idempotency_db():
    engine = create_engine("sqlite:///:memory:")
    IdempotencyKey.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_financial_operation_requires_uuid4(idempotency_db):
    for invalid in (None, "", "not-a-uuid", str(uuid.uuid1())):
        with pytest.raises(HTTPException) as error:
            _operation(idempotency_db, invalid)
        assert error.value.status_code == 400


def test_completed_operation_replays_stored_response(idempotency_db):
    key = str(uuid.uuid4())
    first = _operation(idempotency_db, key)
    response = {"deleted": 2, "failed_count": 0, "failed": []}
    first.complete(response)
    idempotency_db.commit()

    second = _operation(idempotency_db, key)

    assert second.replayed is True
    assert second.replay_body == response
    assert (
        idempotency_db.query(IdempotencyKey)
        .filter(IdempotencyKey.user_id == "7")
        .count()
        == 1
    )


def test_same_key_with_different_data_is_conflict(idempotency_db):
    key = str(uuid.uuid4())
    first = _operation(idempotency_db, key)
    first.complete({"ok": True})
    idempotency_db.commit()

    with pytest.raises(HTTPException) as error:
        _operation(idempotency_db, key, payload={"payment_ids": [99]})

    assert error.value.status_code == 409
    assert "different request data" in str(error.value.detail)


def test_same_uuid_is_scoped_to_authenticated_user(idempotency_db):
    key = str(uuid.uuid4())
    first = _operation(idempotency_db, key, user_id=7)
    first.complete({"owner": 7})
    idempotency_db.commit()

    other_user = _operation(idempotency_db, key, user_id=8)

    assert other_user.replayed is False
    assert other_user.record.user_id == "8"


def test_financial_write_and_claim_roll_back_together(idempotency_db):
    idempotency_db.execute(
        text("CREATE TABLE financial_marker (id INTEGER PRIMARY KEY, amount INTEGER)")
    )
    idempotency_db.commit()
    key = str(uuid.uuid4())

    claim = _operation(idempotency_db, key)
    idempotency_db.execute(
        text("INSERT INTO financial_marker (id, amount) VALUES (1, 500)")
    )
    claim.complete({"ok": True})
    idempotency_db.rollback()

    assert (
        idempotency_db.execute(text("SELECT COUNT(*) FROM financial_marker")).scalar()
        == 0
    )
    assert idempotency_db.query(IdempotencyKey).count() == 0


def test_concurrent_identical_operations_execute_once(tmp_path):
    database_path = tmp_path / "idempotency-concurrency.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    IdempotencyKey.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    key = str(uuid.uuid4())
    first_claimed = threading.Event()
    allow_commit = threading.Event()
    results = []
    errors = []

    def first_worker():
        session = factory()
        try:
            claim = _operation(session, key)
            claim.complete({"payment_id": 42})
            first_claimed.set()
            allow_commit.wait(timeout=5)
            session.commit()
            results.append(("first", claim.replayed))
        except Exception as exc:
            errors.append(exc)
        finally:
            session.close()

    def second_worker():
        session = factory()
        try:
            first_claimed.wait(timeout=5)
            claim = _operation(session, key)
            results.append(("second", claim.replayed))
        except Exception as exc:
            errors.append(exc)
        finally:
            session.rollback()
            session.close()

    first_thread = threading.Thread(target=first_worker)
    second_thread = threading.Thread(target=second_worker)
    first_thread.start()
    second_thread.start()
    first_claimed.wait(timeout=5)
    time.sleep(0.1)
    allow_commit.set()
    first_thread.join(timeout=10)
    second_thread.join(timeout=10)

    try:
        assert errors == []
        assert sorted(results) == [("first", False), ("second", True)]
        with factory() as session:
            assert session.query(IdempotencyKey).count() == 1
    finally:
        engine.dispose()
