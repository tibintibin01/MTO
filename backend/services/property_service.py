# -*- coding: utf-8 -*-
import db_manager as db
from backend.services.auth_service import get_username, require_permission
import backend.services.billing_service as billing
import backend.services.payment_service as payment

class SyncConflictError(Exception):
    """Custom exception raised when a version mismatch is detected during save."""
    def __init__(self, server_data, client_data):
        self.server_data = server_data
        self.client_data = client_data
        super().__init__("Offline Sync Conflict Detected.")


def clean_currency(value):
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").strip() or 0.0)
    except (ValueError, TypeError):
        return 0.0


def search_properties(
    term, limit=100, cursor=None, kind=None, year_start=None, year_end=None, barangay=None
):
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
            where_clauses.append(
                "(td_number LIKE %s OR owner_name LIKE %s OR pin LIKE %s OR location LIKE %s)"
            )
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

    if barangay and barangay != "ALL":
        where_clauses.append("barangay = %s")
        params.append(barangay)

    # 3. Cursor Pagination (Performance Injection)
    if cursor:
        where_clauses.append("id < %s")
        params.append(int(cursor))

    query = f"""
        SELECT id, td_number, owner_name, payor_name, lot_number, area, location, kind_of_property,
               accountable_officer, assessed_value, (assessed_value * 0.01) as basic, (assessed_value * 0.01) as sef,
               penalty, discount, (assessed_value * 0.02 + penalty - discount) as total, or_number, or_date, tax_year,
               pin, block_number, prev_td_number, effectivity_date, barangay
        FROM properties
        WHERE {" AND ".join(where_clauses)}
        ORDER BY id DESC
        LIMIT %s
    """
    params.append(int(limit))
    return db.db_query(query, params, fetch=True, commit=False) or []


def get_barangays():
    """Returns a list of all unique barangay names in the database."""
    query = "SELECT DISTINCT barangay FROM properties WHERE barangay IS NOT NULL AND barangay != '' ORDER BY barangay ASC"
    rows = db.db_query(query, fetch=True, commit=False)
    return [r[0] for r in rows] if rows else []


def get_property_by_id(property_id):
    query = "SELECT * FROM properties WHERE id = %s AND is_deleted = 0 LIMIT 1"
    rows = db.db_query(query, (property_id,), fetch=True, commit=False)
    if not rows:
        return None
    return rows[0]


def release_all_property_locks(username):
    """Clears any orphaned property locks for a user on login."""
    query = "DELETE FROM property_edit_locks WHERE locked_by = %s"
    db.db_query(query, (username,))


def save_property(data, editing_id=None, user=None):
    """
    Main orchestrator for saving or updating a property.
    Refactored into single-responsibility helpers.
    """
    def transaction_wrapper(cur):
        # 1. Validate Business Rules
        from backend.services.validation_service import enforce_property_rules, ValidationError
        try:
            enforce_property_rules(data)
        except ValidationError as e:
            # We can re-raise as HTTPException in main.py, or handle here
            raise Exception(f"VALIDATION_ERROR: {str(e)}")

        # 2. Normalize and Prepare Data
        params = _prepare_property_params(data, editing_id, cur)
        
        # 3. Perform DB Upsert
        client_version = data.get("version", 0)
        prop_id, old_data = _upsert_property_record(cur, params, editing_id, client_version)
        
        # 4. Detailed Audit Log (with Snapshots)
        from backend.services.history_service import log_data_change
        action = "UPDATE" if editing_id else "CREATE"
        
        # Convert tuple params to dict for history
        col_names = ["td_number", "owner_name", "payor_name", "lot_number", "area", "location", "kind_of_property", 
                     "accountable_officer", "assessed_value", "penalty", "discount", "or_number", "or_date", 
                     "tax_year", "pin", "block_number", "prev_td_number", "effectivity_date", "barangay"]
        after_data = dict(zip(col_names, params))
        
        # Map old_data tuple to dict if present
        before_data = None
        if old_data:
            # Note: properties table has id as index 0, so we skip it
            before_data = dict(zip(col_names, old_data[1:20]))
            
        log_data_change(user["id"] if user else 0, "properties", prop_id, action, before=before_data, after=after_data)
        
        # 5. Synchronize Billings and Payments
        _sync_financial_records(cur, prop_id, data)
        
        return {"ok": True, "property_id": prop_id}

    return db.execute_transaction(transaction_wrapper)


