# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone
from sqlalchemy import text, func, cast, Integer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased
from backend.models import Property, PropertyAssessmentHistory, PropertyBilling, Payment, AuditLog, TaxPolicy
from backend.services.auth_service import get_username, require_permission
import backend.services.billing_service as billing
import backend.services.payment_service as payment
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Tax rate helpers for Python-side calculations (search result formatting).
# These cache the policy lookup per-session to avoid N+1 queries.
# ---------------------------------------------------------------------------
_rate_cache: dict = {}


def _get_policy_rates(tax_year_str, db_session: Session):
    """Returns (basic_rate, sef_rate) for a given tax year, with caching."""
    if not tax_year_str or not db_session:
        return (0.01, 0.01)
    # Parse the first year from multi-year strings like "2023, 2024"
    try:
        year_val = int(str(tax_year_str).strip().split(",")[0].split("-")[0].strip())
    except (ValueError, TypeError):
        return (0.01, 0.01)

    cache_key = id(db_session)
    if cache_key not in _rate_cache:
        _rate_cache[cache_key] = {}
    if year_val in _rate_cache[cache_key]:
        return _rate_cache[cache_key][year_val]

    policy = db_session.query(TaxPolicy).filter(TaxPolicy.tax_year == year_val).first()
    if policy:
        rates = (float(policy.basic_rate), float(policy.sef_rate))
    else:
        rates = (0.01, 0.01)
    _rate_cache[cache_key][year_val] = rates
    return rates


def _get_basic_rate(prop, db_session):
    basic, _ = _get_policy_rates(prop.tax_year, db_session)
    return basic


def _get_sef_rate(prop, db_session):
    _, sef = _get_policy_rates(prop.tax_year, db_session)
    return sef


def _get_total_rate(prop, db_session):
    basic, sef = _get_policy_rates(prop.tax_year, db_session)
    return basic + sef

class SyncConflictError(Exception):
    """Custom exception raised when a version mismatch is detected during save."""
    def __init__(self, server_data, client_data):
        self.server_data = server_data
        self.client_data = client_data
        self.is_sync_conflict = True # Marker for cross-module identification
        super().__init__("Offline Sync Conflict Detected.")


def clean_currency(value):
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").strip() or 0.0)
    except (ValueError, TypeError):
        return 0.0


def _effectivity_year_expr(model):
    year_source = func.coalesce(func.nullif(func.trim(model.effectivity_date), ""), model.tax_year)
    return cast(func.substr(year_source, 1, 4), Integer)


