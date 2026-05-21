# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from sqlalchemy import func, cast
from sqlalchemy.types import Date
from sqlalchemy.orm import Session
from backend.models import Property, Payment, SystemStats
from backend.database import SessionLocal
from utils.db_compat import today, this_month_start

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

        # 3. Collections Today
        today_date = today()
        today_coll = db_session.query(func.sum(Payment.amount)).filter(
            cast(Payment.date_paid, Date) == today_date
        ).scalar()
        _update_stat(db_session, "collections_today", float(today_coll or 0))

        # 4. Collections Month
        month_start = this_month_start()
        month_coll = db_session.query(func.sum(Payment.amount)).filter(
            cast(Payment.date_paid, Date) >= month_start
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
