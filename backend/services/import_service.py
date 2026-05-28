# -*- coding: utf-8 -*-
import pandas as pd
import io
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy import or_, text
from sqlalchemy.orm import Session
from backend.models import Property, PropertyAssessmentHistory, Payment, PropertyBilling
from backend.database import SessionLocal
from utils.logger import mto_logger


class DataCleanser:
    @staticmethod
    def to_float(val):
        if pd.isna(val) or val == "": return 0.0
        if isinstance(val, (int, float)): return float(val)
        
        s = str(val).strip()
        # Handle accounting parentheses: (100.00) -> -100.00
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
            
        # Remove everything except digits, dots, and minus signs
        clean = re.sub(r'[^\d.-]', '', s)
        try: return float(clean)
        except Exception: return 0.0

    @staticmethod
    def to_str(val):
        if pd.isna(val): return ""
        return str(val).strip()

    @staticmethod
    def normalize_barangay(val, known_barangays=None):
        val = DataCleanser.to_str(val).upper()
        if not known_barangays: return val
        # Basic fuzzy match or exact match
        if val in known_barangays: return val
        # Check for abbreviations
        if val == "N. POBLACION": return "NORTH POBLACION"
        if val == "S. POBLACION": return "SOUTH POBLACION"
        return val

def validate_property_import(file_content, file_extension, db_session: Session = None):
    """
    Validates a CSV or Excel file for property bulk import.
    Returns a list of rows with validation status and error messages.

    Required columns (case-insensitive, spaces/underscores interchangeable):
      TD NUMBER (or TD No, Tax Declaration)
      Assessed Value (or Value, Assessment)

    Optional:
      Owner Name, Location, Lot Number, Area, Kind of Property, etc.
    """
    try:
        if file_extension.lower() == '.csv':
            df = pd.read_csv(io.BytesIO(file_content))
        else:
            df = pd.read_excel(io.BytesIO(file_content))

        # Normalize headers: lowercase + underscores
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

        # Field mapping — only td_number and assessed_value are truly required
        # owner_name is optional: many import files don't include it
        field_mapping = {
            "td_number":      ["td_number", "td_no", "tax_declaration", "tdnumber", "td"],
            "owner_name":     ["owner_name", "owner", "declared_owner", "property_owner"],
            "assessed_value": ["assessed_value", "value", "assessment", "market_value"],
            "location":       ["location", "address", "barangay", "brgy"],
            "lot_number":     ["lot_number", "lot_no", "lot"],
            "area":           ["area", "sqm", "sq_m"],
            "kind_of_property": ["kind_of_property", "kind", "classification", "class"],
            "tax_year":       ["tax_year", "year", "period"],
            "or_number":      ["or_number", "or_no", "receipt_no"],
            "or_date":        ["or_date", "date_paid", "date", "payment_date"],
            "penalty":        ["penalty", "surcharge"],
            "discount":       ["discount", "less"],
            "amount_paid":    ["amount_paid", "amount", "total", "total_paid"],
        }

        REQUIRED = {"td_number", "assessed_value"}

        found_cols = {}
        for field, aliases in field_mapping.items():
            match = next((c for c in df.columns if c in aliases), None)
            if match is None and field in REQUIRED:
                return {
                    "success": False,
                    "error": (
                        f"Missing required column for '{field}'. "
                        f"Expected one of: {', '.join(aliases[:4])}. "
                        f"Your headers: {', '.join(df.columns.tolist()[:10])}"
                    )
                }
            found_cols[field] = match
        
        # Get existing TD numbers for duplicate check
        existing_tds = {r[0] for r in db_session.query(Property.td_number).all()}

        results = []
        rows_to_import = []

        for index, row in df.iterrows():
            errors = []
            row_data = row.to_dict()

            # TD Number — required
            td_col = found_cols.get("td_number")
            td = DataCleanser.to_str(row_data.get(td_col, "")) if td_col else ""
            if not td:
                errors.append("Missing TD Number")
            elif td in existing_tds:
                errors.append(f"Duplicate TD Number: {td} already exists")

            # Owner Name — optional, no error if absent
            owner_col = found_cols.get("owner_name")
            owner = DataCleanser.to_str(row_data.get(owner_col, "")) if owner_col else ""

            # Assessed Value — required
            av_col = found_cols.get("assessed_value")
            val = 0.0
            if av_col:
                try:
                    raw_val = row_data.get(av_col, 0)
                    val = float(raw_val) if not pd.isna(raw_val) else 0.0
                    if val < 0:
                        errors.append("Assessed Value cannot be negative")
                except Exception as e:
                    mto_logger.warning(f"Error parsing assessed value: {e}")
                    errors.append("Invalid numeric format for Assessed Value")

            status = "❌ ERROR" if errors else "✅ VALID"

            results.append({
                "row_index": index + 2,
                "td_number": td,
                "owner_name": owner,
                "status": status,
                "message": "; ".join(errors) if errors else "Ready to import",
            })

            if not errors:
                def _get(field):
                    col = found_cols.get(field)
                    return DataCleanser.to_str(row_data.get(col, "")) if col else ""

                rows_to_import.append({
                    "td_number":        td,
                    "owner_name":       owner,
                    "assessed_value":   val,
                    "location":         _get("location"),
                    "lot_number":       _get("lot_number"),
                    "area":             _get("area"),
                    "kind_of_property": _get("kind_of_property"),
                    "tax_year":         _get("tax_year"),
                    "or_number":        _get("or_number"),
                    "or_date":          _get("or_date"),
                    "penalty":          DataCleanser.to_float(row_data.get(found_cols["penalty"])) if found_cols.get("penalty") else 0.0,
                    "discount":         DataCleanser.to_float(row_data.get(found_cols["discount"])) if found_cols.get("discount") else 0.0,
                    "amount_paid":      DataCleanser.to_float(row_data.get(found_cols["amount_paid"])) if found_cols.get("amount_paid") else 0.0,
                })

        return {
            "success": True, 
            "report": results, 
            "total_rows": len(df),
            "valid_rows": len(rows_to_import),
            "data": rows_to_import
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def validate_assessment_import(file_content, file_extension, db_session: Session = None):
    """
    Validates an Excel file for Assessment Roll import.
    """
    try:
        if file_extension.lower() == '.csv':
            df = pd.read_csv(io.BytesIO(file_content))
        else:
            df = pd.read_excel(io.BytesIO(file_content))
        
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        mapping = {
            "td_number": ["TD NO.", "TD NUMBER", "TAX DECLARATION", "TD_NO"],
            "pin": ["PIN", "PROPERTY INDEX NUMBER", "INDEX_NO", "PIN_NO"],
            "owner_name": ["PROPERTY OWNER", "OWNER NAME", "OWNER", "DECLARED OWNER"],
            "assessed_value": ["ASSESSED VALUE", "VALUE", "MARKET VALUE", "ASS_VALUE", "ASSESSMENT"],
            "location": ["LOCATION", "ADDRESS", "BARANGAY", "SITIO", "BRGY"],
            "kind": ["CLASSIFICATION", "KIND", "KIND OF PROPERTY", "CLASS"],
            "tax_year": ["YEAR", "TAX YEAR", "TAX_YEAR", "PERIOD", "TAX_PERIOD"],
            "area": ["AREA", "TOTAL AREA", "SQM", "SQ.M.", "SIZE"],
            "lot_number": ["LOT NO.", "LOT NO", "LOT", "LOT_NUMBER", "LOT_NO", "L.", "LOT AND BLK", "LOT/BLK", "LOT & BLK"],
            "block_number": ["BLOCK NO.", "BLOCK NO", "BLOCK", "BLOCK_NUMBER", "BLK", "BLOCK_NO", "B."]
        }



        
        found_cols = {}
        for db_field, aliases in mapping.items():
            match = next((c for c in df.columns if c in aliases), None)
            found_cols[db_field] = match

        results = []
        rows_to_import = []
        seen_tds = set()
        
        # Get existing TD numbers to determine INSERT vs UPDATE
        existing_tds = {r[0] for r in db_session.query(Property.td_number).all()}

        for index, row in df.iterrows():
            errors = []
            td = DataCleanser.to_str(row.get(found_cols.get("td_number")))
            owner = DataCleanser.to_str(row.get(found_cols.get("owner_name")))
            
            if not td: errors.append("Missing TD Number")
            if not owner: errors.append("Missing Owner Name")
            if td:
                if td in seen_tds:
                    errors.append(f"Duplicate TD Number in import file: {td}")
                seen_tds.add(td)
            
            val = DataCleanser.to_float(row.get(found_cols.get("assessed_value")))
                
            action = "UPDATE" if td in existing_tds else "INSERT"
            status = "❌ ERROR" if errors else "✅ VALID"
            
            # Map for frontend preview
            results.append({
                "row_index": index + 2,
                "td_number": td,
                "owner_name": owner,
                "lot_number": DataCleanser.to_str(row.get(found_cols.get("lot_number"))),
                "status": status,

                "action": action if not errors else "N/A",
                "message": "; ".join(errors) if errors else f"Ready for {action}"
            })
            
            if not errors:
                # Store cleaned data for commit
                raw_row = {
                    "td_number": td,
                    "owner_name": owner,
                    "assessed_value": val,
                    "location": DataCleanser.to_str(row.get(found_cols.get("location"))),
                    "pin": DataCleanser.to_str(row.get(found_cols.get("pin"))),
                    "tax_year": DataCleanser.to_str(row.get(found_cols.get("tax_year"))),
                    "area": DataCleanser.to_str(row.get(found_cols.get("area"))),
                    "kind_of_property": DataCleanser.to_str(row.get(found_cols.get("kind"), "LAND")).upper(),
                    "lot_number": DataCleanser.to_str(row.get(found_cols.get("lot_number"))),
                    "block_number": DataCleanser.to_str(row.get(found_cols.get("block_number")))
                }
                
                # Smart Split: Handle combined Lot/Block with comma or space
                raw_lot = raw_row["lot_number"]
                if not raw_row["block_number"] and raw_lot:
                    # Rule 1: Split by comma
                    if "," in raw_lot:
                        raw_lot = raw_lot.split(",", 1)[0].strip()
                    # Rule 2: Split by 3+ spaces
                    import re
                    if re.search(r"\s{3,}", raw_lot):
                        raw_lot = re.split(r"\s{3,}", raw_lot, 1)[0].strip()
                    
                    # Rule 3: Space Split with "Lot" preservation
                    if " " in raw_lot:
                        parts = raw_lot.split(" ")
                        if parts[0].upper() == "LOT" and len(parts) > 1:
                            raw_lot = f"{parts[0]} {parts[1]}".strip()
                        else:
                            raw_lot = parts[0].strip()
                    
                    raw_row["lot_number"] = raw_lot
                
                rows_to_import.append(raw_row)









        return {
            "success": True,
            "report": results,
            "total_rows": len(df),
            "valid_rows": len(rows_to_import),
            "data": rows_to_import
        }
    except Exception as e:
        import traceback
        err_msg = f"Validation Error: {str(e)}"
        print(f"IMPORT FAILED: {err_msg}")
        traceback.print_exc()
        return {"success": False, "error": err_msg}


def commit_assessment_import(data_list, user, db_session: Session = None):
    """
    Saves the validated assessment rows with real-time progress updates.
    """
    from backend.services.system_service import log_action
    
    async def report_progress(percentage, msg):
        try:
            from backend.deps import manager
            await manager.broadcast({
                "type": "PROGRESS",
                "module": "import",
                "percentage": percentage,
                "message": msg
            })
        except Exception as e:
            mto_logger.warning(f"Failed to broadcast import progress: {e}")

    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except Exception as e:
        mto_logger.info(f"No active event loop found, creating new loop: {e}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    inserted = 0
    updated = 0
    failed = 0
    failed_rows = []
    total = len(data_list)
    seen_tds = set()
    
    try:
        for i, row in enumerate(data_list):
            try:
                td = row["td_number"]
                if td in seen_tds:
                    failed += 1
                    failed_rows.append({
                        "row": i + 2,
                        "td_number": td,
                        "reason": f"Duplicate TD Number in import file: {td}",
                    })
                    continue
                seen_tds.add(td)

                prop = db_session.query(Property).filter(Property.td_number == td).first()
                
                if prop:
                    # 1. Capture current state for history before updating
                    history = PropertyAssessmentHistory(
                        property_id=prop.id,
                        td_number=prop.td_number,
                        assessed_value=prop.assessed_value,
                        kind_of_property=prop.kind_of_property,
                        tax_year=prop.tax_year,
                        changed_by=user.get("username", "system")
                    )
                    db_session.add(history)

                    # 2. Perform the update
                    prop.owner_name = row["owner_name"]
                    prop.assessed_value = row["assessed_value"]
                    prop.location = row["location"]
                    prop.kind_of_property = row["kind_of_property"]
                    prop.pin = row["pin"]
                    prop.tax_year = row["tax_year"]
                    prop.area = row["area"]
                    prop.lot_number = row.get("lot_number")
                    prop.block_number = row.get("block_number")
                    updated += 1

                else:
                    # New TD number — insert as new property
                    new_prop = Property(
                        td_number=td,
                        owner_name=row["owner_name"],
                        assessed_value=row["assessed_value"],
                        location=row["location"],
                        kind_of_property=row["kind_of_property"],
                        pin=row["pin"],
                        tax_year=row["tax_year"],
                        area=row["area"],
                        lot_number=row.get("lot_number"),
                        block_number=row.get("block_number")
                    )
                    db_session.add(new_prop)
                    inserted += 1

                # Flush every 10 rows to catch constraint errors early
                if i % 10 == 0 or i == total - 1:
                    db_session.flush()
                    percentage = int(((i + 1) / total) * 100)
                    try:
                        asyncio.run_coroutine_threadsafe(
                            report_progress(percentage, f"Importing: {i+1} / {total} records"),
                            loop
                        )
                    except Exception as prog_err:
                        mto_logger.warning(f"Failed to submit progress update: {prog_err}")

            except Exception as row_err:
                # Roll back only the current flush group, not the whole batch
                db_session.rollback()
                failed += 1
                failed_rows.append({
                    "row": i + 2,
                    "td_number": row.get("td_number", "?"),
                    "reason": str(row_err)[:200],
                })
                mto_logger.warning(
                    f"Assessment import row {i + 2} failed "
                    f"(TD: {row.get('td_number', '?')}): {row_err}"
                )
        
        log_action(user, f"Wizard Assessment Import: {inserted} new, {updated} updated, {failed} failed.", db_session=db_session)
        db_session.commit()
        return {"inserted": inserted, "updated": updated, "failed": failed, "failed_rows": failed_rows[:20]}
    except Exception as e:
        db_session.rollback()
        mto_logger.error(f"commit_assessment_import failed: {e}")
        raise

def commit_property_import(data_list, user, db_session: Session = None):
    """
    Saves the validated rows to the database with real-time progress updates.
    """
    from backend.services.system_service import log_action
    
    async def report_progress(percentage, msg):
        try:
            from backend.deps import manager
            await manager.broadcast({
                "type": "PROGRESS",
                "module": "import",
                "percentage": percentage,
                "message": msg
            })
        except Exception as e:
            mto_logger.warning(f"Failed to broadcast import progress: {e}")

    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except Exception as e:
        mto_logger.info(f"No active event loop found, creating new loop: {e}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    count = 0
    total = len(data_list)
    try:
        for i, row in enumerate(data_list):
            new_prop = Property(
                td_number=row.get("td_number"),
                owner_name=row.get("owner_name"),
                assessed_value=row.get("assessed_value"),
                location=row.get("location"),
                lot_number=row.get("lot_number"),
                area=row.get("area"),
                kind_of_property=row.get("kind_of_property")
            )
            db_session.add(new_prop)
            count += 1
            
            if i % 10 == 0 or i == total - 1:
                db_session.flush()
                percentage = int(((i + 1) / total) * 100)
                try:
                    asyncio.run_coroutine_threadsafe(
                        report_progress(percentage, f"Processing: {i+1} / {total} properties"), 
                        loop
                    )
                except Exception as e:
                    mto_logger.warning(f"Failed to submit progress update: {e}")
        
        log_action(user, f"Bulk imported {count} property records.", db_session=db_session)
        db_session.commit()
        return count
    except Exception as e:
        db_session.rollback()
        mto_logger.error(f"commit_property_import failed: {e}")
        raise

def import_assessment_roll_from_excel(file_path, user, db_session: Session = None):
    """
    Imports the entire Assessment Roll from an Excel file.
    Updates existing records or inserts new ones based on TD Number.
    """
    from backend.services.system_service import log_action
    
    try:
        df = pd.read_excel(file_path)
        # Standardize headers
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        # Mapping for the Assessment Roll specific headers
        mapping = {
            "TD NUMBER": ["TD NO.", "TD NUMBER", "TAX DECLARATION"],
            "PIN": ["PIN", "PROPERTY INDEX NUMBER"],
            "OWNER": ["PROPERTY OWNER", "OWNER NAME", "OWNER"],
            "LOCATION": ["LOCATION", "ADDRESS", "BARANGAY"],
            "VALUE": ["ASSESSED VALUE", "VALUE", "MARKET VALUE"],
            "KIND": ["CLASSIFICATION", "KIND", "KIND OF PROPERTY"],
            "LOT": ["LOT NO.", "LOT NO", "LOT", "LOT_NUMBER", "LOT_NO", "L.", "LOT AND BLK", "LOT/BLK", "LOT & BLK"],
            "BLK": ["BLOCK NO.", "BLOCK NO", "BLOCK", "BLOCK_NUMBER", "BLK", "BLOCK_NO", "B."]
        }





        
        found_cols = {}
        for key, aliases in mapping.items():
            match = next((c for c in df.columns if c in aliases), None)
            found_cols[key] = match

        inserted = 0
        updated = 0
        failed = 0
        errors = []
        
        # Bulk Processing
        records = df.to_dict('records')
        batch_size = 500
        
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            td_numbers = [str(r.get(found_cols["TD NUMBER"], "")).strip() for r in batch if str(r.get(found_cols["TD NUMBER"], "")).strip()]
            
            # Fetch existing properties in this batch
            existing_props = {p.td_number: p for p in db_session.query(Property).filter(Property.td_number.in_(td_numbers)).all()}
            
            to_insert = []
            
            for index_in_batch, row in enumerate(batch):
                try:
                    td = str(row.get(found_cols["TD NUMBER"], "")).strip()
                    if not td: continue
                    
                    owner = str(row.get(found_cols["OWNER"], "")).strip()
                    kind = str(row.get(found_cols["KIND"], "LAND")).strip().upper()
                    loc = str(row.get(found_cols["LOCATION"], "")).strip()
                    try:
                        val = float(row.get(found_cols["VALUE"], 0))
                    except Exception as e:
                        mto_logger.warning(f"Error parsing value for TD {td}: {e}")
                        val = 0.0
                    
                    lot_val = str(row.get(found_cols["LOT"], "")).strip() if found_cols["LOT"] else ""
                    blk_val = str(row.get(found_cols["BLK"], "")).strip() if found_cols["BLK"] else ""
                    
                    # Smart Split: Handle combined Lot/Block with comma or space
                    if lot_val and not blk_val:
                        # Rule 1: Comma
                        if "," in lot_val:
                            lot_val = lot_val.split(",", 1)[0].strip()
                        
                        # Rule 2: 3+ Spaces
                        import re
                        if re.search(r"\s{3,}", lot_val):
                            lot_val = re.split(r"\s{3,}", lot_val, 1)[0].strip()

                        # Rule 3: Space Split with "Lot" preservation
                        if " " in lot_val:
                            parts = lot_val.split(" ")
                            if parts[0].upper() == "LOT" and len(parts) > 1:
                                lot_val = f"{parts[0]} {parts[1]}".strip()
                            else:
                                lot_val = parts[0].strip()

                    if td in existing_props:

                        prop = existing_props[td]
                        prop.owner_name = owner
                        prop.kind_of_property = kind
                        prop.assessed_value = val
                        prop.lot_number = lot_val
                        prop.block_number = "" # Discard the second part as requested
                        updated += 1

                    else:
                        to_insert.append({
                            "td_number": td,
                            "owner_name": owner,
                            "kind_of_property": kind,
                            "assessed_value": val,
                            "location": loc,
                            "lot_number": lot_val,
                            "block_number": "" # Discard the second part as requested
                        })
                        inserted += 1




                except Exception as row_err:
                    failed += 1
                    errors.append(f"Row {i + index_in_batch + 2}: {str(row_err)}")
            
            if to_insert:
                db_session.bulk_insert_mappings(Property, to_insert)
            
            db_session.flush()

        # Stage audit log before commit so data + audit are atomic
        log_action(user, f"Bulk Assessment Import: {inserted} new, {updated} updated.", db_session=db_session)
        db_session.commit()

        # Refresh system stats after bulk import — non-fatal, runs after the transaction
        try:
            from backend.services.stats_service import refresh_system_stats
            refresh_system_stats(db_session=db_session)
        except Exception as stats_err:
            print(f"Stats refresh failed: {stats_err}")

        return {"inserted": inserted, "updated": updated, "failed": failed, "errors": errors}

    except Exception as e:
        db_session.rollback()
        return {"success": False, "error": str(e)}

def validate_payment_import(file_content, file_extension, db_session: Session = None):
    """
    Validates a payment Excel file with smart conflict detection for Assessed Value.

    Supported template headers (case-insensitive):
      TD NUMBER, Assessed Value, Tax Year, PENALTY, DISCOUNT, AMOUNT, OR NUMBER, DATE
    """
    try:
        df = pd.read_excel(io.BytesIO(file_content)) if file_extension.lower() != '.csv' else pd.read_csv(io.BytesIO(file_content))
        df.columns = [str(c).strip().upper() for c in df.columns]

        mapping = {
            # Required
            "td_number":    ["TD NUMBER", "TD NO.", "TD NO", "TAX DECLARATION", "TD_NO", "TDNUMBER"],
            "or_number":    ["OR NUMBER", "OR NO.", "OR NO", "RECEIPT NO", "OR_NO", "ORNUMBER", "OR"],
            "amount_paid":  ["AMOUNT", "TOTAL", "TOTAL PAID", "AMOUNT PAID", "TOTAL_AMOUNT", "BASIC", "AMT"],
            # Optional — owner_name is looked up from the DB via TD number
            "owner_name":   ["OWNER", "OWNER NAME", "DECLARED OWNER", "OWNER_NAME", "PROPERTY OWNER"],
            "tax_year":     ["TAX YEAR", "YEAR", "TAX_YEAR", "PERIOD", "TAXYEAR"],
            "penalty":      ["PENALTY", "SURCHARGE", "PENALTY_AMOUNT"],
            "discount":     ["DISCOUNT", "LESS", "DISCOUNT_AMOUNT"],
            "date_paid":    ["DATE", "DATE PAID", "PAYMENT DATE", "OR DATE", "DATE_PAID"],
            "assessed_value": ["ASSESSED VALUE", "VALUE", "MARKET VALUE", "ASS_VALUE", "ASSESSEDVALUE"],
        }

        # Only td_number, or_number, and amount_paid are truly required
        REQUIRED = {"td_number", "or_number", "amount_paid"}

        found_cols = {}
        for field, aliases in mapping.items():
            match = next((c for c in df.columns if c in aliases), None)
            if match is None and field in REQUIRED:
                return {
                    "success": False,
                    "error": (
                        f"Missing required column for '{field}'. "
                        f"Expected one of: {', '.join(aliases[:4])}. "
                        f"Your headers: {', '.join(df.columns.tolist()[:8])}"
                    )
                }
            found_cols[field] = match
        
        results = []
        data_to_import = []

        # Pre-fetch properties for speed
        td_list = [DataCleanser.to_str(r.get(found_cols["td_number"])) for _, r in df.iterrows()]
        props = {p.td_number: p for p in db_session.query(Property).filter(Property.td_number.in_(td_list)).all()}

        # Pre-fetch existing OR numbers from the DB — keyed by (or_number, tax_year)
        # so we can distinguish true duplicates from same-OR-different-year cases.
        existing_or_keys = {
            (r[0], str(r[1]) if r[1] else "")
            for r in db_session.query(Payment.or_number, Payment.tax_year).filter(
                Payment.or_number != None,
                Payment.or_number != ""
            ).all()
        }
        # Also keep a set of just OR numbers for the "different tax year" warning
        existing_or_numbers = {k[0] for k in existing_or_keys}

        # Track (or_number, tax_year) pairs seen within this file
        seen_in_file: set = set()

        for index, row in df.iterrows():
            errors = []
            td = DataCleanser.to_str(row.get(found_cols["td_number"]))
            # owner_name is optional in the template — fall back to DB value
            owner_col = found_cols.get("owner_name")
            excel_owner = DataCleanser.to_str(row.get(owner_col)) if owner_col else ""
            or_no   = DataCleanser.to_str(row.get(found_cols["or_number"])) if found_cols.get("or_number") else ""
            amt     = DataCleanser.to_float(row.get(found_cols["amount_paid"])) if found_cols.get("amount_paid") else 0.0
            pnlty   = DataCleanser.to_float(row.get(found_cols["penalty"])) if found_cols.get("penalty") else 0.0
            dscnt   = DataCleanser.to_float(row.get(found_cols["discount"])) if found_cols.get("discount") else 0.0
            excel_av = DataCleanser.to_float(row.get(found_cols["assessed_value"])) if found_cols.get("assessed_value") else 0.0
            
            prop = props.get(td)
            status = "✅ VALID"
            msg = "Ready to import"
            system_owner = prop.owner_name if prop else "N/A"
            
            if not td: errors.append("Missing TD Number")
            elif not prop: errors.append(f"TD {td} not found in system")

            if not or_no: errors.append("Missing OR Number")
            if amt <= 0 and pnlty <= 0: errors.append("Invalid Amount")

            # ── Duplicate detection ───────────────────────────────────────
            tax_yr_str = DataCleanser.to_str(row.get(found_cols["tax_year"])) if found_cols.get("tax_year") else ""
            or_key = (or_no, tax_yr_str)

            if or_no:
                if or_key in seen_in_file:
                    # Exact duplicate within this file (same OR + same tax year)
                    errors.append(f"Duplicate in file: OR {or_no} / {tax_yr_str} appears more than once")
                elif or_key in existing_or_keys:
                    # Exact duplicate in the DB (same OR + same tax year)
                    errors.append(f"Duplicate: OR {or_no} for tax year {tax_yr_str} already posted in system")
                elif or_no in existing_or_numbers:
                    # Same OR number exists but with a different tax year — warn, don't block
                    if status == "✅ VALID":
                        status = "⚠️ WARNING"
                        msg = f"OR {or_no} exists in system with a different tax year — verify before importing"

                # Track this (OR, tax_year) pair for intra-file duplicate detection
                seen_in_file.add(or_key)
            
            if errors:
                status = "❌ ERROR"
                msg = "; ".join(errors)
            elif prop:
                # AV CONFLICT CHECK
                db_av = float(prop.assessed_value)
                if excel_av > 0 and abs(excel_av - db_av) > 0.01:
                    status = "⚠️ CONFLICT"
                    msg = f"AV Mismatch: System has {db_av:,.2f}, Excel has {excel_av:,.2f}"
            
            results.append({
                "row_index": index + 2,
                "td_number": td,
                "system_owner": system_owner,
                "or_number": or_no,
                "tax_year": DataCleanser.to_str(row.get(found_cols["tax_year"])) if found_cols.get("tax_year") else "",
                "amount_paid": f"{amt:,.2f}",
                "penalty": f"{pnlty:,.2f}",
                "discount": f"{dscnt:,.2f}",
                "status": status,
                "message": msg
            })

            if status != "❌ ERROR":
                data_to_import.append({
                    "property_id": prop.id if prop else None,
                    "td_number": td,
                    "amount": amt,
                    "penalty": abs(pnlty),
                    "discount": abs(dscnt),
                    "or_number": or_no,
                    "tax_year": DataCleanser.to_str(row.get(found_cols["tax_year"])) if found_cols.get("tax_year") else "",
                    "date_paid": DataCleanser.to_str(row.get(found_cols["date_paid"])) if found_cols.get("date_paid") else "",
                    "posted_by": "NONE"
                })

        return {"success": True, "report": results, "total_rows": len(df), "valid_rows": len(data_to_import), "data": data_to_import}
    except Exception as e:
        return {"success": False, "error": str(e)}

def commit_payment_import(data_list, user, db_session: Session = None):
    """
    Commits validated payment records to the financial ledger.
    Per-row error handling: a single bad row (duplicate OR, bad date, etc.)
    is skipped and logged rather than rolling back the entire batch.
    """
    from backend.services.system_service import log_action
    try:
        inserted = 0
        skipped = 0
        skip_reasons = []

        for row in data_list:
            pid = row.get("property_id")
            if not pid:
                skipped += 1
                skip_reasons.append(f"OR {row.get('or_number', '?')}: no property_id")
                continue

            # Date parsing
            raw_date = row.get("date_paid")
            try:
                if raw_date:
                    date_obj = pd.to_datetime(raw_date).to_pydatetime()
                    if date_obj.tzinfo is None:
                        date_obj = date_obj.replace(tzinfo=timezone.utc)
                else:
                    date_obj = datetime.now(timezone.utc)
            except Exception:
                date_obj = datetime.now(timezone.utc)

            # Per-row try — one bad row skips, doesn't kill the batch
            try:
                payment = Payment(
                    property_id=pid,
                    amount=row["amount"],
                    penalty=row.get("penalty", 0.0),
                    discount=row.get("discount", 0.0),
                    or_number=row["or_number"],
                    tax_year=row["tax_year"],
                    date_paid=date_obj,
                    posted_by=row.get("posted_by", "NONE"),
                )
                db_session.add(payment)
                db_session.flush()  # get payment.id

                year_str = row["tax_year"]
                year = (
                    int(year_str)
                    if year_str and str(year_str).strip().isdigit()
                    else datetime.now(timezone.utc).year
                )

                billing = db_session.query(PropertyBilling).filter(
                    PropertyBilling.property_id == pid,
                    PropertyBilling.tax_year == year,
                ).first()

                if not billing:
                    prop = db_session.query(Property).filter(Property.id == pid).first()
                    av = float(prop.assessed_value or 0.0) if prop else 0.0
                    is_prop_year = str(year) == (prop.tax_year if prop else "")
                    billing_pen = float(row.get("penalty", 0.0))
                    billing_disc = float(row.get("discount", 0.0))
                    if is_prop_year and prop:
                        billing_pen = max(billing_pen, float(prop.penalty or 0.0))
                        billing_disc = max(billing_disc, float(prop.discount or 0.0))
                    billing = PropertyBilling(
                        property_id=pid,
                        tax_year=year,
                        assessed_value=av,
                        penalty=billing_pen,
                        discount=billing_disc,
                        amount_paid=0.0,
                    )
                    db_session.add(billing)
                    db_session.flush()
                else:
                    billing.penalty = float(billing.penalty or 0.0) + float(row.get("penalty", 0.0))
                    billing.discount = float(billing.discount or 0.0) + float(row.get("discount", 0.0))

                from backend.services.billing_service import sync_payment_billings
                sync_payment_billings(
                    None,
                    payment.id,
                    [{"billing_id": billing.id, "tax_year": year, "applied_amount": row["amount"]}],
                    db_session=db_session,
                )
                inserted += 1

            except Exception as row_err:
                db_session.rollback()
                skipped += 1
                reason = f"OR {row.get('or_number', '?')}: {str(row_err)[:120]}"
                skip_reasons.append(reason)
                mto_logger.warning(f"Payment import skipped row: {reason}")

        log_action(
            user,
            f"Bulk Imported {inserted} Payment Records. Skipped: {skipped}.",
            db_session=db_session,
        )
        db_session.commit()

        try:
            from backend.services.stats_service import refresh_system_stats
            refresh_system_stats(db_session=db_session)
        except Exception as e:
            mto_logger.warning(f"Stats refresh failed after payment import: {e}")

        return {
            "inserted": inserted,
            "skipped": skipped,
            "skip_reasons": skip_reasons[:20],
        }

    except Exception as e:
        db_session.rollback()
        mto_logger.error(f"commit_payment_import failed: {e}")
        raise
        raise


def save_import_cache(data: list) -> str | None:
    """
    Saves the validated dictionary array as a JSON file under
    import_cache/import_{token}.json and returns a secure UUID token.

    Returns None if the cache file cannot be written (disk full, permission
    error, etc.). The caller should check for None and skip adding the token
    to the response rather than letting an OSError propagate to the client.
    """
    import os
    import json
    import uuid
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "import_cache")
    try:
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)
        token = uuid.uuid4().hex
        file_path = os.path.join(cache_dir, f"import_{token}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return token
    except OSError as e:
        mto_logger.error(f"save_import_cache: failed to write cache file: {e}")
        return None

def load_import_cache(token: str) -> Optional[list]:
    """Reads the JSON array back from the cache file and immediately deletes it to conserve server space."""
    import os
    import json
    if not token or not isinstance(token, str):
        return None
    # Sanitize token to prevent directory traversal
    clean_token = re.sub(r'[^a-f0-9]', '', token.lower())
    if not clean_token:
        return None
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "import_cache")
    file_path = os.path.join(cache_dir, f"import_{clean_token}.json")
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        try:
            os.remove(file_path)
        except Exception as e:
            mto_logger.warning(f"Failed to delete import cache file {file_path}: {e}")
        return data
    except Exception as e:
        mto_logger.error(f"Failed to load import cache for token {token}: {e}")
        return None

def prune_old_import_cache(max_age_seconds: int = 3600):
    """Background file utility to delete any validation cache files older than 1 hour."""
    import os
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "import_cache")
    if not os.path.exists(cache_dir):
        return
    now = datetime.now(timezone.utc).timestamp()
    for filename in os.listdir(cache_dir):
        if filename.startswith("import_") and filename.endswith(".json"):
            file_path = os.path.join(cache_dir, filename)
            try:
                mtime = os.path.getmtime(file_path)
                if now - mtime > max_age_seconds:
                    os.remove(file_path)
                    mto_logger.info(f"Pruned old import cache file: {filename}")
            except Exception as e:
                mto_logger.warning(f"Failed to prune old cache file {file_path}: {e}")
