from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Any
from utils.sanitizer import sanitize_string, sanitize_numeric_string

class BaseSanitizedModel(BaseModel):
    """Base class that automatically sanitizes all string fields."""
    @field_validator("*", mode="before")
    @classmethod
    def sanitize_all_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_string(v)
        return v

class PropertySaveSchema(BaseSanitizedModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    td_number: Optional[str] = Field(None, alias="TD Number")
    owner_name: Optional[str] = Field(None, alias="Owner Name")
    payor_name: Optional[str] = Field(None, alias="Payor")
    lot_number: Optional[str] = Field(None, alias="Lot Number")
    block_number: Optional[str] = Field(None, alias="Block Number")
    area: Optional[str] = Field(None, alias="Area")
    location: Optional[str] = Field(None, alias="Location")
    barangay: Optional[str] = Field(None, alias="Barangay")
    kind_of_property: Optional[str] = Field(None, alias="Kind of Property")
    accountable_officer: Optional[str] = Field(None, alias="Accountable Officer")
    # --- WIN 1: Use Decimal for all monetary fields to prevent float rounding errors ---
    assessed_value: Optional[Decimal] = Field(Decimal("0.00"), alias="Assessed Value")
    penalty: Optional[Decimal] = Field(Decimal("0.00"), alias="Penalty")
    discount: Optional[Decimal] = Field(Decimal("0.00"), alias="Discount")
    or_number: Optional[str] = Field(None, alias="OR Number")
    or_date: Optional[str] = Field(None, alias="OR Date")
    tax_year: Optional[str] = Field(None, alias="Tax Year")
    amount_paid: Optional[Decimal] = Field(Decimal("0.00"), alias="Amount Paid")
    pin: Optional[str] = Field(None, alias="PIN")
    prev_td_number: Optional[str] = Field(None, alias="Previous TD Number")
    effectivity_date: Optional[str] = Field(None, alias="Effectivity Date")
    version: Optional[int] = None

    @field_validator("td_number", "pin", "prev_td_number", mode="before")
    @classmethod
    def sanitize_ids(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_numeric_string(v)
        return v

    @field_validator("assessed_value", "penalty", "discount", "amount_paid", mode="before")
    @classmethod
    def coerce_to_decimal(cls, v: Any) -> Optional[Decimal]:
        """
        Coerce numeric inputs to Decimal to prevent float rounding errors.
        Accepts int, float, str, or Decimal. Returns None for None/empty.
        """
        if v is None:
            return Decimal("0.00")
        if isinstance(v, Decimal):
            return v
        try:
            # Convert via str to avoid float precision loss (e.g. float 0.1 → "0.1")
            cleaned = str(v).replace(",", "").strip()
            return Decimal(cleaned) if cleaned else Decimal("0.00")
        except Exception:
            return Decimal("0.00")


class ReceiptRecordSchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")
    
    property_id: int
    payment_id: int
    details: dict
    file_path: str
    user_name: str


class LogActionSchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")
    action: str


class UserUpdateSchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserCreateSchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(..., min_length=3)
    full_name: str = Field(..., min_length=3)
    # min_length=12 matches validate_password_complexity requirements.
    # Raised from 6 to 12 to match the PasswordResetSchema and server-side rules.
    password: str = Field(..., min_length=12)
    role: str = "viewer"


class PasswordResetSchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")
    # min_length=12 matches validate_password_complexity requirements.
    # The full rules (uppercase, lowercase, digit, special char) are enforced
    # server-side in validation_service.py — the schema only guards length.
    new_password: str = Field(..., min_length=12)


class BulkUpdateBarangaySchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")
    ids: List[int]
    barangay: str
