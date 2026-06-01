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
from backend.services.billing_service import get_collections_worklist


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
    p = Property(td_number=td, owner_name=owner, barangay=barangay,
                 assessed_value=100_000.0, penalty=0, discount=0)
    db.add(p)
    db.flush()
    return p


def _billing(db, pid, year, assessed=100_000.0, paid=0.0, penalty=0.0, discount=0.0):
    b = PropertyBilling(property_id=pid, tax_year=year, assessed_value=assessed,
                        penalty=penalty, discount=discount, amount_paid=paid)
    db.add(b)
    db.flush()
    return b


def test_only_delinquent_appear(db):
    paid = _prop(db, "TD-PAID")
    _billing(db, paid.id, 2024, paid=2_000.0)   # fully paid → excluded
    owed = _prop(db, "TD-OWED")
    _billing(db, owed.id, 2024, paid=0.0)        # unpaid → included
    db.commit()

    result = get_collections_worklist(db_session=db)
    tds = [i["td_number"] for i in result["items"]]
    assert "TD-OWED" in tds
    assert "TD-PAID" not in tds
    assert result["summary"]["delinquent_count"] == 1


def test_ordered_by_balance_desc(db):
    small = _prop(db, "TD-SMALL")
    _billing(db, small.id, 2024, assessed=50_000.0, paid=0.0)   # due 1,000
    big = _prop(db, "TD-BIG")
    _billing(db, big.id, 2024, assessed=500_000.0, paid=0.0)    # due 10,000
    db.commit()

    result = get_collections_worklist(db_session=db)
    assert result["items"][0]["td_number"] == "TD-BIG"
    assert result["items"][1]["td_number"] == "TD-SMALL"


def test_aging_bucket_from_earliest_year(db):
    p = _prop(db, "TD-OLD")
    # A very old delinquent year should land in 120+
    _billing(db, p.id, 2023, paid=0.0)
    db.commit()

    result = get_collections_worklist(db_session=db)
    row = result["items"][0]
    assert row["earliest_year"] == 2023
    assert row["aging_bucket"] == "120+"
    # Age is measured from Feb 1, 2023
    expected = (date.today() - date(2023, 2, 1)).days
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
    result = get_collections_worklist(min_age_days=age + 1, db_session=db)
    assert all(i["td_number"] != "TD-RECENT" for i in result["items"])


def test_summary_aging_totals_sum_to_balance(db):
    a = _prop(db, "TD-A")
    _billing(db, a.id, 2023, assessed=100_000.0, paid=0.0)   # due 2,000
    b = _prop(db, "TD-B")
    _billing(db, b.id, 2023, assessed=200_000.0, paid=0.0)   # due 4,000
    db.commit()

    result = get_collections_worklist(db_session=db)
    summary = result["summary"]
    assert summary["total_balance"] == 6_000.0
    assert round(sum(summary["aging_totals"].values()), 2) == 6_000.0


def test_barangay_filter(db):
    a = _prop(db, "TD-POB", barangay="POBLACION")
    _billing(db, a.id, 2024, paid=0.0)
    b = _prop(db, "TD-SJ", barangay="SAN JOSE")
    _billing(db, b.id, 2024, paid=0.0)
    db.commit()

    result = get_collections_worklist(barangay="SAN JOSE", db_session=db)
    tds = [i["td_number"] for i in result["items"]]
    assert tds == ["TD-SJ"]
