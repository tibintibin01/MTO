from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend.database import get_db
from backend.models import Payment, PaymentBilling, Property, PropertyBilling, TaxPolicy
from datetime import datetime, timezone
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

# Earliest year for which billing data exists. Records before this were
# back-filled from legacy effectivity dates and are excluded from balances.
DATA_START_YEAR = 2023


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


def _mask_owner_name(name: str) -> str:
    """
    Masks an owner name to protect privacy while remaining recognisable to
    the rightful owner. Shows the first character of each word, masks the rest.

    "JUAN DELA CRUZ" -> "J*** D*** C***"
    Short or empty names fall back to a generic placeholder so a 3-character
    name is never substantially revealed.
    """
    if not name or not name.strip():
        return "Taxpayer"
    parts = [p for p in str(name).strip().split() if p]
    masked_parts = []
    for p in parts:
        if len(p) <= 1:
            masked_parts.append(p)
        else:
            masked_parts.append(p[0] + "*" * 3)
    return " ".join(masked_parts) if masked_parts else "Taxpayer"


def _mask_pin(pin: str) -> str:
    """Masks a PIN, showing only the first and last 4 characters when long enough."""
    if pin and len(pin) > 8:
        return pin[:4] + "****" + pin[-4:]
    return "PIN-****"


def _compute_billing_breakdown(property_id: int, db_session: Session):
    """
    Computes the per-year billing breakdown and totals for a property using
    the configured TaxPolicy rate for each year (falling back to 1%+1%).

    Returns a dict:
      {
        "years": [ {tax_year, assessed_value, basic, sef, penalty,
                    discount, total_due, amount_paid, balance, status}, ... ],
        "total_due": float,
        "total_paid": float,
        "balance": float,
      }

    This is the authoritative source for "how much do I owe" — derived from
    PropertyBilling, not from a payment-year heuristic.
    """
    rows = (
        db_session.query(
            PropertyBilling.tax_year,
            PropertyBilling.assessed_value,
            PropertyBilling.penalty,
            PropertyBilling.discount,
            PropertyBilling.amount_paid,
            func.coalesce(TaxPolicy.basic_rate, 0.0100).label("basic_rate"),
            func.coalesce(TaxPolicy.sef_rate, 0.0100).label("sef_rate"),
        )
        .outerjoin(TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year)
        .filter(
            PropertyBilling.property_id == property_id,
            PropertyBilling.tax_year >= DATA_START_YEAR,
        )
        .order_by(PropertyBilling.tax_year.asc())
        .all()
    )

    receipt_values_by_year = {}
    linked_rows = (
        db_session.query(PaymentBilling, Payment, PropertyBilling.tax_year)
        .join(Payment, Payment.id == PaymentBilling.payment_id)
        .join(PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id)
        .filter(
            PropertyBilling.property_id == property_id,
            PropertyBilling.tax_year >= DATA_START_YEAR,
        )
        .all()
    )
    payment_ids = list({int(payment.id) for _link, payment, _year in linked_rows})
    link_counts = {}
    if payment_ids:
        link_counts = dict(
            db_session.query(PaymentBilling.payment_id, func.count(PaymentBilling.id))
            .filter(PaymentBilling.payment_id.in_(payment_ids))
            .group_by(PaymentBilling.payment_id)
            .all()
        )
    for link, payment, tax_year in linked_rows:
        summary = receipt_values_by_year.setdefault(
            int(tax_year), {"paid": 0.0, "penalty": 0.0, "discount": 0.0}
        )
        if int(link_counts.get(payment.id, 0) or 0) == 1:
            summary["paid"] += float(payment.amount or 0)
            summary["penalty"] += float(payment.penalty or 0)
            summary["discount"] += float(payment.discount or 0)
        else:
            summary["paid"] += float(link.amount_paid or 0)

    years = []
    total_due = 0.0
    total_paid = 0.0
    total_balance = 0.0
    total_credit = 0.0

    for r in rows:
        assessed = float(r.assessed_value or 0)
        basic = round(assessed * float(r.basic_rate or 0.01), 2)
        sef = round(assessed * float(r.sef_rate or 0.01), 2)
        penalty = float(r.penalty or 0)
        discount = float(r.discount or 0)
        paid = float(r.amount_paid or 0)
        receipt_values = receipt_values_by_year.get(int(r.tax_year))
        if receipt_values:
            paid = round(receipt_values["paid"], 2)
            if receipt_values["penalty"] > 0:
                penalty = round(receipt_values["penalty"], 2)
            if receipt_values["discount"] > 0:
                discount = round(receipt_values["discount"], 2)
        due = round(basic + sef + penalty - discount, 2)
        balance = round(max(0.0, due - paid), 2)
        credit = round(max(0.0, paid - due), 2)

        total_due += due
        total_paid += paid
        total_balance += balance
        total_credit += credit

        years.append({
            "tax_year": int(r.tax_year),
            "assessed_value": assessed,
            "basic": basic,
            "sef": sef,
            "penalty": penalty,
            "discount": discount,
            "total_due": due,
            "amount_paid": paid,
            "balance": balance,
            "credit": credit,
            "status": "Paid" if paid >= due and due > 0 else "Partial" if paid > 0 else "Unpaid",
        })

    # Keep excess payments as unapplied credits. They must not automatically
    # reduce a different tax year's outstanding receivable.
    balance = round(total_balance, 2)
    return {
        "years": years,
        "total_due": round(total_due, 2),
        "total_paid": round(total_paid, 2),
        "total_credit": round(total_credit, 2),
        "balance": balance,
    }


