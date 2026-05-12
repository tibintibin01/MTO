# -*- coding: utf-8 -*-
import db_manager as db
from datetime import datetime

def get_collection_summary():
    """Returns key collection totals for today, this month, and this year."""
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    this_month = now.strftime('%Y-%m-%%')
    this_year = now.strftime('%Y-%%')

    query = """
        SELECT 
            SUM(CASE WHEN date_paid = %s THEN amount ELSE 0 END) as today_total,
            SUM(CASE WHEN date_paid LIKE %s THEN amount ELSE 0 END) as month_total,
            SUM(CASE WHEN date_paid LIKE %s THEN amount ELSE 0 END) as year_total,
            COUNT(CASE WHEN date_paid = %s THEN 1 END) as today_count
        FROM payments
    """
    rows = db.db_query(query, (today, this_month, this_year, today), fetch=True, commit=False)
    if not rows:
        return {"today": 0, "month": 0, "year": 0, "count": 0}
    
    row = rows[0]
    return {
        "today": float(row[0] or 0),
        "month": float(row[1] or 0),
        "year": float(row[2] or 0),
        "count": int(row[3] or 0)
    }

def get_monthly_revenue_trend():
    """Returns the last 12 months of revenue for trend analysis."""
    query = """
        SELECT DATE_FORMAT(date_paid, '%Y-%m') as month, SUM(amount) as total
        FROM payments
        WHERE date_paid >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
        GROUP BY month
        ORDER BY month ASC
    """
    rows = db.db_query(query, fetch=True, commit=False)
    return [{"month": r[0], "total": float(r[1] or 0)} for r in rows] if rows else []

def get_barangay_distribution():
    """Returns revenue distribution across barangays."""
    query = """
        SELECT prop.barangay, SUM(pay.amount) as total
        FROM payments pay
        JOIN properties prop ON pay.property_id = prop.id
        WHERE prop.is_deleted = 0
        GROUP BY prop.barangay
        ORDER BY total DESC
        LIMIT 10
    """
    rows = db.db_query(query, fetch=True, commit=False)
    return [{"name": r[0] or "UNKNOWN", "value": float(r[1] or 0)} for r in rows] if rows else []

def get_tax_year_distribution():
    """Returns the distribution of payments across tax years."""
    query = """
        SELECT tax_year, SUM(amount) as total
        FROM payments
        GROUP BY tax_year
        ORDER BY tax_year DESC
        LIMIT 5
    """
    rows = db.db_query(query, fetch=True, commit=False)
    return [{"year": r[0] or "N/A", "total": float(r[1] or 0)} for r in rows] if rows else []
