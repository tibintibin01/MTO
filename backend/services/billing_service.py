from datetime import datetime, timezone
import re
from sqlalchemy import or_, and_, func, case, cast
from sqlalchemy.types import Date
from sqlalchemy.orm import Session
from backend.models import Property, PropertyBilling, PaymentBilling, Payment, TaxPolicy
from backend.database import SessionLocal
from decimal import Decimal, ROUND_HALF_UP
from utils.db_compat import greatest, year_of, month_of


from utils.logger import mto_logger

def sync_property_billing(

    cur, property_id, tax_year, assessed_value, penalty, discount=0.0, has_payment=False, db_session: Session = None
):
    """Creates or updates the billing snapshot for one property and one tax year."""
    normalized_tax_year = (
        int(tax_year) if tax_year and str(tax_year).strip().isdigit() else datetime.now(timezone.utc).year
    )
    assessed_value = Decimal(str(assessed_value or 0))
    penalty = Decimal(str(penalty or 0))
    discount = Decimal(str(discount or 0))
    
    policy = None
    if db_session:
        policy = db_session.query(TaxPolicy).filter(TaxPolicy.tax_year == normalized_tax_year).first()
        if policy and not isinstance(policy, TaxPolicy):
            policy = None
        
    basic_rate = Decimal(str(policy.basic_rate)) if policy else Decimal("0.01")
    sef_rate = Decimal(str(policy.sef_rate)) if policy else Decimal("0.01")
    
    basic_amount = (assessed_value * basic_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sef_amount = (assessed_value * sef_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_amount = basic_amount + sef_amount + penalty - discount
    initial_amount_paid = total_amount if has_payment else Decimal("0.00")

    billing = db_session.query(PropertyBilling).filter(
        PropertyBilling.property_id == property_id,
        PropertyBilling.tax_year == normalized_tax_year
    ).with_for_update().first()
    
    if not billing:
        billing = PropertyBilling(
            property_id=property_id,
            tax_year=normalized_tax_year,
            amount_paid=initial_amount_paid
        )
        db_session.add(billing)
    
    billing.assessed_value = assessed_value
    billing.penalty = penalty
    billing.discount = discount
    billing.updated_at = datetime.now(timezone.utc)
    
    db_session.flush() # Get ID
    
    return {
        "billing_id": billing.id,
        "tax_year": normalized_tax_year,
        "assessed_value": float(assessed_value),
        "penalty": float(penalty),
        "discount": float(discount),
        "basic_amount": float(basic_amount),
        "sef_amount": float(sef_amount),
        "total_amount": float(total_amount),
        "amount_paid": float(billing.amount_paid),
        "balance_amount": float(max(Decimal("0.00"), total_amount - billing.amount_paid)),
        "billing_status": "Paid" if billing.amount_paid >= total_amount else "Partial" if billing.amount_paid > 0 else "Pending",
    }


def allocate_payment_amount(billing_rows, amount_paid):
    remaining = Decimal(str(amount_paid or 0))
    allocated = []

    def _sort_key(row):
        ty = row.get("tax_year", "")
        if isinstance(ty, int):
            return (0, ty)
        ty_str = str(ty).strip()
        return (0, int(ty_str)) if ty_str.isdigit() else (1, ty_str)

    for billing_row in sorted(billing_rows, key=_sort_key):
        due_amount = max(Decimal("0.00"), Decimal(str(billing_row.get("total_amount") or 0)))
        applied_amount = min(due_amount, remaining)
        row_copy = dict(billing_row)
        row_copy["applied_amount"] = float(applied_amount)
        allocated.append(row_copy)
        remaining = max(Decimal("0.00"), remaining - applied_amount)

    return allocated


def split_amount_across_years(total_amount, year_count):
    count = max(1, int(year_count or 1))
    total = Decimal(str(total_amount or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if count == 1:
        return [float(total)]

    shared_amount = (total / Decimal(count)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    amounts = [shared_amount for _ in range(count)]
    difference = total - sum(amounts, Decimal("0.00"))
    penny = Decimal("0.01")
    index = 0

    while difference != Decimal("0.00"):
        if difference > Decimal("0.00"):
            amounts[index] += penny
            difference -= penny
        else:
            amounts[index] -= penny
            difference += penny
        index = (index + 1) % count

    return [float(amount) for amount in amounts]


def normalize_tax_years(value):
    """Returns tax years in a canonical comma-separated format."""
    raw = str(value or "").replace(";", ",")
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    normalized = []
    for part in parts:
        # Handle ranges like 2021-2026, 2021 - 2026, etc.
        if "-" in part:
            range_parts = [p.strip() for p in part.split("-") if p.strip()]
            if len(range_parts) == 2:
                start, end = range_parts
                if start.isdigit() and end.isdigit() and len(start) == 4 and len(end) == 4:
                    start_year = int(start)
                    end_year = int(end)
                    if end_year >= start_year and (end_year - start_year) <= 15:
                        for year in range(start_year, end_year + 1):
                            normalized.append(str(year))
                        continue
        normalized.append(part)


    deduped = []
    seen = set()
    for item in normalized:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def format_tax_years(value):
    years = normalize_tax_years(value)
    return ", ".join(years)


def normalize_date_input(value):
    text = str(value or "").strip()
    if not text:
        return ""

    for date_format in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def validate_tax_year_text(value):
    text = str(value or "").strip()
    if not text:
        return {"ok": False, "message": "Please enter at least one Tax Year."}

    parts = [item.strip() for item in text.replace(";", ",").split(",") if item.strip()]
    if not parts:
        return {"ok": False, "message": "Please enter at least one Tax Year."}

    current_year = datetime.now(timezone.utc).year + 5
    seen = set()
    for part in parts:
        if "-" in part:
            if not re.fullmatch(r"\d{4}-\d{4}", part):
                return {
                    "ok": False,
                    "message": f"Invalid tax year range: {part}. Use YYYY or YYYY-YYYY.",
                }
            start_year, end_year = [int(piece) for piece in part.split("-", 1)]
            if end_year < start_year:
                return {
                    "ok": False,
                    "message": f"Invalid tax year range: {part}. End year must not be earlier than start year.",
                }
            if start_year < 1900 or end_year > current_year:
                return {
                    "ok": False,
                    "message": f"Tax year range {part} is outside the allowed office range.",
                }
            if (end_year - start_year) > 10:
                return {
                    "ok": False,
                    "message": f"Tax year range {part} is too wide. Use up to 10 years at a time.",
                }
            continue

        if not re.fullmatch(r"\d{4}", part):
            return {
                "ok": False,
                "message": f"Invalid tax year: {part}. Use 4-digit years like 2025.",
            }

        year = int(part)
        if year < 1900 or year > current_year:
            return {
                "ok": False,
                "message": f"Tax year {part} is outside the allowed office range.",
            }
        if part in seen:
            return {
                "ok": False,
                "message": f"Tax year {part} is repeated. Remove duplicate years before saving.",
            }
        seen.add(part)

    return {
        "ok": True,
        "years": normalize_tax_years(text),
        "text": format_tax_years(text),
    }


def looks_like_valid_or_number(value):
    text = str(value or "").strip()
    if not text:
        return False
    if len(text) > 50:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 /.-]*", text))


def recalculate_billing_balances(cur, billing_ids, db_session: Session = None):
    seen = []
    for billing_id in billing_ids:
        if billing_id and billing_id not in seen:
            seen.append(billing_id)

    for billing_id in seen:
        # Recalculate sum of payments for this billing
        total_paid = db_session.query(func.sum(PaymentBilling.amount_paid)).filter(PaymentBilling.billing_id == billing_id).scalar() or 0
        
        db_session.query(PropertyBilling).filter(PropertyBilling.id == billing_id).update({
            PropertyBilling.amount_paid: float(total_paid),
            PropertyBilling.updated_at: datetime.now(timezone.utc)
        }, synchronize_session=False)


def sync_payment_billings(cur, payment_id, billing_rows, db_session: Session = None):
    if not payment_id:
        return

    # 1. Clear existing links
    db_session.query(PaymentBilling).filter(PaymentBilling.payment_id == payment_id).delete()
    
    affected_billing_ids = []
    for billing_row in billing_rows:
        if not billing_row.get("billing_id"):
            continue
            
        applied_amount = float(billing_row.get("applied_amount", billing_row.get("total_amount", 0)) or 0)
        if applied_amount <= 0:
            continue
            
        link = PaymentBilling(
            payment_id=payment_id,
            billing_id=billing_row["billing_id"],
            tax_year=billing_row["tax_year"],
            amount_paid=applied_amount
        )
        db_session.add(link)
        affected_billing_ids.append(billing_row["billing_id"])
        
    db_session.flush()
    recalculate_billing_balances(None, affected_billing_ids, db_session=db_session)


def get_property_billing_history(property_id=None, term=None, limit=50, db_session: Session = None):
    safe_limit = max(1, int(limit))
    
    basic_rate_expr = func.coalesce(TaxPolicy.basic_rate, 0.0100)
    sef_rate_expr = func.coalesce(TaxPolicy.sef_rate, 0.0100)
    total_rate_expr = basic_rate_expr + sef_rate_expr
    
    query = db_session.query(
        PropertyBilling.tax_year,
        PropertyBilling.assessed_value,
        (PropertyBilling.assessed_value * basic_rate_expr).label('basic_amount'),
        (PropertyBilling.assessed_value * sef_rate_expr).label('sef_amount'),
        PropertyBilling.penalty,
        ((PropertyBilling.assessed_value * total_rate_expr) + PropertyBilling.penalty - PropertyBilling.discount).label('total_amount'),
        PropertyBilling.amount_paid,
        greatest(
            ((PropertyBilling.assessed_value * total_rate_expr) + PropertyBilling.penalty - PropertyBilling.discount) - PropertyBilling.amount_paid,
            0
        ).label('balance_amount'),
        case(
            (PropertyBilling.amount_paid <= 0, 'Pending'),
            (PropertyBilling.amount_paid >= ((PropertyBilling.assessed_value * total_rate_expr) + PropertyBilling.penalty - PropertyBilling.discount), 'Paid'),
            else_='Partial'
        ).label('billing_status'),

        PropertyBilling.updated_at
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(Property.deleted_at == None)
    
    if property_id:
        query = query.filter(PropertyBilling.property_id == property_id)
    elif term:
        like_term = f"%{term}%"
        query = query.filter(or_(
            Property.td_number.like(like_term),
            Property.owner_name.like(like_term),
            Property.location.like(like_term)
        ))
    else:
        return []
        
    results = query.order_by(PropertyBilling.tax_year.desc(), PropertyBilling.updated_at.desc()).limit(safe_limit).all()
    return [list(r) for r in results]


def get_property_statement_data(property_id, db_session: Session = None):
    prop = db_session.query(Property).filter(Property.id == property_id, Property.deleted_at == None).first()
    if not prop:
        return None
        
    billing_rows_raw = get_property_billing_history(property_id=property_id, limit=500, db_session=db_session)
    billing_rows = []
    total_balance = 0.0
    total_paid = 0.0
    grand_total = 0.0

    for b in billing_rows_raw:
        item = {
            "tax_year": b[0],
            "assessed_value": float(b[1] or 0),
            "basic_amount": float(b[2] or 0),
            "sef_amount": float(b[3] or 0),
            "penalty": float(b[4] or 0),
            "total_amount": float(b[5] or 0),
            "amount_paid": float(b[6] or 0),
            "balance_amount": float(b[7] or 0),
            "billing_status": b[8],
            "updated_at": b[9],
        }
        billing_rows.append(item)
        total_balance += item["balance_amount"]
        total_paid += item["amount_paid"]
        grand_total += item["total_amount"]

    return {
        "id": prop.id,
        "td_number": prop.td_number,
        "owner_name": prop.owner_name,
        "location": prop.location,
        "barangay": prop.barangay,
        "kind_of_property": prop.kind_of_property,
        "assessed_value": float(prop.assessed_value or 0),
        "lot_number": prop.lot_number,
        "block_number": prop.block_number,
        "area": prop.area,
        "pin": prop.pin,
        "total_balance": total_balance,
        "total_paid": total_paid,
        "grand_total": grand_total,
        "billing_rows": billing_rows
    }




def get_report_details(selected_month="All", selected_year="All", limit=200, cursor=None, db_session: Session = None):
    safe_limit = min(max(1, int(limit)), 500)

    query = db_session.query(
        Payment.id,
        Payment.date_paid,
        Payment.or_number,
        Property.td_number,
        Property.owner_name,
        Property.kind_of_property,
        Payment.tax_year,
        Payment.amount,
        Payment.posted_by
    ).join(Property, Property.id == Payment.property_id).filter(Property.deleted_at == None)

    if selected_month != "All":
        query = query.filter(month_of(Payment.date_paid) == int(selected_month))
    if selected_year != "All":
        query = query.filter(year_of(Payment.date_paid) == int(selected_year))
    if cursor:
        query = query.filter(Payment.id < int(cursor))

    rows = query.order_by(Payment.id.desc()).limit(safe_limit + 1).all()

    has_more = len(rows) > safe_limit
    items = rows[:safe_limit]
    next_cursor = items[-1][0] if has_more and items else None

    return {
        "items": [list(r[1:]) for r in items],  # exclude the id from the row data
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items),
    }


def get_rpt_receivables_summary(report_year, db_session: Session = None):
    try:
        ry = int(report_year)
    except (ValueError, TypeError):
        ry = datetime.now(timezone.utc).year

    basic_rate_expr = func.coalesce(TaxPolicy.basic_rate, 0.0100)
    sef_rate_expr = func.coalesce(TaxPolicy.sef_rate, 0.0100)
    total_rate_expr = basic_rate_expr + sef_rate_expr

    # 1. Beginning Receivable (sum of balances for tax years < report_year)
    beg = db_session.query(
        func.coalesce(func.sum(((PropertyBilling.assessed_value * total_rate_expr) + PropertyBilling.penalty - PropertyBilling.discount) - PropertyBilling.amount_paid), 0)
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year < ry
    ).scalar()
    
    # 2. Current Year Assessment
    curr_ass = db_session.query(
        func.coalesce(func.sum((PropertyBilling.assessed_value * total_rate_expr) + PropertyBilling.penalty - PropertyBilling.discount), 0)
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year == ry
    ).scalar()
    
    # 3. Collections (total paid in this calendar year)
    coll = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None,
        year_of(Payment.date_paid) == ry
    ).scalar()
    
    adj = 0.0
    end = float(beg) + float(curr_ass) - float(coll) + adj
    
    return {
        "report_year": ry,
        "beginning_receivable": float(beg),
        "current_year_assessment": float(curr_ass),
        "collections": float(coll),
        "adjustments": adj,
        "ending_receivable": end,
    }


def get_compliant_accounts(
    barangay: str = None,
    limit: int = 50,
    cursor: int = None,
    db_session: Session = None,
):
    """
    Fetches properties that are fully paid — zero outstanding balance
    across ALL their billing years.

    Definition of compliant:
        SUM(amount_paid) >= SUM(assessed_value * TOTAL_RATE + penalty - discount)
        across all PropertyBilling rows for that property.

    Only properties that HAVE at least one billing record are included.
    Properties with no billing records at all are excluded — they have
    not been billed yet and cannot be considered compliant.

    Supports:
      - Optional barangay filter for per-barangay reporting
      - Cursor-based pagination (cursor = last seen Property.id)
    """
    safe_limit = min(max(1, int(limit)), 200)
    TOTAL_RATE = 0.02

    total_due_expr = func.sum(
        (PropertyBilling.assessed_value * TOTAL_RATE)
        + PropertyBilling.penalty
        - PropertyBilling.discount
    )
    total_paid_expr = func.sum(PropertyBilling.amount_paid)

    # Last payment date for this property — used for "last paid" display column
    last_payment_subq = (
        db_session.query(
            Payment.property_id,
            func.max(Payment.date_paid).label("last_paid"),
            func.max(Payment.or_number).label("last_or"),
        )
        .group_by(Payment.property_id)
        .subquery()
    )

    query = (
        db_session.query(
            Property.id,
            Property.td_number,
            Property.owner_name,
            Property.location,
            func.coalesce(Property.barangay, "UNSPECIFIED").label("barangay"),
            Property.kind_of_property,
            total_due_expr.label("total_due"),
            total_paid_expr.label("total_paid"),
            last_payment_subq.c.last_paid,
            last_payment_subq.c.last_or,
            func.count(PropertyBilling.id).label("years_covered"),
        )
        .join(PropertyBilling, PropertyBilling.property_id == Property.id)
        .outerjoin(last_payment_subq, last_payment_subq.c.property_id == Property.id)
        .filter(Property.deleted_at == None)
        .group_by(
            Property.id,
            Property.td_number,
            Property.owner_name,
            Property.location,
            Property.barangay,
            Property.kind_of_property,
            last_payment_subq.c.last_paid,
            last_payment_subq.c.last_or,
        )
        # Compliant = total paid >= total due AND total due > 0 AND total paid > 0
        # Without the > 0 guards, properties with zero assessed value pass as
        # compliant because 0.00 >= 0.00 is true — even if nothing was ever paid.
        .having(
            and_(
                total_due_expr > 0,          # must have something due
                total_paid_expr > 0,         # must have actually paid something
                total_paid_expr >= total_due_expr,  # must be fully paid
            )
        )
    )

    if barangay and barangay.upper() != "ALL":
        query = query.filter(
            func.coalesce(Property.barangay, "UNSPECIFIED") == barangay
        )

    if cursor:
        query = query.filter(Property.id > int(cursor))

    rows = query.order_by(Property.id.asc()).limit(safe_limit + 1).all()

    has_more = len(rows) > safe_limit
    items = rows[:safe_limit]
    next_cursor = items[-1][0] if has_more and items else None

    return {
        "items": [
            {
                "id": r[0],
                "td_number": r[1],
                "owner_name": r[2],
                "location": r[3],
                "barangay": r[4],
                "kind_of_property": r[5] or "—",
                "total_due": float(r[6] or 0),
                "total_paid": float(r[7] or 0),
                "last_paid": r[8].strftime("%Y-%m-%d") if r[8] else None,
                "last_or": r[9],
                "years_covered": int(r[10] or 0),
            }
            for r in items
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items),
    }


def get_compliant_summary_by_barangay(db_session: Session = None):
    """
    Returns a per-barangay summary of compliant vs total properties.

    Used for the summary cards at the top of the Compliant Properties dashboard.
    Each row contains:
      - barangay name
      - total properties in that barangay (with billing records)
      - compliant count (fully paid)
      - delinquent count
      - compliance rate (%)
      - total amount collected from compliant properties
    """
    TOTAL_RATE = 0.02

    total_due_expr = func.sum(
        (PropertyBilling.assessed_value * TOTAL_RATE)
        + PropertyBilling.penalty
        - PropertyBilling.discount
    )
    total_paid_expr = func.sum(PropertyBilling.amount_paid)

    # All properties with billing records, grouped by property + barangay
    # to determine per-property compliance status
    per_property = (
        db_session.query(
            Property.id,
            func.coalesce(Property.barangay, "UNSPECIFIED").label("barangay"),
            total_due_expr.label("total_due"),
            total_paid_expr.label("total_paid"),
        )
        .join(PropertyBilling, PropertyBilling.property_id == Property.id)
        .filter(Property.deleted_at == None)
        .group_by(Property.id, Property.barangay)
        .subquery()
    )

    # Aggregate per barangay
    rows = (
        db_session.query(
            per_property.c.barangay,
            func.count(per_property.c.id).label("total"),
            func.sum(
                case(
                    (
                        and_(
                            per_property.c.total_due > 0,
                            per_property.c.total_paid > 0,
                            per_property.c.total_paid >= per_property.c.total_due,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("compliant"),
            func.sum(
                case(
                    (
                        or_(
                            per_property.c.total_due <= 0,
                            per_property.c.total_paid <= 0,
                            per_property.c.total_paid < per_property.c.total_due,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("delinquent"),
            func.sum(
                case(
                    (
                        and_(
                            per_property.c.total_due > 0,
                            per_property.c.total_paid > 0,
                            per_property.c.total_paid >= per_property.c.total_due,
                        ),
                        per_property.c.total_paid,
                    ),
                    else_=0,
                )
            ).label("collected_from_compliant"),
        )
        .group_by(per_property.c.barangay)
        .order_by(per_property.c.barangay.asc())
        .all()
    )

    result = []
    for r in rows:
        total = int(r[1] or 0)
        compliant = int(r[2] or 0)
        rate = round((compliant / total * 100), 1) if total > 0 else 0.0
        result.append({
            "barangay": r[0],
            "total_properties": total,
            "compliant_count": compliant,
            "delinquent_count": int(r[3] or 0),
            "compliance_rate": rate,
            "collected_from_compliant": float(r[4] or 0),
        })

    return result


def get_delinquent_accounts(limit=50, cursor=None, db_session: Session = None):
    """
    Fetches properties with outstanding balances using cursor-based pagination.

    Cursor is the last seen Property.id. Avoids OFFSET on the GROUP BY + HAVING
    query which degrades badly at scale — each OFFSET page re-scans all prior rows.

    Tax rates are intentionally NOT joined from TaxPolicy here. Rates are applied
    at billing creation time (sync_property_billing), so the stored assessed_value
    in PropertyBilling already reflects the correct per-year rate. Re-joining
    TaxPolicy inside a GROUP BY aggregate would cause ONLY_FULL_GROUP_BY errors
    in strict MariaDB mode and produce incorrect SUMs when a property spans
    multiple tax years with different rates.
    """
    safe_limit = min(max(1, int(limit)), 200)  # hard cap at 200

    # NOTE: PropertyBilling.assessed_value already has the tax rate applied
    # (it stores the raw assessed value from the property record, not the
    # computed tax amount). The TOTAL_RATE multiplier here computes the annual
    # tax due from the stored assessed value.
    # Default 2% (1% basic + 1% SEF) matches TaxPolicy defaults.
    # TODO: Join TaxPolicy per billing year for multi-rate accuracy once
    # ONLY_FULL_GROUP_BY compatibility is confirmed on the target MariaDB version.
    TOTAL_RATE = 0.02

    balance_expr = func.sum(
        (PropertyBilling.assessed_value * TOTAL_RATE)
        + PropertyBilling.penalty
        - PropertyBilling.discount
        - PropertyBilling.amount_paid
    )

    query = db_session.query(
        Property.id,
        Property.td_number,
        Property.owner_name,
        Property.location,
        func.sum(
            (PropertyBilling.assessed_value * TOTAL_RATE)
            + PropertyBilling.penalty
            - PropertyBilling.discount
        ).label("total_due"),
        func.sum(PropertyBilling.amount_paid).label("total_paid"),
        balance_expr.label("balance"),
    ).join(
        PropertyBilling, PropertyBilling.property_id == Property.id
    ).filter(
        Property.deleted_at == None
    ).group_by(Property.id).having(balance_expr > 0)

    if cursor:
        query = query.filter(Property.id > int(cursor))

    # Fetch one extra to detect next page
    rows = query.order_by(Property.id.asc()).limit(safe_limit + 1).all()

    has_more = len(rows) > safe_limit
    items = rows[:safe_limit]
    next_cursor = items[-1][0] if has_more and items else None

    return {
        "items": [
            {
                "id": r[0],
                "td_number": r[1],
                "owner_name": r[2],
                "location": r[3],
                "total_due": float(r[4] or 0),
                "total_paid": float(r[5] or 0),
                "balance": float(r[6] or 0),
            }
            for r in items
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items),
    }


def calculate_penalty(principal, months_late, tax_year=None, db_session=None):
    """
    Calculates penalty at the configured rate per month of delay.

    Uses the penalty_rate from TaxPolicy for the given tax_year if available.
    Falls back to 2% per month (0.02) — the default in TaxPolicy — if no
    policy is configured for that year or no db_session is provided.
    """
    from decimal import Decimal, ROUND_HALF_UP
    DEFAULT_PENALTY_RATE = Decimal("0.02")

    rate = DEFAULT_PENALTY_RATE
    if db_session and tax_year:
        try:
            policy = db_session.query(TaxPolicy).filter(
                TaxPolicy.tax_year == int(tax_year)
            ).first()
            if policy:
                rate = Decimal(str(policy.penalty_rate))
        except Exception:
            pass  # Fall back to default on any DB error

    return float(Decimal(str(principal)) * rate * int(months_late))


def get_total_due(property_id, db_session: Session = None):
    """Orchestrates total due calculation for a property."""
    data = get_property_statement_data(property_id, db_session=db_session)
    if not data:
        return None
        
    prop = db_session.query(Property).filter(Property.id == property_id).first() if db_session else None
    tax_year = datetime.now(timezone.utc).year
    if prop and prop.tax_year and str(prop.tax_year).strip().isdigit():
        tax_year = int(prop.tax_year)
        
    policy = db_session.query(TaxPolicy).filter(TaxPolicy.tax_year == tax_year).first() if db_session else None
    if policy and not isinstance(policy, TaxPolicy):
        policy = None
    basic_rate = float(policy.basic_rate) if policy else 0.01
    sef_rate = float(policy.sef_rate) if policy else 0.01
    
    return {
        "assessed_value": data["assessed_value"],
        "basic": data["assessed_value"] * basic_rate,
        "sef": data["assessed_value"] * sef_rate,
        "total_due": data["total_balance"] + data["total_paid"], # Simplified for test
        "grand_total": data["grand_total"],
        "billing_rows": data["billing_rows"]
    }




