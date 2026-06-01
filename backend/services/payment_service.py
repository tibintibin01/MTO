# -*- coding: utf-8 -*-
import re
from decimal import Decimal
from backend.database import SessionLocal
from backend.models import ReceiptHistory
from sqlalchemy import or_, func, cast
from sqlalchemy.types import Date
from sqlalchemy.orm import Session
from backend.models import Payment, Property, PropertyBilling, PaymentBilling
from backend.services.auth_service import get_username, require_permission
from backend.services.billing_service import format_tax_years, normalize_date_input
from utils.db_compat import year_of, month_of, today


def _d(value) -> Decimal:
    """Convert any numeric value to Decimal safely. Use instead of float() for financial values."""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def find_duplicate_payment(
    property_id, or_number, tax_year_text, exclude_payment_id=None, db_session: Session = None
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
    td_number, or_number, or_date, tax_year_text, exclude_payment_id=None, db_session: Session = None
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


def get_next_or_number(default_prefix="OR-", db_session: Session = None):
    from backend.models import ORSequence

    # Query with exclusive row-level lock
    seq = db_session.query(ORSequence).filter(ORSequence.prefix == default_prefix).with_for_update().first()

    if not seq:
        # No sequence row yet — seed from the latest payments so existing OR
        # numbers are not re-issued, then insert the row.
        #
        # Use a SEPARATE session for the insert so the seed commit is isolated
        # from the caller's transaction. Two concurrent cashiers may both reach
        # this branch simultaneously; the unique constraint on `prefix` ensures
        # only one insert wins. The loser's IntegrityError is swallowed and both
        # threads then re-fetch the winning row on the caller's session below.
        next_val = 1
        digits_len = 6
        prefix_str = default_prefix

        rows = db_session.query(Payment.or_number).filter(
            Payment.or_number != None,
            Payment.or_number != ""
        ).order_by(Payment.id.desc()).limit(20).all()

        for row in rows:
            current = str(row[0]).strip()
            match = re.search(r"^(.*?)(\d+)$", current)
            if match:
                prefix_str, digits = match.groups()
                next_val = int(digits) + 1
                digits_len = len(digits)
                break

        try:
            with SessionLocal() as seed_db:
                seed_db.add(ORSequence(
                    prefix=default_prefix,
                    next_value=next_val,
                    digits=digits_len,
                ))
                seed_db.commit()
        except Exception:
            # Another concurrent request already inserted the row — that's fine.
            pass

        # Re-fetch on the caller's session with the exclusive lock now that the
        # row definitely exists (either we just created it or a peer did).
        seq = db_session.query(ORSequence).filter(
            ORSequence.prefix == default_prefix
        ).with_for_update().first()

    or_num = f"{seq.prefix}{seq.next_value:0{seq.digits}d}"

    # Increment within the caller's transaction — do NOT commit here.
    # Committing mid-transaction would consume the OR number even if the
    # payment fails afterward, creating gaps in the receipt sequence that
    # COA auditors will flag. flush() makes the increment visible within
    # the current transaction without releasing the row lock prematurely.
    seq.next_value += 1
    db_session.add(seq)
    db_session.flush()

    return or_num


def get_recent_payments(limit=8, db_session: Session = None):
    safe_limit = max(1, int(limit))
    rows = db_session.query(
        Payment.date_paid, Payment.or_number, Property.td_number, Property.owner_name, Payment.tax_year, Payment.amount, Payment.id
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None
    ).order_by(
        func.coalesce(Payment.date_paid, cast(Payment.created_at, Date)).desc(), Payment.id.desc()
    ).limit(safe_limit).all()
    return [list(r) for r in rows]


def get_monthly_collection_trend(months=6, db_session: Session = None):
    safe_months = max(1, int(months))
    from datetime import datetime, timedelta, timezone
    start_date = datetime.now(timezone.utc) - timedelta(days=30 * safe_months)

    effective_date = func.coalesce(Payment.date_paid, cast(Payment.created_at, Date))
    yr = year_of(effective_date).label('yr')
    mo = month_of(effective_date).label('mo')

    results = db_session.query(
        yr, mo, func.sum(Payment.amount).label('total')
    ).filter(
        effective_date >= start_date
    ).group_by('yr', 'mo').order_by('yr', 'mo').all()

    return [
        {"month": f"{int(r.yr):04d}-{int(r.mo):02d}", "total": float(_d(r.total))}
        for r in results
    ]


def get_revenue_by_barangay(db_session: Session = None):
    results = db_session.query(
        func.coalesce(Property.barangay, 'UNSPECIFIED').label('brgy'),
        func.sum(Payment.amount).label('total')
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None
    ).group_by('brgy').order_by(func.sum(Payment.amount).desc()).all()
    
    return [{"barangay": r[0], "total": float(_d(r[1]))} for r in results]


def get_collection_kpis(db_session: Session = None):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    today_date = now.date()
    month_start = today_date.replace(day=1)

    total = db_session.query(func.sum(Payment.amount), func.count(Payment.id)).first()
    today_amt = db_session.query(func.sum(Payment.amount)).filter(
        cast(Payment.date_paid, Date) == today_date
    ).scalar()
    month_amt = db_session.query(func.sum(Payment.amount)).filter(
        cast(Payment.date_paid, Date) >= month_start
    ).scalar()

    return {
        "total_revenue": float(_d(total[0])),
        "payment_count": int(total[1] or 0),
        "today": float(_d(today_amt)),
        "month": float(_d(month_amt)),
    }


def get_unified_payment_history(term, db_session: Session = None):
    """
    Unified query for the Integrated Ledger & Receipt History.
    Returns payment details combined with receipt audit info using SQLAlchemy.

    Basic/SEF amounts are derived from the TaxPolicy rate for the billing year.
    Falls back to 1% each if no policy is configured for that year.
    """
    if not term:
        return []

    from backend.models import TaxPolicy
    from backend.services.billing_service import basic_rate_expr, sef_rate_expr

    like_term = f"%{term}%"
    results = db_session.query(
        Payment.id.label('payment_id'),
        Payment.date_paid,
        Payment.or_number,
        Payment.tax_year,
        # Use TaxPolicy rates instead of hardcoded 0.01
        (Property.assessed_value * basic_rate_expr()).label('basic'),
        (Property.assessed_value * sef_rate_expr()).label('sef'),
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
    ).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == Property.tax_year
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
    Uses TaxPolicy rates for the basic/SEF split display.
    """
    from backend.models import TaxPolicy
    from backend.services.billing_service import basic_rate_expr, sef_rate_expr

    results = db_session.query(
        Payment.date_paid,
        Payment.or_number,
        Payment.tax_year,
        (Property.assessed_value * basic_rate_expr()).label('basic'),
        (Property.assessed_value * sef_rate_expr()).label('sef'),
        Payment.penalty,
        Payment.discount,
        Payment.amount
    ).join(Property, Property.id == Payment.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == Property.tax_year
    ).filter(
        Property.td_number == td_number,
        Property.deleted_at == None
    ).order_by(Payment.date_paid.desc(), Payment.id.desc()).all()
    return [list(r) for r in results]


def get_payment_receipt_records(term, limit=50, cursor=None, db_session: Session = None):
    safe_limit = min(max(1, int(limit)), 200)

    like_term = f"%{term}%"
    query = db_session.query(
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
    )

    if cursor:
        query = query.filter(Payment.id < int(cursor))

    rows = query.order_by(Payment.id.desc()).limit(safe_limit + 1).all()

    has_more = len(rows) > safe_limit
    items = rows[:safe_limit]
    next_cursor = items[-1][0] if has_more and items else None

    return {
        "items": [list(r) for r in items],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items),
    }


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
    from datetime import datetime, timezone
    import os

    # Check if a receipt already exists for this payment
    rh = db_session.query(ReceiptHistory).filter(ReceiptHistory.payment_id == payment_id).first()
    if rh:
        # Delete the old PDF from disk before overwriting the path so stale
        # files don't accumulate in the receipts directory.
        old_path = rh.file_path
        if old_path and old_path != file_path and os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError as del_err:
                from utils import log_error_to_file
                log_error_to_file(f"Could not delete old receipt file '{old_path}'", del_err)

        rh.file_path = file_path
        rh.generated_by = get_username(user_name)
        rh.generated_at = datetime.now(timezone.utc)
        rh.status = 'PDF READY'
    else:
        rh = ReceiptHistory(
            property_id=property_id,
            payment_id=payment_id,
            or_number=details.get("or_number"),
            file_path=file_path,
            generated_by=get_username(user_name),
            generated_at=datetime.now(timezone.utc),
            status='PDF READY'
        )
        db_session.add(rh)

    db_session.commit()
    return {"id": rh.id}


@require_permission("payment_delete")
def delete_payment_record(payment_id, user_name, db_session: Session = None, **kwargs):
    """
    Deletes a payment record and reverses its impact on the corresponding PropertyBilling.
    The billing reversal, payment deletion, and audit log are committed atomically.
    Stats refresh runs after the transaction so a stats failure never rolls back the deletion.
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

    try:
        # 2. Reverse Billing Balances (if billing exists)
        billing = db_session.query(PropertyBilling).filter(
            PropertyBilling.property_id == prop_id,
            PropertyBilling.tax_year == tax_year
        ).with_for_update().first()

        if billing:
            billing.amount_paid = max(_d(0), _d(billing.amount_paid) - amt)
            billing.penalty = max(_d(0), _d(billing.penalty) - pen)
            billing.discount = max(_d(0), _d(billing.discount) - disc)

        # 3. Delete Payment (cascade handles ReceiptHistory and PaymentBilling)
        db_session.delete(payment)

        # 4. Stage audit log — same transaction as the deletion and billing reversal
        log_action(user_name, f"Deleted Payment OR {or_no} (Amount: {amt}) and reversed billing.", db_session=db_session)

        # 5. Single atomic commit: billing reversal + deletion + audit
        db_session.commit()

    except Exception:
        db_session.rollback()
        raise

    # 6. Refresh stats outside the transaction — a failure here is non-fatal
    try:
        from backend.services.stats_service import refresh_system_stats
        refresh_system_stats(db_session=db_session)
    except Exception as stats_err:
        from utils import log_error_to_file
        log_error_to_file("Stats refresh failed after payment deletion", stats_err)

    return {"success": True, "message": "Payment deleted successfully."}
