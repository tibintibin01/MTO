# -*- coding: utf-8 -*-
"""Regression tests for property search filters used by Assessment Roll."""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property, PropertyAssessmentHistory
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


def _property(
    db,
    td_number,
    effectivity_date,
    tax_year=None,
    barangay="BAYABAS",
    prev_td_number=None,
    owner_name=None,
):
    row = Property(
        td_number=td_number,
        owner_name=owner_name or f"OWNER {td_number}",
        barangay=barangay,
        effectivity_date=effectivity_date,
        tax_year=tax_year,
        prev_td_number=prev_td_number,
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


def test_search_properties_as_of_year_excludes_replaced_previous_td(db):
    _property(db, "06-0001-00001", "2023")
    _property(db, "06-0001-00099", "2024", prev_td_number="06-0001-00001")
    db.commit()

    rows_2023 = search_properties(
        "", barangay="BAYABAS", as_of_year=2023, db_session=db
    )
    rows_2025 = search_properties(
        "", barangay="BAYABAS", as_of_year=2025, db_session=db
    )

    assert {row[1] for row in rows_2023} == {"06-0001-00001"}
    assert {row[1] for row in rows_2025} == {"06-0001-00099"}


def test_search_properties_as_of_year_keeps_old_td_until_replacement_effective(db):
    _property(db, "06-0001-00001", "2023")
    _property(db, "06-0001-00099", "2026", prev_td_number="06-0001-00001")
    db.commit()

    rows_2025 = search_properties(
        "", barangay="BAYABAS", as_of_year=2025, db_session=db
    )
    rows_2026 = search_properties(
        "", barangay="BAYABAS", as_of_year=2026, db_session=db
    )

    assert {row[1] for row in rows_2025} == {"06-0001-00001"}
    assert {row[1] for row in rows_2026} == {"06-0001-00099"}


def test_as_of_year_uses_historical_snapshot_before_future_revaluation(db):
    prop = _property(db, "TD-REVALUED", "2027", tax_year="2027")
    prop.assessed_value = 200_000
    prop.kind_of_property = "COMMERCIAL"
    db.add(
        PropertyAssessmentHistory(
            property_id=prop.id,
            td_number=prop.td_number,
            assessed_value=100_000,
            tax_year="2024",
            kind_of_property="RESIDENTIAL",
        )
    )
    db.commit()

    rows_2026 = search_properties(
        "", barangay="BAYABAS", as_of_year=2026, db_session=db
    )
    rows_2027 = search_properties(
        "", barangay="BAYABAS", as_of_year=2027, db_session=db
    )

    assert len(rows_2026) == 1
    assert rows_2026[0][1] == "TD-REVALUED"
    assert rows_2026[0][7] == "RESIDENTIAL"
    assert rows_2026[0][9] == 100_000
    assert rows_2026[0][21] == 2024

    assert len(rows_2027) == 1
    assert rows_2027[0][7] == "COMMERCIAL"
    assert rows_2027[0][9] == 200_000
    assert rows_2027[0][21] == 2027


def test_replacement_td_uses_historical_start_year_and_snapshot(db):
    old = _property(db, "TD-OLD", "2023")
    replacement = _property(
        db,
        "TD-NEW",
        "2027",
        tax_year="2027",
        prev_td_number=old.td_number,
    )
    replacement.assessed_value = 200_000
    replacement.kind_of_property = "COMMERCIAL"
    db.add(
        PropertyAssessmentHistory(
            property_id=replacement.id,
            td_number=replacement.td_number,
            assessed_value=150_000,
            tax_year="2026",
            kind_of_property="RESIDENTIAL",
        )
    )
    db.commit()

    rows_2025 = search_properties(
        "", barangay="BAYABAS", as_of_year=2025, db_session=db
    )
    rows_2026 = search_properties(
        "", barangay="BAYABAS", as_of_year=2026, db_session=db
    )
    rows_2027 = search_properties(
        "", barangay="BAYABAS", as_of_year=2027, db_session=db
    )

    assert {row[1] for row in rows_2025} == {"TD-OLD"}
    assert {row[1] for row in rows_2026} == {"TD-NEW"}
    assert rows_2026[0][7] == "RESIDENTIAL"
    assert rows_2026[0][9] == 150_000
    assert rows_2026[0][21] == 2026
    assert {row[1] for row in rows_2027} == {"TD-NEW"}
    assert rows_2027[0][7] == "COMMERCIAL"
    assert rows_2027[0][9] == 200_000


def test_search_properties_keeps_exact_owner_substring_inside_long_name(db):
    _property(
        db,
        "06-0004-00031",
        "2024",
        owner_name="SPS. APALLA, EXAMPLE LONG OWNER NAME WITH MULTIPLE WORDS",
    )
    _property(db, "06-0004-00032", "2024", owner_name="SANTOS, JUAN")
    db.commit()

    rows = search_properties("APALLA", barangay="BAYABAS", db_session=db)

    assert [row[1] for row in rows] == ["06-0004-00031"]


def test_search_properties_finds_replacement_by_previous_td_number(db):
    _property(db, "06-0001-00001", "2023")
    _property(
        db,
        "06-0001-00099",
        "2024",
        prev_td_number="06-0001-00001",
        owner_name="CURRENT OWNER",
    )
    db.commit()

    rows = search_properties("06-0001-00001", barangay="BAYABAS", db_session=db)

    assert [row[1] for row in rows] == ["06-0001-00099", "06-0001-00001"]


def test_exact_td_search_tolerates_stored_whitespace_and_case(db):
    _property(db, "06-0012-02561 ", "2027", barangay="DINADIAWAN")
    db.commit()

    rows = search_properties("06-0012-02561", db_session=db)

    assert len(rows) == 1
    assert rows[0][1].strip() == "06-0012-02561"
