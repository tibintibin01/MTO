from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, ValidationInfo, field_validator
from typing import Optional, List, Any
from utils.sanitizer import sanitize_string, sanitize_numeric_string

class BaseSanitizedModel(BaseModel):
    """Base class that automatically sanitizes all string fields."""
    @field_validator("*", mode="before")
    @classmethod
    def sanitize_all_strings(cls, v: Any, info: ValidationInfo) -> Any:
        if isinstance(v, str):
            if "password" in str(info.field_name or "").lower():
                return v
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
    remarks: Optional[str] = Field(None, alias="Remarks")
    pin: Optional[str] = Field(None, alias="PIN")
    prev_td_number: Optional[str] = Field(None, alias="Previous TD Number")
    previous_property_id: Optional[int] = Field(None, alias="Previous Property ID")
    duplicate_td_verified: Optional[bool] = Field(False, alias="Verified Duplicate TD")
    duplicate_td_reason: Optional[str] = Field(None, alias="Duplicate TD Reason")
    duplicate_td_reference: Optional[str] = Field(None, alias="Assessor Reference")
    duplicate_td_confirmation: Optional[str] = Field(None, alias="Duplicate TD Confirmation")
    effectivity_date: Optional[str] = Field(None, alias="Effectivity Date")
    prior_assessed_value: Optional[Decimal] = Field(None, alias="Prior Assessed Value")
    prior_effectivity_year: Optional[str] = Field(None, alias="Prior Effectivity Year")
    version: Optional[int] = None

    @field_validator("td_number", "pin", "prev_td_number", mode="before")
    @classmethod
    def sanitize_ids(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_numeric_string(v)
        return v

    @field_validator(
        "assessed_value", "penalty", "discount", "amount_paid",
        "prior_assessed_value", mode="before",
    )
    @classmethod
    def coerce_to_decimal(cls, v: Any, info: ValidationInfo) -> Optional[Decimal]:
        """
        Coerce numeric inputs to Decimal to prevent float rounding errors.
        Accepts int, float, str, or Decimal. Returns None for None/empty.
        """
        if v is None:
            if info.field_name == "prior_assessed_value":
                return None
            return Decimal("0.00")
        if isinstance(v, Decimal):
            return v
        try:
            # Convert via str to avoid float precision loss (e.g. float 0.1 → "0.1")
            cleaned = str(v).replace(",", "").strip()
            if not cleaned and info.field_name == "prior_assessed_value":
                return None
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


class RecentPaymentSchema(BaseModel):
    """Stable dashboard contract for a successfully posted payment."""

    id: int
    date_paid: Optional[str] = None
    or_number: Optional[str] = None
    td_number: Optional[str] = None
    owner_name: Optional[str] = None
    tax_year: Optional[str] = None
    amount: float


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
