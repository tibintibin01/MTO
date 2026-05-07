from datetime import datetime
import re
from db_manager import db_query
from decimal import Decimal, ROUND_HALF_UP

def sync_property_billing(cur, property_id, tax_year, assessed_value, penalty, discount=0.0, has_payment=False):
    """Creates or updates the billing snapshot for one property and one tax year."""
    normalized_tax_year = str(tax_year).strip() if str(tax_year).strip() else str(datetime.now().year)
    assessed_value = float(assessed_value or 0)
    penalty = float(penalty or 0)
    discount = float(discount or 0)
    basic_amount = assessed_value * 0.01
    sef_amount = assessed_value * 0.01
    total_amount = basic_amount + sef_amount + penalty - discount
    billing_status = "Paid" if has_payment else "Pending"
    initial_amount_paid = total_amount if has_payment else 0.0
    initial_balance = 0.0 if has_payment else total_amount

    cur.execute(
        """
        INSERT INTO property_billings (
            property_id, tax_year, assessed_value, penalty, discount, amount_paid
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            id = LAST_INSERT_ID(id),
            assessed_value = VALUES(assessed_value),
            penalty = VALUES(penalty),
            discount = VALUES(discount),
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            property_id,
            normalized_tax_year,
            assessed_value,
            penalty,
            discount,
            initial_amount_paid,
        ),
    )
    billing_id = cur.lastrowid
    if not billing_id:
        cur.execute(
            "SELECT id FROM property_billings WHERE property_id = %s AND tax_year = %s LIMIT 1",
            (property_id, normalized_tax_year),
        )
        row = cur.fetchone()
        billing_id = row[0] if row else None

    return {
        "billing_id": billing_id,
        "tax_year": normalized_tax_year,
        "assessed_value": assessed_value,
        "penalty": penalty,
        "discount": discount,
        "basic_amount": basic_amount,
        "sef_amount": sef_amount,
        "total_amount": total_amount,
        "amount_paid": initial_amount_paid,
        "balance_amount": initial_balance,
        "billing_status": billing_status,
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
    total = Decimal(str(total_amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if count == 1:
        return [float(total)]

    shared_amount = (total / Decimal(count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
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
        if "-" in part and len(part) == 9:
            start, end = part.split("-", 1)
            if start.isdigit() and end.isdigit():
                start_year = int(start)
                end_year = int(end)
                if end_year >= start_year and (end_year - start_year) <= 10:
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
                return {"ok": False, "message": f"Invalid tax year range: {part}. Use YYYY or YYYY-YYYY."}
            start_year, end_year = [int(piece) for piece in part.split("-", 1)]
            if end_year < start_year:
                return {"ok": False, "message": f"Invalid tax year range: {part}. End year must not be earlier than start year."}
            if start_year < 1900 or end_year > current_year:
                return {"ok": False, "message": f"Tax year range {part} is outside the allowed office range."}
            if (end_year - start_year) > 10:
                return {"ok": False, "message": f"Tax year range {part} is too wide. Use up to 10 years at a time."}
            continue

        if not re.fullmatch(r"\d{4}", part):
            return {"ok": False, "message": f"Invalid tax year: {part}. Use 4-digit years like 2025."}

        year = int(part)
        if year < 1900 or year > current_year:
            return {"ok": False, "message": f"Tax year {part} is outside the allowed office range."}
        if part in seen:
            return {"ok": False, "message": f"Tax year {part} is repeated. Remove duplicate years before saving."}
        seen.add(part)

    return {"ok": True, "years": normalize_tax_years(text), "text": format_tax_years(text)}


def looks_like_valid_or_number(value):
    text = str(value or "").strip()
    if not text:
        return False
    if len(text) > 50:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 /.-]*", text))


def recalculate_billing_balances(cur, billing_ids):
    seen = []
    for billing_id in billing_ids:
        if billing_id and billing_id not in seen:
            seen.append(billing_id)

    for billing_id in seen:
        # Lock the row for update to prevent race conditions
        cur.execute("SELECT id FROM property_billings WHERE id = %s FOR UPDATE", (billing_id,))
        
        cur.execute(
            """
            SELECT COALESCE(SUM(amount_paid), 0)
            FROM payment_billings
            WHERE billing_id = %s
            """,
            (billing_id,),
        )
        paid_row = cur.fetchone()
        amount_paid = float(paid_row[0] or 0)

        cur.execute(
            """
            UPDATE property_billings
            SET amount_paid = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (amount_paid, billing_id),
        )