def search_properties(
    term, limit=100, cursor=None, kind=None, year_start=None, year_end=None,
    as_of_year=None, barangay=None, db_session: Session = None
):
    """
    Enhanced search with optional filters and fuzzy owner-name matching.

    Search strategy:
      - TD number / PIN (contains dashes or is all-digits): exact SQL match only.
        Fuzzy matching on structured identifiers produces false positives.
      - Owner name / location (contains letters, no dashes): SQL LIKE for
        candidate retrieval, then Python-side fuzzy re-ranking using
        difflib.SequenceMatcher. This catches typos, missing spaces, and
        slight misspellings without any new dependencies.

    Fuzzy threshold: 0.55 similarity ratio (0–1 scale).
      - "dela crus" vs "DELA CRUZ"  → ~0.89 ✅
      - "delacrus"  vs "DELA CRUZ"  → ~0.72 ✅
      - "juan"      vs "JUAN DELA CRUZ" → ~0.44 ❌ (too short, use LIKE instead)
    Results are sorted by similarity score descending so the best match
    appears first.
    """
    import difflib

    query = db_session.query(Property).filter(Property.deleted_at == None)

    # Determine search mode from the term
    is_id_search = False
    if term:
        clean_term = str(term).strip()
        if " " in clean_term and not any(c.isalpha() for c in clean_term):
            # Looks like a spaced TD number — convert spaces to dashes
            dashed_term = clean_term.replace(" ", "-")
            query = query.filter(
                (Property.td_number == dashed_term) |
                (Property.pin == dashed_term) |
                (Property.prev_td_number == dashed_term) |
                (Property.td_number.like(f"%{dashed_term}%")) |
                (Property.pin.like(f"%{dashed_term}%")) |
                (Property.prev_td_number.like(f"%{dashed_term}%"))
            )
            is_id_search = True
        elif "-" in clean_term:
            # Structured TD number / PIN — exact match only
            query = query.filter(
                (Property.td_number == clean_term) |
                (Property.pin == clean_term) |
                (Property.prev_td_number == clean_term)
            )
            is_id_search = True
        else:
            # Name / location search — broad LIKE to pull candidates, then fuzzy-rank
            like_term = f"%{clean_term}%"
            query = query.filter(
                (Property.td_number.like(like_term)) |
                (Property.prev_td_number.like(like_term)) |
                (Property.owner_name.like(like_term)) |
                (Property.payor_name.like(like_term)) |
                (Property.pin.like(like_term)) |
                (Property.location.like(like_term))
            )

    if kind and kind != "ALL":
        query = query.filter(Property.kind_of_property == kind)

    if as_of_year:
        as_of = int(as_of_year)
        effectivity_year = _effectivity_year_expr(Property)
        replacement = aliased(Property)
        replacement_effectivity_year = _effectivity_year_expr(replacement)
        replaced_td_numbers = (
            db_session.query(func.trim(replacement.prev_td_number))
            .filter(
                replacement.deleted_at == None,
                replacement.prev_td_number != None,
                func.trim(replacement.prev_td_number) != "",
                replacement_effectivity_year <= as_of,
            )
            .scalar_subquery()
        )
        query = query.filter(effectivity_year <= as_of)
        query = query.filter(~func.trim(Property.td_number).in_(replaced_td_numbers))
    elif year_start or year_end:
        # effectivity_date is legacy text and may contain either "2024" or
        # full dates like "2024-01-01". Compare on the extracted year so the
        # "TO" filter includes full dates within that year.
        effectivity_year = _effectivity_year_expr(Property)
        if year_start:
            query = query.filter(effectivity_year >= int(year_start))
        if year_end:
            query = query.filter(effectivity_year <= int(year_end))

    if barangay and barangay != "ALL":
        query = query.filter(Property.barangay == barangay)

    if cursor:
        query = query.filter(Property.id < int(cursor))

    # Fetch a larger candidate pool when fuzzy matching will be applied so
    # we have enough results to rank before trimming to the requested limit.
    fetch_limit = limit if is_id_search or not term else min(limit * 4, 400)
    results = query.order_by(Property.id.desc()).limit(fetch_limit).all()

    # ── Fuzzy re-ranking for name searches ──────────────────────────────────
    # Only apply when the term contains letters and is not a structured ID.
    FUZZY_THRESHOLD = 0.55

    if term and not is_id_search and any(c.isalpha() for c in str(term).strip()):
        search_upper = str(term).strip().upper()

        def _score(prop) -> float:
            """
            Returns the best similarity ratio across the searchable text fields.
            Uses SequenceMatcher which handles insertions, deletions, and
            substitutions — good for name typos and missing spaces.
            """
            candidates = [
                prop.owner_name or "",
                prop.payor_name or "",
                prop.location or "",
                prop.td_number or "",
                prop.prev_td_number or "",
            ]
            if any(search_upper in c.upper() for c in candidates):
                return 1.0
            return max(
                difflib.SequenceMatcher(None, search_upper, c.upper()).ratio()
                for c in candidates
            )

        scored = [(p, _score(p)) for p in results]
        # Keep only results above the threshold, sorted best-first
        scored = [(p, s) for p, s in scored if s >= FUZZY_THRESHOLD]
        scored.sort(key=lambda x: x[1], reverse=True)
        results = [p for p, _ in scored[:limit]]
    else:
        results = results[:limit]

    return [
        (
            p.id, p.td_number, p.owner_name, p.payor_name, p.lot_number, p.area, p.location, p.kind_of_property,
            p.accountable_officer, float(p.assessed_value or 0),
            float(p.assessed_value or 0) * _get_basic_rate(p, db_session),
            float(p.assessed_value or 0) * _get_sef_rate(p, db_session),
            float(p.penalty or 0), float(p.discount or 0),
            float(p.assessed_value or 0) * _get_total_rate(p, db_session) + float(p.penalty or 0) - float(p.discount or 0),
            p.or_number, p.or_date, p.tax_year, p.pin, p.block_number, p.prev_td_number, p.effectivity_date, p.barangay
        )
        for p in results
    ]


