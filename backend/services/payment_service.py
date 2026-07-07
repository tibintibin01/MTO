# -*- coding: utf-8 -*-
import re
from datetime import datetime, timedelta
from decimal import Decimal
from backend.database import SessionLocal
from backend.models import ReceiptHistory
from sqlalchemy import or_, func, cast, literal, inspect
from sqlalchemy.types import Date
from sqlalchemy.orm import Session
from backend.models import Payment, Property, PropertyBilling, PaymentBilling, TaxPolicy
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


def _clean_remarks(value):
    text = str(value or "").strip()
    return text[:500] if text else None


def _payment_remarks_expr(db_session: Session = None):
    """Return Payment.remarks only when the live DB has the column.

    This keeps ledger reads working during a rolling update where a desktop
    client or API process is newer than the database schema.
    """
    try:
        bind = db_session.get_bind() if db_session is not None else None
        if bind is None:
            return literal(None).label("remarks")
        inspector = inspect(bind)
        columns = {col["name"] for col in inspector.get_columns("payments")}
        if "remarks" in columns:
            return Payment.remarks
    except Exception:
        pass
    return literal(None).label("remarks")


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

    date_start = datetime.strptime(date_text, "%Y-%m-%d")
    date_end = date_start + timedelta(days=1)
    row = db_session.query(Payment, Property).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None,
        Property.td_number == td_text,
        Payment.or_number == or_text,
        Payment.date_paid >= date_start,
        Payment.date_paid < date_end,
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
        _payment_remarks_expr(db_session),
        ReceiptHistory.file_path,
        ReceiptHistory.id.label('receipt_id'),
        Property.td_number,
        Property.owner_name,
        Property.id.label('property_id')
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
        Payment.amount,
        _payment_remarks_expr(db_session)
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
        _payment_remarks_expr(db_session),
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
        "remarks": row.remarks,
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



