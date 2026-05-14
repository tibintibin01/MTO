# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from backend.models import Property, Payment, AuditLog
from backend.database import SessionLocal


def get_retention_summary(db_session: Session = None):
    """Calculates how much data is eligible for archival based on a 10-year policy."""
    if not db_session:
        db_session = SessionLocal()

    ten_years_ago = datetime.now() - timedelta(days=3650)
    
    prop_count = db_session.query(func.count(Property.id)).filter(
        Property.created_at < ten_years_ago,
        Property.is_deleted == False
    ).scalar()
    
    pay_count = db_session.query(func.count(Payment.id)).filter(
        Payment.date_paid < ten_years_ago.date()
    ).scalar()
    
    return {
        "eligible_properties": prop_count or 0,
        "eligible_payments": pay_count or 0,
        "cutoff_date": ten_years_ago.strftime("%Y-%m-%d")
    }


def run_archival_policy(user="SYSTEM", db_session: Session = None):
    """
    Moves data older than 10 years to archive tables to maintain performance.
    """
    if not db_session:
        db_session = SessionLocal()

    cutoff_date = datetime.now() - timedelta(days=3650)
    
    try:
        # 1. Ensure Archive Tables Exist
        db_session.execute(text("CREATE TABLE IF NOT EXISTS properties_archive LIKE properties"))
        db_session.execute(text("CREATE TABLE IF NOT EXISTS payments_archive LIKE payments"))
        
        # 2. Archive Old Properties
        db_session.execute(
            text("INSERT INTO properties_archive SELECT * FROM properties WHERE created_at < :cutoff"),
            {"cutoff": cutoff_date}
        )
        # SQLAlchemy core doesn't easily give rowcount for INSERT SELECT in this way without more ceremony
        # but we can query it or just trust the DB
        
        db_session.execute(
            text("DELETE FROM properties WHERE created_at < :cutoff"),
            {"cutoff": cutoff_date}
        )
        
        # 3. Archive Old Payments
        db_session.execute(
            text("INSERT INTO payments_archive SELECT * FROM payments WHERE date_paid < :cutoff"),
            {"cutoff": cutoff_date.date()}
        )
        
        db_session.execute(
            text("DELETE FROM payments WHERE date_paid < :cutoff"),
            {"cutoff": cutoff_date.date()}
        )
        
        # 4. Log the policy enforcement
        log = AuditLog(
            username=user,
            action=f"RETENTION_POLICY_ENFORCED",
            timestamp=datetime.now()
        )
        db_session.add(log)
        db_session.commit()
        
        return {
            "status": "success"
        }
    except Exception as e:
        db_session.rollback()
        return {
            "status": "error",
            "message": str(e)
        }