def get_barangays(db_session: Session):
    """Returns a list of all unique barangay names in the database."""
    results = db_session.query(Property.barangay).filter(Property.barangay != None, Property.barangay != "").distinct().order_by(Property.barangay.asc()).all()
    return [r[0] for r in results]


def get_property_by_id(property_id, db_session: Session):
    return db_session.query(Property).filter(Property.id == property_id, Property.deleted_at == None).first()


def save_property(data, editing_id=None, user=None, db_session: Session = None):
    """
    Main orchestrator for saving or updating a property using ORM.
    """
    from backend.services.validation_service import enforce_property_rules, ValidationError
    from backend.services.history_service import log_data_change
    
    try:
        # 1. Validate
        enforce_property_rules(data)
        
        # 2. Get or Create Property
        if editing_id:
            prop = db_session.query(Property).filter(Property.id == editing_id).first()
            if not prop:
                raise HTTPException(status_code=404, detail="Property not found")
            
            # Conflict Detection
            client_version = data.get("version", 0)
            if client_version is not None and int(client_version) < prop.version:
                raise SyncConflictError(prop.__dict__, data)
            
            action = "UPDATE"
            before_data = {c.name: getattr(prop, c.name) for c in prop.__table__.columns}
        else:
            prop = Property()
            db_session.add(prop)
            action = "CREATE"
            before_data = None

        # 3. Map Fields (Normalize)
        def _up(v): return str(v).strip().upper() if v else None

        new_td_number = _up(data.get("TD Number", prop.td_number))
        duplicate_query = db_session.query(Property).filter(Property.td_number == new_td_number)
        if prop.id:
            duplicate_query = duplicate_query.filter(Property.id != prop.id)
        duplicate = duplicate_query.first()
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"TD Number {new_td_number} is already used by property "
                    f"ID {duplicate.id}: {duplicate.owner_name}"
                ),
            )

        prop.td_number = new_td_number
        prop.owner_name = _up(data.get("Owner Name", prop.owner_name))
        prop.payor_name = _up(data.get("Payor", prop.payor_name) or data.get("Owner Name", prop.owner_name))
        prop.lot_number = _up(data.get("Lot Number", prop.lot_number))
        prop.area = _up(data.get("Area", prop.area))
        prop.location = _up(data.get("Location", prop.location))
        prop.kind_of_property = _up(data.get("Kind of Property", prop.kind_of_property))
        prop.accountable_officer = _up(data.get("Accountable Officer", prop.accountable_officer))
        prop.assessed_value = clean_currency(data.get("Assessed Value", prop.assessed_value))
        prop.penalty = clean_currency(data.get("Penalty", prop.penalty))
        prop.discount = clean_currency(data.get("Discount", prop.discount))
        prop.or_number = _up(data.get("OR Number", prop.or_number))
        prop.or_date = data.get("OR Date", prop.or_date)
        prop.tax_year = _up(data.get("Tax Year", prop.tax_year))
        prop.pin = _up(data.get("PIN", prop.pin))
        prop.block_number = _up(data.get("Block Number", prop.block_number))
        prop.prev_td_number = _up(data.get("Previous TD Number", prop.prev_td_number))
        prop.effectivity_date = data.get("Effectivity Date", prop.effectivity_date)
        prop.barangay = _up(data.get("Barangay", prop.barangay) or data.get("Location", prop.location))
        
        if editing_id:
            prop.version += 1
        else:
            prop.version = 1
            prop.deleted_at = None

        db_session.flush() # Get ID for new properties
        
        # 4. Log Change
        after_data = {c.name: getattr(prop, c.name) for c in prop.__table__.columns}
        log_data_change(
            user["id"] if user else 0,
            "properties",
            prop.id,
            action,
            before=before_data,
            after=after_data,
            username=get_username(user) if user else "unknown",
            db_session=db_session,
        )
        
        # 5. Financial Sync
        _sync_financial_records(prop.id, data, db_session)
        
        db_session.commit()
        return {
            "ok": True,
            "property_id": prop.id,
            "new_version": prop.version
        }

    except Exception as e:
        db_session.rollback()
        if isinstance(e, (HTTPException, ValidationError, SyncConflictError)):
            raise
        if isinstance(e, IntegrityError) and "uq_properties_td_number" in str(e):
            raise HTTPException(
                status_code=409,
                detail="TD Number is already used by another property.",
            )
        raise HTTPException(status_code=500, detail=f"Save failed: {str(e)}")


