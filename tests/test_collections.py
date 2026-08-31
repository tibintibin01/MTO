# -*- coding: utf-8 -*-
"""
Tests for the collections worklist (aging-aware delinquency prioritisation).

Verifies:
  - only properties with an outstanding balance appear
  - results are ordered by balance descending (collections priority)
  - aging buckets are computed from the earliest delinquent tax year
  - min_age_days filtering works
  - summary totals aggregate across the full matching set
"""

import pytest
from datetime import date

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property, PropertyBilling
from backend.services.billing_service import (
    get_delinquent_accounts,
    get_collections_worklist,
    get_property_statement_data,
)


TEST_AS_OF = date(2023, 7, 1)


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    s = Session()
    yield s
    s.rollback()
    s.close()
    Base.metadata.drop_all(eng)
    eng.dispose()


def _prop(db, td, owner="OWNER", barangay="POBLACION"):
    p = Property(
        td_number=td,
        owner_name=owner,
        barangay=barangay,
        assessed_value=100_000.0,
        penalty=0,
        discount=0,
    )
    db.add(p)
    db.flush()
    return p


def _billing(db, pid, year, assessed=100_000.0, paid=0.0, penalty=0.0, discount=0.0):
    b = PropertyBilling(
        property_id=pid,
        tax_year=year,
        assessed_value=assessed,
        penalty=penalty,
        discount=discount,
        amount_paid=paid,
    )
    db.add(b)
    db.flush()
    return b


def test_only_delinquent_appear(db):
    paid = _prop(db, "TD-PAID")
    _billing(db, paid.id, 2023, paid=2_000.0)  # fully paid → excluded
    owed = _prop(db, "TD-OWED")
    _billing(db, owed.id, 2023, paid=0.0)  # unpaid → included
    db.commit()

    result = get_collections_worklist(as_of_date=TEST_AS_OF, db_session=db)
    tds = [i["td_number"] for i in result["items"]]
    assert "TD-OWED" in tds
    assert "TD-PAID" not in tds
    assert result["summary"]["delinquent_count"] == 1


def test_ordered_by_balance_desc(db):
    small = _prop(db, "TD-SMALL")
    _billing(db, small.id, 2023, assessed=50_000.0, paid=0.0)  # due 1,000
    big = _prop(db, "TD-BIG")
    _billing(db, big.id, 2023, assessed=500_000.0, paid=0.0)  # due 10,000
    db.commit()

    result = get_collections_worklist(as_of_date=TEST_AS_OF, db_session=db)
    assert result["items"][0]["td_number"] == "TD-BIG"
    assert result["items"][1]["td_number"] == "TD-SMALL"


def test_aging_bucket_from_earliest_year(db):
    p = _prop(db, "TD-OLD")
    # A very old delinquent year should land in 120+
    _billing(db, p.id, 2023, paid=0.0)
    db.commit()

    result = get_collections_worklist(as_of_date=TEST_AS_OF, db_session=db)
    row = result["items"][0]
    assert row["earliest_year"] == 2023
    assert row["aging_bucket"] == "120+"
    # Age is measured from Feb 1, 2023
    expected = (TEST_AS_OF - date(2023, 2, 1)).days
    assert row["age_days"] == expected


def test_min_age_filter_excludes_recent(db):
    # Build a billing for a future-ish year so its age is below the threshold.
    current_year = date.today().year
    p = _prop(db, "TD-RECENT")
    _billing(db, p.id, current_year, paid=0.0)
    db.commit()

    # Age from Feb 1 of the current year
    age = max(0, (date.today() - date(current_year, 2, 1)).days)

    # Requiring 120+ days should drop it if today is < ~Jun 1
    result = get_collections_worklist(
        min_age_days=age + 1,
        as_of_date=date.today(),
        db_session=db,
    )
    assert all(i["td_number"] != "TD-RECENT" for i in result["items"])


