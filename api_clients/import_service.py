import pandas as pd
from datetime import datetime
from db_manager import (
    validate_tax_year_text,
    normalize_date_input,
    looks_like_valid_or_number,
    find_duplicate_payment_entry,
    find_duplicate_payment,
    execute_transaction,
    split_amount_across_years,
    sync_property_billing,
    allocate_payment_amount,
    sync_payment_billings,
)


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
    return str(value).strip()


def _clean_number(value):
    if pd.isna(value) or value == "":
        return 0.0
    cleaned = (
        str(value)
        .replace(",", "")
        .replace("PHP", "")
        .replace("P", "")
        .replace("₱", "")
        .replace("â‚±", "")
        .strip()
    )
    return float(cleaned) if cleaned else 0.0


def _clean_excel_date(value):
    if pd.isna(value) or value == "":
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d")
    except Exception:
        return str(value).strip() or None


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
        return normalize_date_input(value) or ""


def _clean_import_tax_year(value):
    if pd.isna(value) or value == "":
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric_value = float(value)
        if numeric_value.is_integer():
            return str(int(numeric_value))
    return str(value).strip()


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

    missing = [
        label
        for label, aliases in required_groups.items()
        if not any(alias in df.columns for alias in aliases)
    ]
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

    summary = {
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "duplicates": 0,
        "errors": [],
    }

    for row_number, raw_row in enumerate(df.to_dict(orient="records"), start=2):
        td_number = _clean_text(_pick_field(raw_row, required_groups["td_number"]))
        owner_name = _clean_text(_pick_field(raw_row, required_groups["owner_name"]))

        if not td_number and not owner_name:
            summary["skipped"] += 1
            continue

        if not td_number or not owner_name:
            summary["failed"] += 1
            summary["errors"].append(
                f"Row {row_number}: TD Number and Owner Name are required."
            )
            continue

        try:
            assessed_value = _clean_number(
                _pick_field(raw_row, required_groups["assessed_value"], 0)
            )
            penalty = _clean_number(_pick_field(raw_row, ["penalty", "penalties"], 0))
            or_number = _clean_import_or_number(
                _pick_field(raw_row, required_groups["or_number"], "")
            )
            or_date = _normalize_import_date(
                _pick_field(raw_row, required_groups["or_date"], "")
            )
            tax_year_raw = _clean_import_tax_year(
                _pick_field(raw_row, required_groups["tax_year"], "")
            )
            tax_year_check = validate_tax_year_text(tax_year_raw)

            if not or_number:
                raise ValueError("OR Number is required.")
            if or_number in {"0", "0.0", "0.00"}:
                raise ValueError("OR Number cannot be zero.")
            if not looks_like_valid_or_number(or_number):
                raise ValueError("OR Number contains invalid characters.")
            if not or_date:
                raise ValueError("OR Date is required. Use YYYY-MM-DD or MM/DD/YYYY.")
            if not normalize_date_input(or_date):
                raise ValueError("OR Date is invalid. Use YYYY-MM-DD or MM/DD/YYYY.")
            if not tax_year_check.get("ok"):
                raise ValueError(tax_year_check["message"])

            normalized_tax_year_text = tax_year_check["text"]
            tax_years = tax_year_check["years"]
            total_amount = (assessed_value * 0.01) + (assessed_value * 0.01) + penalty

            property_values = (
                td_number,
                owner_name,
                _clean_text(
                    _pick_field(raw_row, ["payor", "payor_name", "paid_by"], owner_name)
                ),
                _clean_text(_pick_field(raw_row, ["lot_number", "lot_no", "lot"], "")),
                _clean_text(_pick_field(raw_row, ["area"], "")),
                _clean_text(_pick_field(raw_row, ["location", "address"], "")),
                _clean_text(
                    _pick_field(
                        raw_row,
                        ["kind_of_property", "property_kind", "property_type", "kind"],
                        "",
                    )
                ),
                _clean_text(
                    _pick_field(
                        raw_row,
                        ["accountable_officer", "posted_by", "officer"],
                        user_name,
                    )
                ),
                assessed_value,
                penalty,
                or_number,
                or_date,
                normalized_tax_year_text,
            )

            def import_row_transaction(cur):
                cur.execute(
                    "SELECT id FROM properties WHERE td_number = %s LIMIT 1",
                    (td_number,),
                )
                existing = cur.fetchone()
                property_id = existing[0] if existing else None

                if property_id:
                    raise ValueError(
                        f"TD Number {td_number} already exists in the system. "
                        "Import will not overwrite existing property records."
                    )

                duplicate_entry = find_duplicate_payment_entry(
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
                    duplicate_payment = find_duplicate_payment(
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
                        or_number, or_date, tax_year, is_deleted
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
                    """,
                    property_values,
                )
                property_id = cur.lastrowid
                action = "inserted"

                cur.execute(
                    "SELECT id FROM payments WHERE property_id = %s ORDER BY id DESC LIMIT 1",
                    (property_id,),
                )
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
                assessed_shares = split_amount_across_years(
                    assessed_value, len(tax_years)
                )
                penalty_shares = split_amount_across_years(penalty, len(tax_years))
                for tax_year, assessed_share, penalty_share in zip(
                    tax_years, assessed_shares, penalty_shares
                ):
                    billing_rows.append(
                        sync_property_billing(
                            cur,
                            property_id,
                            tax_year,
                            assessed_share,
                            penalty_share,
                            has_payment=True,
                        )
                    )

                allocated_billing_rows = allocate_payment_amount(
                    billing_rows, total_amount
                )
                if not payment_id:
                    raise ValueError(
                        "Payment record could not be verified after import."
                    )
                sync_payment_billings(cur, payment_id, allocated_billing_rows)

                return action

            result = execute_transaction(
                import_row_transaction, show_errors=False, return_error=True
            )
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
