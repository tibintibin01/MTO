from datetime import date, datetime, timezone
import re
from sqlalchemy import or_, and_, func, case, cast, Integer
from sqlalchemy.orm import Session, aliased
from backend.models import Property, PropertyBilling, PaymentBilling, Payment, TaxPolicy
from decimal import Decimal, ROUND_HALF_UP
from utils.db_compat import greatest, year_of, month_of
from backend.services.assessment_value_service import (
    assessed_value_for_year,
    assessment_versions,
)


ANNUAL_PENALTY_START_MONTH = 7
MAX_PENALTY_MONTHS = 36
MONEY = Decimal("0.01")


def annual_penalty_months(tax_year: int, as_of_date=None) -> int:
    """Return office-standard annual penalty months, capped at 36 months."""
    as_of = as_of_date or date.today()
    start = date(int(tax_year), ANNUAL_PENALTY_START_MONTH, 1)
    if as_of <= start:
        return 0
    months = (as_of.year - start.year) * 12 + (as_of.month - start.month)
    return min(MAX_PENALTY_MONTHS, max(0, months))


def calculate_current_billing_amounts(
    *,
    assessed_value,
    tax_year,
    paid=0,
    recorded_penalty=0,
    discount=0,
    basic_rate=0.01,
    sef_rate=0.01,
    penalty_rate=0.02,
    as_of_date=None,
):
    """Calculate current receivable without double-charging paid penalties."""
    assessed = Decimal(str(assessed_value or 0))
    paid_amount = Decimal(str(paid or 0))
    historical_penalty = Decimal(str(recorded_penalty or 0))
    discount_amount = Decimal(str(discount or 0))
    tax_principal = (
        assessed * (Decimal(str(basic_rate or 0.01)) + Decimal(str(sef_rate or 0.01)))
    ).quantize(MONEY, rounding=ROUND_HALF_UP)
    principal_credit = max(
        Decimal("0.00"), paid_amount + discount_amount - historical_penalty
    )
    remaining_principal = max(Decimal("0.00"), tax_principal - principal_credit)
    months = annual_penalty_months(int(tax_year), as_of_date)
    accrued_penalty = (
        remaining_principal * Decimal(str(penalty_rate or 0.02)) * Decimal(months)
    ).quantize(MONEY, rounding=ROUND_HALF_UP)
    total_penalty = historical_penalty + accrued_penalty
    total_due = (tax_principal + total_penalty - discount_amount).quantize(
        MONEY, rounding=ROUND_HALF_UP
    )
    balance = max(Decimal("0.00"), total_due - paid_amount).quantize(
        MONEY, rounding=ROUND_HALF_UP
    )
    return {
        "tax_principal": tax_principal,
        "recorded_penalty": historical_penalty,
        "accrued_penalty": accrued_penalty,
        "penalty": total_penalty,
        "discount": discount_amount,
        "paid": paid_amount,
        "remaining_principal": remaining_principal,
        "total_due": total_due,
        "balance": balance,
        "penalty_months": months,
    }


# ---------------------------------------------------------------------------
# Shared tax rate expression builders
# ---------------------------------------------------------------------------
# These produce SQLAlchemy column expressions that resolve the correct rate
# from TaxPolicy for each billing row's tax_year. If no policy exists for a
# given year, they fall back to the statutory default (1% basic + 1% SEF).
#
# Usage: join/outerjoin TaxPolicy on tax_year, then use these expressions
# in .query() or .filter() clauses.
#
# For queries that already join TaxPolicy:
#   basic_rate_expr()  → per-row basic rate
#   sef_rate_expr()    → per-row SEF rate
#   total_rate_expr()  → basic + SEF combined
#
# For queries that need a correlated subquery (no explicit join):
#   tax_rate_subquery(db_session, billing_tax_year_col) → scalar subquery
# ---------------------------------------------------------------------------

def basic_rate_expr():
    """Basic tax rate expression — requires TaxPolicy to be joined/outerjoined."""
    return func.coalesce(TaxPolicy.basic_rate, 0.0100)


def sef_rate_expr():
    """SEF tax rate expression — requires TaxPolicy to be joined/outerjoined."""
    return func.coalesce(TaxPolicy.sef_rate, 0.0100)


def total_rate_expr():
    """Combined basic + SEF rate — requires TaxPolicy to be joined/outerjoined."""
    return basic_rate_expr() + sef_rate_expr()


def _assigned_barangay_filters():
    """Only real barangay names, excluding blank/null cleanup placeholders."""
    trimmed = func.trim(Property.barangay)
    return (
        Property.barangay != None,
        trimmed != "",
        func.upper(trimmed) != "UNSPECIFIED",
    )


def _property_effectivity_year_expr(model):
    year_source = func.coalesce(
        func.nullif(func.trim(model.effectivity_date), ""),
        func.nullif(func.trim(model.tax_year), ""),
    )
    return cast(func.substr(year_source, 1, 4), Integer)


def _compliance_property_scope(as_of_year: int, db_session: Session):
    """Filters properties to those active for the selected compliance year."""
    year = int(as_of_year)
    effectivity_year = _property_effectivity_year_expr(Property)
    replacement = aliased(Property)
    replacement_effectivity_year = _property_effectivity_year_expr(replacement)
    replaced_td_numbers = (
        db_session.query(func.trim(replacement.prev_td_number))
        .filter(
            replacement.deleted_at == None,
            replacement.prev_td_number != None,
            func.trim(replacement.prev_td_number) != "",
            replacement_effectivity_year <= year,
        )
        .scalar_subquery()
    )
    return (
        or_(effectivity_year == None, effectivity_year <= year),
        ~func.trim(Property.td_number).in_(replaced_td_numbers),
    )


def tax_rate_subquery(db_session: Session, billing_tax_year_col):
    """
    Correlated scalar subquery that resolves the total rate for a billing row.
    Use when TaxPolicy is NOT already joined in the outer query.

    Returns a scalar expression: basic_rate + sef_rate for the matching year,
    or 0.02 if no policy row exists.
    """
    return func.coalesce(
        db_session.query(TaxPolicy.basic_rate + TaxPolicy.sef_rate)
        .filter(TaxPolicy.tax_year == billing_tax_year_col)
        .correlate(PropertyBilling)
        .scalar_subquery(),
        0.02
    )


def _paid_to_billing_expr(db_session: Session, *, year_lt=None, year_lte=None, year_eq=None):
    """Payments applied to the outer PropertyBilling row, filtered by OR date year."""
    pb_pay = aliased(PaymentBilling)
    pay = aliased(Payment)
    query = db_session.query(func.coalesce(func.sum(pb_pay.amount_paid), 0)).join(
        pay, pay.id == pb_pay.payment_id
    ).filter(
        pb_pay.billing_id == PropertyBilling.id,
        pay.date_paid != None,
    )
    paid_year = year_of(pay.date_paid)
    if year_lt is not None:
        query = query.filter(paid_year < int(year_lt))
    if year_lte is not None:
        query = query.filter(paid_year <= int(year_lte))
    if year_eq is not None:
        query = query.filter(paid_year == int(year_eq))
    return query.correlate(PropertyBilling).scalar_subquery()

