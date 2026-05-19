# -*- coding: utf-8 -*-
import re
from decimal import Decimal, ROUND_HALF_UP
# import db_manager as db # Mark for removal
from backend.database import SessionLocal
from backend.models import ReceiptHistory
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session
from backend.models import Payment, Property, PropertyBilling, PaymentBilling
from backend.services.auth_service import get_username, require_permission
from backend.services.billing_service import format_tax_years, normalize_date_input


def _d(value) -> Decimal:
    """Convert any numeric value to Decimal safely. Use instead of float() for financial values."""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def find_duplicate_payment(
    property_id, or_number, tax_year_text, exclude_payment_id=None, cur=None, db_session: Session = None
):
    normalized_years = format_tax_years(tax_year_text)
    if not property_id or not or_number or not normalized_years:
        return None

    query = db_session.query(Payment).filter(
        Payment.property_id == property_id,
        Payment.or_number == or_number,
        func.coalesce(Payment.tax_year, '') == normalized_years
    )
    if exclude_payment_id:
        query = query.filter(Payment.id != exclude_payment_id)
    
    row = query.order_by(Payment.id.desc()).first()
    if not row:
        return None
    return {
        "payment_id": row.id,
        "or_number": row.or_number,
        "tax_year": row.tax_year,
        "amount": float(_d(row.amount)),
        "date_paid": row.date_paid,
    }


def find_duplicate_payment_entry(
    td_number, or_number, or_date, tax_year_text, exclude_payment_id=None, cur=None, db_session: Session = None
):
    td_text = str(td_number or "").strip()
    or_text = str(or_number or "").strip()
    date_text = normalize_date_input(or_date)
    normalized_years = format_tax_years(tax_year_text)
    if not td_text or not or_text or not date_text or not normalized_years:
        return None

    row = db_session.query(Payment, Property).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None,
        Property.td_number == td_text,
        Payment.or_number == or_text,
        Payment.date_paid == date_text,
        func.coalesce(Payment.tax_year, '') == normalized_years
    )
    if exclude_payment_id:
        row = row.filter(Payment.id != exclude_payment_id)
    
    result = row.order_by(Payment.id.desc()).first()
    if not result:
        return None
    pay, prop = result
    return {
        "payment_id": pay.id,
        "property_id": prop.id,
        "td_number": prop.td_number,
        "owner_name": prop.owner_name,
        "or_number": pay.or_number,
        "date_paid": pay.date_paid,
        "tax_year": pay.tax_year,
        "amount": float(_d(pay.amount)),
    }


def get_existing_payment_amount(property_id, or_number, or_date, tax_year_text, db_session: Session = None):
    normalized_years = format_tax_years(tax_year_text)
    normalized_date = normalize_date_input(or_date)
    if not property_id or not or_number or not normalized_date or not normalized_years:
        return None
    
    row = db_session.query(Payment.amount).filter(
        Payment.property_id == property_id,
        Payment.or_number == str(or_number).strip(),
        Payment.date_paid == normalized_date,
        func.coalesce(Payment.tax_year, '') == normalized_years
    ).order_by(Payment.id.desc()).first()
    return float(_d(row[0])) if row else None


def acquire_payment_post_lock(property_id, user_name, stale_minutes=30):
    return {"ok": True, "locked_by": user_name}


def release_payment_post_lock(property_id, user_name):
    pass


def release_all_payment_post_locks(user_name):
    pass


def get_next_or_number(default_prefix="OR-", db_session: Session = None):
    rows = db_session.query(Payment.or_number).filter(Payment.or_number != None, Payment.or_number != '').order_by(Payment.id.desc()).limit(20).all()
    for row in rows:
        current = str(row[0]).strip()
        match = re.search(r"^(.*?)(\d+)$", current)
        if not match:
            continue
        prefix, digits = match.groups()
        next_value = int(digits) + 1
        return f"{prefix}{next_value:0{len(digits)}d}"
    return f"{default_prefix}000001"


def get_recent_payments(limit=8, db_session: Session = None):
    safe_limit = max(1, int(limit))
    rows = db_session.query(
        Payment.date_paid, Payment.or_number, Property.td_number, Property.owner_name, Payment.tax_year, Payment.amount, Payment.id
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None
    ).order_by(
        func.coalesce(Payment.date_paid, func.date(Payment.created_at)).desc(), Payment.id.desc()
    ).limit(safe_limit).all()
    return [list(r) for r in rows]


