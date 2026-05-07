# -*- coding: utf-8 -*-
import db_manager as db
from backend.services.auth_service import get_username, require_permission
import backend.services.billing_service as billing
import backend.services.payment_service as payment

def clean_currency(value):
    if value is None: return 0.0
    try:
        return float(str(value).replace(",", "").strip() or 0.0)
    except (ValueError, TypeError):
        return 0.0

def search_properties(term, limit=100, offset=0, kind=None, year_start=None, year_end=None):
    """
    Enhanced search with optional filters for kind and effectivity year ranges.
    """
    clean_term = str(term).strip() if term else ""
    where_clauses = ["is_deleted = 0"]
    params = []

    # 1. Term Search
    if clean_term:
        if "-" in clean_term:
            where_clauses.append("(td_number = %s OR pin = %s)")
            params.extend([clean_term, clean_term])
        else:
            where_clauses.append("(td_number LIKE %s OR owner_name LIKE %s OR pin LIKE %s OR location LIKE %s)")
            like_term = f"%{clean_term}%"
            params.extend([like_term, like_term, like_term, like_term])

    # 2. Advanced Filters
    if kind and kind != "ALL":
        where_clauses.append("kind_of_property = %s")
        params.append(kind)
    
    if year_start:
        where_clauses.append("effectivity_date >= %s")
        params.append(year_start)
    
    if year_end:
        where_clauses.append("effectivity_date <= %s")
        params.append(year_end)

    query = f"""
        SELECT id, td_number, owner_name, payor_name, lot_number, area, location, kind_of_property,
               accountable_officer, assessed_value, (assessed_value * 0.01) as basic, (assessed_value * 0.01) as sef,
               penalty, discount, (assessed_value * 0.02 + penalty - discount) as total, or_number, or_date, tax_year,
               pin, block_number, prev_td_number, effectivity_date, barangay
        FROM properties
        WHERE {" AND ".join(where_clauses)}
        ORDER BY effectivity_date DESC, id DESC
        LIMIT %s OFFSET %s
    """
    params.extend([int(limit), int(offset)])
    return db.db_query(query, params, fetch=True, commit=False) or []

def get_property_by_id(property_id):
    query = "SELECT * FROM properties WHERE id = %s AND is_deleted = 0 LIMIT 1"
    rows = db.db_query(query, (property_id,), fetch=True, commit=False)
    if not rows: return None
    return rows[0]

def release_all_property_locks(username):
    """Clears any orphaned property locks for a user on login."""
    query = "DELETE FROM property_edit_locks WHERE locked_by = %s"
    db.db_query(query, (username,))