def _derive_status(breakdown: dict) -> str:
    """
    Derives the public status label from the COMPUTED balance, not from a
    payment-year heuristic.

      DELINQUENT — outstanding balance > 0
      UPDATED    — has billing, fully paid (balance == 0)
      PENDING    — no billing records yet (not assessed for the data period)
    """
    if not breakdown["years"]:
        return "PENDING"
    if breakdown["balance"] > 0:
        return "DELINQUENT"
    return "UPDATED"


@router.get("/property/{query}")
@limiter.limit("10/minute")
def search_property_public(query: str, request: Request, db_session: Session = Depends(get_db)):
    """
    Publicly accessible property inquiry endpoint for the web portal.

    Returns the property's COMPUTED outstanding balance and a per-year billing
    breakdown so a taxpayer can see exactly how much they owe without visiting
    the office. Limited fields are exposed and PII is masked for privacy.

    Rate-limited to 10 requests/minute per IP.
    """
    _validate_public_query(query)

    prop = db_session.query(Property).filter(
        (Property.td_number == query) | (Property.pin == query),
        Property.deleted_at == None
    ).first()

    if not prop:
        raise HTTPException(status_code=404, detail="Property not found.")

    breakdown = _compute_billing_breakdown(prop.id, db_session)
    status = _derive_status(breakdown)

    # Most recent payment for the "last payment" summary line
    last_pay = (
        db_session.query(Payment.date_paid, Payment.tax_year, Payment.amount)
        .filter(Payment.property_id == prop.id, Payment.date_paid != None)
        .order_by(Payment.date_paid.desc())
        .first()
    )
    last_payment = None
    if last_pay:
        last_payment = {
            "date_paid": last_pay.date_paid.strftime("%Y-%m-%d") if last_pay.date_paid else None,
            "period": last_pay.tax_year,
            "amount": float(last_pay.amount or 0),
        }

    return {
        "td_number": prop.td_number,
        "pin": _mask_pin(prop.pin),
        "owner_name": _mask_owner_name(prop.owner_name),
        "location": prop.location,
        "kind": prop.kind_of_property,
        "assessed_value": float(prop.assessed_value or 0),
        "status": status,
        # Real computed figures — the answer to "how much do I owe?"
        "balance": breakdown["balance"],
        "total_due": breakdown["total_due"],
        "total_paid": breakdown["total_paid"],
        "billing_breakdown": breakdown["years"],
        "last_payment": last_payment,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
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


# ---------------------------------------------------------------------------
# "Find my TDN" — owner-name + barangay lookup
# ---------------------------------------------------------------------------
# Lets a taxpayer who doesn't know their TDN find candidate properties by
# owner name within a barangay. Returns MASKED results (partial owner name +
# last 4 of the TDN) so the portal never exposes a full registry listing.
# The taxpayer recognises their own record and taps through; a scraper learns
# nothing useful.

_BARANGAY_RE = re.compile(r'^[A-Za-z0-9 .\-ñÑ]{1,60}$')


def _mask_td_tail(td: str) -> str:
    """Shows only the last 4 characters of a TDN: '06-0012-01379' -> '…1379'."""
    if not td:
        return "…"
    tail = td[-4:]
    return f"…{tail}"


@router.get("/find")
@limiter.limit("10/minute")
def find_property_by_owner(
    request: Request,
    name: str,
    barangay: str = None,
    db_session: Session = Depends(get_db),
):
    """
    Finds candidate properties by partial owner name, optionally scoped to a
    barangay. Returns up to 10 masked results.

    Privacy controls:
      - Requires at least 3 characters of name to prevent enumeration.
      - Results are masked (owner first-initials + TDN tail only).
      - Capped at 10 results; never paginated (no bulk extraction).
    Rate-limited to 10 requests/minute per IP.
    """
    clean_name = (name or "").strip()
    if len(clean_name) < 3:
        raise HTTPException(
            status_code=400,
            detail="Please enter at least 3 characters of the owner's name.",
        )
    if len(clean_name) > 60 or not _BARANGAY_RE.match(clean_name.replace("'", "")):
        raise HTTPException(status_code=400, detail="Invalid name format.")

    query = db_session.query(
        Property.td_number,
        Property.owner_name,
        Property.barangay,
        Property.kind_of_property,
    ).filter(
        Property.deleted_at == None,
        Property.owner_name.like(f"%{clean_name}%"),
    )

    if barangay and barangay.strip() and barangay.upper() != "ALL":
        clean_brgy = barangay.strip()
        if not _BARANGAY_RE.match(clean_brgy):
            raise HTTPException(status_code=400, detail="Invalid barangay format.")
        query = query.filter(Property.barangay == clean_brgy)

    rows = query.order_by(Property.owner_name.asc()).limit(11).all()

    # If more than 10 match, ask the user to refine rather than dumping results
    if len(rows) > 10:
        return {
            "results": [],
            "too_many": True,
            "message": "Too many matches. Add your barangay or more of your name.",
        }

    return {
        "results": [
            {
                "owner_name": _mask_owner_name(r.owner_name),
                "td_tail": _mask_td_tail(r.td_number),
                "td_number": r.td_number,  # full TDN — needed to navigate to detail
                "barangay": r.barangay,
                "kind": r.kind_of_property,
            }
            for r in rows
        ],
        "too_many": False,
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# Public Statement of Account (PDF)
# ---------------------------------------------------------------------------
# Lets a taxpayer download a printable SOA showing their per-year balance.
# PII is masked (owner/payor) to stay consistent with the inquiry view's
# privacy policy — the financial breakdown is the value, and the rightful
# owner already knows their own name.

@router.get("/property/{query}/soa")
@limiter.limit("5/minute")
def download_soa_public(query: str, request: Request, db_session: Session = Depends(get_db)):
    """
    Generates and returns a Statement of Account PDF for the given property.
    Rate-limited to 5 requests/minute per IP (PDF generation is heavier).
    """
    import os
    import asyncio  # noqa: F401 — kept for parity; generation runs sync here
    from fastapi.responses import FileResponse

    _validate_public_query(query)

    prop = db_session.query(Property).filter(
        (Property.td_number == query) | (Property.pin == query),
        Property.deleted_at == None
    ).first()

    if not prop:
        raise HTTPException(status_code=404, detail="Property not found.")

    breakdown = _compute_billing_breakdown(prop.id, db_session)
    if not breakdown["years"]:
        raise HTTPException(status_code=404, detail="No billing records to generate a statement.")

    # Map the computed breakdown to the SOA generator's expected row shape,
    # using MASKED owner/payor to match the public inquiry privacy policy.
    statement_data = {
        "td_number": prop.td_number,
        "owner_name": _mask_owner_name(prop.owner_name),
        "payor_name": _mask_owner_name(prop.payor_name) if prop.payor_name else _mask_owner_name(prop.owner_name),
        "location": prop.location,
        "kind_of_property": prop.kind_of_property,
        "accountable_officer": "—",  # not exposed publicly
        "grand_total": breakdown["balance"],
        "billing_rows": [
            {
                "tax_year": y["tax_year"],
                "assessed_value": y["assessed_value"],
                "basic_amount": y["basic"],
                "sef_amount": y["sef"],
                "penalty": y["penalty"],
                "total_amount": y["total_due"],
                "amount_paid": y["amount_paid"],
                "balance_amount": y["balance"],
            }
            for y in breakdown["years"]
        ],
    }

    from backend.generators import soa_gen
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_path = soa_gen.generate_statement_of_account(statement_data, base_dir)
    file_name = os.path.basename(pdf_path)

    return FileResponse(pdf_path, media_type="application/pdf", filename=file_name)