def get_monthly_collection_trend(months=6, db_session: Session = None):
    safe_months = max(1, int(months))
    from datetime import datetime, timedelta
    start_date = datetime.now() - timedelta(days=30 * safe_months)
    
    results = db_session.query(
        func.date_format(func.coalesce(Payment.date_paid, func.date(Payment.created_at)), '%Y-%m').label('month'),
        func.sum(Payment.amount).label('total')
    ).filter(
        func.coalesce(Payment.date_paid, func.date(Payment.created_at)) >= start_date
    ).group_by('month').order_by('month').all()
    
    return [{"month": r[0], "total": float(_d(r[1]))} for r in results]


def get_revenue_by_barangay(db_session: Session = None):
    results = db_session.query(
        func.coalesce(Property.barangay, 'UNSPECIFIED').label('brgy'),
        func.sum(Payment.amount).label('total')
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None
    ).group_by('brgy').order_by(func.sum(Payment.amount).desc()).all()
    
    return [{"barangay": r[0], "total": float(_d(r[1]))} for r in results]


def get_collection_kpis(db_session: Session = None):
    total = db_session.query(func.sum(Payment.amount), func.count(Payment.id)).first()
    today = db_session.query(func.sum(Payment.amount)).filter(func.date(Payment.date_paid) == func.curdate()).scalar()
    month = db_session.query(func.sum(Payment.amount)).filter(
        func.year(Payment.date_paid) == func.year(func.curdate()),
        func.month(Payment.date_paid) == func.month(func.curdate())
    ).scalar()
    
    return {
        "total_revenue": float(_d(total[0])),
        "payment_count": int(total[1] or 0),
        "today": float(_d(today)),
        "month": float(_d(month))
    }


def get_unified_payment_history(term, db_session: Session = None):
    """
    Unified query for the Integrated Ledger & Receipt History.
    Returns payment details combined with receipt audit info using SQLAlchemy.
    """
    if not term:
        return []

    like_term = f"%{term}%"
    results = db_session.query(
        Payment.id.label('payment_id'),
        Payment.date_paid,
        Payment.or_number,
        Payment.tax_year,
        (Property.assessed_value * 0.01).label('basic'),
        (Property.assessed_value * 0.01).label('sef'),
        Payment.penalty,
        Payment.discount,
        Payment.amount,
        Payment.posted_by,
        ReceiptHistory.file_path,
        ReceiptHistory.id.label('receipt_id'),
        Property.td_number,
        Property.owner_name
    ).join(Property, Property.id == Payment.property_id).outerjoin(
        ReceiptHistory, ReceiptHistory.payment_id == Payment.id
    ).filter(
        Property.deleted_at == None,
        or_(
            Property.td_number == term,
            Property.owner_name.like(like_term),
            Payment.or_number.like(like_term)
        )
    ).order_by(Payment.date_paid.desc(), Payment.id.desc()).all()
    
    return [list(r) for r in results]


def get_payment_ledger(td_number, db_session: Session = None):
    """
    Specific ledger query for the Dossier UI using SQLAlchemy.
    """
    results = db_session.query(
        Payment.date_paid,
        Payment.or_number,
        Payment.tax_year,
        (Property.assessed_value * 0.01).label('basic'),
        (Property.assessed_value * 0.01).label('sef'),
        Payment.penalty,
        Payment.discount,
        Payment.amount
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.td_number == td_number,
        Property.deleted_at == None
    ).order_by(Payment.date_paid.desc(), Payment.id.desc()).all()
    return [list(r) for r in results]


def get_payment_receipt_records(term, limit=50, offset=0, db_session: Session = None):
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))
    
    like_term = f"%{term}%"
    results = db_session.query(
        Payment.id,
        Payment.date_paid,
        Property.td_number,
        Property.owner_name,
        Property.kind_of_property,
        Payment.or_number,
        Payment.tax_year,
        Payment.amount,
        ReceiptHistory.file_path,
        ReceiptHistory.generated_by,
        ReceiptHistory.status,
        ReceiptHistory.id.label('rh_id')
    ).join(Property, Property.id == Payment.property_id).outerjoin(
        ReceiptHistory, ReceiptHistory.payment_id == Payment.id
    ).filter(
        Property.deleted_at == None,
        or_(
            Property.td_number.like(like_term),
            Property.owner_name.like(like_term),
            Payment.or_number.like(like_term)
        )
    ).order_by(Payment.date_paid.desc(), Payment.id.desc()).limit(safe_limit).offset(safe_offset).all()
    
    return [list(r) for r in results]


