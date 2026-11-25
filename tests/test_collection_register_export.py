"""Synthetic whole-period export/paging regression; never office records."""

import asyncio
from datetime import datetime
from decimal import Decimal
import io

import openpyxl
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import Payment, Property
from backend.routes.billing import ExportReportRequest, export_billing_excel
from backend.services.report_payload_service import build_collection_report


def test_collection_register_exports_all_pages_by_receipt_date_without_writes():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        prop = Property(
            td_number="DEMO-COLLECTION",
            owner_name="SYNTHETIC OWNER",
            assessed_value=100000,
            effectivity_date="2023",
            barangay="SYNTHETIC",
        )
        db.add(prop)
        db.flush()
        for index in range(706):
            db.add(
                Payment(
                    property_id=prop.id,
                    amount=Decimal("1.01"),
                    tax_year="2027",
                    date_paid=datetime(2026, 11, 2),
                    or_number=f"DEMO-OR-{index:04d}",
                    posted_by="DEMO OPERATOR",
                )
            )
        for date, amount, number in [
            (datetime(2026, 10, 31), 99, "DEMO-OCTOBER"),
            (datetime(2027, 1, 1), 88, "DEMO-NEXT-YEAR"),
        ]:
            db.add(
                Payment(
                    property_id=prop.id,
                    amount=amount,
                    tax_year="2026",
                    date_paid=date,
                    or_number=number,
                )
            )
        db.commit()
        before = (
            db.query(
                Payment.id,
                Payment.amount,
                Payment.date_paid,
                Payment.tax_year,
                Payment.or_number,
            )
            .order_by(Payment.id)
            .all()
        )
        statements = []

        def capture_statement(
            connection, cursor, statement, parameters, context, executemany
        ):
            statements.append(statement.strip().upper())

        event.listen(engine, "before_cursor_execute", capture_statement)
        try:
            first = build_collection_report("11", "2026", db, limit=100)
            pages, cursors = [first], [None]
            while pages[-1]["has_more"]:
                cursors.append(pages[-1]["next_cursor"])
                pages.append(
                    build_collection_report(
                        "11",
                        "2026",
                        db,
                        limit=100,
                        cursor=cursors[-1],
                        anchor=first["anchor"],
                    )
                )
            assert [len(page["items"]) for page in pages] == [100] * 7 + [6]
            preview_rows = [row for page in pages for row in page["items"]]
            assert len({row[1] for row in preview_rows}) == 706
            assert all(
                page["total_count"] == 706
                and Decimal(str(page["cash_total"])) == Decimal("713.06")
                for page in pages
            )
            # The desktop Previous action reuses a page's stored cursor and
            # the same anchored snapshot rather than inventing offsets.
            previous = build_collection_report(
                "11", "2026", db, limit=100, cursor=cursors[-2], anchor=first["anchor"]
            )
            assert previous["items"] == pages[-2]["items"]

            async def workbook_bytes():
                response = await export_billing_excel(
                    ExportReportRequest(
                        report_type="collections", month="11", year="2026"
                    ),
                    current_user={"id": 0, "username": "SYNTHETIC", "role": "admin"},
                    db_session=db,
                )
                return b"".join([chunk async for chunk in response.body_iterator])

            sheet = openpyxl.load_workbook(
                io.BytesIO(asyncio.run(workbook_bytes())), data_only=False
            ).active
            assert sheet.title == "Collections"
            assert sheet.max_row == 711
            assert Decimal(str(sheet["G711"].value)) == Decimal("713.06")
            exported_ors = {sheet.cell(row, 2).value for row in range(5, 711)}
            assert exported_ors == {row[1] for row in preview_rows}
            # Tax year 2027 receipts dated in November 2026 stay in this
            # receipt-date report; a different period is not silently added.
            assert {sheet.cell(row, 6).value for row in range(5, 711)} == {"2027"}
            assert (
                "DEMO-OCTOBER" not in exported_ors
                and "DEMO-NEXT-YEAR" not in exported_ors
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture_statement)
        assert not any(
            s.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "ALTER", "CREATE"))
            for s in statements
        )
        after = (
            db.query(
                Payment.id,
                Payment.amount,
                Payment.date_paid,
                Payment.tax_year,
                Payment.or_number,
            )
            .order_by(Payment.id)
            .all()
        )
        assert before == after
    finally:
        db.close()
        engine.dispose()
