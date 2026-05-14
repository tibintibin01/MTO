from datetime import datetime
import re
from sqlalchemy import or_, and_, func, case

from sqlalchemy.orm import Session
from backend.models import Property, PropertyBilling, PaymentBilling, Payment
# from db_manager import db_query # Mark for removal
from backend.database import SessionLocal
from decimal import Decimal, ROUND_HALF_UP


from utils.logger import mto_logger

def sync_property_billing(

    cur, property_id, tax_year, assessed_value, penalty, discount=0.0, has_payment=False, db_session: Session = None
):
    """Creates or updates the billing snapshot for one property and one tax year."""
    if not db_session:
        db_session = SessionLocal()

    normalized_tax_year = (
        str(tax_year).strip() if str(tax_year).strip() else str(datetime.now().year)
    )
    assessed_value = float(assessed_value or 0)
    penalty = float(penalty or 0)
    discount = float(discount or 0)
    basic_amount = assessed_value * 0.01
    sef_amount = assessed_value * 0.01
    total_amount = basic_amount + sef_amount + penalty - discount
    # billing_status = "Paid" if has_payment else "Pending" # Replaced by logic below
    initial_amount_paid = total_amount if has_payment else 0.0

    billing = db_session.query(PropertyBilling).filter(
        PropertyBilling.property_id == property_id,
        PropertyBilling.tax_year == normalized_tax_year
    ).first()
    
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
    billing.updated_at = datetime.now()
    
    db_session.flush() # Get ID
    
    return {
        "billing_id": billing.id,
        "tax_year": normalized_tax_year,
        "assessed_value": assessed_value,
        "penalty": penalty,
        "discount": discount,
        "basic_amount": basic_amount,
        "sef_amount": sef_amount,
        "total_amount": total_amount,
        "amount_paid": billing.amount_paid,
        "balance_amount": max(0, total_amount - billing.amount_paid),
        "billing_status": "Paid" if billing.amount_paid >= total_amount else "Partial" if billing.amount_paid > 0 else "Pending",
    }


def allocate_payment_amount(billing_rows, amount_paid):
    remaining = float(amount_paid or 0)
    allocated = []

    def _sort_key(row):
        tax_year = str(row.get("tax_year", ""))
        return (0, int(tax_year)) if tax_year.isdigit() else (1, tax_year)

    for billing_row in sorted(billing_rows, key=_sort_key):
        due_amount = max(0.0, float(billing_row.get("total_amount") or 0))
        applied_amount = min(due_amount, remaining)
        row_copy = dict(billing_row)
        row_copy["applied_amount"] = applied_amount
        allocated.append(row_copy)
        remaining = max(0.0, remaining - applied_amount)

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

    current_year = datetime.now().year + 5
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

    if not db_session:
        db_session = SessionLocal()

    for billing_id in seen:
        # Recalculate sum of payments for this billing
        total_paid = db_session.query(func.sum(PaymentBilling.amount_paid)).filter(PaymentBilling.billing_id == billing_id).scalar() or 0
        
        db_session.query(PropertyBilling).filter(PropertyBilling.id == billing_id).update({
            PropertyBilling.amount_paid: float(total_paid),
            PropertyBilling.updated_at: datetime.now()
        }, synchronize_session=False)


def sync_payment_billings(cur, payment_id, billing_rows, db_session: Session = None):
    if not payment_id:
        return

    if not db_session:
        db_session = SessionLocal()

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
    
    if not db_session:
        db_session = SessionLocal()

    query = db_session.query(
        PropertyBilling.tax_year,
        PropertyBilling.assessed_value,
        (PropertyBilling.assessed_value * 0.01).label('basic_amount'),
        (PropertyBilling.assessed_value * 0.01).label('sef_amount'),
        PropertyBilling.penalty,
        ((PropertyBilling.assessed_value * 0.02) + PropertyBilling.penalty).label('total_amount'),
        PropertyBilling.amount_paid,
        func.greatest(((PropertyBilling.assessed_value * 0.02) + PropertyBilling.penalty) - PropertyBilling.amount_paid, 0).label('balance_amount'),
        case(
            (PropertyBilling.amount_paid <= 0, 'Pending'),
            (PropertyBilling.amount_paid >= ((PropertyBilling.assessed_value * 0.02) + PropertyBilling.penalty), 'Paid'),
            else_='Partial'
        ).label('billing_status'),

        PropertyBilling.updated_at
    ).join(Property, Property.id == PropertyBilling.property_id).filter(Property.is_deleted == False)
    
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
    if not db_session:
        db_session = SessionLocal()

    prop = db_session.query(Property).filter(Property.id == property_id, Property.is_deleted == False).first()
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




