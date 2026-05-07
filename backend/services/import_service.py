import pandas as pd
from datetime import datetime
from db_manager import (
    execute_transaction, db_query
)
import backend.services.billing_service as billing_svc
import backend.services.payment_service as payment_svc
from backend.services.auth_service import require_permission

def _normalize_header(value):
    text = str(value).strip().lower()
    replacements = {
        " ": "_",
        "/": "_",
        "-": "_",
        ".": "",
        "(": "",
        ")": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def _clean_number(value):
    if pd.isna(value) or value == "":
        return 0.0
    cleaned = str(value).replace(",", "").replace("PHP", "").replace("P", "").replace("₱", "").replace("â‚±", "").strip()
    return float(cleaned) if cleaned else 0.0


def _clean_excel_date(value):
    if pd.isna(value) or value == "":
        return None
    
    # Handle numeric values (like years stored as 2023 or 2023.0)
    if isinstance(value, (int, float)):
        try:
            val_int = int(value)
            # If it's a reasonable year, treat it as YYYY-01-01
            if 1900 <= val_int <= 2100:
                return f"{val_int}-01-01"
        except:
            pass

    val_str = str(value).strip()
    # If it's just a year string (4 digits)
    if val_str.isdigit() and len(val_str) == 4:
        return f"{val_str}-01-01"

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    try:
        # If it's a large numeric value (Excel date serial), pandas handles it
        return pd.to_datetime(value).strftime("%Y-%m-%d")
    except Exception:
        return val_str or None


def _pick_field(row, aliases, default=""):
    for alias in aliases:
        if alias in row and not pd.isna(row[alias]):
            return row[alias]
    return default


def _clean_import_or_number(value):
    if pd.isna(value) or value == "":
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric_value = float(value)
        if numeric_value <= 0:
            return ""
        if numeric_value.is_integer():
            return str(int(numeric_value))
        return str(value).strip()
    return str(value).strip()


def _normalize_import_date(value):
    if pd.isna(value) or value == "":
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d")
    except Exception:
        return billing_svc.normalize_date_input(value) or ""


def _clean_import_tax_year(value):
    if pd.isna(value) or value == "":
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric_value = float(value)
        if numeric_value.is_integer():
            return str(int(numeric_value))
    return str(value).strip()


@require_permission("import_data")
def import_properties_from_excel(file_path, user_name):
    """Imports property and payment rows from Excel and returns a summary."""
    df = pd.read_excel(file_path)
    if df.empty:
        return {
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "duplicates": 0,
            "errors": ["The selected Excel file is empty."],
        }

    df.columns = [_normalize_header(col) for col in df.columns]

    required_groups = {
        "td_number": ["td_number", "td_no", "td"],
        "owner_name": ["owner_name", "owner", "name"],
        "assessed_value": ["assessed_value", "assessed", "assessed_val"],
        "or_number": ["or_number", "ornumber", "receipt_number"],
        "or_date": ["or_date", "date_paid", "payment_date"],
        "tax_year": ["tax_year"],
    }

    missing = [label for label, aliases in required_groups.items() if not any(alias in df.columns for alias in aliases)]
    if missing:
        pretty = ", ".join(missing)
        return {
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "duplicates": 0,
            "errors": [f"Missing required Excel column(s): {pretty}"],
        }

    summary = {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0, "duplicates": 0, "errors": []}

    for row_number, raw_row in enumerate(df.to_dict(orient="records"), start=2):
        td_number = _clean_text(_pick_field(raw_row, required_groups["td_number"]))
        owner_name = _clean_text(_pick_field(raw_row, required_groups["owner_name"]))

        if not td_number and not owner_name:
            summary["skipped"] += 1
            continue

        if not td_number or not owner_name:
            summary["failed"] += 1
            summary["errors"].append(f"Row {row_number}: TD Number and Owner Name are required.")
            continue

        try:
            assessed_value = _clean_number(_pick_field(raw_row, required_groups["assessed_value"], 0))
            penalty = _clean_number(_pick_field(raw_row, ["penalty", "penalties"], 0))
            or_number = _clean_import_or_number(_pick_field(raw_row, required_groups["or_number"], ""))
            or_date = _normalize_import_date(_pick_field(raw_row, required_groups["or_date"], ""))
            tax_year_raw = _clean_import_tax_year(_pick_field(raw_row, required_groups["tax_year"], ""))
            tax_year_check = billing_svc.validate_tax_year_text(tax_year_raw)

            if not or_number:
                raise ValueError("OR Number is required.")
            if or_number in {"0", "0.0", "0.00"}:
                raise ValueError("OR Number cannot be zero.")
            if not billing_svc.looks_like_valid_or_number(or_number):
                raise ValueError("OR Number contains invalid characters.")
            if not or_date:
                raise ValueError("OR Date is required. Use YYYY-MM-DD or MM/DD/YYYY.")
            if not billing_svc.normalize_date_input(or_date):
                raise ValueError("OR Date is invalid. Use YYYY-MM-DD or MM/DD/YYYY.")
            if not tax_year_check.get("ok"):
                raise ValueError(tax_year_check["message"])

            normalized_tax_year_text = tax_year_check["text"]
            tax_years = tax_year_check["years"]
            total_amount = (assessed_value * 0.01) + (assessed_value * 0.01) + penalty

            # Smart mapping for location/barangay
            loc_val = _clean_text(_pick_field(raw_row, ["location", "barangay", "address"], ""))
            
            property_values = (
                td_number,
                owner_name,
                _clean_text(_pick_field(raw_row, ["payor", "payor_name", "paid_by"], owner_name)),
                _clean_text(_pick_field(raw_row, ["lot_number", "lot_no", "lot"], "")),
                _clean_text(_pick_field(raw_row, ["area"], "")),
                loc_val, # For 'location' column
                _clean_text(_pick_field(raw_row, ["kind_of_property", "property_kind", "property_type", "kind"], "")),
                _clean_text(_pick_field(raw_row, ["accountable_officer", "posted_by", "officer"], user_name)),
                assessed_value,
                penalty,
                or_number,
                or_date,
                normalized_tax_year_text,
                _clean_text(_pick_field(raw_row, ["pin", "property_index_number"], "")),
                _clean_text(_pick_field(raw_row, ["block_number", "block"], "")),
                _clean_text(_pick_field(raw_row, ["prev_td_number", "previous_td"], "")),
                _clean_text(_pick_field(raw_row, ["effectivity_date", "effectivity"], "")),
                loc_val # For 'barangay' column
            )

            def import_row_transaction(cur):
                cur.execute("SELECT id FROM properties WHERE td_number = %s LIMIT 1", (td_number,))
                existing = cur.fetchone()
                property_id = existing[0] if existing else None

                if property_id:
                    raise ValueError(
                        f"TD Number {td_number} already exists in the system. "
                        "Import will not overwrite existing property records."
                    )

                duplicate_entry = payment_svc.find_duplicate_payment_entry(
                    td_number,
                    or_number,
                    or_date,
                    normalized_tax_year_text,
                    cur=cur,
                )
                if duplicate_entry:
                    raise ValueError(
                        "Duplicate payment entry detected during import. "
                        f"TD Number: {duplicate_entry['td_number']}, "
                        f"OR Number: {duplicate_entry['or_number']}, "
                        f"OR Date: {duplicate_entry['date_paid']}, "
                        f"Tax Year(s): {duplicate_entry['tax_year']}."
                    )

                if property_id:
                    duplicate_payment = payment_svc.find_duplicate_payment(
                        property_id,
                        or_number,
                        normalized_tax_year_text,
                        cur=cur,
                    )
                    if duplicate_payment:
                        raise ValueError(
                            "Possible duplicate payment detected during import. "
                            f"OR Number: {duplicate_payment['or_number']}, "
                            f"Tax Year(s): {duplicate_payment['tax_year']}."
                        )

                cur.execute(
                    """
                    INSERT INTO properties (
                        td_number, owner_name, payor_name, lot_number, area, location, kind_of_property,
                        accountable_officer, assessed_value, penalty,
                        or_number, or_date, tax_year,
                        pin, block_number, prev_td_number, effectivity_date, barangay,
                        is_deleted
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
                    """,
                    property_values,
                )
                property_id = cur.lastrowid
                action = "inserted"

                cur.execute("SELECT id FROM payments WHERE property_id = %s ORDER BY id DESC LIMIT 1", (property_id,))
                payment_row = cur.fetchone()
                payment_values = (
                    total_amount,
                    property_values[9],
                    property_values[10],
                    property_values[11],
                    property_values[6],
                    property_values[2],
                )

                if payment_row:
                    payment_id = payment_row[0]
                    cur.execute(
                        """
                        UPDATE payments
                        SET amount=%s, or_number=%s, date_paid=%s, tax_year=%s, posted_by=%s, payor_name=%s
                        WHERE id=%s
                        """,
                        (*payment_values, payment_id),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO payments (property_id, amount, or_number, date_paid, tax_year, posted_by, payor_name)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            property_id,
                            total_amount,
                            property_values[9],
                            property_values[10],
                            property_values[11],
                            property_values[6],
                            property_values[2],
                        ),
                    )
                    payment_id = cur.lastrowid

                billing_rows = []
                assessed_shares = billing_svc.split_amount_across_years(assessed_value, len(tax_years))
                penalty_shares = billing_svc.split_amount_across_years(penalty, len(tax_years))
                for tax_year, assessed_share, penalty_share in zip(tax_years, assessed_shares, penalty_shares):
                    billing_rows.append(
                        billing_svc.sync_property_billing(
                            cur,
                            property_id,
                            tax_year,
                            assessed_share,
                            penalty_share,
                            has_payment=True,
                        )
                    )

                allocated_billing_rows = billing_svc.allocate_payment_amount(billing_rows, total_amount)
                if not payment_id:
                    raise ValueError("Payment record could not be verified after import.")
                billing_svc.sync_payment_billings(cur, payment_id, allocated_billing_rows)

                return action

            result = execute_transaction(import_row_transaction, show_errors=False, return_error=True)
            if result == "inserted":
                summary["inserted"] += 1
            elif result == "updated":
                summary["updated"] += 1
            else:
                error_text = str(result) if result else "Database transaction failed."
                lowered_error = error_text.lower()
                if (
                    "already exists in the system" in lowered_error
                    or "duplicate payment" in lowered_error
                    or "possible duplicate" in lowered_error
                ):
                    summary["duplicates"] += 1
                else:
                    summary["failed"] += 1
                summary["errors"].append(f"Row {row_number}: {error_text}")
        except Exception as e:
            error_text = str(e)
            lowered_error = error_text.lower()
            if (
                "already exists in the system" in lowered_error
                or "duplicate payment" in lowered_error
                or "possible duplicate" in lowered_error
            ):
                summary["duplicates"] += 1
            else:
                summary["failed"] += 1
            summary["errors"].append(f"Row {row_number}: {error_text}")

    return summary


