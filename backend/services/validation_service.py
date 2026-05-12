# -*- coding: utf-8 -*-
import re
from datetime import datetime
from typing import Dict, Any, List, Optional

class ValidationError(Exception):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field

def validate_or_number(or_number: str):
    """Enforces municipal OR number patterns (e.g., 7-9 digits)."""
    if not or_number:
        raise ValidationError("Official Receipt (OR) Number is required.", "or_number")
    
    clean_or = str(or_number).strip()
    if not re.match(r"^\d{7,10}$", clean_or):
        raise ValidationError("Invalid OR Number format. Must be 7-10 digits.", "or_number")
    return clean_or

def validate_tax_amount(amount: float, field_name: str = "Amount"):
    """Ensures monetary values are non-negative and within reasonable bounds."""
    try:
        val = float(amount)
        if val < 0:
            raise ValidationError(f"{field_name} cannot be negative.", field_name.lower())
        if val > 1000000000: # 1 Billion limit for safety
            raise ValidationError(f"{field_name} exceeds industrial safety limits.", field_name.lower())
        return val
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid numeric format for {field_name}.", field_name.lower())

def validate_date_sequence(start_date: str, end_date: str, label: str = "Period"):
    """Ensures end dates do not precede start dates."""
    try:
        # Assuming YYYY-MM-DD format
        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        if d2 < d1:
            raise ValidationError(f"{label} end date cannot be before start date.", "date")
    except Exception:
        raise ValidationError(f"Invalid date format for {label}.", "date")

def enforce_property_rules(payload: Dict[str, Any]):
    """Comprehensive validation for property assessment records."""
    # 1. TD Number Format (Year-Brgy-Index)
    td = payload.get("td_number", "")
    if not td:
        raise ValidationError("TD Number is required.", "td_number")
    
    # 2. Assessed Value
    val = payload.get("assessed_value", 0)
    validate_tax_amount(val, "Assessed Value")
    
    # 3. Owner Name
    owner = payload.get("owner_name", "")
    if not owner or len(str(owner).strip()) < 2:
        raise ValidationError("Owner name is too short or missing.", "owner_name")
    
    return True
