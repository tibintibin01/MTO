# -*- coding: utf-8 -*-
import pandas as pd
import io
import db_manager as db
from datetime import datetime

def validate_property_import(file_content, file_extension):
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
        
        # Required fields mapping (Mapping typical spreadsheet headers to DB fields)
        required_fields = {
            "td_number": ["td_no", "td_number", "tax_declaration"],
            "owner_name": ["owner", "owner_name", "declared_owner"],
            "assessed_value": ["value", "assessed_value", "assessment"]
        }
        
        results = []
        rows_to_import = []
        
        # Check if basic columns exist
        found_cols = {}
        for db_field, aliases in required_fields.items():
            match = next((c for c in df.columns if c in aliases), None)
            if not match:
                return {"success": False, "error": f"Missing required column for '{db_field}'. Please check your headers."}
            found_cols[db_field] = match

        # Get existing TD numbers for duplicate check
        existing_tds = set()
        rows = db.db_query("SELECT td_number FROM properties", fetch=True, commit=False) or []
        for r in rows:
            existing_tds.add(str(r[0]).strip())

        for index, row in df.iterrows():
            errors = []
            row_data = row.to_dict()
            
            # 1. Check TD Number
            td = str(row_data.get(found_cols["td_number"], "")).strip()
            if not td:
                errors.append("Missing TD Number")
            elif td in existing_tds:
                errors.append(f"Duplicate TD Number: {td} already exists")
            
            # 2. Check Owner
            owner = str(row_data.get(found_cols["owner_name"], "")).strip()
            if not owner:
                errors.append("Missing Owner Name")
                
            # 3. Check Assessed Value
            try:
                val = float(row_data.get(found_cols["assessed_value"], 0))
                if val < 0: errors.append("Assessed Value cannot be negative")
            except:
                errors.append("Invalid numeric format for Assessed Value")
                
            status = "❌ ERROR" if errors else "✅ VALID"
            
            results.append({
                "row_index": index + 2, # +2 for Excel/CSV row numbering (1-indexed + header)
                "td_number": td,
                "owner_name": owner,
                "status": status,
                "message": "; ".join(errors) if errors else "Ready to import"
            })
            
            if not errors:
                rows_to_import.append(row_data)

        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def validate_assessment_import(file_content, file_extension):
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
            "td_number": ["TD NO.", "TD NUMBER", "TAX DECLARATION"],
            "owner_name": ["PROPERTY OWNER", "OWNER NAME", "OWNER"],
            "assessed_value": ["ASSESSED VALUE", "VALUE", "MARKET VALUE"]
        }
        
        found_cols = {}
        for db_field, aliases in mapping.items():
            match = next((c for c in df.columns if c in aliases), None)
            if not match:
                return {"success": False, "error": f"Missing required column for '{db_field}'."}
            found_cols[db_field] = match

        results = []
        rows_to_import = []
        
        for index, row in df.iterrows():
            errors = []
            td = str(row.get(found_cols["td_number"], "")).strip()
            owner = str(row.get(found_cols["owner_name"], "")).strip()
            
            if not td: errors.append("Missing TD Number")
            if not owner: errors.append("Missing Owner Name")
            
            try:
                val = float(row.get(found_cols["assessed_value"], 0))
            except:
                errors.append("Invalid Numeric Value")
                
            status = "❌ ERROR" if errors else "✅ VALID"
            
            # Map for frontend preview
            results.append({
                "row_index": index + 2,
                "td_number": td,
                "owner_name": owner,
                "status": status,
                "message": "; ".join(errors) if errors else "Assessment record valid"
            })
            
            if not errors:
                # Store cleaned data for commit
                rows_to_import.append({
                    "td_number": td,
                    "owner_name": owner,
                    "assessed_value": val,
                    "location": str(row.get("LOCATION", "")).strip(),
                    "kind": str(row.get("KIND", "LAND")).strip().upper()
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

def commit_assessment_import(data_list, user):
    """
    Saves the validated assessment rows.
    """
    from backend.services.system_service import log_action
    
    def operation(cur):
        inserted = 0
        updated = 0
        for row in data_list:
            td = row["td_number"]
            cur.execute("SELECT id FROM properties WHERE td_number = %s", (td,))
            exists = cur.fetchone()
            
            if exists:
                cur.execute(
                    "UPDATE properties SET owner_name = %s, assessed_value = %s, updated_at = NOW() WHERE id = %s",
                    (row["owner_name"], row["assessed_value"], exists[0])
                )
                updated += 1
            else:
                cur.execute(
                    "INSERT INTO properties (td_number, owner_name, assessed_value, location, kind_of_property, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, NOW(), NOW())",
                    (td, row["owner_name"], row["assessed_value"], row["location"], row["kind"])
                )
                inserted += 1
        
        log_action(user, f"Wizard Assessment Import: {inserted} new, {updated} updated.")
        return {"inserted": inserted, "updated": updated}

    return db.execute_transaction(operation)

def commit_property_import(data_list, user):
    """
    Saves the validated rows to the database.
    """
    from backend.services.system_service import log_action
    
    def operation(cur):
        count = 0
        for row in data_list:
            # Map spreadsheet fields back to DB fields
            # This is a simplified version, ideally we map all possible fields
            cur.execute(
                """
                INSERT INTO properties (td_number, owner_name, assessed_value, created_at, updated_at)
                VALUES (%s, %s, %s, NOW(), NOW())
                """,
                (row.get("td_number"), row.get("owner_name"), row.get("assessed_value"))
            )
            count += 1
        
        log_action(user, f"Bulk imported {count} property records.")
        return count

def import_assessment_roll_from_excel(file_path, user):
    """
    Imports the entire Assessment Roll from an Excel file.
    Updates existing records or inserts new ones based on TD Number.
    """
    from backend.services.system_service import log_action
    import pandas as pd
    
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
            "KIND": ["CLASSIFICATION", "KIND", "KIND OF PROPERTY"]
        }
        
        found_cols = {}
        for key, aliases in mapping.items():
            match = next((c for c in df.columns if c in aliases), None)
            found_cols[key] = match

        def operation(cur):
            inserted = 0
            updated = 0
            failed = 0
            errors = []
            
            for index, row in df.iterrows():
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
                        
                    # Check if exists
                    cur.execute("SELECT id FROM properties WHERE td_number = %s", (td,))
                    exists = cur.fetchone()
                    
                    if exists:
                        cur.execute(
                            "UPDATE properties SET owner_name = %s, kind_of_property = %s, assessed_value = %s, updated_at = NOW() WHERE id = %s",
                            (owner, kind, val, exists[0])
                        )
                        updated += 1
                    else:
                        cur.execute(
                            "INSERT INTO properties (td_number, owner_name, kind_of_property, assessed_value, location, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, NOW(), NOW())",
                            (td, owner, kind, val, loc)
                        )
                        inserted += 1
                except Exception as row_err:
                    failed += 1
                    errors.append(f"Row {index+2}: {str(row_err)}")
            
            log_action(user, f"Bulk Assessment Import: {inserted} new, {updated} updated.")
            return {"inserted": inserted, "updated": updated, "failed": failed, "errors": errors}

        return db.execute_transaction(operation)
    except Exception as e:
        return {"success": False, "error": str(e)}
