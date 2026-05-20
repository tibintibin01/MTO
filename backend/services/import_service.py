# -*- coding: utf-8 -*-
import pandas as pd
import io
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy import or_, text
from sqlalchemy.orm import Session
from backend.models import Property, PropertyAssessmentHistory, Payment, PropertyBilling
from backend.database import SessionLocal


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
        except: return 0.0

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
    """
    try:
        if file_extension.lower() == '.csv':
            df = pd.read_csv(io.BytesIO(file_content))
        else:
            df = pd.read_excel(io.BytesIO(file_content))
        
        # Standardize column names (lowercase and underscores)
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        
        # Required fields mapping
        required_fields = {
            "td_number": ["td_no", "td_number", "tax_declaration"],
            "owner_name": ["owner", "owner_name", "declared_owner"],
            "assessed_value": ["value", "assessed_value", "assessment"]
        }
        
        # Check if basic columns exist
        found_cols = {}
        for db_field, aliases in required_fields.items():
            match = next((c for c in df.columns if c in aliases), None)
            if not match:
                return {"success": False, "error": f"Missing required column for '{db_field}'. Please check your headers."}
            found_cols[db_field] = match
        
        # Get existing TD numbers for duplicate check
        existing_tds = {r[0] for r in db_session.query(Property.td_number).all()}
            
        results = []
        rows_to_import = []
        
        for index, row in df.iterrows():
            errors = []
            row_data = row.to_dict()
            
            # 1. Check TD Number
            td = DataCleanser.to_str(row_data.get(found_cols["td_number"], ""))
            if not td:
                errors.append("Missing TD Number")
            elif td in existing_tds:
                errors.append(f"Duplicate TD Number: {td} already exists")
            
            # 2. Check Owner
            owner = DataCleanser.to_str(row_data.get(found_cols["owner_name"], ""))
            if not owner:
                errors.append("Missing Owner Name")
                
            try:
                raw_val = row_data.get(found_cols["assessed_value"], 0)
                val = float(raw_val) if not pd.isna(raw_val) else 0.0
                if val < 0: errors.append("Assessed Value cannot be negative")
            except:
                errors.append("Invalid numeric format for Assessed Value")
                
            status = "❌ ERROR" if errors else "✅ VALID"
            
            results.append({
                "row_index": index + 2,
                "td_number": td,
                "owner_name": owner,
                "status": status,
                "message": "; ".join(errors) if errors else "Ready to import"
            })
            
            if not errors:
                rows_to_import.append({
                    "td_number": td,
                    "owner_name": owner,
                    "assessed_value": val,
                    "location": DataCleanser.to_str(row_data.get("location")),
                    "lot_number": DataCleanser.to_str(row_data.get("lot_number")),
                    "area": DataCleanser.to_str(row_data.get("area")),
                    "kind_of_property": DataCleanser.to_str(row_data.get("kind_of_property")),
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
        
        # Get existing TD numbers to determine INSERT vs UPDATE
        existing_tds = {r[0] for r in db_session.query(Property.td_number).all()}

        for index, row in df.iterrows():
            errors = []
            td = DataCleanser.to_str(row.get(found_cols.get("td_number")))
            owner = DataCleanser.to_str(row.get(found_cols.get("owner_name")))
            
            if not td: errors.append("Missing TD Number")
            if not owner: errors.append("Missing Owner Name")
            
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
        except: pass

    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    inserted = 0
    updated = 0
    total = len(data_list)
    
    try:
        for i, row in enumerate(data_list):
            td = row["td_number"]
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
            
            if i % 10 == 0 or i == total - 1:
                db_session.flush()
                percentage = int(((i + 1) / total) * 100)
                try:
                    asyncio.run_coroutine_threadsafe(
                        report_progress(percentage, f"Importing: {i+1} / {total} records"), 
                        loop
                    )
                except: pass
        
        log_action(user, f"Wizard Assessment Import: {inserted} new, {updated} updated.", db_session=db_session)
        db_session.commit()
        return {"inserted": inserted, "updated": updated}
    except Exception as e:
        db_session.rollback()
        raise e

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
        except: pass

    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except:
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
                except: pass
        
        log_action(user, f"Bulk imported {count} property records.", db_session=db_session)
        db_session.commit()
        return count
    except Exception as e:
        db_session.rollback()
        raise e

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
                    except:
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
    """
    try:
        df = pd.read_excel(io.BytesIO(file_content)) if file_extension.lower() != '.csv' else pd.read_csv(io.BytesIO(file_content))
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        mapping = {
            "td_number": ["TD NO.", "TD NUMBER", "TAX DECLARATION", "TD_NO"],
            "owner_name": ["OWNER", "OWNER NAME", "DECLARED OWNER", "OWNER_NAME"],
            "or_number": ["OR NO.", "OR NUMBER", "RECEIPT NO", "OR_NO"],
            "tax_year": ["YEAR", "TAX YEAR", "TAX_YEAR", "PERIOD"],
            "amount_paid": ["TOTAL", "TOTAL PAID", "AMOUNT", "AMOUNT PAID", "TOTAL_AMOUNT", "BASIC"],
            "penalty": ["PENALTY", "SURCHARGE", "PENALTY_AMOUNT"],
            "discount": ["DISCOUNT", "LESS", "DISCOUNT_AMOUNT"],
            "date_paid": ["DATE", "DATE PAID", "PAYMENT DATE", "OR DATE"],
            "assessed_value": ["ASSESSED VALUE", "VALUE", "MARKET VALUE", "ASS_VALUE"]
        }
        
        found_cols = {f: next((c for c in df.columns if c in aliases), None) for f, aliases in mapping.items()}
        
        results = []
        data_to_import = []
        
        # Pre-fetch properties for speed
        td_list = [DataCleanser.to_str(r.get(found_cols["td_number"])) for _, r in df.iterrows()]
        props = {p.td_number: p for p in db_session.query(Property).filter(Property.td_number.in_(td_list)).all()}

        for index, row in df.iterrows():
            errors = []
            td = DataCleanser.to_str(row.get(found_cols["td_number"]))
            excel_owner = DataCleanser.to_str(row.get(found_cols["owner_name"]))
            or_no = DataCleanser.to_str(row.get(found_cols["or_number"]))
            amt = DataCleanser.to_float(row.get(found_cols["amount_paid"]))
            pnlty = DataCleanser.to_float(row.get(found_cols["penalty"]))
            dscnt = DataCleanser.to_float(row.get(found_cols["discount"]))
            excel_av = DataCleanser.to_float(row.get(found_cols["assessed_value"]))
            
            prop = props.get(td)
            status = "✅ VALID"
            msg = "Ready to import"
            system_owner = prop.owner_name if prop else "N/A"
            
            if not td: errors.append("Missing TD Number")
            elif not prop: errors.append(f"TD {td} not found in system")
            
            if not or_no: errors.append("Missing OR Number")
            if amt <= 0 and pnlty <= 0: errors.append("Invalid Amount")
            
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
                "tax_year": DataCleanser.to_str(row.get(found_cols["tax_year"])),
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
                    "tax_year": DataCleanser.to_str(row.get(found_cols["tax_year"])),
                    "date_paid": DataCleanser.to_str(row.get(found_cols["date_paid"])),
                    "posted_by": "NONE"
                })

        return {"success": True, "report": results, "total_rows": len(df), "valid_rows": len(data_to_import), "data": data_to_import}
    except Exception as e:
        return {"success": False, "error": str(e)}

