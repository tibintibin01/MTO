"""Read report components from one repeatable-read database transaction."""

from datetime import datetime, timezone
from contextlib import contextmanager

from sqlalchemy.orm import Session

from backend.services import billing_service as billing
from backend.services import property_service as properties


@contextmanager
def report_read_session(db_session):
    bind = db_session.get_bind()
    isolation = "SERIALIZABLE" if bind.dialect.name == "sqlite" else "REPEATABLE READ"
    # Authentication may already have opened the request session's transaction.
    # A dedicated read session pins all components to one database snapshot.
    with Session(bind=bind.execution_options(isolation_level=isolation)) as report_db:
        with report_db.begin():
            yield report_db


def build_receivables_report(
    year, db_session, *, diagnostics=False, full_details=False
):
    year = int(year) if year is not None else None
    if year is not None and not 1900 <= year <= 2100:
        raise ValueError("Select a valid fiscal year between 1900 and 2100.")
    with report_read_session(db_session) as report_db:
        result = {
            "report_year": year,
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "basis": (
                "Fiscal-year ending balances"
                if year is not None
                else "All billing years, all recorded payment dates"
            ),
            "scope": "Non-deleted properties; all available billing years; credits shown separately",
            "adjustment_basis": "Equal shares across linked billing rows (legacy convention)",
            "charge_basis": "Stored yearly assessments and recorded adjustments; not a live SOA accrued-interest estimate",
            "barangays": properties.get_receivables_by_barangay(
                report_year=year,
                data_start_year=None,
                fiscal_year=year,
                include_credits=True,
                db_session=report_db,
            ),
        }
        if year is not None:
            result["summary"] = billing.get_rpt_receivables_summary(
                year, db_session=report_db
            )
        if diagnostics:
            if year is None:
                raise ValueError("Reconciliation requires a fiscal year.")
            result["metrics"] = billing.get_reconciliation_metrics(
                year, db_session=report_db
            )
            result["diagnostics"] = billing.get_reconciliation_diagnostics(
                year,
                limit=None if full_details else 25,
                db_session=report_db,
                summary=result["summary"],
                metrics=result["metrics"],
            )
        from backend.services.report_credit_service import credit_scope

        result["credit_scope"] = credit_scope(report_db, year)
        return result


def build_collection_report(month, year, db_session, **options):
    with report_read_session(db_session) as report_db:
        result = billing.get_report_details(
            month, year, db_session=report_db, **options
        )
        result["captured_at_utc"] = datetime.now(timezone.utc).isoformat()
        return result