def save_property(data, editing_id=None, user=None):
    """Saves or Updates a property and its associated billing/payment records."""
    def save_transaction(cur):
        old_data = None
        if editing_id:
            cur.execute("SELECT * FROM properties WHERE id=%s", (editing_id,))
            old_data = cur.fetchone()

        def _up(v):
            return str(v).strip().upper() if v else None

        def get_v(key, old_idx=None):
            if key in data:
                return data.get(key)
            if old_data and old_idx is not None:
                return old_data[old_idx]
            return None

        # Prepare normalized values
        td_number = _up(get_v("TD Number", 1))
        owner_name = _up(get_v("Owner Name", 2))
        payor_name = _up(get_v("Payor", 3) or get_v("Owner Name", 2))
        lot_number = _up(get_v("Lot Number", 4))
        area = _up(get_v("Area", 5))
        location = _up(get_v("Location", 6))
        kind = _up(get_v("Type", 7) or get_v("Kind of Property", 7))
        officer = _up(get_v("Accountable Officer", 8))
        av = get_v("Assessed Value", 9)
        penalty = get_v("Penalty", 10)
        discount = get_v("Discount", 11)
        or_number = _up(get_v("OR Number", 12))
        or_date = get_v("OR Date", 13)
        tax_year = _up(get_v("Tax Year", 14))
        pin = _up(get_v("PIN", 15))
        block = _up(get_v("Block Number", 16))
        prev_td = _up(get_v("Previous TD Number", 17) or get_v("Previous TD", 17))
        eff_date = get_v("Effectivity Date", 18)
        barangay = _up(get_v("Barangay", 19) or get_v("Location", 6))

        property_params = (
            td_number, owner_name, payor_name, lot_number, area, location,
            kind, officer, clean_currency(av), clean_currency(penalty), clean_currency(discount),
            or_number, or_date, tax_year, pin, block, prev_td, eff_date, barangay
        )
        
        if editing_id:
            cur.execute(
                """
                UPDATE properties
                SET td_number=%s, owner_name=%s, payor_name=%s, lot_number=%s, area=%s, location=%s,
                    kind_of_property=%s, accountable_officer=%s, assessed_value=%s, penalty=%s, discount=%s,
                    or_number=%s, or_date=%s, tax_year=%s,
                    pin=%s, block_number=%s, prev_td_number=%s, effectivity_date=%s, barangay=%s
                WHERE id=%s
                """,
                (*property_params, editing_id),
            )
            property_id = editing_id
            
            # Audit: Get new data
            cur.execute("SELECT * FROM properties WHERE id=%s", (editing_id,))
            new_data = cur.fetchone()
            
            if user:
                db.record_audit_log_with_cur(cur, user, "UPDATE_PROPERTY", "properties", property_id, old_data, new_data)
        else:
            cur.execute(
                """
                INSERT INTO properties (
                    td_number, owner_name, payor_name, lot_number, area, location, kind_of_property,
                    accountable_officer, assessed_value, penalty, discount,
                    or_number, or_date, tax_year, 
                    pin, block_number, prev_td_number, effectivity_date, barangay,
                    is_deleted
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
                """,
                property_params,
            )
            property_id = cur.lastrowid
            if not property_id:
                cur.execute("SELECT LAST_INSERT_ID()")
                res = cur.fetchone()
                property_id = res[0] if res else None
            
            if not property_id:
                raise Exception("CRITICAL: Failed to retrieve new Property ID from database after INSERT.")
            
            # Diagnostic Log
            from utils import log_error_to_file
            log_error_to_file(f"DEBUG: New Property Created - ID: {property_id}", error=None)

            if user:
                # Convert tuple to dict for better audit logging
                new_data_dict = dict(zip([
                    "td_number", "owner_name", "payor_name", "lot_number", "area", "location", "kind_of_property",
                    "accountable_officer", "assessed_value", "penalty", "or_number", "or_date", "tax_year",
                    "pin", "block_number", "prev_td_number", "effectivity_date", "barangay"
                ], property_params))
                db.record_audit_log_with_cur(cur, user, "CREATE_PROPERTY", "properties", property_id, None, new_data_dict)

        # Sync billings & payments
        tax_years = billing.normalize_tax_years(data.get("Tax Year"))
        assessed_value = clean_currency(data.get("Assessed Value"))
        penalty_value = clean_currency(data.get("Penalty"))
        
        billing_rows = []
        assessed_shares = billing.split_amount_across_years(assessed_value, len(tax_years))
        penalty_shares = billing.split_amount_across_years(penalty_value, len(tax_years))
        discount_value = clean_currency(data.get("Discount"))
        discount_shares = billing.split_amount_across_years(discount_value, len(tax_years))
        
        should_record_payment = bool(data.get("OR Number"))
        
        for tax_year, assessed_share, penalty_share, discount_share in zip(tax_years, assessed_shares, penalty_shares, discount_shares):
            billing_rows.append(
                billing.sync_property_billing(
                    cur, property_id, tax_year, assessed_share, penalty_share, discount_share, has_payment=should_record_payment
                )
            )

        if should_record_payment:
            amount_paid = clean_currency(data.get("Amount Paid"))
            allocated_billing_rows = billing.allocate_payment_amount(billing_rows, amount_paid)
            
            cur.execute(
                "SELECT id FROM payments WHERE property_id = %s AND or_number = %s AND date_paid = %s ORDER BY id DESC LIMIT 1 FOR UPDATE",
                (property_id, data.get("OR Number"), data.get("OR Date")),
            )
            payment_row = cur.fetchone()
            
            if payment_row:
                payment_id = payment_row[0]
                cur.execute(
                    "UPDATE payments SET amount=%s, or_number=%s, date_paid=%s, tax_year=%s, posted_by=%s, payor_name=%s WHERE id=%s",
                    (amount_paid, data.get("OR Number"), data.get("OR Date"), data.get("Tax Year"), data.get("Accountable Officer"), data.get("Payor") or data.get("Owner Name"), payment_id),
                )
            else:
                cur.execute(
                    "INSERT INTO payments (property_id, amount, or_number, date_paid, tax_year, posted_by, payor_name) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (property_id, amount_paid, data.get("OR Number"), data.get("OR Date"), data.get("Tax Year"), data.get("Accountable Officer"), data.get("Payor") or data.get("Owner Name")),
                )
                cur.execute("SELECT LAST_INSERT_ID()")
                payment_id = cur.fetchone()[0]
            
            billing.sync_payment_billings(cur, payment_id, allocated_billing_rows)

        return {"ok": True, "property_id": property_id}

    return db.execute_transaction(save_transaction)

@require_permission("property_edit")
def update_property_details(prop_id, data, user):
    """Wrapper to update property details with professional permission check."""
    return save_property(data, editing_id=prop_id, user=user)

