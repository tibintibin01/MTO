# -*- coding: utf-8 -*-
from sqlalchemy import func, cast
from sqlalchemy.types import Date
from sqlalchemy.orm import Session
from backend.models import Payment, Property, PropertyBilling, TaxPolicy
from backend.database import SessionLocal
from backend.services.billing_service import tax_rate_subquery
from datetime import datetime, timezone
from utils.db_compat import year_of, month_of, today, this_month_start, this_year_start

def get_collection_summary(db_session: Session = None):
    """Returns key collection totals for today, this month, and this year."""
    if not db_session:
        with SessionLocal() as session:
            return get_collection_summary(db_session=session)

    today_date = today()
    month_start = this_month_start()
    year_start = this_year_start()

    today_data = db_session.query(
        func.coalesce(func.sum(Payment.amount), 0),
        func.count(Payment.id)
    ).filter(cast(Payment.date_paid, Date) == today_date).first()

    month_total = db_session.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(cast(Payment.date_paid, Date) >= month_start).scalar()

    year_total = db_session.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(cast(Payment.date_paid, Date) >= year_start).scalar()

    # Total receivables = sum of all outstanding balances in property_billings
    # Uses TaxPolicy rates via correlated subquery (no hardcoded 0.02)
    rate_expr = tax_rate_subquery(db_session, PropertyBilling.tax_year)
    total_receivables = db_session.query(
        func.coalesce(
            func.sum(
                (PropertyBilling.assessed_value * rate_expr)
                + PropertyBilling.penalty
                - PropertyBilling.discount
            ), 0
        )
    ).join(Property, Property.id == PropertyBilling.property_id).filter(
        Property.deleted_at == None
    ).scalar()

    total_collected = db_session.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).scalar()

    collection_rate = float((float(total_collected) / float(total_receivables)) * 100) if float(total_receivables) > 0 else 0.0

    total_properties = db_session.query(
        func.count(Property.id)
    ).filter(Property.deleted_at == None).scalar()

    # Calculate active delinquencies (where outstanding balance > 0)
    balance_expr = func.sum(
        (PropertyBilling.assessed_value * rate_expr)
        + PropertyBilling.penalty
        - PropertyBilling.discount
        - PropertyBilling.amount_paid
    )
    try:
        active_delinquencies = db_session.query(Property.id).join(
            PropertyBilling, PropertyBilling.property_id == Property.id
        ).filter(Property.deleted_at == None).group_by(Property.id).having(balance_expr > 0).count()
    except Exception:
        active_delinquencies = 0

    return {
        "today": float(today_data[0] or 0),
        "month": float(month_total or 0),
        "year": float(year_total or 0),
        "count": int(today_data[1] or 0),
        "total_receivables": float(total_receivables or 0),
        "total_collected": float(total_collected or 0),
        "collection_rate": float(collection_rate),
        "total_properties": int(total_properties or 0),
        "active_delinquencies": int(active_delinquencies or 0)
    }


def get_last_year_summary(db_session: Session = None):
    """
    Returns the same key metrics as get_collection_summary but for the
    previous calendar year — used to compute year-over-year % change.
    """
    if not db_session:
        with SessionLocal() as session:
            return get_last_year_summary(db_session=session)

    from datetime import date
    current_year = datetime.now(timezone.utc).year
    last_year = current_year - 1
    last_year_start = date(last_year, 1, 1)
    last_year_end   = date(last_year, 12, 31)

    # Total collected in last year — use year_of() consistent with rest of codebase
    last_year_collected = db_session.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(
        Payment.date_paid != None,
        year_of(Payment.date_paid) == last_year,
    ).scalar()

    # Total receivables as of end of last year (billing records up to last year)
    # Uses TaxPolicy rates via correlated subquery
    rate_expr = tax_rate_subquery(db_session, PropertyBilling.tax_year)
    last_year_receivables = db_session.query(
        func.coalesce(
            func.sum(
                (PropertyBilling.assessed_value * rate_expr)
                + PropertyBilling.penalty
                - PropertyBilling.discount
            ), 0
        )
    ).join(Property, Property.id == PropertyBilling.property_id).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year <= last_year,
    ).scalar()

    last_year_rate = (
        float(float(last_year_collected) / float(last_year_receivables) * 100)
        if float(last_year_receivables or 0) > 0 else 0.0
    )

    # Total properties registered as of last year
    last_year_properties = db_session.query(
        func.count(Property.id)
    ).filter(
        Property.deleted_at == None,
        year_of(Property.created_at) <= last_year,
    ).scalar()

    return {
        "year":               last_year,
        "total_collected":    float(last_year_collected or 0),
        "total_receivables":  float(last_year_receivables or 0),
        "collection_rate":    float(last_year_rate),
        "total_properties":   int(last_year_properties or 0),
    }


