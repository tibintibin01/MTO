from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Any

class PropertySaveSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra='allow'
    )

    td_number: Optional[Any] = Field(None, alias="TD Number")
    owner_name: Optional[Any] = Field(None, alias="Owner Name")
    payor_name: Optional[Any] = Field(None, alias="Payor")
    lot_number: Optional[Any] = Field(None, alias="Lot Number")
    block_number: Optional[Any] = Field(None, alias="Block Number")
    area: Optional[Any] = Field(None, alias="Area")
    location: Optional[Any] = Field(None, alias="Location")
    barangay: Optional[Any] = Field(None, alias="Barangay")
    kind_of_property: Optional[Any] = Field(None, alias="Kind of Property")
    accountable_officer: Optional[Any] = Field(None, alias="Accountable Officer")
    assessed_value: Optional[Any] = Field(None, alias="Assessed Value")
    penalty: Optional[Any] = Field(None, alias="Penalty")
    discount: Optional[Any] = Field(None, alias="Discount")
    or_number: Optional[Any] = Field(None, alias="OR Number")
    or_date: Optional[Any] = Field(None, alias="OR Date")
    tax_year: Optional[Any] = Field(None, alias="Tax Year")
    amount_paid: Optional[Any] = Field(None, alias="Amount Paid")
    pin: Optional[Any] = Field(None, alias="PIN")
    prev_td_number: Optional[Any] = Field(None, alias="Previous TD Number")
    effectivity_date: Optional[Any] = Field(None, alias="Effectivity Date")

class ReceiptRecordSchema(BaseModel):
    property_id: int
    payment_id: int
    details: dict
    file_path: str
    user_name: str

class LogActionSchema(BaseModel):
    action: str

class UserUpdateSchema(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None

class UserCreateSchema(BaseModel):
    username: str = Field(..., min_length=3)
    full_name: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    role: str = "viewer"

class PasswordResetSchema(BaseModel):
    new_password: str = Field(..., min_length=6)