def _sync_financial_records(prop_id, data, db_session: Session):
    """Synchronizes property billings and payments based on the saved property data."""
    tax_years = billing.normalize_tax_years(data.get("Tax Year"))
    av = clean_currency(data.get("Assessed Value"))
    pen = clean_currency(data.get("Penalty"))
    disc = clean_currency(data.get("Discount"))
    
    # Split amounts across multiple years if applicable
    av_shares = billing.split_amount_across_years(av, len(tax_years))
    pen_shares = billing.split_amount_across_years(pen, len(tax_years))
    disc_shares = billing.split_amount_across_years(disc, len(tax_years))
    
    should_pay = bool(data.get("OR Number"))
    billing_rows = []
    
    for year, a_s, p_s, d_s in zip(tax_years, av_shares, pen_shares, disc_shares):
        billing_rows.append(
            billing.sync_property_billing(prop_id, year, a_s, p_s, d_s, has_payment=should_pay, db_session=db_session)
        )
        
    if should_pay:
        paid = clean_currency(data.get("Amount Paid"))
        allocated = billing.allocate_payment_amount(billing_rows, paid)
        
        # Upsert payment record using ORM
        from backend.models import Payment
        or_no = data.get("OR Number")
        or_dt_raw = data.get("OR Date")
        
        # Parse or_date if it's a string
        or_dt = None
        if or_dt_raw:
            if isinstance(or_dt_raw, str):
                try:
                    or_dt = datetime.strptime(or_dt_raw, "%Y-%m-%d")
                except ValueError:
                    # or_date string is not in expected format; leave or_dt as None
                    pass
            elif isinstance(or_dt_raw, datetime):
                or_dt = or_dt_raw

        pay_obj = db_session.query(Payment).filter(
            Payment.property_id == prop_id,
            Payment.or_number == or_no,
            Payment.date_paid == or_dt
        ).order_by(Payment.id.desc()).first()
        
        payor_name = data.get("Payor") or data.get("Owner Name")
        tax_year_str = data.get("Tax Year")
        posted_by = data.get("Accountable Officer")

        if not pay_obj:
            pay_obj = Payment(property_id=prop_id)
            db_session.add(pay_obj)
            
        pay_obj.amount = paid
        pay_obj.or_number = or_no
        pay_obj.date_paid = or_dt
        pay_obj.tax_year = tax_year_str
        pay_obj.posted_by = posted_by
        pay_obj.payor_name = payor_name
        pay_obj.penalty = pen    # store penalty on Payment record
        pay_obj.discount = disc  # store discount on Payment record
        
        db_session.flush() # Get payment_id
        billing.sync_payment_billings(pay_obj.id, allocated, db_session=db_session)



@require_permission("property_edit")
def update_property_details(prop_id, data, user):
    """Wrapper to update property details with professional permission check."""
    return save_property(data, editing_id=prop_id, user=user)