def get_monthly_revenue_trend(db_session: Session = None):
    """Returns the last 12 months of revenue for trend analysis."""
    if not db_session:
        with SessionLocal() as session:
            return get_monthly_revenue_trend(db_session=session)

    from datetime import timedelta
    start_date = datetime.now(timezone.utc) - timedelta(days=365)

    yr = year_of(Payment.date_paid).label('yr')
    mo = month_of(Payment.date_paid).label('mo')

    results = db_session.query(
        yr, mo, func.sum(Payment.amount).label('total')
    ).filter(Payment.date_paid >= start_date).group_by('yr', 'mo').order_by('yr', 'mo').all()

    return [
        {"month": f"{int(r.yr):04d}-{int(r.mo):02d}", "total": float(r.total or 0)}
        for r in results
    ]

def get_barangay_distribution(db_session: Session = None):
    """Returns revenue distribution across barangays."""
    if not db_session:
        with SessionLocal() as session:
            return get_barangay_distribution(db_session=session)

    # 1. Get receivables per barangay from property_billings (accurate after sync)
    # Uses TaxPolicy rates via correlated subquery
    rate_expr = tax_rate_subquery(db_session, PropertyBilling.tax_year)
    receivables_query = db_session.query(
        Property.barangay,
        func.coalesce(
            func.sum(
                (PropertyBilling.assessed_value * rate_expr)
                + PropertyBilling.penalty
                - PropertyBilling.discount
            ), 0
        ).label('receivables')
    ).join(PropertyBilling, PropertyBilling.property_id == Property.id).filter(
        Property.deleted_at == None
    ).group_by(Property.barangay).all()

    # 2. Get collected per barangay
    collected_query = db_session.query(
        Property.barangay,
        func.coalesce(func.sum(Payment.amount), 0).label('collected')
    ).join(Payment, Payment.property_id == Property.id).filter(
        Property.deleted_at == None
    ).group_by(Property.barangay).all()

    data = {}
    for r in receivables_query:
        brgy = r[0] or "UNKNOWN"
        data[brgy] = {"name": brgy, "value": float(r[1]), "collected": 0.0, "percentage": 0.0}

    for c in collected_query:
        brgy = c[0] or "UNKNOWN"
        if brgy not in data:
            data[brgy] = {"name": brgy, "value": 0.0, "collected": float(c[1]), "percentage": 0.0}
        else:
            data[brgy]["collected"] = float(c[1])

    result = []
    for brgy, stats in data.items():
        if stats["value"] > 0:
            stats["percentage"] = (stats["collected"] / stats["value"]) * 100
        else:
            stats["percentage"] = 0.0 if stats["collected"] == 0 else 100.0
        result.append(stats)
        
    result.sort(key=lambda x: x["collected"], reverse=True)
    return result

def get_tax_year_distribution(db_session: Session = None):
    """Returns the distribution of payments across tax years."""
    if not db_session:
        with SessionLocal() as session:
            return get_tax_year_distribution(db_session=session)

    results = db_session.query(
        Payment.tax_year,
        func.sum(Payment.amount).label('total')
    ).group_by(Payment.tax_year).order_by(Payment.tax_year.desc()).limit(5).all()
    
    return [{"year": r[0] or "N/A", "total": float(r[1] or 0)} for r in results]
