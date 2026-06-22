# -*- coding: utf-8 -*-
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property
from backend.services.property_service import get_deleted_properties


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
