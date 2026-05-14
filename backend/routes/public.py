# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import Property, Payment
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/public", tags=["Public Portal"])

@router.get("/property/{query}")
def search_property_public(query: str, db_session: Session = Depends(get_db)):
    """
    Publicly accessible endpoint for the web portal.
    Exposes limited information for privacy.
    """
    prop = db_session.query(Property).filter(
        (Property.td_number == query) | (Property.pin == query),
        Property.is_deleted == False
    ).first()

    if not prop:
        raise HTTPException(status_code=404, detail="Property not found.")

    # Calculate status
    # In a real system, we'd check delinquency logic here
    has_unpaid = db_session.query(Payment).filter(Payment.property_id == prop.id).count() == 0
    
    return {
        "td_number": prop.td_number,
        "pin": prop.pin,
        "owner_name": f"{prop.owner_name[:3]}*** {prop.owner_name.split()[-1] if ' ' in prop.owner_name else ''}", # Masked for privacy
        "location": prop.location,
        "kind": prop.kind_of_property,
        "assessed_value": float(prop.assessed_value or 0),
        "status": "DELINQUENT" if has_unpaid else "UPDATED",
        "last_payment": None # To be implemented with payment history
    }

@router.get("/property/{query}/history")
def get_property_history_public(query: str, db_session: Session = Depends(get_db)):
    """Exposes payment history for a property."""
    prop = db_session.query(Property).filter(
        (Property.td_number == query) | (Property.pin == query),
        Property.is_deleted == False
    ).first()

    if not prop:
        raise HTTPException(status_code=404, detail="Property not found.")

    payments = db_session.query(Payment).filter(Payment.property_id == prop.id).order_by(Payment.date_paid.desc()).all()
    
    return [
        {
            "or_number": p.or_number,
            "date_paid": p.date_paid.strftime("%Y-%m-%d") if p.date_paid else None,
            "amount": float(p.amount or 0),
            "period": p.tax_year
        }
        for p in payments
    ]