def _prepare_property_params(data, editing_id, cur):
    """Normalizes and prepares parameters for the SQL query."""
    old_data = None
    if editing_id:
        cur.execute("SELECT * FROM properties WHERE id=%s", (editing_id,))
        old_data = cur.fetchone()

    def _up(v):
        return str(v).strip().upper() if v else None

    def get_v(key, old_idx=None):
        if key in data: return data.get(key)
        return old_data[old_idx] if old_data and old_idx is not None else None

    return (
        _up(get_v("TD Number", 1)),
        _up(get_v("Owner Name", 2)),
        _up(get_v("Payor", 3) or get_v("Owner Name", 2)),
        _up(get_v("Lot Number", 4)),
        _up(get_v("Area", 5)),
        _up(get_v("Location", 6)),
        _up(get_v("Kind of Property", 7)),
        _up(get_v("Accountable Officer", 8)),
        clean_currency(get_v("Assessed Value", 9)),
        clean_currency(get_v("Penalty", 10)),
        clean_currency(get_v("Discount", 11)),
        _up(get_v("OR Number", 12)),
        get_v("OR Date", 13),
        _up(get_v("Tax Year", 14)),
        _up(get_v("PIN", 15)),
        _up(get_v("Block Number", 16)),
        _up(get_v("Previous TD Number", 17)),
        get_v("Effectivity Date", 18),
        _up(get_v("Barangay", 19) or get_v("Location", 6)),
    )


def _upsert_property_record(cur, params, editing_id, client_version=None):
    """Handles the actual SQL INSERT/UPDATE with conflict detection."""
    old_data = None
    if editing_id:
        cur.execute("SELECT * FROM properties WHERE id=%s", (editing_id,))
        old_data = cur.fetchone()
        
        if not old_data:
            raise Exception("Record not found for update.")

        # CONFLICT DETECTION (Optimistic Locking)
        # properties index for version (after migration) should be at the end
        # We need to find the correct index for 'version'
        # To be safe, let's fetch by column name or check schema
        cur.execute("SHOW COLUMNS FROM properties")
        cols = [c[0] for c in cur.fetchall()]
        version_idx = cols.index("version")
        
        server_version = old_data[version_idx]
        
        if client_version is not None and int(client_version) < int(server_version):
            # Convert old_data tuple to dict for the conflict response
            server_data_dict = dict(zip(cols, old_data))
            raise SyncConflictError(server_data_dict, params)

        cur.execute(f"""
            UPDATE properties SET 
                td_number=%s, owner_name=%s, payor_name=%s, lot_number=%s, area=%s, location=%s,
                kind_of_property=%s, accountable_officer=%s, assessed_value=%s, penalty=%s, discount=%s,
                or_number=%s, or_date=%s, tax_year=%s, pin=%s, block_number=%s, 
                prev_td_number=%s, effectivity_date=%s, barangay=%s,
                version = version + 1
            WHERE id=%s
        """, (*params, editing_id))
        return editing_id, old_data
    else:
        cur.execute("""
            INSERT INTO properties (
                td_number, owner_name, payor_name, lot_number, area, location, kind_of_property,
                accountable_officer, assessed_value, penalty, discount, or_number, or_date, tax_year,
                pin, block_number, prev_td_number, effectivity_date, barangay, is_deleted, version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 1)
        """, params)
        return cur.lastrowid, None


def _audit_property_change(cur, prop_id, params, old_data, editing_id, user):
    """Records the change in the audit trail if a user is provided."""
    if not user:
        return
        
    action = "UPDATE_PROPERTY" if editing_id else "CREATE_PROPERTY"
    # Convert tuple to dict for audit logging
    col_names = ["td_number", "owner_name", "payor_name", "lot_number", "area", "location", "kind_of_property", 
                 "accountable_officer", "assessed_value", "penalty", "discount", "or_number", "or_date", 
                 "tax_year", "pin", "block_number", "prev_td_number", "effectivity_date", "barangay"]
    new_data_dict = dict(zip(col_names, params))
    
    db.record_audit_log_with_cur(cur, user, action, "properties", prop_id, old_data, new_data_dict)