@require_permission("property_delete")
def soft_delete_property(property_id, user=None, ip_address=None, db_session: Session = None):
    """Soft deletes a property - requires 'property_delete' permission."""
    prop = db_session.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return 0
    
    old_data = {c.name: getattr(prop, c.name) for c in prop.__table__.columns}
    prop.deleted_at = datetime.now(timezone.utc)
    
    if user:
        audit = AuditLog(
            user_id=user.get("id"),
            username=user.get("username", "unknown"),
            action="SOFT_DELETE",
            table_name="properties",
            record_id=property_id,
            old_values=json.dumps(old_data, default=str),
            new_values=json.dumps({"deleted_at": prop.deleted_at.isoformat() if hasattr(prop.deleted_at, "isoformat") else str(prop.deleted_at)}),
            ip_address=ip_address,
            timestamp=datetime.now(timezone.utc)
        )
        db_session.add(audit)
        
    db_session.commit()
    return 1


def get_deleted_properties(limit=50, cursor=None, db_session: Session = None):
    """Fetches soft-deleted properties using cursor-based pagination."""
    safe_limit = min(max(1, int(limit)), 200)

    query = db_session.query(Property).filter(Property.deleted_at != None)
    if cursor:
        query = query.filter(Property.id < int(cursor))

    rows = query.order_by(Property.id.desc()).limit(safe_limit + 1).all()

    has_more = len(rows) > safe_limit
    items = rows[:safe_limit]
    next_cursor = items[-1].id if has_more and items else None

    return {
        "items": [
            (prop.id, prop.td_number, prop.owner_name, prop.location, prop.assessed_value)
            for prop in items
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items),
    }


@require_permission("property_edit")
def restore_property(property_id, user=None, db_session: Session = None):
    """Restores a soft-deleted property."""
    prop = db_session.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return 0
    
    prop.deleted_at = None
    
    if user:
        from datetime import datetime, timezone
        audit = AuditLog(
            user_id=user.get("id"),
            username=user.get("username", "unknown"),
            action="RESTORE",
            table_name="properties",
            record_id=property_id,
            old_values=str({"deleted_at": "deleted"}),
            new_values=str({"deleted_at": None}),
            timestamp=datetime.now(timezone.utc)
        )
        db_session.add(audit)
        
    db_session.commit()
    return 1


@require_permission("property_delete")
def purge_property(property_id, user=None, db_session: Session = None):
    """
    Permanently deletes a property and ALL its child records from the database.

    Deletion order matters — FK constraints with RESTRICT must be satisfied:
      1. payment_billings  (FK → payments.id CASCADE, but delete explicitly first)
      2. receipt_history   (FK → properties.id RESTRICT)
      3. property_assessment_history (FK → properties.id RESTRICT)
      4. property_billings (FK → properties.id RESTRICT)
      5. payments          (FK → properties.id RESTRICT)
      6. property          (the record itself)
    """
    from backend.models import (
        PaymentBilling, ReceiptHistory, PropertyAssessmentHistory
    )

    prop = db_session.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return 0

    full_data = {c.name: getattr(prop, c.name) for c in prop.__table__.columns}

    try:
        # 1. payment_billings — must go before payments
        payment_ids = [
            r[0] for r in db_session.query(Payment.id)
            .filter(Payment.property_id == property_id).all()
        ]
        if payment_ids:
            db_session.query(PaymentBilling).filter(
                PaymentBilling.payment_id.in_(payment_ids)
            ).delete(synchronize_session=False)

        # 2. receipt_history
        db_session.query(ReceiptHistory).filter(
            ReceiptHistory.property_id == property_id
        ).delete(synchronize_session=False)

        # 3. property_assessment_history
        db_session.query(PropertyAssessmentHistory).filter(
            PropertyAssessmentHistory.property_id == property_id
        ).delete(synchronize_session=False)

        # 4. property_billings
        db_session.query(PropertyBilling).filter(
            PropertyBilling.property_id == property_id
        ).delete(synchronize_session=False)

        # 5. payments
        db_session.query(Payment).filter(
            Payment.property_id == property_id
        ).delete(synchronize_session=False)

        # 6. the property itself
        db_session.delete(prop)
        db_session.flush()

        # Audit log
        if user:
            from backend.services.history_service import log_data_change
            log_data_change(
                user_id=user.get("id") if isinstance(user, dict) else 0,
                username=get_username(user),
                table_name="properties",
                record_id=property_id,
                action="PURGE",
                before=full_data,
                after=None,
                db_session=db_session,
            )

        db_session.commit()
        return 1

    except Exception:
        db_session.rollback()
        raise

    if user:
        from backend.services.history_service import log_data_change
        log_data_change(
            user_id=user.get("id") if isinstance(user, dict) else 0,
            username=get_username(user),
            table_name="properties",
            record_id=property_id,
            action="PURGE",
            before=full_data,
            after=None,
            db_session=db_session
        )
    return 1