def get_payment_receipt_details(payment_id, db_session: Session = None):
    row = db_session.query(
        Property.id.label('property_id'),
        Property.td_number,
        Property.owner_name,
        Property.payor_name,
        Property.lot_number,
        Property.area,
        Property.location,
        Property.kind_of_property,
        Property.accountable_officer,
        Property.assessed_value,
        Payment.penalty,
        Payment.discount,
        Payment.id.label('payment_id'),
        Payment.amount,
        Payment.or_number,
        Payment.date_paid,
        Payment.tax_year,
        ReceiptHistory.file_path,
        ReceiptHistory.id.label('rh_id')
    ).join(Property, Property.id == Payment.property_id).outerjoin(
        ReceiptHistory, ReceiptHistory.payment_id == Payment.id
    ).filter(
        Payment.id == payment_id,
        Property.deleted_at == None
    ).first()
    
    if not row:
        return None
    return {
        "property_id": row.property_id,
        "td_number": row.td_number,
        "owner_name": row.owner_name,
        "payor_name": row.payor_name,
        "lot_number": row.lot_number,
        "area": row.area,
        "location": row.location,
        "kind_of_property": row.kind_of_property,
        "accountable_officer": row.accountable_officer,
        "assessed_value": float(_d(row.assessed_value)),
        "penalty": float(_d(row.penalty)),
        "discount": float(_d(row.discount)),
        "payment_id": row.payment_id,
        "amount": float(_d(row.amount)),
        "or_number": row.or_number,
        "date_paid": row.date_paid,
        "tax_year": row.tax_year,
        "file_path": row.file_path,
        "receipt_history_id": row.rh_id,
    }


@require_permission("receipt_generate")
def save_receipt_record(
    property_id, payment_id, details, file_path, user_name, db_session: Session = None, **kwargs
):
    from datetime import datetime
    
    # Check if exists
    rh = db_session.query(ReceiptHistory).filter(ReceiptHistory.payment_id == payment_id).first()
    if rh:
        rh.file_path = file_path
        rh.generated_by = get_username(user_name)
        rh.generated_at = datetime.now()
        rh.status = 'PDF READY'
    else:
        rh = ReceiptHistory(
            property_id=property_id,
            payment_id=payment_id,
            or_number=details.get("or_number"),
            file_path=file_path,
            generated_by=get_username(user_name),
            generated_at=datetime.now(),
            status='PDF READY'
        )
        db_session.add(rh)
    
    db_session.commit()
    return {"id": rh.id}


@require_permission("payment_delete")
def delete_payment_record(payment_id, user_name, db_session: Session = None, **kwargs):
    """
    Deletes a payment record and reverses its impact on the corresponding PropertyBilling.
    """
    from backend.services.system_service import log_action

    # 1. Fetch Payment
    payment = db_session.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise Exception("Payment record not found.")

    prop_id = payment.property_id
    tax_year = payment.tax_year
    amt = _d(payment.amount)
    pen = _d(payment.penalty)
    disc = _d(payment.discount)
    or_no = payment.or_number

    # 2. Reverse Billing Balances (if billing exists)
    billing = db_session.query(PropertyBilling).filter(
        PropertyBilling.property_id == prop_id,
        PropertyBilling.tax_year == tax_year
    ).with_for_update().first()

    if billing:
        # Subtract the amounts back out
        billing.amount_paid = max(_d(0), _d(billing.amount_paid) - amt)
        billing.penalty = max(_d(0), _d(billing.penalty) - pen)
        billing.discount = max(_d(0), _d(billing.discount) - disc)

    # 3. Delete Payment (cascade will handle ReceiptHistory and PaymentBilling)
    db_session.delete(payment)

    # 4. Audit & Commit
    log_action(user_name, f"Deleted Payment OR {or_no} (Amount: {amt}) and reversed billing.", db_session=db_session)
    db_session.commit()
    
    # 5. Refresh System Stats
    try:
        from backend.services.stats_service import refresh_system_stats
        refresh_system_stats(db_session=db_session)
    except:
        pass

    return {"success": True, "message": "Payment deleted successfully."}