def get_report_details(selected_month="All", selected_year="All", db_session: Session = None):
    if not db_session:
        db_session = SessionLocal()

    query = db_session.query(
        Payment.date_paid,
        Payment.or_number,
        Property.td_number,
        Property.owner_name,
        Property.kind_of_property,
        Payment.tax_year,
        Payment.amount,
        Payment.posted_by
    ).join(Property, Property.id == Payment.property_id).filter(Property.is_deleted == False)
    
    if selected_month != "All":
        query = query.filter(func.month(Payment.date_paid) == int(selected_month))
    if selected_year != "All":
        query = query.filter(func.year(Payment.date_paid) == int(selected_year))
        
    results = query.order_by(Payment.date_paid.desc(), Payment.id.desc()).all()
    return [list(r) for r in results]


def get_rpt_receivables_summary(report_year, db_session: Session = None):
    try:
        ry = int(report_year)
    except:
        ry = datetime.now().year

    if not db_session:
        db_session = SessionLocal()

    # 1. Beginning Receivable (sum of balances for tax years < report_year)
    beg = db_session.query(
        func.coalesce(func.sum(((PropertyBilling.assessed_value * 0.02) + PropertyBilling.penalty) - PropertyBilling.amount_paid), 0)
    ).join(Property, Property.id == PropertyBilling.property_id).filter(
        Property.is_deleted == False,
        PropertyBilling.tax_year < str(ry)
    ).scalar()
    
    # 2. Current Year Assessment
    curr_ass = db_session.query(
        func.coalesce(func.sum((PropertyBilling.assessed_value * 0.02) + PropertyBilling.penalty), 0)
    ).join(Property, Property.id == PropertyBilling.property_id).filter(
        Property.is_deleted == False,
        PropertyBilling.tax_year == str(ry)
    ).scalar()
    
    # 3. Collections (total paid in this calendar year)
    coll = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(Property, Property.id == Payment.property_id).filter(
        Property.is_deleted == False,
        func.year(Payment.date_paid) == ry
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


def get_delinquent_accounts(limit=50, offset=0, db_session: Session = None):
    """
    Fetches properties with outstanding balances across any tax year using SQLAlchemy.
    """
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))
    
    if not db_session:
        db_session = SessionLocal()

    # Use having clause for balance > 0
    balance_expr = func.sum((PropertyBilling.assessed_value * 0.02) + PropertyBilling.penalty - PropertyBilling.discount - PropertyBilling.amount_paid)
    
    results = db_session.query(
        Property.id,
        Property.td_number,
        Property.owner_name,
        Property.location,
        func.sum((PropertyBilling.assessed_value * 0.02) + PropertyBilling.penalty - PropertyBilling.discount).label('total_due'),
        func.sum(PropertyBilling.amount_paid).label('total_paid'),
        balance_expr.label('balance')
    ).join(PropertyBilling, PropertyBilling.property_id == Property.id).filter(
        Property.is_deleted == False
    ).group_by(Property.id).having(balance_expr > 0).order_by(balance_expr.desc()).limit(safe_limit).offset(safe_offset).all()
    
    return [list(r) for r in results]


def calculate_penalty(principal, months_late):
    """Calculates penalty at 2% per month of delay."""
    return float(principal) * 0.02 * int(months_late)


def get_total_due(property_id, db_session: Session = None):
    """Orchestrates total due calculation for a property."""
    data = get_property_statement_data(property_id, db_session=db_session)
    if not data:
        return None
        
    return {
        "assessed_value": data["assessed_value"],
        "basic": data["assessed_value"] * 0.01,
        "sef": data["assessed_value"] * 0.01,
        "total_due": data["total_balance"] + data["total_paid"], # Simplified for test
        "grand_total": data["grand_total"],
        "billing_rows": data["billing_rows"]
    }