@require_permission("payment_post")
def update_payment_record(payment_id, data, user_name, db_session: Session = None, **kwargs):
    """Update a single payment row and keep PropertyBilling totals in sync."""
    from datetime import datetime
    from backend.services.system_service import log_action
    from backend.services.billing_service import recalculate_billing_balances, sync_payment_billings

    payment = db_session.query(Payment).filter(Payment.id == payment_id).with_for_update().first()
    if not payment:
        raise Exception("Payment record not found.")

    links = db_session.query(PaymentBilling).filter(PaymentBilling.payment_id == payment.id).all()
    if len(links) > 1:
        raise Exception("This payment is allocated to multiple tax years. Please delete and repost it instead of editing in-place.")

    prop = db_session.query(Property).filter(Property.id == payment.property_id).first()
    if not prop:
        raise Exception("Linked property was not found.")

    or_number = str(data.get("or_number") or "").strip()
    tax_year_text = format_tax_years(data.get("tax_year"))
    if not or_number or not tax_year_text:
        raise Exception("OR Number and Tax Year are required.")
    years = [part.strip() for part in tax_year_text.split(",") if part.strip()]
    if len(years) != 1 or not years[0].isdigit():
        raise Exception("Edit Payment supports one tax year at a time. For multi-year corrections, delete and repost the payment.")
    tax_year = int(years[0])

    date_text = normalize_date_input(data.get("date_paid") or data.get("or_date"))
    if not date_text:
        raise Exception("Invalid OR Date. Use YYYY-MM-DD.")
    date_paid = datetime.strptime(date_text, "%Y-%m-%d")

    amount = _d(data.get("amount") if data.get("amount") is not None else data.get("amount_paid"))
    penalty = _d(data.get("penalty"))
    discount = _d(data.get("discount"))
    if amount < 0 or penalty < 0 or discount < 0:
        raise Exception("Amount, penalty, and discount cannot be negative.")

    duplicate = find_duplicate_payment(
        payment.property_id,
        or_number,
        tax_year_text,
        exclude_payment_id=payment.id,
        db_session=db_session,
    )
    if duplicate:
        raise Exception(f"Another payment already uses OR {or_number} for tax year {tax_year_text}.")

    old_or = payment.or_number
    old_amount = _d(payment.amount)
    old_penalty = _d(payment.penalty)
    old_discount = _d(payment.discount)
    old_billing_ids = [link.billing_id for link in links if link.billing_id]
    if not old_billing_ids and str(payment.tax_year or "").strip().isdigit():
        legacy_billing = db_session.query(PropertyBilling).filter(
            PropertyBilling.property_id == payment.property_id,
            PropertyBilling.tax_year == int(str(payment.tax_year).strip()),
        ).with_for_update().first()
        if legacy_billing:
            old_billing_ids.append(legacy_billing.id)

    try:
        for billing_id in dict.fromkeys(old_billing_ids):
            billing = db_session.query(PropertyBilling).filter(PropertyBilling.id == billing_id).with_for_update().first()
            if billing:
                billing.penalty = max(_d(0), _d(billing.penalty) - old_penalty)
                billing.discount = max(_d(0), _d(billing.discount) - old_discount)

        db_session.query(PaymentBilling).filter(PaymentBilling.payment_id == payment.id).delete()
        recalculate_billing_balances(old_billing_ids, db_session=db_session)

        billing = db_session.query(PropertyBilling).filter(
            PropertyBilling.property_id == payment.property_id,
            PropertyBilling.tax_year == tax_year,
        ).with_for_update().first()
        if not billing:
            billing = PropertyBilling(
                property_id=payment.property_id,
                tax_year=tax_year,
                assessed_value=_d(prop.assessed_value),
                penalty=0,
                discount=0,
                amount_paid=0,
            )
            db_session.add(billing)
            db_session.flush()

        billing.penalty = _d(billing.penalty) + penalty
        billing.discount = _d(billing.discount) + discount

        payment.or_number = or_number
        payment.date_paid = date_paid
        payment.tax_year = tax_year_text
        payment.amount = amount
        payment.penalty = penalty
        payment.discount = discount
        payment.posted_by = get_username(user_name)
        payment.remarks = _clean_remarks(data.get("remarks"))

        db_session.flush()
        sync_payment_billings(
            payment.id,
            [{"billing_id": billing.id, "tax_year": tax_year, "applied_amount": amount}],
            db_session=db_session,
        )

        log_action(
            user_name,
            f"Edited Payment OR {old_or} -> {or_number} (Amount: {old_amount} -> {amount}).",
            db_session=db_session,
        )
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    try:
        from backend.services.stats_service import refresh_system_stats
        refresh_system_stats(db_session=db_session)
    except Exception as stats_err:
        from utils import log_error_to_file
        log_error_to_file("Stats refresh failed after payment edit", stats_err)

    return {"success": True, "message": "Payment updated successfully."}


def _extract_single_year(value):
    years = [int(match) for match in re.findall(r"(?:19|20)\d{2}", str(value or ""))]
    unique_years = []
    for year in years:
        if year not in unique_years:
            unique_years.append(year)
    return unique_years[0] if len(unique_years) == 1 else None


