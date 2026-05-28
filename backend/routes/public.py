from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import Property, Payment
from typing import List, Optional
from datetime import datetime
from backend.deps import limiter
import re

router = APIRouter(prefix="/public", tags=["Public Portal"])

# ---------------------------------------------------------------------------
# Public query validation
# ---------------------------------------------------------------------------
# TD numbers follow patterns like: 06-0012-01379, TD-2023-001, or plain PIN
# digits. We validate server-side (not just in the Next.js frontend) so
# malformed or oversized inputs are rejected before touching the DB.
#
# Rules:
#   - 1–50 characters
#   - Only alphanumeric, hyphen, dot, slash, hash, space
#   - Must start with an alphanumeric character (no leading special chars)
_QUERY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9\-./# ]{0,49}$')
_MAX_QUERY_LEN = 50


def _validate_public_query(query: str) -> None:
    """
    Raises HTTP 400 if the query string is malformed or oversized.
    Called before any DB access so invalid inputs never reach the database.
    """
    if not query or len(query) > _MAX_QUERY_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Query must be 1–{_MAX_QUERY_LEN} characters.",
        )
    if not _QUERY_RE.match(query):
        raise HTTPException(
            status_code=400,
            detail="Invalid query format. Use your TDN (e.g. 06-0012-01379) or PIN.",
        )


@router.get("/property/{query}")
@limiter.limit("10/minute")
def search_property_public(query: str, request: Request, db_session: Session = Depends(get_db)):
    """
    Publicly accessible endpoint for the web portal.
    Exposes limited information for privacy.
    Rate-limited to 10 requests/minute per IP.
    """
    _validate_public_query(query)

    prop = db_session.query(Property).filter(
        (Property.td_number == query) | (Property.pin == query),
        Property.deleted_at == None
    ).first()

    if not prop:
        raise HTTPException(status_code=404, detail="Property not found.")

    # Business rule: if the property has a payment for the current year,
    # it is considered UPDATED — you cannot pay the current year without
    # settling prior years first (municipal treasury policy).
    # If no current year payment exists, check the most recent payment year
    # against the most recent billing year to determine status.
    from backend.models import PropertyBilling, Payment
    from sqlalchemy import func
    from datetime import datetime, timezone

    current_year = datetime.now(timezone.utc).year
    DATA_START_YEAR = 2023
    TOTAL_RATE = 0.02

    # Check if there is a payment for the current year
    has_current_year_payment = db_session.query(Payment.id).filter(
        Payment.property_id == prop.id,
        Payment.tax_year == str(current_year),
    ).first() is not None

    if has_current_year_payment:
        # Paid current year = settled all arrears per municipal policy
        status = "UPDATED"
    else:
        # Check most recent payment year
        latest_payment_year = db_session.query(
            func.max(Payment.tax_year)
        ).filter(
            Payment.property_id == prop.id,
            Payment.tax_year != None,
            Payment.tax_year != "",
        ).scalar()

        if latest_payment_year:
            try:
                latest_yr = int(str(latest_payment_year).strip())
                # If paid last year and no billing data uploaded for current year yet
                # treat as updated — data may not be uploaded yet
                if latest_yr >= current_year - 1:
                    status = "UPDATED"
                else:
                    status = "DELINQUENT"
            except (ValueError, TypeError):
                status = "DELINQUENT"
        else:
            # No payments at all — check billing records
            billing_summary = db_session.query(
                func.coalesce(func.sum(
                    (PropertyBilling.assessed_value * TOTAL_RATE)
                    + PropertyBilling.penalty
                    - PropertyBilling.discount
                ), 0).label("total_due"),
                func.coalesce(func.sum(PropertyBilling.amount_paid), 0).label("total_paid_billing"),
            ).filter(
                PropertyBilling.property_id == prop.id,
                PropertyBilling.tax_year >= DATA_START_YEAR,
            ).first()

            total_due = float(billing_summary.total_due or 0)
            if total_due == 0:
                status = "PENDING"
            else:
                status = "DELINQUENT"
    
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
        "status": status,
        "last_payment": None
    }

@router.get("/property/{query}/history")
@limiter.limit("10/minute")
def get_property_history_public(query: str, request: Request, db_session: Session = Depends(get_db)):
    """
    Exposes payment history for a property with rate-limiting protection.
    Rate-limited to 10 requests/minute per IP.
    """
    _validate_public_query(query)

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
