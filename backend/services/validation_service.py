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
    """Comprehensive validation for property assessment records using aliased keys."""
    # 1. TD Number Format
    td = payload.get("TD Number") or payload.get("td_number")
    if not td or not str(td).strip():
        raise ValidationError("TD Number is required.", "td_number")
    
    # 2. Assessed Value
    val = payload.get("Assessed Value") or payload.get("assessed_value") or 0
    validate_tax_amount(val, "Assessed Value")
    
    # 3. Owner Name
    owner = payload.get("Owner Name") or payload.get("owner_name")
    if not owner or len(str(owner).strip()) < 2:
        raise ValidationError("Owner name is too short or missing.", "owner_name")
    
    return True

def validate_password_complexity(password: str):
    """
    Enforces government-grade password complexity requirements.
    Must be called before hashing inside create_user() and reset_user_password().
    """
    if not password or not isinstance(password, str):
        raise ValidationError("Password is required.", "password")
    if len(password) < 12:
        raise ValidationError("Password must be at least 12 characters long.", "password")
    if not re.search(r"[A-Z]", password):
        raise ValidationError("Password must contain at least one uppercase letter.", "password")
    if not re.search(r"[a-z]", password):
        raise ValidationError("Password must contain at least one lowercase letter.", "password")
    if not re.search(r"\d", password):
        raise ValidationError("Password must contain at least one digit (0-9).", "password")
    if not re.search(r"[!@#$%^&*()\-_=+\[\]{}|;:',.<>?/`~\"\\]", password):
        raise ValidationError("Password must contain at least one special character.", "password")
    return True