def test_summary_aging_totals_sum_to_balance(db):
    a = _prop(db, "TD-A")
    _billing(db, a.id, 2023, assessed=100_000.0, paid=0.0)  # due 2,000
    b = _prop(db, "TD-B")
    _billing(db, b.id, 2023, assessed=200_000.0, paid=0.0)  # due 4,000
    db.commit()

    result = get_collections_worklist(as_of_date=TEST_AS_OF, db_session=db)
    summary = result["summary"]
    # P6,000 principal + seven calendar months at 2% = P6,840.
    assert summary["total_balance"] == 6_840.0
    assert round(sum(summary["aging_totals"].values()), 2) == 6_840.0


def test_worklist_materializes_account_aggregates_once(db):
    first = _prop(db, "TD-ONE-PASS-A")
    _billing(db, first.id, 2023, assessed=100_000.0)
    second = _prop(db, "TD-ONE-PASS-B")
    _billing(db, second.id, 2023, assessed=200_000.0)
    db.commit()

    select_count = 0

    def count_selects(_conn, _cursor, statement, _parameters, _context, _many):
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(db.get_bind(), "before_cursor_execute", count_selects)
    try:
        result = get_collections_worklist(
            as_of_date=TEST_AS_OF,
            db_session=db,
        )
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count_selects)

    assert result["summary"]["delinquent_count"] == 2
    assert select_count == 1


def test_paginated_worklist_keeps_full_set_summary_in_one_query(db):
    for index, assessed in enumerate((100_000.0, 200_000.0, 300_000.0), start=1):
        prop = _prop(db, f"TD-PAGE-{index}")
        _billing(db, prop.id, 2023, assessed=assessed)
    db.commit()

    result = get_collections_worklist(
        limit=1,
        offset=1,
        as_of_date=TEST_AS_OF,
        db_session=db,
    )

    assert result["count"] == 1
    assert result["total_matching"] == 3
    assert result["summary"]["delinquent_count"] == 3
    assert result["summary"]["total_balance"] == pytest.approx(13_680.0)
    assert result["has_more"] is True
    assert result["next_offset"] == 2


def test_barangay_filter(db):
    a = _prop(db, "TD-POB", barangay="POBLACION")
    _billing(db, a.id, 2023, paid=0.0)
    b = _prop(db, "TD-SJ", barangay="SAN JOSE")
    _billing(db, b.id, 2023, paid=0.0)
    db.commit()

    result = get_collections_worklist(
        barangay="SAN JOSE",
        as_of_date=TEST_AS_OF,
        db_session=db,
    )
    tds = [i["td_number"] for i in result["items"]]
    assert tds == ["TD-SJ"]


def test_exact_duplicate_td_search_keeps_property_accounts_separate(db):
    first = _prop(db, "06-0012-00094", owner="FIRST OWNER")
    second = _prop(db, "06-0012-00094", owner="SECOND OWNER")
    first.duplicate_td_verified = True
    second.duplicate_td_verified = True
    _billing(db, first.id, 2023, assessed=47_900.0)
    _billing(db, second.id, 2023, assessed=46_350.0)
    db.commit()

    result = get_collections_worklist(
        search="06-0012-00094",
        as_of_date=TEST_AS_OF,
        db_session=db,
    )

    assert result["summary"]["delinquent_count"] == 2
    assert {item["id"] for item in result["items"]} == {first.id, second.id}
    assert {item["owner_name"] for item in result["items"]} == {
        "FIRST OWNER",
        "SECOND OWNER",
    }


def test_worklist_adds_live_penalty_to_unpaid_balance(db):
    prop = _prop(db, "TD-LIVE-PENALTY")
    _billing(db, prop.id, 2024, assessed=100_000.0, paid=0.0)
    db.commit()

    result = get_collections_worklist(
        as_of_date=date(2025, 8, 1),
        db_session=db,
    )
    row = next(item for item in result["items"] if item["td_number"] == prop.td_number)

    # P2,000 tax principal + 20 months x 2% = P2,800.
    assert row["total_due"] == pytest.approx(2_800.0)
    assert row["balance"] == pytest.approx(2_800.0)


def test_worklist_excludes_fully_paid_year_with_recorded_penalty(db):
    prop = _prop(db, "TD-PAID-LATE")
    _billing(
        db,
        prop.id,
        2024,
        assessed=30_000.0,
        paid=624.0,
        penalty=24.0,
    )
    db.commit()

    result = get_collections_worklist(
        as_of_date=date(2026, 7, 1),
        db_session=db,
    )
    assert prop.td_number not in [item["td_number"] for item in result["items"]]


