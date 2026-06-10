# -*- coding: utf-8 -*-
"""Regression tests for property effectivity-date normalization."""

import pytest
from fastapi import HTTPException

from backend.services.property_service import _normalize_effectivity_date


def test_normalize_effectivity_accepts_year_only():
    assert _normalize_effectivity_date("2023") == "2023-01-01"


def test_normalize_effectivity_accepts_full_iso_date():
    assert _normalize_effectivity_date("2023-07-15") == "2023-07-15"


def test_normalize_effectivity_accepts_slash_date():
    assert _normalize_effectivity_date("07/15/2023") == "2023-07-15"


def test_normalize_effectivity_rejects_invalid_text():
    with pytest.raises(HTTPException) as exc:
        _normalize_effectivity_date("year 2023")

    assert exc.value.status_code == 422
    assert "Effectivity" in exc.value.detail