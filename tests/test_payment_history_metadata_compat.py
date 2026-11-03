"""Native-driver metadata compatibility; synthetic DBs and in-memory exports only."""

from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable
from sqlalchemy.pool import StaticPool

from backend.models import Base, Payment, Property
from backend.services.property_payment_history_service import (
    _effectivity_metadata,
    get_property_payment_history,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("2027", "2027"),
        ("2027-01-01", "2027-01-01"),
        (2027, 2027),
        (date(2027, 1, 1), "2027-01-01"),
        (datetime(2027, 1, 1, 23, 59, 58, 123456), "2027-01-01T23:59:58.123456"),
        (
            datetime(2027, 1, 1, 1, 2, 3, tzinfo=timezone(timedelta(hours=8))),
            "2027-01-01T01:02:03+08:00",
        ),
    ],
)
def test_metadata_serialization_preserves_values_precision_and_timezone(
    value, expected
):
    assert _effectivity_metadata(value) == expected


@pytest.fixture(params=["DATE", "TIMESTAMP"])
def native_db(request):
    # The model intentionally remains String. DBAPI converters reproduce what
    # MariaDB returns from existing DATE/DATETIME columns without a migration.
    engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
            "detect_types": sqlite3.PARSE_DECLTYPES,
        },
        native_datetime=True,
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ddl = str(CreateTable(Property.__table__).compile(engine))
    assert ddl.count("effectivity_date VARCHAR(100)") == 1
    ddl = ddl.replace(
        "effectivity_date VARCHAR(100)", f"effectivity_date {request.param}"
    )
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE properties"))
        connection.execute(text(ddl))
    current = "2027-01-01" if request.param == "DATE" else "2027-01-01 23:59:58.123456"
    previous = "2026-01-01" if request.param == "DATE" else "2026-01-01 00:00:00"
    with Session(engine) as db:
        db.add_all(
            [
                Property(
                    id=8,
                    td_number="PREV-SYNTHETIC",
                    owner_name="SYNTHETIC",
                    effectivity_date=previous,
                    tax_year="2026",
                    deleted_at=datetime(2026, 10, 1),
                ),
                Property(
                    id=7,
                    td_number="CURRENT-SYNTHETIC",
                    owner_name="SYNTHETIC",
                    effectivity_date=current,
                    tax_year="2027",
                    previous_property_id=8,
                    prev_td_number="PREV-SYNTHETIC",
                ),
                Property(
                    id=9,
                    td_number="CURRENT-SYNTHETIC",
                    owner_name="SYNTHETIC",
                    effectivity_date=current,
                    tax_year="2027",
                ),
                Payment(
                    id=17,
                    property_id=7,
                    date_paid=datetime(2026, 5, 13),
                    tax_year="2027",
                    amount="1288.80",
                    penalty=0,
                    discount="322.20",
                    or_number="0000123",
                ),
                Payment(
                    id=18,
                    property_id=7,
                    date_paid=datetime(2026, 1, 1),
                    tax_year="2024,2025",
                    amount="100.00",
                    penalty=10,
                    discount=0,
                    or_number="MULTI-SYNTHETIC",
                ),
                Payment(
                    id=19,
                    property_id=8,
                    date_paid=datetime(2025, 1, 1),
                    tax_year="2026",
                    amount="50.00",
                    penalty=0,
                    discount=0,
                    or_number="PREV-SYNTHETIC",
                ),
                Payment(
                    id=20,
                    property_id=9,
                    date_paid=datetime(2026, 5, 13),
                    tax_year="2027",
                    amount="900000.00",
                    penalty=0,
                    discount=0,
                    or_number="OTHER-ACCOUNT",
                ),
            ]
        )
        db.commit()
        yield db, request.param
    engine.dispose()


def financial_snapshot(db):
    return {
        table: [
            tuple(row) for row in db.execute(text(f"SELECT * FROM {table} ORDER BY id"))
        ]
        for table in (
            "properties",
            "payments",
            "property_billings",
            "payment_billings",
            "receipt_history",
            "property_assessment_history",
            "audit_logs",
        )
    }


@pytest.mark.parametrize("include_previous", [False, True])
def test_native_metadata_preview_and_exports_preserve_financial_rows(
    native_db, include_previous
):
    from backend.routes.payments import router
    from backend.deps import get_current_user, get_db

    db, kind = native_db
    raw = db.query(Property.effectivity_date).filter(Property.id == 7).scalar()
    assert type(raw) is (date if kind == "DATE" else datetime)
    before = financial_snapshot(db)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "username": "synthetic-viewer",
        "role": "viewer",
    }
    client = TestClient(app)
    path = "/payments/property/7/history"
    preview = client.get(path, params={"include_previous": include_previous})
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    payload = preview.json()
    assert [s["property_id"] for s in payload["sections"]] == (
        [8, 7] if include_previous else [7]
    )
    selected = payload["sections"][-1]
    assert selected["effectivity"] == raw.isoformat()
    assert (
        selected["recorded_cash_total"] == "1388.80" and selected["payment_count"] == 2
    )
    assert selected["payments"][-1]["discount"] == "322.20"
    assert selected["payments"][-1]["cash"] == "1288.80"
    assert payload["recorded_cash_total"] == (
        "1438.80" if include_previous else "1388.80"
    )
    assert payload["payment_count"] == (3 if include_previous else 2)
    if include_previous:
        assert payload["sections"][0]["archived"] is True
    json.dumps(payload)
    again = client.get(path, params={"include_previous": include_previous}).json()
    assert payload["fingerprint"] == again["fingerprint"]
    for fmt, signature in (("pdf", b"%PDF"), ("xlsx", b"PK")):
        exported = client.get(
            path + "/export",
            params={
                "include_previous": include_previous,
                "format": fmt,
                "fingerprint": payload["fingerprint"],
            },
        )
        assert exported.status_code == 200 and exported.content.startswith(signature)
        if fmt == "xlsx":
            book = load_workbook(BytesIO(exported.content))
            assert "Account 7" in book.sheetnames and "Account 9" not in book.sheetnames
            assert ("Account 8" in book.sheetnames) is include_previous
            sheet = book["Account 7"]
            assert sheet["C11"].value == "0000123"
            assert sheet["F11"].value == 322.20 and sheet["G11"].value == 1288.80
    assert financial_snapshot(db) == before


def test_native_effectivity_change_still_invalidates_review_fingerprint(native_db):
    db, kind = native_db
    before = get_property_payment_history(7, db_session=db)["fingerprint"]
    value = "2027-02-01" if kind == "DATE" else "2027-02-01 23:59:58.123456"
    db.execute(
        text("UPDATE properties SET effectivity_date=:value WHERE id=7"),
        {"value": value},
    )
    db.commit()
    assert get_property_payment_history(7, db_session=db)["fingerprint"] != before
