# -*- coding: utf-8 -*-
"""
Database-portable SQLAlchemy expression helpers.

All functions here produce expressions that work on MySQL, MariaDB,
PostgreSQL, and SQLite without dialect-specific SQL functions.

Rules:
- Never use func.date_format(), func.curdate(), func.year(),
  func.month(), func.greatest(), or func.interval() directly.
  Use the helpers below instead.
"""
from datetime import date, datetime, timedelta
from sqlalchemy import cast, extract, case, func
from sqlalchemy.types import Date


def today() -> date:
    """Returns today's date as a Python date object for use in filter()."""
    return datetime.now().date()


def this_month_start() -> date:
    """Returns the first day of the current month."""
    d = today()
    return d.replace(day=1)


def this_year_start() -> date:
    """Returns the first day of the current year."""
    d = today()
    return d.replace(month=1, day=1)


def days_ago(n: int) -> datetime:
    """Returns a datetime n days in the past."""
    return datetime.now() - timedelta(days=n)


def date_trunc(col):
    """
    Casts a DateTime column to Date for date-equality comparisons.

    Replaces: func.date(col) == func.curdate()
    Use as:   cast(col, Date) == today()
    """
    return cast(col, Date)


def year_of(col):
    """
    Extracts the year from a DateTime column.

    Replaces: func.year(col) == some_year
    Use as:   year_of(col) == some_year
    """
    return extract('year', col)


def month_of(col):
    """
    Extracts the month (1-12) from a DateTime column.

    Replaces: func.month(col) == some_month
    Use as:   month_of(col) == some_month
    """
    return extract('month', col)


def greatest(a, b):
    """
    Returns the greater of two SQL expressions.

    Replaces: func.greatest(a, b)
    Use as:   greatest(expr_a, expr_b)
    """
    return case((a > b, a), else_=b)


def month_label(col):
    """
    Produces a sortable (year, month) tuple for GROUP BY month queries.

    Replaces: func.date_format(col, '%Y-%m')

    Returns (year_expr, month_expr) — use both in .group_by() and build
    the 'YYYY-MM' string in Python from the result tuple. This avoids
    func.concat / func.lpad which are also MySQL-specific.

    Usage:
        yr = year_of(Payment.date_paid).label('yr')
        mo = month_of(Payment.date_paid).label('mo')
        rows = db.query(yr, mo, func.sum(Payment.amount).label('total'))
                  .group_by('yr', 'mo').order_by('yr', 'mo').all()
        return [
            {"month": f"{int(r.yr):04d}-{int(r.mo):02d}", "total": float(r.total or 0)}
            for r in rows
        ]

    See get_monthly_collection_trend() and get_monthly_revenue_trend()
    for reference implementations.
    """
    return year_of(col), month_of(col)
