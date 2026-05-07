# -*- coding: utf-8 -*-
import re
import db_manager as db
from services.auth_service import get_username, require_permission
from services.billing_service import format_tax_years, normalize_date_input

def find_duplicate_payment(property_id, or_number, tax_year_text, exclude_payment_id=None, cur=None):
    normalized_years = format_tax_years(tax_year_text)
    if not property_id or not or_number or not normalized_years:
        return None
    query = """
        SELECT id, or_number, tax_year, amount, date_paid
        FROM payments
        WHERE property_id = %s AND or_number = %s AND COALESCE(tax_year, '') = %s
    """
    params = [property_id, or_number, normalized_years]
    if exclude_payment_id:
        query += " AND id <> %s"
        params.append(exclude_payment_id)
    query += " ORDER BY id DESC LIMIT 1"
    if cur is not None:
        cur.execute(query, tuple(params))
        row = cur.fetchone()
        if not row: return None
    else:
        rows = db.db_query(query, tuple(params), fetch=True, commit=False)
        if not rows: return None
        row = rows[0]
    return {
        "payment_id": row[0],
        "or_number": row[1],
        "tax_year": row[2],
        "amount": float(row[3] or 0),
        "date_paid": row[4],
    }

def find_duplicate_payment_entry(td_number, or_number, or_date, tax_year_text, exclude_payment_id=None, cur=None):
    td_text = str(td_number or "").strip()
    or_text = str(or_number or "").strip()
    date_text = normalize_date_input(or_date)
    normalized_years = format_tax_years(tax_year_text)
    if not td_text or not or_text or not date_text or not normalized_years:
        return None
    query = """
        SELECT pay.id, prop.id, prop.td_number, prop.owner_name, pay.or_number, pay.date_paid, pay.tax_year, pay.amount
        FROM payments pay
        JOIN properties prop ON prop.id = pay.property_id
        WHERE prop.is_deleted = 0
          AND prop.td_number = %s
          AND pay.or_number = %s
          AND pay.date_paid = %s
          AND COALESCE(pay.tax_year, '') = %s
    """
    params = [td_text, or_text, date_text, normalized_years]
    if exclude_payment_id:
        query += " AND pay.id <> %s"
        params.append(exclude_payment_id)
    query += " ORDER BY pay.id DESC LIMIT 1"
    if cur is not None:
        cur.execute(query, tuple(params))
        row = cur.fetchone()
        if not row: return None
    else:
        rows = db.db_query(query, tuple(params), fetch=True, commit=False)
        if not rows: return None
        row = rows[0]
    return {
        "payment_id": row[0],
        "property_id": row[1],
        "td_number": row[2],
        "owner_name": row[3],
        "or_number": row[4],
        "date_paid": row[5],
        "tax_year": row[6],
        "amount": float(row[7] or 0),
    }

