# -*- coding: utf-8 -*-
"""
Structured error codes for the MTO Treasury API.

Every error response includes a machine-parseable `code` field alongside
the human-readable `detail` message. This lets the desktop client branch
on the code rather than doing fragile string matching on the message text.

Response shape:
    {
        "code":    "AUTH_ACCOUNT_LOCKED",          # stable, never changes
        "detail":  "Account locked for 5 minutes.", # human-readable, may change
        "request_id": "abc-123"                     # for support tracing
    }

Usage in route handlers:
    from backend.error_codes import raise_api_error, E

    raise_api_error(E.NOT_FOUND, "Property TD-001 not found.")
    raise_api_error(E.AUTH_ACCOUNT_LOCKED, f"Try again in {minutes} minute(s).")
"""

from enum import Enum
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from utils.logger import mto_logger


class E(str, Enum):
    """Stable error code identifiers. Never rename these — clients depend on them."""

    # Authentication
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_ACCOUNT_LOCKED      = "AUTH_ACCOUNT_LOCKED"
    AUTH_ACCOUNT_DISABLED    = "AUTH_ACCOUNT_DISABLED"
    AUTH_TOKEN_EXPIRED       = "AUTH_TOKEN_EXPIRED"
    AUTH_TOKEN_INVALID       = "AUTH_TOKEN_INVALID"

    # Authorisation
    PERMISSION_DENIED        = "PERMISSION_DENIED"
    CSRF_VIOLATION           = "CSRF_VIOLATION"

    # Resource
    NOT_FOUND                = "NOT_FOUND"
    DUPLICATE_ENTRY          = "DUPLICATE_ENTRY"
    SYNC_CONFLICT            = "SYNC_CONFLICT"

    # Input
    VALIDATION_ERROR         = "VALIDATION_ERROR"

    # Infrastructure
    RATE_LIMITED             = "RATE_LIMITED"
    TIMEOUT                  = "TIMEOUT"
    DB_UNAVAILABLE           = "DB_UNAVAILABLE"
    INTERNAL_ERROR           = "INTERNAL_ERROR"


# Map each code to its default HTTP status code
_STATUS_MAP: dict[E, int] = {
    E.AUTH_INVALID_CREDENTIALS: 401,
    E.AUTH_ACCOUNT_LOCKED:      401,
    E.AUTH_ACCOUNT_DISABLED:    401,
    E.AUTH_TOKEN_EXPIRED:       401,
    E.AUTH_TOKEN_INVALID:       401,
    E.PERMISSION_DENIED:        403,
    E.CSRF_VIOLATION:           403,
    E.NOT_FOUND:                404,
    E.DUPLICATE_ENTRY:          409,
    E.SYNC_CONFLICT:            409,
    E.VALIDATION_ERROR:         422,
    E.RATE_LIMITED:             429,
    E.TIMEOUT:                  504,
    E.DB_UNAVAILABLE:           503,
    E.INTERNAL_ERROR:           500,
}


def raise_api_error(
    code: E,
    detail: str,
    status_code: int | None = None,
    extra: dict | None = None,
) -> None:
    """
    Raises an HTTPException with a structured body.

    The exception is caught by FastAPI's exception handler which converts
    it to a JSON response via the `api_error_handler` registered in main.py.
    """
    http_status = status_code or _STATUS_MAP.get(code, 500)
    # Attach the code and extra data to the exception detail as a dict
    # so the exception handler can serialize it properly.
    payload = {"code": code.value, "detail": detail}
    if extra:
        payload.update(extra)
    raise HTTPException(status_code=http_status, detail=payload)


def error_response(
    code: E,
    detail: str,
    request: Request | None = None,
    status_code: int | None = None,
    extra: dict | None = None,
) -> JSONResponse:
    """
    Returns a JSONResponse directly (for use in middleware where you
    can't raise HTTPException).
    """
    from utils import get_request_id
    http_status = status_code or _STATUS_MAP.get(code, 500)
    body = {
        "code": code.value,
        "detail": detail,
        "request_id": get_request_id(),
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=http_status, content=body)