def sync_payment_billings(cur, payment_id, billing_rows):
    if not payment_id:
        return

    cur.execute("SELECT billing_id FROM payment_billings WHERE payment_id = %s", (payment_id,))
    previous_links = [row[0] for row in cur.fetchall() or []]
    cur.execute("DELETE FROM payment_billings WHERE payment_id = %s", (payment_id,))
    affected_billing_ids = list(previous_links)
    for billing_row in billing_rows:
        if not billing_row.get("billing_id"):
            raise ValueError(
                f"Missing billing link for tax year {billing_row.get('tax_year', 'unknown')}. "
                "The yearly billing record was not created correctly."
            )
        applied_amount = float(billing_row.get("applied_amount", billing_row.get("total_amount", 0)) or 0)
        affected_billing_ids.append(billing_row["billing_id"])
        if applied_amount <= 0:
            continue
        cur.execute(
            """
            INSERT INTO payment_billings (payment_id, billing_id, tax_year, amount_paid)
            VALUES (%s, %s, %s, %s)
            """,
            (
                payment_id,
                billing_row["billing_id"],
                billing_row["tax_year"],
                applied_amount,
            ),
        )
    recalculate_billing_balances(cur, affected_billing_ids)


def get_property_billing_history(property_id=None, term=None, limit=50):
    safe_limit = max(1, int(limit))
    query = """
        SELECT pb.tax_year, 
               pb.assessed_value, 
               (pb.assessed_value * 0.01) AS basic_amount, 
               (pb.assessed_value * 0.01) AS sef_amount,
               pb.penalty, 
               ((pb.assessed_value * 0.02) + pb.penalty) AS total_amount, 
               pb.amount_paid, 
               GREATEST(((pb.assessed_value * 0.02) + pb.penalty) - pb.amount_paid, 0) AS balance_amount,
               CASE 
                   WHEN pb.amount_paid <= 0 THEN 'Pending'
                   WHEN pb.amount_paid >= ((pb.assessed_value * 0.02) + pb.penalty) THEN 'Paid'
                   ELSE 'Partial'
               END AS billing_status, 
               pb.updated_at
        FROM property_billings pb
        JOIN properties prop ON prop.id = pb.property_id
        WHERE prop.is_deleted = 0
    """
    params = []
    if property_id:
        query += " AND pb.property_id = %s"
        params.append(property_id)
    elif term:
        like_term = f"%{term}%"
        query += " AND (prop.td_number LIKE %s OR prop.owner_name LIKE %s OR prop.location LIKE %s OR COALESCE(prop.or_number, '') LIKE %s OR COALESCE(prop.tax_year, '') LIKE %s OR prop.accountable_officer LIKE %s)"
        params.extend([like_term, like_term, like_term, like_term, like_term, like_term])
    else:
        return []

    query += f" ORDER BY pb.tax_year DESC, pb.updated_at DESC LIMIT {safe_limit}"
    return db_query(query, tuple(params), fetch=True, commit=False) or []