@require_permission("property_delete")
def soft_delete_property(property_id, user=None, ip_address=None):
    """Soft deletes a property - requires 'property_delete' permission."""
    old_data = get_property_by_id(property_id)
    def operation(cur):
        cur.execute("UPDATE properties SET is_deleted = 1 WHERE id = %s", (property_id,))
        return cur.rowcount
    res = db.execute_transaction(operation)
    if res and user:
        db.record_audit_log(user, "SOFT_DELETE", "properties", property_id, old_data, {"is_deleted": 1}, ip_address)
    return res

def get_deleted_properties():
    """Fetches all properties marked as deleted."""
    query = """
        SELECT id, td_number, owner_name, location, assessed_value 
        FROM properties 
        WHERE is_deleted = 1 
        ORDER BY id DESC
    """
    return db.db_query(query, fetch=True, commit=False) or []

@require_permission("property_edit")
def restore_property(property_id, user=None):
    """Restores a soft-deleted property."""
    def operation(cur):
        cur.execute("UPDATE properties SET is_deleted = 0 WHERE id = %s", (property_id,))
        return cur.rowcount
    res = db.execute_transaction(operation)
    if res and user:
        db.record_audit_log(user, "RESTORE", "properties", property_id, {"is_deleted": 1}, {"is_deleted": 0})
    return res

@require_permission("property_delete")
def purge_property(property_id, user=None):
    """Permanently deletes a property from the database."""
    old_data = get_property_by_id(property_id) # This might return None since it filters for is_deleted=0
    # Let's get it specifically for purging
    query = "SELECT * FROM properties WHERE id = %s LIMIT 1"
    raw = db.db_query(query, (property_id,), fetch=True, dictionary=True)
    full_data = raw[0] if raw else None

    def operation(cur):
        # Delete associated billings and payments first if needed (cascade or manual)
        # Assuming database has cascade or we handle it here
        cur.execute("DELETE FROM property_billings WHERE property_id = %s", (property_id,))
        cur.execute("DELETE FROM payments WHERE property_id = %s", (property_id,))
        cur.execute("DELETE FROM properties WHERE id = %s", (property_id,))
        return cur.rowcount
    
    res = db.execute_transaction(operation)
    if res and user:
        db.record_audit_log(user, "PURGE", "properties", property_id, full_data, None)
    return res

def get_unspecified_properties():
    """Fetches all properties where barangay is NULL, empty, or 'UNSPECIFIED'."""
    query = """
        SELECT id, td_number, owner_name, location, barangay
        FROM properties
        WHERE is_deleted = 0 
          AND (barangay IS NULL OR TRIM(barangay) = '' OR barangay = 'UNSPECIFIED')
        ORDER BY owner_name ASC
    """
    return db.db_query(query, fetch=True, commit=False) or []

@require_permission("property_edit")
def bulk_update_barangay(property_ids, new_barangay, user=None):
    """Updates the barangay for multiple properties at once."""
    if not property_ids or not new_barangay:
        return 0
        
    def operation(cur):
        placeholders = ', '.join(['%s'] * len(property_ids))
        query = f"UPDATE properties SET barangay = %s WHERE id IN ({placeholders})"
        params = [new_barangay] + list(property_ids)
        cur.execute(query, params)
        return cur.rowcount
        
    res = db.execute_transaction(operation)
    if res and user:
        db.record_audit_log(user, "BULK_UPDATE", "properties", None, {"ids": property_ids}, {"barangay": new_barangay})
    return res

def get_property_by_td(td_number):
    query = "SELECT * FROM properties WHERE td_number = %s AND is_deleted = 0 LIMIT 1"
    res = db.db_query(query, (td_number,), fetch=True, dictionary=True)
    return res[0] if res else None

def get_assessment_roll():
    query = "SELECT td_number, owner_name, location, kind_of_property, assessed_value FROM properties WHERE is_deleted = 0 ORDER BY owner_name ASC"
    return db.db_query(query, fetch=True, commit=False) or []

def get_receivables_by_barangay():
    query = """
        SELECT 
            COALESCE(prop.barangay, 'UNSPECIFIED') as barangay,
            SUM(bill.assessed_value) as total_assessed,
            SUM((bill.assessed_value * 0.02) + bill.penalty - bill.discount) as total_due,
            SUM(bill.penalty) as total_penalty,
            SUM(bill.discount) as total_discount,
            SUM(bill.amount_paid) as total_collected,
            SUM((bill.assessed_value * 0.02) + bill.penalty - bill.discount - bill.amount_paid) as total_receivable
        FROM properties prop
        JOIN property_billings bill ON bill.property_id = prop.id
        WHERE prop.is_deleted = 0
        GROUP BY prop.barangay
        ORDER BY total_receivable DESC
    """
    return db.db_query(query, fetch=True, commit=False) or []
