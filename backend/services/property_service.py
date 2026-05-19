# -*- coding: utf-8 -*-
import json
from datetime import datetime
from sqlalchemy import text, func
from sqlalchemy.orm import Session
from backend.models import Property, PropertyAssessmentHistory, PropertyBilling, Payment, AuditLog
from backend.services.auth_service import get_username, require_permission
import backend.services.billing_service as billing
import backend.services.payment_service as payment
from fastapi import HTTPException

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


def search_properties(
    term, limit=100, cursor=None, kind=None, year_start=None, year_end=None, barangay=None, db_session: Session = None
):
    """
    Enhanced search with optional filters using SQLAlchemy ORM.
    """
    query = db_session.query(Property).filter(Property.deleted_at == None)
    
    if term:
        clean_term = str(term).strip()
        if "-" in clean_term:
            query = query.filter((Property.td_number == clean_term) | (Property.pin == clean_term))
        else:
            like_term = f"%{clean_term}%"
            query = query.filter(
                (Property.td_number.like(like_term)) | 
                (Property.owner_name.like(like_term)) | 
                (Property.pin.like(like_term)) | 
                (Property.location.like(like_term))
            )
    
    if kind and kind != "ALL":
        query = query.filter(Property.kind_of_property == kind)
    
    if year_start:
        query = query.filter(Property.effectivity_date >= str(year_start))
    
    if year_end:
        query = query.filter(Property.effectivity_date <= str(year_end))
        
    if barangay and barangay != "ALL":
        query = query.filter(Property.barangay == barangay)
        
    if cursor:
        query = query.filter(Property.id < int(cursor))
        
    results = query.order_by(Property.id.desc()).limit(limit).all()
    
    return [
        (
            p.id, p.td_number, p.owner_name, p.payor_name, p.lot_number, p.area, p.location, p.kind_of_property,
            p.accountable_officer, float(p.assessed_value or 0), float(p.assessed_value or 0) * 0.01, float(p.assessed_value or 0) * 0.01,
            float(p.penalty or 0), float(p.discount or 0), float(p.assessed_value or 0) * 0.02 + float(p.penalty or 0) - float(p.discount or 0),
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


def release_all_property_locks(username, db_session: Session = None):
    """No-op. Deprecated in favor of native Optimistic Concurrency Control (OCC)."""
    pass


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
        
        prop.td_number = _up(data.get("TD Number", prop.td_number))
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
        log_data_change(user["id"] if user else 0, "properties", prop.id, action, before=before_data, after=after_data)
        
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
        if isinstance(e, (ValidationError, SyncConflictError)):
            raise
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
            billing.sync_property_billing(None, prop_id, year, a_s, p_s, d_s, has_payment=should_pay, db_session=db_session)
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
        
        db_session.flush() # Get payment_id
        billing.sync_payment_billings(None, pay_obj.id, allocated, db_session=db_session)



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
    prop.deleted_at = datetime.now()
    
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
            timestamp=datetime.now()
        )
        db_session.add(audit)
        
    db_session.commit()
    return 1


def get_deleted_properties(limit=50, offset=0, db_session: Session = None):
    """Fetches all properties marked as deleted with pagination support."""
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))
    rows = (
        db_session.query(Property)
        .filter(Property.deleted_at != None)
        .order_by(Property.id.desc())
        .limit(safe_limit)
        .offset(safe_offset)
        .all()
    )
    return [
        (
            prop.id,
            prop.td_number,
            prop.owner_name,
            prop.location,
            prop.assessed_value,
        )
        for prop in rows
    ]


@require_permission("property_edit")
def restore_property(property_id, user=None, db_session: Session = None):
    """Restores a soft-deleted property."""
    prop = db_session.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return 0
    
    prop.deleted_at = None
    
    if user:
        from datetime import datetime
        audit = AuditLog(
            user_id=user.get("id"),
            username=user.get("username", "unknown"),
            action="RESTORE",
            table_name="properties",
            record_id=property_id,
            old_values=str({"deleted_at": "deleted"}),
            new_values=str({"deleted_at": None}),
            timestamp=datetime.now()
        )
        db_session.add(audit)
        
    db_session.commit()
    return 1


@require_permission("property_delete")
def purge_property(property_id, user=None, db_session: Session = None):
    """Permanently deletes a property from the database."""
    prop = db_session.query(Property).filter(Property.id == property_id).first()
    if not prop:
        return 0
        
    full_data = {c.name: getattr(prop, c.name) for c in prop.__table__.columns}

    # Delete associated billings and payments first
    db_session.query(PropertyBilling).filter(PropertyBilling.property_id == property_id).delete()
    db_session.query(Payment).filter(Payment.property_id == property_id).delete()
    db_session.delete(prop)
    db_session.commit()

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
        count = db_session.query(Property).filter(Property.id.in_(property_ids)).update({Property.barangay: new_barangay}, synchronize_session=False)
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


def get_assessment_roll(limit=100, offset=0, db_session: Session = None):
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))
    results = db_session.query(Property).filter(Property.deleted_at == None).order_by(Property.owner_name.asc()).limit(safe_limit).offset(safe_offset).all()
    return [(p.td_number, p.owner_name, p.location, p.kind_of_property, float(p.assessed_value or 0)) for p in results]


def get_receivables_by_barangay(db_session: Session = None):
    results = (
        db_session.query(
            func.coalesce(Property.barangay, "UNSPECIFIED").label("barangay"),
            func.sum(PropertyBilling.assessed_value).label("total_assessed"),
            func.sum((PropertyBilling.assessed_value * 0.02) + PropertyBilling.penalty - PropertyBilling.discount).label("total_due"),
            func.sum(PropertyBilling.penalty).label("total_penalty"),
            func.sum(PropertyBilling.discount).label("total_discount"),
            func.sum(PropertyBilling.amount_paid).label("total_collected"),
            func.sum((PropertyBilling.assessed_value * 0.02) + PropertyBilling.penalty - PropertyBilling.discount - PropertyBilling.amount_paid).label("total_receivable")
        )
        .join(PropertyBilling, PropertyBilling.property_id == Property.id)
        .filter(Property.deleted_at == None)
        .group_by(Property.barangay)
        .order_by(text("total_receivable DESC"))
        .all()
    )
    return [tuple(r) for r in results]