@require_permission("import_data")
def import_assessment_roll_from_excel(file_path, user):
    """Imports or Updates property records specifically for the Assessment Roll using a single fast transaction."""
    import db_manager as db
    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        return {"error": f"Failed to read Excel: {str(e)}"}

    if df.empty:
        return {"error": "The selected Excel file is empty."}

    df.columns = [_normalize_header(col) for col in df.columns]

    field_map = {
        "td_number": ["td_no", "td_number", "tax_dec"],
        "pin": ["pin", "property_index_no"],
        "lot_blk": ["lot_blk", "lot_block", "lot_and_blk"],
        "owner_name": ["property_owner", "owner", "owner_name"],
        "barangay": ["location", "property_location", "barangay"],
        "classification": ["classification", "kind", "kind_of_property"],
        "assessed_value": ["assessed_value", "av", "assessed_val"],
        "prev_td": ["previous_td", "prev_td", "prev_td_no"],
        "effectivity": ["effectivity", "fiscal_effectivity", "eff_date"]
    }

    summary = {"inserted": 0, "updated": 0, "failed": 0, "errors": []}

    def bulk_transaction(cur):
        nonlocal summary
        for row_idx, row in df.iterrows():
            try:
                td = _clean_text(_pick_field(row, field_map["td_number"]))
                owner = _clean_text(_pick_field(row, field_map["owner_name"]))
                
                if not td or not owner:
                    summary["failed"] += 1
                    summary["errors"].append(f"Row {row_idx+2}: Missing TD or Owner.")
                    continue

                lb_raw = _clean_text(_pick_field(row, field_map["lot_blk"]))
                lot, blk = "", ""
                if lb_raw:
                    parts = lb_raw.split("/") if "/" in lb_raw else lb_raw.split("&")
                    lot = parts[0].strip()
                    blk = parts[1].strip() if len(parts) > 1 else ""

                data = {
                    "td_number": td,
                    "owner_name": owner,
                    "pin": _clean_text(_pick_field(row, field_map["pin"])),
                    "lot_number": lot,
                    "block_number": blk,
                    "barangay": _clean_text(_pick_field(row, field_map["barangay"])),
                    "kind_of_property": _clean_text(_pick_field(row, field_map["classification"])),
                    "assessed_value": _clean_number(_pick_field(row, field_map["assessed_value"])),
                    "prev_td_number": _clean_text(_pick_field(row, field_map["prev_td"])),
                    "effectivity_date": _clean_excel_date(_pick_field(row, field_map["effectivity"]))
                }

                # High-speed upsert check
                cur.execute("SELECT id FROM properties WHERE td_number = %s AND is_deleted = 0", (td,))
                exists = cur.fetchone()
                
                if exists:
                    query = """
                        UPDATE properties SET 
                        owner_name=%s, pin=%s, lot_number=%s, block_number=%s, 
                        barangay=%s, kind_of_property=%s, assessed_value=%s, 
                        prev_td_number=%s, effectivity_date=%s
                        WHERE id=%s
                    """
                    cur.execute(query, (
                        data["owner_name"], data["pin"], data["lot_number"], data["block_number"],
                        data["barangay"], data["kind_of_property"], data["assessed_value"],
                        data["prev_td_number"], data["effectivity_date"], exists[0]
                    ))
                    summary["updated"] += 1
                else:
                    query = """
                        INSERT INTO properties (
                            td_number, owner_name, pin, lot_number, block_number, 
                            barangay, kind_of_property, assessed_value, 
                            prev_td_number, effectivity_date
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cur.execute(query, (
                        data["td_number"], data["owner_name"], data["pin"], 
                        data["lot_number"], data["block_number"], data["barangay"], 
                        data["kind_of_property"], data["assessed_value"], 
                        data["prev_td_number"], data["effectivity_date"]
                    ))
                    property_id = cur.lastrowid
                    if not property_id:
                        cur.execute("SELECT LAST_INSERT_ID()")
                        property_id = cur.fetchone()[0]
                    
                    # NEW: Auto-generate billing based on Effectivity Year (if available) or current year
                    eff_date = data["effectivity_date"]
                    billing_year = datetime.now().year
                    if eff_date:
                        try:
                            # Try to extract year from string or date object
                            if isinstance(eff_date, str) and len(eff_date) >= 4:
                                billing_year = int(eff_date[:4])
                            elif hasattr(eff_date, 'year'):
                                billing_year = eff_date.year
                        except: pass

                    billing_svc.sync_property_billing(
                        cur, property_id, billing_year, 
                        data["assessed_value"], 0.0, has_payment=False
                    )
                    summary["inserted"] += 1

            except Exception as e:
                summary["failed"] += 1
                summary["errors"].append(f"Row {row_idx+2}: {str(e)}")

    # Execute everything in ONE database connection
    db.execute_transaction(bulk_transaction)
    return summary