def get_existing_payment_amount(property_id, or_number, or_date, tax_year_text):
    normalized_years = format_tax_years(tax_year_text)
    normalized_date = normalize_date_input(or_date)
    if not property_id or not or_number or not normalized_date or not normalized_years:
        return None
    rows = db.db_query(
        """
        SELECT amount
        FROM payments
        WHERE property_id = %s
          AND or_number = %s
          AND date_paid = %s
          AND COALESCE(tax_year, '') = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (property_id, str(or_number).strip(), normalized_date, normalized_years),
        fetch=True,
        commit=False,
    )
    if not rows: return None
    return float(rows[0][0] or 0)

def acquire_payment_post_lock(property_id, user_name, stale_minutes=30):
    return db._acquire_named_lock("payment_post_locks", "property_id", property_id, user_name, stale_minutes)

def release_payment_post_lock(property_id, user_name):
    db._release_named_lock("payment_post_locks", "property_id", property_id, user_name)

def release_all_payment_post_locks(user_name):
    db._release_all_named_locks("payment_post_locks", user_name)

def get_next_or_number(default_prefix="OR-"):
    rows = db.db_query(
        """
        SELECT or_number
        FROM payments
        WHERE or_number IS NOT NULL AND TRIM(or_number) <> ''
        ORDER BY id DESC
        LIMIT 20
        """,
        fetch=True,
        commit=False,
    )
    for row in rows or []:
        current = str(row[0]).strip()
        match = re.search(r"^(.*?)(\d+)$", current)
        if not match: continue
        prefix, digits = match.groups()
        next_value = int(digits) + 1
        return f"{prefix}{next_value:0{len(digits)}d}"
    return f"{default_prefix}000001"

def get_recent_payments(limit=8):
    safe_limit = max(1, int(limit))
    rows = db.db_query(
        f"""
        SELECT pay.date_paid, pay.or_number, prop.td_number, prop.owner_name, pay.tax_year, pay.amount
        FROM payments pay
        JOIN properties prop ON prop.id = pay.property_id
        WHERE prop.is_deleted = 0
        ORDER BY COALESCE(pay.date_paid, DATE(pay.created_at)) DESC, pay.id DESC
        LIMIT {safe_limit}
        """,
        fetch=True,
        commit=False,
    ) or []
    cleaned = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 6:
            cleaned.append(row)
    return cleaned

def get_monthly_collection_trend(months=6):
    safe_months = max(1, int(months))
    rows = db.db_query(
        f"""
        SELECT DATE_FORMAT(bucket.month_start, '%%Y-%%m') AS month_key,
               COALESCE(SUM(pay.amount), 0) AS total_amount
        FROM (
            SELECT DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL seq.n MONTH), '%%Y-%%m-01') AS month_start
            FROM (
                SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
                UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7
                UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11
            ) seq
            WHERE seq.n < {safe_months}
        ) bucket
        LEFT JOIN payments pay
            ON DATE_FORMAT(COALESCE(pay.date_paid, DATE(pay.created_at)), '%%Y-%%m-01') = bucket.month_start
        GROUP BY bucket.month_start
        ORDER BY bucket.month_start
        """,
        fetch=True,
        commit=False,
    ) or []
    cleaned = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            cleaned.append({"month": row[0] or "", "total": float(row[1] or 0)})
    return cleaned

def get_unified_payment_history(term):
    """
    Unified query for the Integrated Ledger & Receipt History.
    Returns payment details combined with receipt audit info.
    """
    if not term:
        return []
    like_term = f"%{term}%"
    query = """
        SELECT 
            pay.id as payment_id,
            pay.date_paid, 
            pay.or_number, 
            pay.tax_year,
            (prop.assessed_value * 0.01) AS basic,
            (prop.assessed_value * 0.01) AS sef,
            prop.penalty, 
            prop.discount,
            pay.amount, 
            pay.posted_by,
            rh.file_path,
            rh.id as receipt_id,
            prop.td_number,
            prop.owner_name
        FROM payments pay
        JOIN properties prop ON prop.id = pay.property_id
        LEFT JOIN receipt_history rh ON rh.payment_id = pay.id
        WHERE prop.is_deleted = 0
          AND (prop.td_number = %s OR prop.owner_name LIKE %s OR pay.or_number LIKE %s)
        ORDER BY pay.date_paid DESC, pay.id DESC
    """
    params = (term, like_term, like_term)
    return db.db_query(query, params, fetch=True, commit=False) or []

def get_payment_ledger(td_number):
    """
    Specific ledger query for the Dossier UI.
    Indices: 0:Date, 1:OR, 2:Year, 3:Basic, 4:SEF, 5:Penalty, 6:Total
    """
    query = """
        SELECT 
            pay.date_paid, 
            pay.or_number, 
            pay.tax_year,
            (prop.assessed_value * 0.01) AS basic,
            (prop.assessed_value * 0.01) AS sef,
            prop.penalty,
            pay.amount
        FROM payments pay
        JOIN properties prop ON prop.id = pay.property_id
        WHERE prop.td_number = %s AND prop.is_deleted = 0
        ORDER BY pay.date_paid DESC, pay.id DESC
    """
    return db.db_query(query, (td_number,), fetch=True, commit=False) or []

def get_payment_receipt_records(term):
    like_term = f"%{term}%"
    return db.db_query(
        """
        SELECT pay.id, pay.date_paid, prop.td_number, prop.owner_name,
               prop.kind_of_property, pay.or_number, pay.tax_year, pay.amount,
               rh.file_path, rh.generated_by, rh.status, rh.id as rh_id
        FROM payments pay
        JOIN properties prop ON prop.id = pay.property_id
        LEFT JOIN receipt_history rh ON rh.payment_id = pay.id
        WHERE prop.is_deleted = 0
          AND (prop.td_number LIKE %s OR prop.owner_name LIKE %s OR pay.or_number LIKE %s)
        ORDER BY pay.date_paid DESC, pay.id DESC
        """,
        (like_term, like_term, like_term),
        fetch=True,
        commit=False,
    ) or []

def get_payment_receipt_details(payment_id):
    rows = db.db_query(
        """
        SELECT prop.id, prop.td_number, prop.owner_name, prop.payor_name, prop.lot_number,
               prop.area, prop.location, prop.kind_of_property, prop.accountable_officer,
               prop.assessed_value, prop.penalty, pay.id, pay.amount, pay.or_number,
               pay.date_paid, pay.tax_year, rh.file_path, rh.id as rh_id
        FROM payments pay
        JOIN properties prop ON prop.id = pay.property_id
        LEFT JOIN receipt_history rh ON rh.payment_id = pay.id
        WHERE pay.id = %s AND prop.is_deleted = 0
        LIMIT 1
        """,
        (payment_id,),
        fetch=True,
        commit=False,
    )
    if not rows: return None
    r = rows[0]
    return {
        "property_id": r[0], "td_number": r[1], "owner_name": r[2], "payor_name": r[3],
        "lot_number": r[4], "area": r[5], "location": r[6], "kind_of_property": r[7],
        "accountable_officer": r[8], "assessed_value": float(r[9] or 0),
        "penalty": float(r[10] or 0), "payment_id": r[11], "amount": float(r[12] or 0),
        "or_number": r[13], "date_paid": r[14], "tax_year": r[15], "file_path": r[16],
        "receipt_history_id": r[17]
    }

@require_permission("receipt_generate")
def save_receipt_record(property_id, payment_id, details, file_path, user_name, **kwargs):
    def operation(cur):
        cur.execute(
            """
            INSERT INTO receipt_history (property_id, payment_id, or_number, file_path, generated_by, status)
            VALUES (%s, %s, %s, %s, %s, 'PDF READY')
            ON DUPLICATE KEY UPDATE file_path=%s, generated_by=%s, generated_at=NOW(), status='PDF READY'
            """,
            (property_id, payment_id, details.get("or_number"), file_path, get_username(user_name), file_path, get_username(user_name)),
        )
        return {"lastrowid": cur.lastrowid}
    return db.execute_transaction(operation)