def get_unspecified_properties(db_session: Session = None):
    """Fetches all properties where barangay is NULL, empty, or 'UNSPECIFIED'."""
    results = db_session.query(Property).filter(
        Property.deleted_at == None,
        (Property.barangay == None) | (text("TRIM(barangay) = ''")) | (Property.barangay == "UNSPECIFIED")
    ).order_by(Property.owner_name.asc()).all()

    return [
        (p.id, p.td_number, p.owner_name, p.location, p.barangay)
        for p in results
    ]


@require_permission("property_edit")
def bulk_update_barangay(property_ids, new_barangay, user=None, db_session: Session = None):
    """Updates the barangay for multiple properties at once."""
    if not property_ids or not new_barangay:
        return 0
    count = db_session.query(Property).filter(Property.id.in_(property_ids)).update(
        {Property.barangay: new_barangay}, synchronize_session=False
    )
    db_session.commit()

    if count and user:
        from backend.services.history_service import log_data_change
        log_data_change(
            user_id=user.get("id") if isinstance(user, dict) else 0,
            username=get_username(user),
            table_name="properties",
            record_id=0,
            action="BULK_UPDATE_BARANGAY",
            before={"ids": property_ids},
            after={"barangay": new_barangay},
            db_session=db_session
        )
    return count


def get_property_by_td(td_number, db_session: Session = None):
    prop = db_session.query(Property).filter(Property.td_number == td_number, Property.deleted_at == None).first()
    if not prop:
        return None
    return {c.name: getattr(prop, c.name) for c in prop.__table__.columns}


def get_assessment_roll(limit=100, cursor=None, db_session: Session = None):
    """
    Returns a paginated assessment roll using cursor-based pagination.
    Cursor is the last seen Property.id — avoids OFFSET degradation on large tables.
    """
    safe_limit = min(max(1, int(limit)), 200)  # hard cap at 200

    query = db_session.query(
        Property.id,
        Property.td_number,
        Property.owner_name,
        Property.location,
        Property.kind_of_property,
        Property.assessed_value,
        Property.barangay,
    ).filter(Property.deleted_at == None)

    if cursor:
        query = query.filter(Property.id > int(cursor))

    # Fetch one extra row to determine if there are more pages
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
                "kind_of_property": r[4],
                "assessed_value": float(r[5] or 0),
                "barangay": r[6],
            }
            for r in items
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(items),
    }