def _date_key(value):
    if not value:
        return ""
    if hasattr(value, "date"):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_payment_cleanup_candidates(year=None, limit=500, db_session: Session = None):
    """
    Preview payment rows that can explain reconciliation drift.

    These are review candidates, not automatic deletion targets. Reasons include
    visible year vs billing-link mismatch, impossible OR dates, duplicate-looking
    rows, stale allocation years, and overpaid billing rows.
    """
    if db_session is None:
        return {"year": year, "found": 0, "total_candidates": 0, "summary": {}, "preview": []}

    safe_limit = max(1, min(int(limit or 500), 1000))
    review_year = int(year or today().year)
    candidates = {}

    def add_candidate(payment, prop, reason, link=None, billing=None, credit_amount=0, severity=50):
        if not payment or not prop:
            return
        key = int(payment.id)
        item = candidates.setdefault(key, {
            "payment_id": int(payment.id),
            "or_number": payment.or_number,
            "tax_year": payment.tax_year,
            "amount": float(_d(payment.amount)),
            "discount": float(_d(payment.discount)),
            "penalty": float(_d(payment.penalty)),
            "date_paid": payment.date_paid.strftime("%Y-%m-%d") if payment.date_paid else None,
            "td_number": prop.td_number,
            "owner_name": prop.owner_name,
            "barangay": prop.barangay,
            "link_tax_year": int(link.tax_year) if link and link.tax_year is not None else None,
            "billing_tax_year": int(billing.tax_year) if billing and billing.tax_year is not None else None,
            "linked_amount": float(_d(link.amount_paid)) if link else 0.0,
            "credit_amount": float(abs(credit_amount or 0)),
            "cleanup_reason": reason,
            "_severity": severity,
        })
        reasons = {part.strip() for part in str(item.get("cleanup_reason") or "").split(";") if part.strip()}
        reasons.add(reason)
        item["cleanup_reason"] = "; ".join(sorted(reasons))
        item["credit_amount"] = max(float(item.get("credit_amount") or 0), float(abs(credit_amount or 0)))
        item["_severity"] = max(int(item.get("_severity", 0)), int(severity))

    rows = (
        db_session.query(Payment, Property, PaymentBilling, PropertyBilling)
        .join(Property, Property.id == Payment.property_id)
        .outerjoin(PaymentBilling, PaymentBilling.payment_id == Payment.id)
        .outerjoin(PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id)
        .filter(Property.deleted_at == None)
        .order_by(Payment.id.desc())
        .limit(25000)
        .all()
    )

    duplicate_seen = {}
    for payment, prop, link, billing in rows:
        visible_year = _extract_single_year(payment.tax_year)
        billing_year = int(billing.tax_year) if billing and billing.tax_year is not None else None
        link_year = int(link.tax_year) if link and link.tax_year is not None else None

        if visible_year and billing_year and visible_year != billing_year:
            add_candidate(
                payment, prop,
                f"Visible year {visible_year} is linked to billing year {billing_year}",
                link=link, billing=billing, severity=95,
            )
        if link_year and billing_year and link_year != billing_year:
            add_candidate(
                payment, prop,
                f"Allocation year {link_year} does not match billing year {billing_year}",
                link=link, billing=billing, severity=90,
            )
        if payment.date_paid and (payment.date_paid.year < 1900 or payment.date_paid.year > review_year + 3):
            add_candidate(
                payment, prop,
                f"Unusual OR date {payment.date_paid.strftime('%Y-%m-%d')}",
                link=link, billing=billing, severity=85,
            )

        duplicate_key = (
            int(payment.property_id or 0),
            str(payment.or_number or "").strip(),
            _date_key(payment.date_paid),
            str(payment.tax_year or "").strip(),
            str(_d(payment.amount).quantize(Decimal("0.01"))),
        )
        duplicate_seen.setdefault(duplicate_key, []).append((payment, prop, link, billing))

    for group in duplicate_seen.values():
        if len(group) <= 1:
            continue
        for payment, prop, link, billing in group:
            add_candidate(
                payment, prop,
                f"Possible duplicate receipt row ({len(group)} same property/OR/date/year/amount)",
                link=link, billing=billing, severity=75,
            )

    rate_expr = func.coalesce(TaxPolicy.basic_rate, 0.01) + func.coalesce(TaxPolicy.sef_rate, 0.01)
    credit_expr = PropertyBilling.amount_paid - (
        (PropertyBilling.assessed_value * rate_expr) + PropertyBilling.penalty - PropertyBilling.discount
    )
    overpaid_rows = (
        db_session.query(PropertyBilling.id, credit_expr.label("credit_amount"))
        .join(Property, Property.id == PropertyBilling.property_id)
        .outerjoin(TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year)
        .filter(
            Property.deleted_at == None,
            PropertyBilling.tax_year <= review_year,
            credit_expr > 0.01,
        )
        .order_by(credit_expr.desc())
        .limit(1000)
        .all()
    )
    overpaid_by_billing = {int(row[0]): float(row[1] or 0) for row in overpaid_rows if row[0]}
    if overpaid_by_billing:
        linked_overpaid = (
            db_session.query(Payment, Property, PaymentBilling, PropertyBilling)
            .join(Property, Property.id == Payment.property_id)
            .join(PaymentBilling, PaymentBilling.payment_id == Payment.id)
            .join(PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id)
            .filter(PaymentBilling.billing_id.in_(list(overpaid_by_billing.keys())))
            .order_by(PropertyBilling.tax_year.desc(), Payment.amount.desc())
            .limit(2500)
            .all()
        )
        for payment, prop, link, billing in linked_overpaid:
            add_candidate(
                payment, prop,
                f"Billing year {int(billing.tax_year)} has credit balance",
                link=link,
                billing=billing,
                credit_amount=overpaid_by_billing.get(int(billing.id), 0),
                severity=60,
            )

    preview = sorted(
        candidates.values(),
        key=lambda item: (-int(item.get("_severity", 0)), -float(item.get("credit_amount") or 0), item.get("td_number") or ""),
    )[:safe_limit]
    for item in preview:
        item.pop("_severity", None)

    summary = {
        "visible_link_mismatch": sum(1 for item in candidates.values() if "Visible year" in item.get("cleanup_reason", "")),
        "allocation_year_mismatch": sum(1 for item in candidates.values() if "Allocation year" in item.get("cleanup_reason", "")),
        "unusual_dates": sum(1 for item in candidates.values() if "Unusual OR date" in item.get("cleanup_reason", "")),
        "possible_duplicates": sum(1 for item in candidates.values() if "Possible duplicate" in item.get("cleanup_reason", "")),
        "credit_balance_rows": len(overpaid_by_billing),
    }
    return {
        "year": review_year,
        "found": len(preview),
        "total_candidates": len(candidates),
        "limit": safe_limit,
        "summary": summary,
        "preview": preview,
    }


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
    amt = _d(payment.amount)
    pen = _d(payment.penalty)
    disc = _d(payment.discount)
    or_no = payment.or_number
    links = db_session.query(PaymentBilling).filter(PaymentBilling.payment_id == payment.id).all()
    billing_ids = [link.billing_id for link in links if link.billing_id]

    try:
        # 2. Reverse summary adjustments on the linked billing row.
        # Amount paid is recalculated from PaymentBilling links after deletion,
        # so rows like "3RD QTR 2024" do not depend on parsing payment.tax_year.
        if not billing_ids:
            visible_year = _extract_single_year(payment.tax_year)
            if visible_year:
                billing = db_session.query(PropertyBilling).filter(
                    PropertyBilling.property_id == prop_id,
                    PropertyBilling.tax_year == visible_year
                ).with_for_update().first()
                if billing:
                    billing_ids.append(billing.id)

        unique_billing_ids = list(dict.fromkeys(billing_ids))
        if len(unique_billing_ids) == 1:
            billing = db_session.query(PropertyBilling).filter(PropertyBilling.id == unique_billing_ids[0]).with_for_update().first()
            if billing:
                billing.penalty = max(_d(0), _d(billing.penalty) - pen)
                billing.discount = max(_d(0), _d(billing.discount) - disc)

        # 3. Delete Payment (cascade handles ReceiptHistory and PaymentBilling)
        db_session.delete(payment)
        db_session.flush()
        from backend.services.billing_service import recalculate_billing_balances
        recalculate_billing_balances(unique_billing_ids, db_session=db_session)

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
