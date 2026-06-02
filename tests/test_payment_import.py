# -*- coding: utf-8 -*-
"""Regression tests for ledger payment bulk import."""

import io

import pandas as pd
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Property, Payment, PaymentBilling
from backend.services.import_service import validate_payment_import, commit_payment_import


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
    session.add(
        Property(
            td_number="06-0001-0001",
            owner_name="JUAN DELA CRUZ",
            assessed_value=100_000.0,
            tax_year="2024",
        )
    )
    session.commit()
    yield session
    session.rollback()
    session.close()
    eng.dispose()


def test_payment_import_commit_links_billing(db):
    buf = io.BytesIO()
    pd.DataFrame(
        [
            {
                "TD NUMBER": "06-0001-0001",
                "OR NUMBER": "OR-REG-001",
                "AMOUNT": 1500.0,
                "TAX YEAR": 2024,
                "DATE": "2024-03-15",
            }
        ]
    ).to_excel(buf, index=False)
    buf.seek(0)

    validated = validate_payment_import(buf.read(), ".xlsx", db_session=db)
    assert validated["success"] is True
    assert validated["valid_rows"] == 1

    result = commit_payment_import(validated["data"], {"username": "admin"}, db_session=db)
    assert result["inserted"] == 1
    assert result["skipped"] == 0
    assert db.query(Payment).count() == 1
    assert db.query(PaymentBilling).count() == 1
