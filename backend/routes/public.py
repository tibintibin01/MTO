from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import Property, Payment
from typing import List, Optional
from datetime import datetime
from backend.deps import limiter

router = APIRouter(prefix="/public", tags=["Public Portal"])

@router.get("/property/{query}")
@limiter.limit("20/minute")
def search_property_public(query: str, request: Request, db_session: Session = Depends(get_db)):
    """
    Publicly accessible endpoint for the web portal.
    Exposes limited information for privacy.
    """
    prop = db_session.query(Property).filter(
        (Property.td_number == query) | (Property.pin == query),
        Property.deleted_at == None
    ).first()

    if not prop:
        raise HTTPException(status_code=404, detail="Property not found.")

    # Calculate status
    has_unpaid = db_session.query(Payment).filter(Payment.property_id == prop.id).count() == 0
    
    # Securely mask PIN and Owner Name to protect citizen privacy
    masked_pin = prop.pin[:4] + "****" + prop.pin[-4:] if prop.pin and len(prop.pin) > 8 else "PIN-****"
    masked_owner = f"{prop.owner_name[:3]}*******" if prop.owner_name else "Taxpayer*******"

    return {
        "td_number": prop.td_number,
        "pin": masked_pin,
        "owner_name": masked_owner,
        "location": prop.location,
        "kind": prop.kind_of_property,
        "assessed_value": float(prop.assessed_value or 0),
        "status": "DELINQUENT" if has_unpaid else "UPDATED",
        "last_payment": None
    }

@router.get("/property/{query}/history")
@limiter.limit("20/minute")
def get_property_history_public(query: str, request: Request, db_session: Session = Depends(get_db)):
    """Exposes payment history for a property with rate-limiting protection."""
    prop = db_session.query(Property).filter(
        (Property.td_number == query) | (Property.pin == query),
        Property.deleted_at == None
    ).first()

    if not prop:
        raise HTTPException(status_code=404, detail="Property not found.")

    payments = db_session.query(Payment).filter(Payment.property_id == prop.id).order_by(Payment.date_paid.desc()).all()
    
    return [
        {
            "or_number": p.or_number[:3] + "****" if p.or_number else None,
            "date_paid": p.date_paid.strftime("%Y-%m-%d") if p.date_paid else None,
            "amount": float(p.amount or 0),
            "period": p.tax_year
        }
        for p in payments
    ]