def get_property_statement_data(property_id):
    rows = db_query(
        """
        SELECT id, td_number, owner_name, payor_name, lot_number, area, location,
               kind_of_property, accountable_officer, assessed_value, penalty,
               or_number, or_date, tax_year
        FROM properties
        WHERE id = %s AND is_deleted = 0
        LIMIT 1
        """,
        (property_id,),
        fetch=True,
        commit=False,
    )
    if not rows:
        return None

    row = rows[0]
    billing_rows_raw = get_property_billing_history(property_id=property_id, limit=500)
    billing_rows = []
    total_balance = 0.0
    total_paid = 0.0
    grand_total = 0.0

    for billing_row in billing_rows_raw:
        item = {
            "tax_year": billing_row[0],
            "assessed_value": float(billing_row[1] or 0),
            "basic_amount": float(billing_row[2] or 0),
            "sef_amount": float(billing_row[3] or 0),
            "penalty": float(billing_row[4] or 0),
            "total_amount": float(billing_row[5] or 0),
            "amount_paid": float(billing_row[6] or 0),
            "balance_amount": float(billing_row[7] or 0),
            "billing_status": billing_row[8],
            "updated_at": billing_row[9],
        }
        billing_rows.append(item)
        total_balance += item["balance_amount"]
        total_paid += item["amount_paid"]
        grand_total += item["total_amount"]

    return {
        "property_id": row[0],
        "td_number": row[1] or "",
        "owner_name": row[2] or "",
        "payor_name": row[3] or row[2] or "",
        "lot_number": row[4] or "",
        "area": row[5] or "",
        "location": row[6] or "",
        "kind_of_property": row[7] or "",
        "accountable_officer": row[8] or "",
        "assessed_value": float(row[9] or 0),
        "penalty": float(row[10] or 0),
        "or_number": row[11] or "",
        "or_date": row[12] or "",
        "tax_year": row[13] or "",
        "billing_rows": billing_rows,
        "total_balance": total_balance,
        "total_paid": total_paid,
        "grand_total": grand_total,
    }

def get_report_details(selected_month="All", selected_year="All"):
    filters = []
    params = []
    if selected_month != "All":
        filters.append("MONTH(pay.date_paid) = %s")
        params.append(int(selected_month))
    if selected_year != "All":
        filters.append("YEAR(pay.date_paid) = %s")
        params.append(int(selected_year))

    where_clause = "WHERE prop.is_deleted = 0"
    if filters: where_clause += " AND " + " AND ".join(filters)

    return db_query(
        f"""
        SELECT pay.date_paid, pay.or_number, prop.td_number, prop.owner_name,
               prop.kind_of_property, pay.tax_year, pay.amount, pay.posted_by
        FROM payments pay
        JOIN properties prop ON prop.id = pay.property_id
        {where_clause}
        ORDER BY pay.date_paid DESC, pay.id DESC
        """,
        tuple(params),
        fetch=True,
        commit=False,
    )

def get_rpt_receivables_summary(report_year):
    try:
        ry = int(report_year)
    except:
        ry = datetime.now().year

    res = db_query(
        """
        SELECT
            (SELECT COALESCE(SUM(((pb.assessed_value * 0.02) + pb.penalty) - pb.amount_paid), 0)
             FROM property_billings pb JOIN properties p ON p.id = pb.property_id
             WHERE p.is_deleted = 0 AND pb.tax_year < %s),
            (SELECT COALESCE(SUM((pb.assessed_value * 0.02) + pb.penalty), 0)
             FROM property_billings pb JOIN properties p ON p.id = pb.property_id
             WHERE p.is_deleted = 0 AND pb.tax_year = %s),
            (SELECT COALESCE(SUM(pay_b.amount_paid), 0)
             FROM payment_billings pay_b
             JOIN payments pay ON pay.id = pay_b.payment_id
             JOIN properties p ON p.id = pay.property_id
             WHERE p.is_deleted = 0 AND YEAR(pay.date_paid) = %s)
        """,
        (ry, ry, ry),
        fetch=True,
        commit=False,
    )
    if not res: return None
    row = res[0]
    beg = float(row[0] or 0)
    curr_ass = float(row[1] or 0)
    coll = float(row[2] or 0)
    adj = 0.0 # Placeholder
    end = beg + curr_ass - coll + adj

    return {
        "report_year": ry,
        "beginning_receivable": beg,
        "current_year_assessment": curr_ass,
        "collections": coll,
        "adjustments": adj,
        "ending_receivable": end,
    }


