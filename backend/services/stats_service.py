# -*- coding: utf-8 -*-
from datetime import datetime, timezone, timedelta, time, date
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend.models import Property, Payment, SystemStats

# Philippine Standard Time — treasury operations use local calendar days.
_PH_TZ = timezone(timedelta(hours=8))
_STATS_STALE_SECONDS = 300


def _today_ph() -> date:
    return datetime.now(_PH_TZ).date()


def _month_start_ph() -> date:
    d = _today_ph()
    return d.replace(day=1)


def _ph_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=_PH_TZ).astimezone(timezone.utc)
    end = datetime.combine(day, time.max, tzinfo=_PH_TZ).astimezone(timezone.utc)
    return start, end


def _effective_payment_datetime():
    """Use date_paid when present, otherwise fall back to created_at."""
    return func.coalesce(Payment.date_paid, Payment.created_at)


def refresh_system_stats(db_session: Session = None):
    """
    Recalculates heavy dashboard statistics and persists them to SystemStats.
    This should be called by a background worker or after major data changes.
    """
    try:
        # 1. Total Properties
        total_props = db_session.query(func.count(Property.id)).filter(Property.deleted_at == None).scalar()
        _update_stat(db_session, "total_properties", total_props)

        # 2. Unpaid Properties (Slow query optimization)
        unpaid_props = db_session.query(func.count(Property.id)).filter(
            Property.deleted_at == None,
            ~Property.id.in_(db_session.query(Payment.property_id))
        ).scalar()
        _update_stat(db_session, "unpaid_properties", unpaid_props)

        # 3. Collections Today (Philippine calendar day, UTC-safe bounds)
        paid_at = _effective_payment_datetime()
        day_start, day_end = _ph_day_bounds(_today_ph())
        today_coll, receipts_today = db_session.query(
            func.sum(Payment.amount),
            func.count(Payment.id),
        ).filter(
            paid_at >= day_start,
            paid_at <= day_end,
        ).one()
        _update_stat(db_session, "collections_today", float(today_coll or 0))
        _update_stat(db_session, "receipts_today", int(receipts_today or 0))

        # 4. Collections Month-to-Date (exclude future-dated payment records)
        month_start = datetime.combine(_month_start_ph(), time.min, tzinfo=_PH_TZ).astimezone(timezone.utc)
        month_coll = db_session.query(func.sum(Payment.amount)).filter(
            paid_at >= month_start,
            paid_at <= day_end,
        ).scalar()
        _update_stat(db_session, "collections_month", float(month_coll or 0))

        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        print(f"ERROR: Failed to refresh system stats: {e}")
        return False

def _update_stat(db_session: Session, key: str, value: float):
    stat = db_session.query(SystemStats).filter(SystemStats.stat_key == key).first()
    if not stat:
        stat = SystemStats(stat_key=key, stat_value=value)
        db_session.add(stat)
    else:
        stat.stat_value = value
        stat.last_updated = datetime.now(timezone.utc)

def get_cached_stat(key: str, default=0, db_session: Session = None):
    """Retrieves a pre-calculated stat from the database."""
    stat = db_session.query(SystemStats).filter(SystemStats.stat_key == key).first()
    return float(stat.stat_value) if stat else default


def stats_are_stale(db_session: Session, max_age_seconds: int = _STATS_STALE_SECONDS) -> bool:
    """Returns True when dashboard stats have never been computed or are older than max_age."""
    stat = (
        db_session.query(SystemStats)
        .filter(SystemStats.stat_key == "total_properties")
        .first()
    )
    if not stat or not stat.last_updated:
        return True
    updated = stat.last_updated
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    return age > max_age_seconds
