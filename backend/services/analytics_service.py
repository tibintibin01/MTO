# -*- coding: utf-8 -*-
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend.models import Payment, Property
from backend.database import SessionLocal
from datetime import datetime

def get_collection_summary(db_session: Session = None):
    """Returns key collection totals for today, this month, and this year."""
    if not db_session:
        db_session = SessionLocal()

    now = datetime.now()
    today = now.date()
    this_month_start = today.replace(day=1)
    this_year_start = today.replace(month=1, day=1)

    # Today's total and count
    today_data = db_session.query(
        func.coalesce(func.sum(Payment.amount), 0),
        func.count(Payment.id)
    ).filter(func.date(Payment.date_paid) == today).first()

    # Month total
    month_total = db_session.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(func.date(Payment.date_paid) >= this_month_start).scalar()

    # Year total
    year_total = db_session.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(func.date(Payment.date_paid) >= this_year_start).scalar()

    return {
        "today": float(today_data[0] or 0),
        "month": float(month_total or 0),
        "year": float(year_total or 0),
        "count": int(today_data[1] or 0)
    }

def get_monthly_revenue_trend(db_session: Session = None):
    """Returns the last 12 months of revenue for trend analysis."""
    if not db_session:
        db_session = SessionLocal()

    from datetime import timedelta
    start_date = datetime.now() - timedelta(days=365)
    
    results = db_session.query(
        func.date_format(Payment.date_paid, '%Y-%m').label('month'),
        func.sum(Payment.amount).label('total')
    ).filter(Payment.date_paid >= start_date).group_by('month').order_by('month').all()
    
    return [{"month": r[0], "total": float(r[1] or 0)} for r in results]

def get_barangay_distribution(db_session: Session = None):
    """Returns revenue distribution across barangays."""
    if not db_session:
        db_session = SessionLocal()

    results = db_session.query(
        Property.barangay,
        func.sum(Payment.amount).label('total')
    ).join(Payment, Payment.property_id == Property.id).filter(
        Property.is_deleted == False
    ).group_by(Property.barangay).order_by(func.sum(Payment.amount).desc()).limit(10).all()
    
    return [{"name": r[0] or "UNKNOWN", "value": float(r[1] or 0)} for r in results]

def get_tax_year_distribution(db_session: Session = None):
    """Returns the distribution of payments across tax years."""
    if not db_session:
        db_session = SessionLocal()

    results = db_session.query(
        Payment.tax_year,
        func.sum(Payment.amount).label('total')
    ).group_by(Payment.tax_year).order_by(Payment.tax_year.desc()).limit(5).all()
    
    return [{"year": r[0] or "N/A", "total": float(r[1] or 0)} for r in results]