def commit_payment_import(data_list, user, db_session: Session = None):
    """
    Commits validated payment records to the financial ledger.
    """
    from backend.services.system_service import log_action
    try:
        inserted = 0
        for row in data_list:
            pid = row.get("property_id")
            if not pid: continue
            
            # Robust Date Parsing
            raw_date = row.get("date_paid")
            try:
                if raw_date:
                    date_obj = pd.to_datetime(raw_date).to_pydatetime()
                else:
                    date_obj = datetime.now()
            except:
                date_obj = datetime.now()

            # 1. Save Payment Record
            payment = Payment(
                property_id=pid,
                amount=row["amount"],
                penalty=row.get("penalty", 0.0),
                discount=row.get("discount", 0.0),
                or_number=row["or_number"],
                tax_year=row["tax_year"],
                date_paid=date_obj,
                posted_by=row.get("posted_by", "NONE")
            )
            db_session.add(payment)
            db_session.flush() # Populate payment.id
            
            # 2. Update Property Billing (to reflect in Receivables)
            year = row["tax_year"]
            billing = db_session.query(PropertyBilling).filter(
                PropertyBilling.property_id == pid,
                PropertyBilling.tax_year == year
            ).first()
            
            if not billing:
                # Find the property to get assessed value
                prop = db_session.query(Property).filter(Property.id == pid).first()
                av = float(prop.assessed_value or 0.0) if prop else 0.0
                
                # Determine penalty and discount
                is_prop_year = (year == (prop.tax_year if prop else ""))
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
                    amount_paid=0.0
                )
                db_session.add(billing)
                db_session.flush() # Populate billing.id
            else:
                # Add penalty and discount
                billing.penalty = float(billing.penalty or 0.0) + float(row.get("penalty", 0.0))
                billing.discount = float(billing.discount or 0.0) + float(row.get("discount", 0.0))
                
            # 3. Create PaymentBilling Link and update amount_paid
            from backend.services.billing_service import sync_payment_billings
            sync_payment_billings(
                None, 
                payment.id, 
                [{"billing_id": billing.id, "tax_year": year, "applied_amount": row["amount"]}], 
                db_session=db_session
            )

            inserted += 1
            
        # Stage audit log before commit so data + audit are atomic
        log_action(user, f"Bulk Imported {inserted} Payment Records to Ledger.", db_session=db_session)
        db_session.commit()

        # Refresh system stats — non-fatal, runs after the transaction
        try:
            from backend.services.stats_service import refresh_system_stats
            refresh_system_stats(db_session=db_session)
        except:
            pass

        return {"inserted": inserted}
    except Exception as e:
        db_session.rollback()
        raise e
