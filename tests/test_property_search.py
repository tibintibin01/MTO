# -*- coding: utf-8 -*-
"""Regression tests for property search filters used by Assessment Roll."""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property
from backend.services.property_service import search_properties


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


def _property(db, td_number, effectivity_date, tax_year=None, barangay="BAYABAS"):
    row = Property(
        td_number=td_number,
        owner_name=f"OWNER {td_number}",
        barangay=barangay,
        effectivity_date=effectivity_date,
        tax_year=tax_year,
        assessed_value=100_000,
        penalty=0,
        discount=0,
    )
    db.add(row)
    db.flush()
    return row


def test_search_properties_year_filter_matches_full_effectivity_dates(db):
    _property(db, "TD-2022", "2022-01-01")
    _property(db, "TD-2023", "2023-01-01")
    _property(db, "TD-2024", "2024")
    _property(db, "TD-2025", "2025-12-31")
    _property(db, "TD-2026", "2026-01-01")
    db.commit()

    rows = search_properties(
        "",
        barangay="BAYABAS",
        year_start=2023,
        year_end=2025,
        db_session=db,
    )

    td_numbers = {row[1] for row in rows}
    assert td_numbers == {"TD-2023", "TD-2024", "TD-2025"}


def test_search_properties_year_filter_falls_back_to_tax_year(db):
    _property(db, "TD-TAX-2024", "", tax_year="2024")
    _property(db, "TD-TAX-2026", "", tax_year="2026")
    db.commit()

    rows = search_properties(
        "",
        barangay="BAYABAS",
        year_start=2023,
        year_end=2025,
        db_session=db,
    )

    assert [row[1] for row in rows] == ["TD-TAX-2024"]