def sync_property_billing(
    property_id, tax_year, assessed_value, penalty, discount=0.0, has_payment=False, db_session: Session = None
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


def resolve_assessed_value_for_billing_year(
    property_id,
    tax_year,
    fallback_assessed_value=None,
    db_session: Session = None,
):
    """
    Resolve the assessed value that should be used for a specific billing year.

    Property.assessed_value is the current master value. Payment/billing rows are
    historical snapshots, so older tax years must use the assessment value that
    was effective for that year when prior assessment history exists.
    """
    fallback = Decimal(str(fallback_assessed_value or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if not db_session or not property_id:
        return fallback

    normalized_tax_year = (
        int(tax_year) if tax_year and str(tax_year).strip().isdigit() else None
    )
    if not normalized_tax_year:
        return fallback

    prop = db_session.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return fallback

    resolved = assessed_value_for_year(prop, normalized_tax_year, db_session)
    if resolved is None or resolved <= Decimal("0.00"):
        return fallback
    return resolved


def _year_from_value(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(19|20|21|22)\d{2}", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except (TypeError, ValueError):
        return None


def sync_existing_billing_assessed_value(
    property_id,
    assessed_value,
    effective_year=None,
    db_session: Session = None,
):
    """
    Keeps existing PropertyBilling assessment snapshots aligned after an
    assessment-roll/property AV correction.

    Billing rows are historical snapshots, so the update starts at the
    property's effectivity year when available. Payment allocations, penalties,
    and discounts are not touched; only the assessed value used for levy and
    reconciliation is corrected.
    """
    if not db_session or not property_id:
        return {"updated": 0, "years": []}

    new_value = Decimal(str(assessed_value or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if new_value <= Decimal("0.00"):
        return {"updated": 0, "years": []}

    start_year = _year_from_value(effective_year)
    query = db_session.query(PropertyBilling).filter(
        PropertyBilling.property_id == property_id,
        PropertyBilling.is_archived == False,
    )
    if start_year:
        query = query.filter(PropertyBilling.tax_year >= start_year)

    updated_years = []
    for row in query.with_for_update().all():
        current = Decimal(str(row.assessed_value or 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if current != new_value:
            row.assessed_value = new_value
            row.updated_at = datetime.now(timezone.utc)
            updated_years.append(int(row.tax_year))

    if updated_years:
        db_session.flush()

    return {"updated": len(updated_years), "years": sorted(updated_years)}


def repair_billing_assessed_value_snapshots(
    dry_run=True,
    sample_limit=100,
    db_session: Session = None,
):
    """
    Finds PropertyBilling assessed-value snapshots that no longer match the
    active property master value, then optionally repairs them.

    Scope is intentionally conservative:
      - active properties only
      - positive current property AV only
      - non-archived billing rows only
      - from effectivity year onward when effectivity is available

    This fixes reconciliation rows where ledger payments are correct but
    stale billing snapshots still use an old AV.
    """
    if not db_session:
        return {
            "dry_run": bool(dry_run),
            "properties_scanned": 0,
            "properties_affected": 0,
            "rows_to_update": 0,
            "rows_updated": 0,
            "sample": [],
        }

    sample_limit = max(1, min(int(sample_limit or 100), 500))
    props = db_session.query(Property).filter(
        Property.deleted_at == None,
        Property.assessed_value != None,
        Property.assessed_value > 0,
    ).order_by(Property.id.asc()).all()

    sample = []
    affected_property_ids = set()
    rows_to_update = 0
    rows_updated = 0

    for prop in props:
        versions = assessment_versions(prop, db_session)
        query = db_session.query(PropertyBilling).filter(
            PropertyBilling.property_id == prop.id,
            PropertyBilling.is_archived == False,
        )

        for row in query.order_by(PropertyBilling.tax_year.asc()).all():
            new_value = assessed_value_for_year(
                prop, row.tax_year, db_session, versions=versions
            )
            if new_value is None or new_value <= Decimal("0.00"):
                continue
            current = Decimal(str(row.assessed_value or 0)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if current == new_value:
                continue

            rows_to_update += 1
            affected_property_ids.add(prop.id)
            if len(sample) < sample_limit:
                sample.append({
                    "property_id": prop.id,
                    "billing_id": row.id,
                    "td_number": prop.td_number,
                    "owner_name": prop.owner_name,
                    "barangay": prop.barangay,
                    "tax_year": int(row.tax_year or 0),
                    "old_assessed_value": float(current),
                    "new_assessed_value": float(new_value),
                    "effectivity_year": _year_from_value(prop.effectivity_date or prop.tax_year),
                })

            if not dry_run:
                row.assessed_value = new_value
                row.updated_at = datetime.now(timezone.utc)
                rows_updated += 1

    if not dry_run and rows_updated:
        db_session.flush()

    return {
        "dry_run": bool(dry_run),
        "properties_scanned": len(props),
        "properties_affected": len(affected_property_ids),
        "rows_to_update": rows_to_update,
        "rows_updated": rows_updated,
        "sample": sample,
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


def recalculate_billing_balances(billing_ids, db_session: Session = None):
    seen = []
    for billing_id in billing_ids:
        if billing_id and billing_id not in seen:
            seen.append(billing_id)

    for billing_id in seen:
        total_paid, total_penalty, total_discount = db_session.query(
            func.coalesce(func.sum(PaymentBilling.amount_paid), 0),
            func.coalesce(func.sum(Payment.penalty), 0),
            func.coalesce(func.sum(Payment.discount), 0),
        ).outerjoin(
            Payment, Payment.id == PaymentBilling.payment_id
        ).filter(
            PaymentBilling.billing_id == billing_id
        ).one()

        db_session.query(PropertyBilling).filter(PropertyBilling.id == billing_id).update({
            PropertyBilling.amount_paid: float(total_paid or 0),
            PropertyBilling.penalty: float(total_penalty or 0),
            PropertyBilling.discount: float(total_discount or 0),
            PropertyBilling.updated_at: datetime.now(timezone.utc)
        }, synchronize_session=False)


def sync_payment_billings(payment_id, billing_rows, db_session: Session = None):
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
    recalculate_billing_balances(affected_billing_ids, db_session=db_session)


def repair_payment_billing_allocations(
    dry_run=True,
    sample_limit=100,
    db_session: Session = None,
):
    """
    Repairs the accounting bridge between payments and yearly billings.

    The visible ledger reads from payments, while reconciliation reads from
    payment_billings plus property_billings. Older imports/manual edits can
    leave a payment row without its allocation link, leave the link amount
    stale, or leave billing paid/penalty/discount summaries stale. This
    function fixes only unambiguous cases:
      - active property only
      - missing links: payment tax_year resolves to exactly one numeric year
      - stale single-link payments: payment has one link and one tax year

    It never changes OR numbers, payment dates, or payment amounts.
    """
    empty = {
        "dry_run": bool(dry_run),
        "payments_scanned": 0,
        "missing_links": 0,
        "stale_link_amounts": 0,
        "stale_billing_summaries": 0,
        "ambiguous_payments_skipped": 0,
        "billing_rows_to_recalculate": 0,
        "billing_rows_recalculated": 0,
        "billing_rows_created": 0,
        "properties_affected": 0,
        "sample": [],
    }
    if not db_session:
        return empty

    sample_limit = max(1, min(int(sample_limit or 100), 500))
    sample = []
    affected_property_ids = set()
    affected_billing_ids = set()
    missing_links = 0
    stale_link_amounts = 0
    stale_billing_summaries = 0
    skipped = 0
    created_billings = 0

    def add_sample(item):
        if len(sample) < sample_limit:
            sample.append(item)

    linked_paid_expr = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).filter(
        PaymentBilling.billing_id == PropertyBilling.id
    ).correlate(PropertyBilling).scalar_subquery()

    mismatch_rows = db_session.query(PropertyBilling.id, PropertyBilling.property_id).join(
        Property, Property.id == PropertyBilling.property_id
    ).filter(
        Property.deleted_at == None,
        func.abs(PropertyBilling.amount_paid - linked_paid_expr) > 0.01,
    ).all()
    for billing_id, property_id in mismatch_rows:
        if billing_id:
            affected_billing_ids.add(int(billing_id))
        if property_id:
            affected_property_ids.add(int(property_id))

    has_links = db_session.query(PaymentBilling.id).filter(
        PaymentBilling.payment_id == Payment.id
    ).exists()
    payment_rows = db_session.query(Payment, Property).join(
        Property, Property.id == Payment.property_id
    ).filter(
        Property.deleted_at == None,
        Payment.amount != None,
        ~has_links,
    ).order_by(Payment.id.asc()).all()

    for payment, prop in payment_rows:
        years = []
        for part in normalize_tax_years(payment.tax_year):
            part = str(part).strip()
            if part.isdigit():
                years.append(int(part))
        if len(years) != 1:
            skipped += 1
            add_sample({
                "action": "skipped_ambiguous_tax_year",
                "td_number": prop.td_number,
                "owner_name": prop.owner_name,
                "or_number": payment.or_number,
                "tax_year": payment.tax_year,
                "amount": float(Decimal(str(payment.amount or 0))),
            })
            continue

        tax_year = years[0]
        amount = Decimal(str(payment.amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount <= Decimal("0.00"):
            skipped += 1
            continue

        billing = db_session.query(PropertyBilling).filter(
            PropertyBilling.property_id == prop.id,
            PropertyBilling.tax_year == tax_year,
        ).first()

        missing_links += 1
        affected_property_ids.add(int(prop.id))
        add_sample({
            "action": "create_payment_billing_link",
            "td_number": prop.td_number,
            "owner_name": prop.owner_name,
            "or_number": payment.or_number,
            "payment_id": payment.id,
            "tax_year": tax_year,
            "amount": float(amount),
            "billing_exists": bool(billing),
        })

        if dry_run:
            continue

        if not billing:
            billing = PropertyBilling(
                property_id=prop.id,
                tax_year=tax_year,
                assessed_value=resolve_assessed_value_for_billing_year(
                    prop.id,
                    tax_year,
                    prop.assessed_value,
                    db_session=db_session,
                ),
                penalty=Decimal("0.00"),
                discount=Decimal("0.00"),
                amount_paid=Decimal("0.00"),
                is_archived=False,
            )
            db_session.add(billing)
            db_session.flush()
            created_billings += 1

        db_session.add(PaymentBilling(
            payment_id=payment.id,
            billing_id=billing.id,
            tax_year=tax_year,
            amount_paid=amount,
        ))
        affected_billing_ids.add(int(billing.id))

    single_link_rows = db_session.query(Payment, PaymentBilling, PropertyBilling, Property).join(
        PaymentBilling, PaymentBilling.payment_id == Payment.id
    ).join(
        PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id
    ).join(
        Property, Property.id == Payment.property_id
    ).filter(
        Property.deleted_at == None,
        Payment.amount != None,
    ).all()

    link_counts = {}
    for payment, _link, _billing, _prop in single_link_rows:
        link_counts[payment.id] = link_counts.get(payment.id, 0) + 1

    for payment, link, billing, prop in single_link_rows:
        if link_counts.get(payment.id, 0) != 1:
            continue
        years = [int(str(part).strip()) for part in normalize_tax_years(payment.tax_year) if str(part).strip().isdigit()]
        if len(years) != 1 or years[0] != int(billing.tax_year):
            continue

        expected_amount = Decimal(str(payment.amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        current_amount = Decimal(str(link.amount_paid or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if abs(expected_amount - current_amount) <= Decimal("0.01"):
            continue

        stale_link_amounts += 1
        affected_property_ids.add(int(prop.id))
        affected_billing_ids.add(int(billing.id))
        add_sample({
            "action": "fix_stale_link_amount",
            "td_number": prop.td_number,
            "owner_name": prop.owner_name,
            "or_number": payment.or_number,
            "payment_id": payment.id,
            "tax_year": int(billing.tax_year),
            "old_amount": float(current_amount),
            "amount": float(expected_amount),
        })
        if not dry_run:
            link.amount_paid = expected_amount

    summary_rows = db_session.query(
        PropertyBilling,
        Property,
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0),
        func.coalesce(func.sum(Payment.penalty), 0),
        func.coalesce(func.sum(Payment.discount), 0),
        func.count(PaymentBilling.id),
    ).join(
        Property, Property.id == PropertyBilling.property_id
    ).outerjoin(
        PaymentBilling, PaymentBilling.billing_id == PropertyBilling.id
    ).outerjoin(
        Payment, Payment.id == PaymentBilling.payment_id
    ).filter(
        Property.deleted_at == None,
    ).group_by(PropertyBilling.id, Property.id).all()

    for billing, prop, linked_paid, linked_penalty, linked_discount, link_count in summary_rows:
        if int(link_count or 0) <= 0:
            continue
        expected_paid = Decimal(str(linked_paid or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        expected_penalty = Decimal(str(linked_penalty or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        expected_discount = Decimal(str(linked_discount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        current_paid = Decimal(str(billing.amount_paid or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        current_penalty = Decimal(str(billing.penalty or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        current_discount = Decimal(str(billing.discount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if (
            abs(current_paid - expected_paid) <= Decimal("0.01")
            and abs(current_penalty - expected_penalty) <= Decimal("0.01")
            and abs(current_discount - expected_discount) <= Decimal("0.01")
        ):
            continue

        stale_billing_summaries += 1
        affected_property_ids.add(int(prop.id))
        affected_billing_ids.add(int(billing.id))
        add_sample({
            "action": "fix_billing_summary",
            "td_number": prop.td_number,
            "owner_name": prop.owner_name,
            "tax_year": int(billing.tax_year),
            "old_paid": float(current_paid),
            "amount": float(expected_paid),
            "old_penalty": float(current_penalty),
            "new_penalty": float(expected_penalty),
            "old_discount": float(current_discount),
            "new_discount": float(expected_discount),
        })
        if not dry_run:
            billing.amount_paid = expected_paid
            billing.penalty = expected_penalty
            billing.discount = expected_discount
            billing.updated_at = datetime.now(timezone.utc)

    rows_to_recalculate = len(affected_billing_ids)
    rows_recalculated = 0
    if not dry_run and affected_billing_ids:
        db_session.flush()
        recalculate_billing_balances(sorted(affected_billing_ids), db_session=db_session)
        rows_recalculated = rows_to_recalculate
        db_session.flush()

    return {
        "dry_run": bool(dry_run),
        "payments_scanned": len(payment_rows) + len(single_link_rows),
        "missing_links": missing_links,
        "stale_link_amounts": stale_link_amounts,
        "stale_billing_summaries": stale_billing_summaries,
        "ambiguous_payments_skipped": skipped,
        "billing_rows_to_recalculate": rows_to_recalculate,
        "billing_rows_recalculated": rows_recalculated,
        "billing_rows_created": created_billings,
        "properties_affected": len(affected_property_ids),
        "sample": sample,
    }


def get_property_billing_history(
    property_id=None,
    term=None,
    limit=50,
    as_of_date=None,
    db_session: Session = None,
):
    safe_limit = max(1, int(limit))

    basic_rate_expr = func.coalesce(TaxPolicy.basic_rate, 0.0100)
    sef_rate_expr = func.coalesce(TaxPolicy.sef_rate, 0.0100)
    current = _billing_current_amount_exprs(db_session, as_of_date)
    
    query = db_session.query(
        PropertyBilling.tax_year,
        PropertyBilling.assessed_value,
        (PropertyBilling.assessed_value * basic_rate_expr).label('basic_amount'),
        (PropertyBilling.assessed_value * sef_rate_expr).label('sef_amount'),
        current["total_penalty"].label('penalty'),
        current["total_due"].label('total_amount'),
        current["paid"].label('amount_paid'),
        current["balance"].label('balance_amount'),
        case(
            (current["paid"] <= 0, 'Pending'),
            (current["balance"] <= 0, 'Paid'),
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


def get_property_statement_data(property_id, as_of_date=None, db_session: Session = None):
    prop = db_session.query(Property).filter(Property.id == property_id, Property.deleted_at == None).first()
    if not prop:
        return None
        
    billing_rows_raw = get_property_billing_history(
        property_id=property_id,
        limit=500,
        as_of_date=as_of_date,
        db_session=db_session,
    )
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

    last_payment = (
        db_session.query(Payment)
        .filter(Payment.property_id == property_id)
        .order_by(Payment.date_paid.desc(), Payment.id.desc())
        .first()
    )

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
        "accountable_officer": prop.accountable_officer,
        "last_payment_date": last_payment.date_paid if last_payment else None,
        "last_or_number": last_payment.or_number if last_payment else None,
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


def _billing_effective_amount_exprs(db_session: Session):
    """Use linked payments as the authoritative billing amounts when they exist."""
    linked_paid_expr = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).filter(
        PaymentBilling.billing_id == PropertyBilling.id
    ).correlate(PropertyBilling).scalar_subquery()
    linked_penalty_expr = db_session.query(
        func.coalesce(func.sum(Payment.penalty), 0)
    ).join(
        PaymentBilling, PaymentBilling.payment_id == Payment.id
    ).filter(
        PaymentBilling.billing_id == PropertyBilling.id
    ).correlate(PropertyBilling).scalar_subquery()
    linked_discount_expr = db_session.query(
        func.coalesce(func.sum(Payment.discount), 0)
    ).join(
        PaymentBilling, PaymentBilling.payment_id == Payment.id
    ).filter(
        PaymentBilling.billing_id == PropertyBilling.id
    ).correlate(PropertyBilling).scalar_subquery()
    linked_count_expr = db_session.query(
        func.count(PaymentBilling.id)
    ).filter(
        PaymentBilling.billing_id == PropertyBilling.id
    ).correlate(PropertyBilling).scalar_subquery()

    return {
        "paid": case((linked_count_expr > 0, linked_paid_expr), else_=PropertyBilling.amount_paid),
        "penalty": case((linked_count_expr > 0, linked_penalty_expr), else_=PropertyBilling.penalty),
        "discount": case((linked_count_expr > 0, linked_discount_expr), else_=PropertyBilling.discount),
        "linked_count": linked_count_expr,
    }


def _billing_current_amount_exprs(db_session: Session, as_of_date=None):
    """SQL expressions for the live, as-of-date balance of each billing row."""
    as_of = as_of_date or date.today()
    effective = _billing_effective_amount_exprs(db_session)
    total_rate = tax_rate_subquery(db_session, PropertyBilling.tax_year)
    penalty_rate = func.coalesce(
        db_session.query(TaxPolicy.penalty_rate)
        .filter(TaxPolicy.tax_year == PropertyBilling.tax_year)
        .correlate(PropertyBilling)
        .scalar_subquery(),
        0.02,
    )
    raw_months = (
        (int(as_of.year) - PropertyBilling.tax_year) * 12
        + (int(as_of.month) - ANNUAL_PENALTY_START_MONTH)
    )
    months = case(
        (raw_months < 0, 0),
        (raw_months > MAX_PENALTY_MONTHS, MAX_PENALTY_MONTHS),
        else_=raw_months,
    )
    tax_principal = PropertyBilling.assessed_value * total_rate
    principal_credit = greatest(
        effective["paid"] + effective["discount"] - effective["penalty"],
        0,
    )
    remaining_principal = greatest(tax_principal - principal_credit, 0)
    accrued_penalty = func.round(remaining_principal * penalty_rate * months, 2)
    total_penalty = effective["penalty"] + accrued_penalty
    total_due = tax_principal + total_penalty - effective["discount"]
    balance = greatest(total_due - effective["paid"], 0)
    return {
        **effective,
        "tax_principal": tax_principal,
        "remaining_principal": remaining_principal,
        "accrued_penalty": accrued_penalty,
        "total_penalty": total_penalty,
        "total_due": total_due,
        "balance": balance,
        "penalty_months": months,
    }


def get_rpt_receivables_summary(report_year, db_session: Session = None):
    try:
        ry = int(report_year)
    except (ValueError, TypeError):
        ry = datetime.now(timezone.utc).year

    basic_rate_expr = func.coalesce(TaxPolicy.basic_rate, 0.0100)
    sef_rate_expr = func.coalesce(TaxPolicy.sef_rate, 0.0100)
    total_rate_expr = basic_rate_expr + sef_rate_expr
    effective = _billing_effective_amount_exprs(db_session)
    effective_penalty_expr = effective["penalty"]
    effective_discount_expr = effective["discount"]
    due_expr = (PropertyBilling.assessed_value * total_rate_expr) + effective_penalty_expr - effective_discount_expr
    paid_before_year = _paid_to_billing_expr(db_session, year_lt=ry)
    paid_through_year = _paid_to_billing_expr(db_session, year_lte=ry)

    # Beginning receivable is a point-in-time balance at the start of the selected fiscal year.
    # It must not include payments posted after that year, even if PropertyBilling.amount_paid is cumulative today.
    beg = db_session.query(
        func.coalesce(func.sum(greatest(due_expr - paid_before_year, 0)), 0)
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year < ry,
    ).scalar()

    curr_row = db_session.query(
        func.coalesce(func.sum(PropertyBilling.assessed_value * total_rate_expr), 0),
        func.coalesce(func.sum(effective_penalty_expr), 0),
        func.coalesce(func.sum(effective_discount_expr), 0),
        func.coalesce(func.sum(due_expr), 0),
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year == ry,
    ).one()
    curr_levy = float(curr_row[0] or 0)
    curr_penalty = float(curr_row[1] or 0)
    curr_discount = float(curr_row[2] or 0)
    curr_net = float(curr_row[3] or 0)

    calendar_applicable_collections = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
        PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None,
        Payment.date_paid != None,
        year_of(Payment.date_paid) == ry,
        PropertyBilling.tax_year <= ry,
    ).scalar()

    prepaid_current_year = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
        PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None,
        Payment.date_paid != None,
        year_of(Payment.date_paid) < ry,
        PropertyBilling.tax_year == ry,
    ).scalar()

    future_year_prepayments = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
        PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None,
        Payment.date_paid != None,
        year_of(Payment.date_paid) == ry,
        PropertyBilling.tax_year > ry,
    ).scalar()

    end = db_session.query(
        func.coalesce(func.sum(greatest(due_expr - paid_through_year, 0)), 0)
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year <= ry,
    ).scalar()

    calendar_applicable_collections = float(calendar_applicable_collections or 0)
    prepaid_current_year = float(prepaid_current_year or 0)
    applied_collections = calendar_applicable_collections + prepaid_current_year
    future_year_prepayments = float(future_year_prepayments or 0)
    adj = 0.0
    expected_end = float(beg or 0) + curr_net - applied_collections + adj

    return {
        "report_year": ry,
        "beginning_receivable": float(beg or 0),
        "current_year_assessment": curr_net,
        "current_year_levy": curr_levy,
        "current_year_penalty": curr_penalty,
        "current_year_discount": curr_discount,
        "current_year_net_collectible": curr_net,
        "collections": calendar_applicable_collections,
        "calendar_applicable_collections": calendar_applicable_collections,
        "prepaid_current_year": prepaid_current_year,
        "applied_collections": applied_collections,
        "future_year_prepayments": future_year_prepayments,
        "adjustments": adj,
        "ending_receivable": float(end or 0),
        "expected_ending_receivable": expected_end,
        "equation_variance": expected_end - float(end or 0),
    }


def get_reconciliation_metrics(report_year, db_session: Session = None):
    """Department-level metrics for COA reconciliation review."""
    try:
        ry = int(report_year)
    except (ValueError, TypeError):
        ry = datetime.now(timezone.utc).year

    basic = basic_rate_expr()
    sef = sef_rate_expr()
    total = basic + sef
    effective = _billing_effective_amount_exprs(db_session)
    effective_penalty_expr = effective["penalty"]
    effective_discount_expr = effective["discount"]
    due_expr = (PropertyBilling.assessed_value * total) + effective_penalty_expr - effective_discount_expr
    paid_through_year = _paid_to_billing_expr(db_session, year_lte=ry)
    balance_as_of_expr = due_expr - paid_through_year

    assessor_row = db_session.query(
        func.coalesce(func.sum(PropertyBilling.assessed_value), 0),
        func.count(func.distinct(PropertyBilling.property_id)),
        func.coalesce(func.sum(PropertyBilling.assessed_value * total), 0),
        func.coalesce(func.sum(effective_penalty_expr), 0),
        func.coalesce(func.sum(effective_discount_expr), 0),
        func.coalesce(func.sum(due_expr), 0),
        func.coalesce(func.avg(basic), 0.0100),
        func.coalesce(func.avg(total), 0.0200),
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year == ry,
    ).one()

    basic_share = case((total > 0, basic / total), else_=0.5)
    applied_filter = or_(
        and_(year_of(Payment.date_paid) == ry, PropertyBilling.tax_year <= ry),
        and_(year_of(Payment.date_paid) < ry, PropertyBilling.tax_year == ry),
    )
    treasury_row = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid * basic_share), 0),
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0),
        func.count(func.distinct(Payment.property_id)),
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
        Property, Property.id == Payment.property_id
    ).join(PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        Payment.date_paid != None,
        applied_filter,
    ).one()

    cash_collected_this_year = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
        Property, Property.id == Payment.property_id
    ).filter(
        Property.deleted_at == None,
        Payment.date_paid != None,
        year_of(Payment.date_paid) == ry,
    ).scalar()

    calendar_applicable_collections = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
        PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None,
        Payment.date_paid != None,
        year_of(Payment.date_paid) == ry,
        PropertyBilling.tax_year <= ry,
    ).scalar()

    prepaid_current_year = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
        PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None,
        Payment.date_paid != None,
        year_of(Payment.date_paid) < ry,
        PropertyBilling.tax_year == ry,
    ).scalar()

    future_year_prepayments = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
        PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id
    ).join(Property, Property.id == Payment.property_id).filter(
        Property.deleted_at == None,
        Payment.date_paid != None,
        year_of(Payment.date_paid) == ry,
        PropertyBilling.tax_year > ry,
    ).scalar()

    delinquency_row = db_session.query(
        func.coalesce(func.sum(case((balance_as_of_expr > 0, balance_as_of_expr), else_=0)), 0),
        func.coalesce(func.sum(case((and_(PropertyBilling.tax_year == ry, balance_as_of_expr > 0), balance_as_of_expr), else_=0)), 0),
        func.coalesce(func.sum(case((and_(PropertyBilling.tax_year < ry, balance_as_of_expr > 0), balance_as_of_expr), else_=0)), 0),
        func.count(func.distinct(case((balance_as_of_expr > 0, PropertyBilling.property_id), else_=None))),
        func.coalesce(func.sum(case((balance_as_of_expr > 0, effective_penalty_expr), else_=0)), 0),
        func.count(func.distinct(case((and_(paid_through_year > 0, balance_as_of_expr > 0), PropertyBilling.property_id), else_=None))),
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year <= ry,
    ).one()

    return {
        "report_year": ry,
        "assessor": {
            "total_assessed_value": float(assessor_row[0] or 0),
            "tax_rate_percent": float(assessor_row[6] or 0) * 100,
            "total_tax_rate_percent": float(assessor_row[7] or 0) * 100,
            "taxable_properties": int(assessor_row[1] or 0),
            "total_billed_levy": float(assessor_row[2] or 0),
            "current_year_levy": float(assessor_row[2] or 0),
            "current_year_penalty": float(assessor_row[3] or 0),
            "current_year_discount": float(assessor_row[4] or 0),
            "current_year_net_collectible": float(assessor_row[5] or 0),
        },
        "treasury": {
            "basic_tax_collected": float(treasury_row[0] or 0),
            "total_collected": float(treasury_row[1] or 0),
            "accounts_paid": int(treasury_row[2] or 0),
            "partial_payments": int(delinquency_row[5] or 0),
            "cash_collected_this_year": float(cash_collected_this_year or 0),
            "calendar_applicable_collections": float(calendar_applicable_collections or 0),
            "prepaid_current_year": float(prepaid_current_year or 0),
            "future_year_prepayments": float(future_year_prepayments or 0),
        },
        "delinquency": {
            "total_delinquent_amount": float(delinquency_row[0] or 0),
            "current_year_receivables": float(delinquency_row[1] or 0),
            "prior_year_receivables": float(delinquency_row[2] or 0),
            "delinquent_accounts": int(delinquency_row[3] or 0),
            "penalties_interest": float(delinquency_row[4] or 0),
            "total_unpaid": float(delinquency_row[0] or 0),
        },
    }


def get_reconciliation_diagnostics(report_year, limit=50, db_session: Session = None):
    """Return audit drilldown rows that can explain reconciliation variance."""
    try:
        ry = int(report_year)
    except (ValueError, TypeError):
        ry = datetime.now(timezone.utc).year

    safe_limit = max(5, min(int(limit or 50), 200))
    total = total_rate_expr()
    linked_paid_expr = db_session.query(
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0)
    ).filter(
        PaymentBilling.billing_id == PropertyBilling.id
    ).correlate(PropertyBilling).scalar_subquery()
    linked_penalty_expr = db_session.query(
        func.coalesce(func.sum(Payment.penalty), 0)
    ).join(
        PaymentBilling, PaymentBilling.payment_id == Payment.id
    ).filter(
        PaymentBilling.billing_id == PropertyBilling.id
    ).correlate(PropertyBilling).scalar_subquery()
    linked_discount_expr = db_session.query(
        func.coalesce(func.sum(Payment.discount), 0)
    ).join(
        PaymentBilling, PaymentBilling.payment_id == Payment.id
    ).filter(
        PaymentBilling.billing_id == PropertyBilling.id
    ).correlate(PropertyBilling).scalar_subquery()
    linked_count_expr = db_session.query(
        func.count(PaymentBilling.id)
    ).filter(
        PaymentBilling.billing_id == PropertyBilling.id
    ).correlate(PropertyBilling).scalar_subquery()
    effective_penalty_expr = case(
        (linked_count_expr > 0, linked_penalty_expr),
        else_=PropertyBilling.penalty,
    )
    effective_discount_expr = case(
        (linked_count_expr > 0, linked_discount_expr),
        else_=PropertyBilling.discount,
    )
    effective_paid_expr = case(
        (linked_count_expr > 0, linked_paid_expr),
        else_=PropertyBilling.amount_paid,
    )
    due_expr = (PropertyBilling.assessed_value * total) + effective_penalty_expr - effective_discount_expr
    paid_through_year = _paid_to_billing_expr(db_session, year_lte=ry)
    balance_expr = due_expr - paid_through_year
    raw_cumulative_balance_expr = due_expr - effective_paid_expr
    payment_gap_expr = PropertyBilling.amount_paid - linked_paid_expr

    summary = get_rpt_receivables_summary(ry, db_session=db_session)
    metrics = get_reconciliation_metrics(ry, db_session=db_session)
    expected_end = float(summary.get("expected_ending_receivable", summary.get("ending_receivable", 0)) or 0)
    tracker_total = float(metrics.get("delinquency", {}).get("total_unpaid", 0) or 0)
    tracker_variance = tracker_total - expected_end
    raw_tracker_total = db_session.query(
        func.coalesce(func.sum(case((raw_cumulative_balance_expr > 0, raw_cumulative_balance_expr), else_=0)), 0)
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year <= ry,
    ).scalar()
    raw_tracker_total = float(raw_tracker_total or 0)
    raw_tracker_variance = raw_tracker_total - expected_end

    def money_float(value):
        return float(value or 0)

    def billing_row(row, issue):
        return {
            "issue": issue,
            "td_number": row[0],
            "owner_name": row[1],
            "barangay": row[2],
            "tax_year": int(row[3] or 0),
            "total_due": money_float(row[4]),
            "recorded_paid": money_float(row[5]),
            "linked_paid": money_float(row[6]) if len(row) > 6 else None,
            "balance": money_float(row[7]) if len(row) > 7 else None,
            "difference": money_float(row[8]) if len(row) > 8 else None,
        }

    payment_link_rows = db_session.query(
        Property.td_number,
        Property.owner_name,
        Property.barangay,
        PropertyBilling.tax_year,
        due_expr,
        PropertyBilling.amount_paid,
        linked_paid_expr,
        balance_expr,
        payment_gap_expr,
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year <= ry,
        func.abs(payment_gap_expr) > 0.01,
    ).order_by(func.abs(payment_gap_expr).desc()).limit(safe_limit).all()

    overpaid_rows = db_session.query(
        Property.td_number,
        Property.owner_name,
        Property.barangay,
        PropertyBilling.tax_year,
        due_expr,
        PropertyBilling.amount_paid,
        linked_paid_expr,
        balance_expr,
        balance_expr,
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year <= ry,
        balance_expr < -0.01,
    ).order_by(balance_expr.asc()).limit(safe_limit).all()

    largest_balance_rows = db_session.query(
        Property.td_number,
        Property.owner_name,
        Property.barangay,
        PropertyBilling.tax_year,
        due_expr,
        PropertyBilling.amount_paid,
        linked_paid_expr,
        balance_expr,
        balance_expr,
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year <= ry,
        balance_expr > 0.01,
    ).order_by(balance_expr.desc()).limit(safe_limit).all()

    def payment_group_rows(year_filter, issue):
        rows = db_session.query(
            PropertyBilling.tax_year,
            func.count(PaymentBilling.id),
            func.count(func.distinct(PropertyBilling.property_id)),
            func.coalesce(func.sum(PaymentBilling.amount_paid), 0),
        ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
            PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id
        ).join(Property, Property.id == PropertyBilling.property_id).filter(
            Property.deleted_at == None,
            year_of(Payment.date_paid) == ry,
            year_filter,
        ).group_by(PropertyBilling.tax_year).order_by(PropertyBilling.tax_year).all()
        return [
            {
                "issue": issue,
                "tax_year": int(row[0] or 0),
                "payment_rows": int(row[1] or 0),
                "properties": int(row[2] or 0),
                "amount": money_float(row[3]),
            }
            for row in rows
        ]

    prior_year_collections = payment_group_rows(PropertyBilling.tax_year < ry, "Collections posted this year for prior tax years")
    future_year_collections = payment_group_rows(PropertyBilling.tax_year > ry, "Collections posted this year for future tax years / prepayments")

    outside_rows = db_session.query(
        PropertyBilling.tax_year,
        year_of(Payment.date_paid),
        func.count(PaymentBilling.id),
        func.count(func.distinct(PropertyBilling.property_id)),
        func.coalesce(func.sum(PaymentBilling.amount_paid), 0),
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
        PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id
    ).join(Property, Property.id == PropertyBilling.property_id).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year == ry,
        or_(Payment.date_paid == None, year_of(Payment.date_paid) != ry),
    ).group_by(PropertyBilling.tax_year, year_of(Payment.date_paid)).order_by(year_of(Payment.date_paid)).all()

    current_year_paid_outside = [
        {
            "issue": "Payments for selected tax year posted outside selected calendar year",
            "tax_year": int(row[0] or 0),
            "payment_year": int(row[1] or 0) if row[1] else None,
            "payment_rows": int(row[2] or 0),
            "properties": int(row[3] or 0),
            "amount": money_float(row[4]),
        }
        for row in outside_rows
    ]


    outside_detail_rows = db_session.query(
        Property.td_number,
        Property.owner_name,
        Property.barangay,
        PropertyBilling.tax_year,
        year_of(Payment.date_paid),
        Payment.date_paid,
        Payment.or_number,
        PaymentBilling.amount_paid,
    ).join(Payment, Payment.id == PaymentBilling.payment_id).join(
        PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id
    ).join(Property, Property.id == PropertyBilling.property_id).filter(
        Property.deleted_at == None,
        PropertyBilling.tax_year == ry,
        or_(Payment.date_paid == None, year_of(Payment.date_paid) != ry),
    ).order_by(year_of(Payment.date_paid), PaymentBilling.amount_paid.desc()).limit(safe_limit).all()

    current_year_paid_outside_details = [
        {
            "issue": "Selected tax year paid outside selected calendar year",
            "td_number": row[0],
            "owner_name": row[1],
            "barangay": row[2],
            "tax_year": int(row[3] or 0),
            "payment_year": int(row[4] or 0) if row[4] else None,
            "payment_date": row[5].strftime("%Y-%m-%d") if row[5] else None,
            "or_number": row[6],
            "amount": money_float(row[7]),
        }
        for row in outside_detail_rows
    ]

    # Flag out-of-order payment histories. A later tax year with a linked
    # payment should not normally coexist with a missing or incomplete prior
    # year. Work from linked allocations (the accounting source of truth), not
    # the free-form tax-year label displayed on the payment row.
    sequence_rows = db_session.query(
        Property.id,
        Property.td_number,
        Property.owner_name,
        Property.barangay,
        Property.effectivity_date,
        PropertyBilling.tax_year,
        due_expr,
        linked_paid_expr,
    ).join(Property, Property.id == PropertyBilling.property_id).outerjoin(
        TaxPolicy, TaxPolicy.tax_year == PropertyBilling.tax_year
    ).filter(
        Property.deleted_at == None,
        Property.archived == False,
        PropertyBilling.is_archived == False,
        PropertyBilling.tax_year <= ry,
    ).order_by(Property.id.asc(), PropertyBilling.tax_year.asc()).all()

    sequence_by_property = {}
    for row in sequence_rows:
        bucket = sequence_by_property.setdefault(int(row[0]), {
            "td_number": row[1],
            "owner_name": row[2],
            "barangay": row[3],
            "effectivity_year": _year_from_value(row[4]),
            "years": {},
        })
        bucket["years"][int(row[5])] = {
            "total_due": money_float(row[6]),
            "linked_paid": money_float(row[7]),
        }

    payment_sequence_gaps = []
    for bucket in sequence_by_property.values():
        year_rows = bucket["years"]
        paid_years = sorted(
            year for year, values in year_rows.items()
            if values["linked_paid"] > 0.01
        )
        if not paid_years:
            continue

        latest_paid_year = paid_years[-1]
        first_billed_year = min(year_rows)
        start_year = bucket["effectivity_year"] or first_billed_year
        start_year = max(2023, int(start_year))
        if latest_paid_year <= start_year:
            continue

        for gap_year in range(start_year, latest_paid_year):
            values = year_rows.get(gap_year)
            if values is None:
                issue = "Missing billing/payment year before a later paid year"
                total_due_value = None
                linked_paid_value = 0.0
                outstanding = None
                status = "missing_billing"
            else:
                total_due_value = values["total_due"]
                linked_paid_value = values["linked_paid"]
                outstanding = max(0.0, total_due_value - linked_paid_value)
                if total_due_value <= 0.01 or outstanding <= 0.01:
                    continue
                status = "unpaid" if linked_paid_value <= 0.01 else "partial"
                issue = (
                    "Unpaid prior year before a later paid year"
                    if status == "unpaid"
                    else "Partially paid prior year before a later paid year"
                )

            payment_sequence_gaps.append({
                "issue": issue,
                "td_number": bucket["td_number"],
                "owner_name": bucket["owner_name"],
                "barangay": bucket["barangay"],
                "tax_year": gap_year,
                "gap_status": status,
                "total_due": total_due_value,
                "linked_paid": linked_paid_value,
                "outstanding": outstanding,
                "later_paid_year": latest_paid_year,
            })

    payment_sequence_gaps.sort(
        key=lambda item: (
            item["tax_year"],
            -(item["outstanding"] or 0),
            item["td_number"] or "",
        )
    )
    payment_sequence_gap_count = len(payment_sequence_gaps)
    payment_sequence_gaps = payment_sequence_gaps[:safe_limit]

    unlinked_raw_rows = db_session.query(
        Payment.id,
        Property.td_number,
        Property.owner_name,
        Property.barangay,
        Payment.tax_year,
        Payment.date_paid,
        Payment.or_number,
        Payment.amount,
    ).join(Property, Property.id == Payment.property_id).outerjoin(
        PaymentBilling, PaymentBilling.payment_id == Payment.id
    ).filter(
        Property.deleted_at == None,
        Payment.amount != None,
    ).group_by(
        Payment.id,
        Property.td_number,
        Property.owner_name,
        Property.barangay,
        Payment.tax_year,
        Payment.date_paid,
        Payment.or_number,
        Payment.amount,
    ).having(func.count(PaymentBilling.id) == 0).order_by(
        Payment.date_paid.desc(), Payment.id.desc()
    ).limit(safe_limit * 4).all()

    unlinked_payments = []
    for row in unlinked_raw_rows:
        years = []
        for part in normalize_tax_years(row[4]):
            part = str(part).strip()
            if part.isdigit():
                years.append(int(part))
        if years and not any(year <= ry for year in years):
            continue
        display_year = years[0] if len(years) == 1 else (str(row[4] or "") or None)
        unlinked_payments.append({
            "issue": "Payment exists in ledger but has no billing allocation link",
            "payment_id": int(row[0]),
            "td_number": row[1],
            "owner_name": row[2],
            "barangay": row[3],
            "tax_year": display_year,
            "payment_date": row[5].strftime("%Y-%m-%d") if row[5] else None,
            "or_number": row[6],
            "amount": money_float(row[7]),
        })
        if len(unlinked_payments) >= safe_limit:
            break

    return {
        "report_year": ry,
        "expected_ending_receivable": expected_end,
        "tracker_total_unpaid": tracker_total,
        "tracker_variance": tracker_variance,
        "raw_tracker_total_unpaid": raw_tracker_total,
        "raw_tracker_variance": raw_tracker_variance,
        "payment_link_mismatches": [billing_row(row, "Recorded paid does not match linked payment allocations") for row in payment_link_rows],
        "unlinked_payments": unlinked_payments,
        "overpaid_or_credit_rows": [billing_row(row, "Overpaid / credit balance row") for row in overpaid_rows],
        "largest_open_balances": [billing_row(row, "Largest open receivable row") for row in largest_balance_rows],
        "prior_year_collections": prior_year_collections,
        "future_year_collections": future_year_collections,
        "current_year_paid_outside_selected_year": current_year_paid_outside,
        "current_year_paid_outside_details": current_year_paid_outside_details,
        "payment_sequence_gap_count": payment_sequence_gap_count,
        "payment_sequence_gaps": payment_sequence_gaps,
    }
def get_compliant_accounts(
    barangay: str = None,
    search: str = None,
    limit: int = 50,
    cursor: int = None,
    as_of_year: int = None,
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
    selected_year = int(as_of_year or datetime.now(timezone.utc).year)

    # Use per-year rate from TaxPolicy via correlated subquery.
    # Falls back to 0.02 (1% basic + 1% SEF) if no policy row exists for that year.
    rate_expr = func.coalesce(
        db_session.query(TaxPolicy.basic_rate + TaxPolicy.sef_rate)
        .filter(TaxPolicy.tax_year == PropertyBilling.tax_year)
        .correlate(PropertyBilling)
        .scalar_subquery(),
        0.02
    )

    total_due_expr = func.sum(
        (PropertyBilling.assessed_value * rate_expr)
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
        .join(PaymentBilling, PaymentBilling.payment_id == Payment.id)
        .join(PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id)
        .filter(PropertyBilling.tax_year <= selected_year)
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
        .filter(PropertyBilling.tax_year <= selected_year)
        .filter(*_compliance_property_scope(selected_year, db_session))
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

    if search and str(search).strip():
        term = str(search).strip()
        like_term = f"%{term}%"
        query = query.filter(or_(
            Property.td_number.like(like_term),
            Property.prev_td_number.like(like_term),
            Property.pin.like(like_term),
            Property.owner_name.like(like_term),
            Property.payor_name.like(like_term),
            Property.location.like(like_term),
            Property.barangay.like(like_term),
        ))

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
        "as_of_year": selected_year,
    }


def get_compliant_summary_by_barangay(
    as_of_year: int = None,
    db_session: Session = None,
):
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
    selected_year = int(as_of_year or datetime.now(timezone.utc).year)

    # Use per-year rate from TaxPolicy via correlated subquery.
    rate_expr = func.coalesce(
        db_session.query(TaxPolicy.basic_rate + TaxPolicy.sef_rate)
        .filter(TaxPolicy.tax_year == PropertyBilling.tax_year)
        .correlate(PropertyBilling)
        .scalar_subquery(),
        0.02
    )

    total_due_expr = func.sum(
        (PropertyBilling.assessed_value * rate_expr)
        + PropertyBilling.penalty
        - PropertyBilling.discount
    )
    total_paid_expr = func.sum(PropertyBilling.amount_paid)

    # All properties with billing records, grouped by property + barangay
    # to determine per-property compliance status
    per_property = (
        db_session.query(
            Property.id,
            func.trim(Property.barangay).label("barangay"),
            total_due_expr.label("total_due"),
            total_paid_expr.label("total_paid"),
        )
        .join(PropertyBilling, PropertyBilling.property_id == Property.id)
        .filter(Property.deleted_at == None)
        .filter(PropertyBilling.tax_year <= selected_year)
        .filter(*_compliance_property_scope(selected_year, db_session))
        .filter(*_assigned_barangay_filters())
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


def get_delinquent_accounts(
    limit=50,
    cursor=None,
    as_of_date=None,
    db_session: Session = None,
):
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

    current = _billing_current_amount_exprs(db_session, as_of_date)
    balance_expr = func.sum(current["balance"])

    query = db_session.query(
        Property.id,
        Property.td_number,
        Property.owner_name,
        Property.location,
        func.sum(current["total_due"]).label("total_due"),
        func.sum(current["paid"]).label("total_paid"),
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


def get_collections_worklist(
    barangay: str = None,
    search: str = None,
    payment_status: str = None,
    min_balance: float = None,
    min_age_days: int = 0,
    limit: int = 50,
    offset: int = 0,
    as_of_date=None,
    db_session: Session = None,
):
    """
    Collections worklist: delinquent properties prioritised by balance (largest
    first) with aging metadata so staff can chase the highest-value, oldest
    arrears first.

    Aging is derived from the EARLIEST billed tax year that still contributes to
    the outstanding balance. February 1 is used only as the worklist's
    operational age reference; monetary penalties come from the shared office
    penalty calculator.

    Params:
      barangay     — optional filter
      min_age_days — only include accounts at least this old (0/30/60/90/120)
      limit/offset — pagination (offset is acceptable here: the delinquent set
                     is bounded and this is an admin worklist, not a public feed)

    Returns aging buckets per row:
      CURRENT (<30d), 30, 60, 90, 120+  with a label and the computed age_days.
    """
    safe_limit = min(max(1, int(limit)), 200)
    safe_offset = max(0, int(offset))
    current = _billing_current_amount_exprs(db_session, as_of_date)
    balance_expr = func.sum(current["balance"])

    query = db_session.query(
        Property.id,
        Property.td_number,
        Property.owner_name,
        Property.location,
        func.coalesce(Property.barangay, "UNSPECIFIED").label("barangay"),
        func.sum(current["total_due"]).label("total_due"),
        func.sum(current["paid"]).label("total_paid"),
        balance_expr.label("balance"),
        func.min(PropertyBilling.tax_year).label("earliest_year"),
        func.count(PropertyBilling.id).label("years_billed"),
    ).join(
        PropertyBilling, PropertyBilling.property_id == Property.id
    ).filter(
        Property.deleted_at == None
    )

    if barangay and barangay.strip() and barangay.upper() != "ALL":
        query = query.filter(Property.barangay == barangay.strip())

    if search and str(search).strip():
        term = str(search).strip()
        like_term = f"%{term}%"
        query = query.filter(or_(
            Property.td_number.like(like_term),
            Property.prev_td_number.like(like_term),
            Property.pin.like(like_term),
            Property.owner_name.like(like_term),
            Property.payor_name.like(like_term),
            Property.location.like(like_term),
            Property.barangay.like(like_term),
        ))

    query = query.group_by(Property.id).having(balance_expr > 0)

    if min_balance is not None:
        query = query.having(balance_expr >= float(min_balance))

    status = str(payment_status or "").strip().upper()
    total_paid_expr = func.sum(current["paid"])
    if status == "NO_PAYMENT":
        query = query.having(total_paid_expr <= 0)
    elif status == "PARTIAL":
        query = query.having(total_paid_expr > 0)

    # Order by balance DESC — collections priority is biggest arrears first
    rows = query.order_by(balance_expr.desc(), Property.id.asc()).all()

    today = as_of_date or date.today()

    def _age_days(earliest_year) -> int:
        try:
            yr = int(earliest_year)
        except (ValueError, TypeError):
            return 0
        # Aging is an operational age indicator, independent of penalty months.
        start = date(yr, 2, 1)
        return max(0, (today - start).days)

    def _bucket(days: int) -> str:
        if days >= 120:
            return "120+"
        if days >= 90:
            return "90"
        if days >= 60:
            return "60"
        if days >= 30:
            return "30"
        return "CURRENT"

    enriched = []
    for r in rows:
        age = _age_days(r.earliest_year)
        if age < min_age_days:
            continue
        enriched.append({
            "id": r.id,
            "td_number": r.td_number,
            "owner_name": r.owner_name,
            "location": r.location,
            "barangay": r.barangay,
            "total_due": float(r.total_due or 0),
            "total_paid": float(r.total_paid or 0),
            "balance": float(r.balance or 0),
            "earliest_year": int(r.earliest_year) if r.earliest_year else None,
            "years_billed": int(r.years_billed or 0),
            "age_days": age,
            "aging_bucket": _bucket(age),
        })

    total_matching = len(enriched)
    page = enriched[safe_offset:safe_offset + safe_limit]

    # Summary totals across the full matching set (not just the page)
    total_balance = sum(e["balance"] for e in enriched)
    bucket_totals = {"CURRENT": 0.0, "30": 0.0, "60": 0.0, "90": 0.0, "120+": 0.0}
    for e in enriched:
        bucket_totals[e["aging_bucket"]] += e["balance"]

    return {
        "items": page,
        "count": len(page),
        "total_matching": total_matching,
        "has_more": (safe_offset + safe_limit) < total_matching,
        "next_offset": safe_offset + safe_limit if (safe_offset + safe_limit) < total_matching else None,
        "summary": {
            "delinquent_count": total_matching,
            "total_balance": round(total_balance, 2),
            "aging_totals": {k: round(v, 2) for k, v in bucket_totals.items()},
        },
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

    capped_months = min(MAX_PENALTY_MONTHS, max(0, int(months_late or 0)))
    return float(
        (Decimal(str(principal or 0)) * rate * capped_months).quantize(
            MONEY, rounding=ROUND_HALF_UP
        )
    )


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




