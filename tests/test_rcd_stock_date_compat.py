"""Native DATE/DATETIME-shaped rows only; no office records or live database."""

from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from backend.services.daily_rcd_service import validate_stock_history


def history_session(value):
    db = Mock(spec=Session)
    db.query.return_value.filter.return_value.limit.return_value.all.return_value = [
        SimpleNamespace(or_number="000123", date_paid=value)
    ]
    return db


def stock(cancelled=False):
    return {
        "available_identities": [("", 123)],
        "cancelled_identities": [("", 123)] if cancelled else [],
    }


@pytest.mark.parametrize(
    "paid_on",
    [
        date(2026, 10, 20),
        date(2026, 10, 21),
        datetime(2026, 10, 20),
        datetime(2026, 10, 20, 23, 59, 59),
        datetime(2026, 10, 21),
        datetime(2026, 10, 20, tzinfo=timezone.utc),
        datetime(2026, 10, 20, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_stock_history_accepts_same_or_future_recorded_calendar_day(paid_on):
    db = history_session(paid_on)
    validate_stock_history(db, {"report_date": "2026-10-20"}, stock())
    db.add.assert_not_called()
    db.execute.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    "paid_on",
    [None, date(2026, 10, 19), datetime(2026, 10, 19, 23, 59, 59)],
)
def test_prior_or_undated_usage_still_blocks_without_repair(paid_on):
    db = history_session(paid_on)
    with pytest.raises(ValueError, match="earlier or undated payment"):
        validate_stock_history(db, {"report_date": "2026-10-20"}, stock())
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize("paid_on", ["2026-10-20", 123, True])
def test_unsupported_driver_value_fails_closed_without_guessing_a_date(paid_on):
    db = history_session(paid_on)
    with pytest.raises(ValueError, match="unsupported receipt date"):
        validate_stock_history(db, {"report_date": "2026-10-20"}, stock())
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    "paid_on", [None, date(2026, 10, 20), date(2026, 10, 21), datetime(2026, 10, 21)]
)
def test_a_saved_payment_always_blocks_a_zero_collection_cancellation(paid_on):
    db = history_session(paid_on)
    with pytest.raises(ValueError, match="saved payment entry"):
        validate_stock_history(db, {"report_date": "2026-10-20"}, stock(True))
    db.commit.assert_not_called()