def _sync_financial_records(cur, prop_id, data):
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
            billing.sync_property_billing(cur, prop_id, year, a_s, p_s, d_s, has_payment=should_pay)
        )
        
    if should_pay:
        paid = clean_currency(data.get("Amount Paid"))
        allocated = billing.allocate_payment_amount(billing_rows, paid)
        
        # Upsert payment record
        cur.execute("""
            SELECT id FROM payments WHERE property_id = %s AND or_number = %s AND date_paid = %s 
            ORDER BY id DESC LIMIT 1 FOR UPDATE
        """, (prop_id, data.get("OR Number"), data.get("OR Date")))
        
        pay_row = cur.fetchone()
        pay_params = (paid, data.get("OR Number"), data.get("OR Date"), data.get("Tax Year"), 
                      data.get("Accountable Officer"), data.get("Payor") or data.get("Owner Name"))
        
        if pay_row:
            cur.execute("UPDATE payments SET amount=%s, or_number=%s, date_paid=%s, tax_year=%s, posted_by=%s, payor_name=%s WHERE id=%s", 
                        (*pay_params, pay_row[0]))
            payment_id = pay_row[0]
        else:
            cur.execute("INSERT INTO payments (property_id, amount, or_number, date_paid, tax_year, posted_by, payor_name) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                        (prop_id, *pay_params))
            payment_id = cur.lastrowid
            
        billing.sync_payment_billings(cur, payment_id, allocated)


@require_permission("property_edit")
def update_property_details(prop_id, data, user):
    """Wrapper to update property details with professional permission check."""
    return save_property(data, editing_id=prop_id, user=user)


@require_permission("property_delete")
def soft_delete_property(property_id, user=None, ip_address=None):
    """Soft deletes a property - requires 'property_delete' permission."""
    old_data = get_property_by_id(property_id)

    def operation(cur):
        cur.execute(
            "UPDATE properties SET is_deleted = 1 WHERE id = %s", (property_id,)
        )
        return cur.rowcount

    res = db.execute_transaction(operation)
    if res and user:
        db.record_audit_log(
            user,
            "SOFT_DELETE",
            "properties",
            property_id,
            old_data,
            {"is_deleted": 1},
            ip_address,
        )
    return res


def get_deleted_properties(limit=50, offset=0):
    """Fetches all properties marked as deleted with pagination support."""
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))
    query = f"""
        SELECT id, td_number, owner_name, location, assessed_value 
        FROM properties 
        WHERE is_deleted = 1 
        ORDER BY id DESC
        LIMIT {safe_limit} OFFSET {safe_offset}
    """
    return db.db_query(query, fetch=True, commit=False) or []


@require_permission("property_edit")
def restore_property(property_id, user=None):
    """Restores a soft-deleted property."""

    def operation(cur):
        cur.execute(
            "UPDATE properties SET is_deleted = 0 WHERE id = %s", (property_id,)
        )
        return cur.rowcount

    res = db.execute_transaction(operation)
    if res and user:
        db.record_audit_log(
            user,
            "RESTORE",
            "properties",
            property_id,
            {"is_deleted": 1},
            {"is_deleted": 0},
        )
    return res


@require_permission("property_delete")
def purge_property(property_id, user=None):
    """Permanently deletes a property from the database."""
    old_data = get_property_by_id(
        property_id
    )  # This might return None since it filters for is_deleted=0
    # Let's get it specifically for purging
    query = "SELECT * FROM properties WHERE id = %s LIMIT 1"
    raw = db.db_query(query, (property_id,), fetch=True, dictionary=True)
    full_data = raw[0] if raw else None

    def operation(cur):
        # Delete associated billings and payments first if needed (cascade or manual)
        # Assuming database has cascade or we handle it here
        cur.execute(
            "DELETE FROM property_billings WHERE property_id = %s", (property_id,)
        )
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
        placeholders = ", ".join(["%s"] * len(property_ids))
        query = f"UPDATE properties SET barangay = %s WHERE id IN ({placeholders})"
        params = [new_barangay] + list(property_ids)
        cur.execute(query, params)
        return cur.rowcount

    res = db.execute_transaction(operation)
    if res and user:
        db.record_audit_log(
            user,
            "BULK_UPDATE",
            "properties",
            None,
            {"ids": property_ids},
            {"barangay": new_barangay},
        )
    return res


def get_property_by_td(td_number):
    query = "SELECT * FROM properties WHERE td_number = %s AND is_deleted = 0 LIMIT 1"
    res = db.db_query(query, (td_number,), fetch=True, dictionary=True)
    return res[0] if res else None


def get_assessment_roll(limit=100, offset=0):
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))
    query = f"SELECT td_number, owner_name, location, kind_of_property, assessed_value FROM properties WHERE is_deleted = 0 ORDER BY owner_name ASC LIMIT {safe_limit} OFFSET {safe_offset}"
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