def test_replaced_td_keeps_only_pre_replacement_delinquency(db):
    old = Property(
        td_number="06-0004-00414",
        owner_name="OLD OWNER",
        barangay="BORLONGAN",
        assessed_value=100_000.0,
        effectivity_date="2023-01-01",
        penalty=0,
        discount=0,
    )
    replacement = Property(
        td_number="06-0004-01265",
        prev_td_number="06-0004-00414",
        owner_name="NEW OWNER",
        barangay="BORLONGAN",
        assessed_value=150_000.0,
        effectivity_date="2025-01-01",
        penalty=0,
        discount=0,
    )
    db.add_all([old, replacement])
    db.flush()
    _billing(db, old.id, 2023, paid=2_000.0)
    _billing(db, old.id, 2024, paid=0.0)
    _billing(db, old.id, 2025, paid=0.0)  # Invalid stale row after replacement.
    _billing(db, replacement.id, 2025, assessed=150_000.0, paid=3_000.0)
    db.commit()

    result = get_collections_worklist(
        as_of_date=date(2026, 7, 1),
        db_session=db,
    )
    old_row = next(
        item for item in result["items"] if item["td_number"] == old.td_number
    )

    assert old_row["earliest_year"] == 2023
    assert old_row["years_billed"] == 2  # 2023 and 2024 only; stale 2025 is excluded.
    assert replacement.td_number not in [item["td_number"] for item in result["items"]]

    delinquent = get_delinquent_accounts(
        as_of_date=date(2026, 7, 1),
        db_session=db,
    )
    old_delinquent = next(
        item for item in delinquent["items"] if item["td_number"] == old.td_number
    )
    # Only the unpaid 2024 row remains: P2,000 + 31 months x 2% = P3,240.
    assert old_delinquent["balance"] == pytest.approx(3_240.0)

    statement = get_property_statement_data(
        old.id,
        as_of_date=date(2026, 7, 1),
        db_session=db,
    )
    assert [row["tax_year"] for row in statement["billing_rows"]] == [2024, 2023]


def test_replaced_td_with_paid_history_ignores_stale_later_billing(db):
    old = Property(
        td_number="TD-PAID-OLD",
        owner_name="OLD OWNER",
        barangay="BORLONGAN",
        assessed_value=100_000.0,
        effectivity_date="2023-01-01",
        penalty=0,
        discount=0,
    )
    replacement = Property(
        td_number="TD-PAID-NEW",
        prev_td_number="TD-PAID-OLD",
        owner_name="NEW OWNER",
        barangay="BORLONGAN",
        assessed_value=100_000.0,
        effectivity_date="2025-01-01",
        penalty=0,
        discount=0,
    )
    db.add_all([old, replacement])
    db.flush()
    _billing(db, old.id, 2023, paid=2_000.0)
    _billing(db, old.id, 2024, paid=2_000.0)
    _billing(db, old.id, 2025, paid=0.0)  # Must not revive the cancelled TD.
    db.commit()

    result = get_collections_worklist(
        as_of_date=date(2026, 7, 1),
        db_session=db,
    )
    assert old.td_number not in [item["td_number"] for item in result["items"]]

    delinquent = get_delinquent_accounts(
        as_of_date=date(2026, 7, 1),
        db_session=db,
    )
    assert old.td_number not in [item["td_number"] for item in delinquent["items"]]


def test_statement_rows_include_live_penalty_for_notice_generation(db):
    prop = _prop(db, "TD-NOTICE-PENALTY")
    _billing(db, prop.id, 2024, assessed=100_000.0, paid=0.0)
    db.commit()

    statement = get_property_statement_data(
        prop.id,
        as_of_date=date(2025, 8, 1),
        db_session=db,
    )
    row = statement["billing_rows"][0]

    assert row["penalty"] == pytest.approx(800.0)
    assert row["total_amount"] == pytest.approx(2_800.0)
    assert row["balance_amount"] == pytest.approx(2_800.0)
