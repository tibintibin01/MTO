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
    assessed_value: Optional[float] = Field(0.0, alias="Assessed Value")
    penalty: Optional[float] = Field(0.0, alias="Penalty")
    discount: Optional[float] = Field(0.0, alias="Discount")
    or_number: Optional[str] = Field(None, alias="OR Number")
    or_date: Optional[str] = Field(None, alias="OR Date")
    tax_year: Optional[str] = Field(None, alias="Tax Year")
    amount_paid: Optional[float] = Field(0.0, alias="Amount Paid")
    pin: Optional[str] = Field(None, alias="PIN")
    prev_td_number: Optional[str] = Field(None, alias="Previous TD Number")
    effectivity_date: Optional[str] = Field(None, alias="Effectivity Date")

    @field_validator("td_number", "pin", "prev_td_number", mode="before")
    @classmethod
    def sanitize_ids(cls, v: Any) -> Any:
        if isinstance(v, str):
            return sanitize_numeric_string(v)
        return v


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
    password: str = Field(..., min_length=6)
    role: str = "viewer"


class PasswordResetSchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str = Field(..., min_length=6)


class BulkUpdateBarangaySchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")
    ids: List[int]
    barangay: str
