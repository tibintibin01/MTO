# -*- coding: utf-8 -*-
"""Dashboard stats refresh and timezone boundary tests."""

from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property, Payment, SystemStats
from backend.services.stats_service import refresh_system_stats, stats_are_stale
from backend.services.system_service import get_dashboard_summary


@pytest.fixture()
def db():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def enable_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    session = Session()
    prop = Property(
        td_number="06-0001-0001",
        owner_name="JUAN DELA CRUZ",
        assessed_value=100_000.0,
        tax_year="2024",
    )
    session.add(prop)
    session.flush()

    ph_now = datetime.now(timezone(timedelta(hours=8)))
    session.add(
        Payment(
            property_id=prop.id,
            amount=500.0,
            or_number="OR-100",
            tax_year="2024",
            date_paid=ph_now.astimezone(timezone.utc),
            posted_by="admin",
        )
    )
    session.commit()
    yield session
    session.rollback()
    session.close()
    eng.dispose()


def test_refresh_system_stats_counts_property_and_collections(db):
    assert refresh_system_stats(db_session=db) is True

    stats = {s.stat_key: float(s.stat_value) for s in db.query(SystemStats).all()}
    assert stats["total_properties"] == 1
    assert stats["collections_today"] == 500.0
    assert stats["collections_month"] == 500.0
    assert stats["receipts_today"] == 1


def test_get_dashboard_summary_refreshes_stale_cache(db):
    summary = get_dashboard_summary(db_session=db)
    assert summary["total_properties"] == 1
    assert summary["collections_today"] == 500.0
    assert summary["collections_month"] == 500.0
    assert summary["receipts_today"] == 1
    assert stats_are_stale(db) is False
