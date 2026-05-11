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

        return {
            "success": True, 
            "report": results, 
            "total_rows": len(df),
            "valid_rows": len(rows_to_import),
            "data": rows_to_import if len(rows_to_import) == len(df) else [] # Only return if 100% clean for now
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}

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

    return db.execute_transaction(operation)
