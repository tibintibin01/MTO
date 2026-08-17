# -*- coding: utf-8 -*-

from typing import Optional

from pydantic import ConfigDict, Field, field_validator

from backend.schemas import BaseSanitizedModel


class PortfolioCreateSchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if len(cleaned) < 2:
            raise ValueError("Portfolio name must contain at least two characters.")
        return cleaned


class PortfolioUpdateSchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=2, max_length=255)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()
        if len(cleaned) < 2:
            raise ValueError("Portfolio name must contain at least two characters.")
        return cleaned


class PortfolioPropertyLinkSchema(BaseSanitizedModel):
    model_config = ConfigDict(extra="forbid")

    property_id: int = Field(..., gt=0)