def get_receivables_by_barangay(report_year: int = None, data_start_year: int = 2023, db_session: Session = None):
    """
    Returns receivables breakdown by barangay.

    Parameters
    ----------
    report_year : int, optional
        Show cumulative receivables up to and including this year.
        If None, shows all-time totals.
    data_start_year : int
        The earliest year to include in the report. Defaults to 2023.
        Billing records before this year (created by the sync from old
        effectivity_date values) are excluded.
    """
    close_session = False
    if not db_session:
        from backend.database import SessionLocal
        db_session = SessionLocal()
        close_session = True

    try:
        from backend.models import Payment, PaymentBilling

        year_filter = str(report_year) if report_year else None

        # 1. Total Due per barangay — sum all billing records up to report_year
        # Join TaxPolicy per billing year so the rate reflects any policy changes.
        # Uses COALESCE to fall back to 1%+1%=2% if no policy row exists for a year.
        from backend.models import TaxPolicy as _TaxPolicy
        tp_alias = db_session.query(_TaxPolicy).subquery()

        due_query = (
            db_session.query(
                func.coalesce(Property.barangay, "UNSPECIFIED").label("barangay"),
                func.sum(PropertyBilling.assessed_value).label("total_assessed"),
                func.sum(
                    (PropertyBilling.assessed_value *
                     func.coalesce(
                         db_session.query(_TaxPolicy.basic_rate + _TaxPolicy.sef_rate)
                         .filter(_TaxPolicy.tax_year == PropertyBilling.tax_year)
                         .correlate(PropertyBilling)
                         .scalar_subquery(),
                         0.02
                     ))
                    + PropertyBilling.penalty
                    - PropertyBilling.discount
                ).label("total_due"),
                func.sum(PropertyBilling.penalty).label("total_penalty"),
                func.sum(PropertyBilling.discount).label("total_discount"),
            )
            .join(PropertyBilling, PropertyBilling.property_id == Property.id)
            .filter(Property.deleted_at == None)
        )
        if year_filter:
            due_query = due_query.filter(PropertyBilling.tax_year <= year_filter)
        # Always apply the data start year floor to exclude pre-data billing records
        due_query = due_query.filter(PropertyBilling.tax_year >= str(data_start_year))

        due_results = due_query.group_by(Property.barangay).all()

        # 2. Total Collected per barangay — sum payments where date_paid falls
        # within the selected year range. Uses cast to Date for reliable comparison
        # and explicitly excludes NULL date_paid rows.
        from sqlalchemy import cast
        from datetime import date as pydate

        coll_query = (
            db_session.query(
                func.coalesce(Property.barangay, "UNSPECIFIED").label("barangay"),
                func.sum(Payment.amount).label("total_collected"),
            )
            .join(Property, Property.id == Payment.property_id)
            .filter(
                Property.deleted_at == None,
                Payment.date_paid != None,  # exclude null dates
            )
        )
        if year_filter:
            # Use a direct date boundary comparison — more reliable than
            # extract(year) which can behave inconsistently across DB drivers.
            # "Payments made on or before Dec 31 of the selected year"
            year_end = pydate(int(year_filter), 12, 31)
            coll_query = coll_query.filter(Payment.date_paid <= year_end)
        # Also apply data_start_year floor to collections
        year_start = pydate(data_start_year, 1, 1)
        coll_query = coll_query.filter(Payment.date_paid >= year_start)

        coll_results = coll_query.group_by(Property.barangay).all()

        # Merge into a single dict keyed by barangay
        data = {}
        for r in due_results:
            brgy = r[0] or "UNSPECIFIED"
            data[brgy] = {
                "barangay": brgy,
                "total_assessed": float(r[1] or 0),
                "total_due": float(r[2] or 0),
                "total_penalty": float(r[3] or 0),
                "total_discount": float(r[4] or 0),
                "total_collected": 0.0,
            }

        for r in coll_results:
            brgy = r[0] or "UNSPECIFIED"
            if brgy not in data:
                data[brgy] = {
                    "barangay": brgy,
                    "total_assessed": 0.0,
                    "total_due": 0.0,
                    "total_penalty": 0.0,
                    "total_discount": 0.0,
                    "total_collected": 0.0,
                }
            data[brgy]["total_collected"] = float(r[1] or 0)

        # Build result tuples: (brgy, assessed, due, penalty, discount, collected, receivable)
        results = []
        for brgy, d in sorted(
            data.items(),
            key=lambda x: x[1]["total_due"] - x[1]["total_discount"] - x[1]["total_collected"],
            reverse=True
        ):
            # Correct formula: Total Due already has discount subtracted in the SQL
            # (assessed*0.02 + penalty - discount), so receivable = total_due - collected
            # BUT total_due in the query is: (assessed*0.02) + penalty - discount
            # so discount is already baked in. The displayed "Total Discount" column
            # is informational. Receivable = total_due - total_collected is correct.
            # However the sort should use the same formula for consistency.
            receivable = d["total_due"] - d["total_collected"]
            results.append((
                brgy,
                d["total_assessed"],
                d["total_due"],
                d["total_penalty"],
                d["total_discount"],
                d["total_collected"],
                receivable,
            ))

        return results

    finally:
        if close_session:
            db_session.close()
