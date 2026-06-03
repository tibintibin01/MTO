# -*- coding: utf-8 -*-
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi.errors import RateLimitExceeded as _RateLimitExceeded
from utils import get_request_id

def _get_req_id() -> str:
    try:
        return get_request_id()
    except Exception:
        return "SYSTEM"

async def rate_limit_handler(request: Request, exc: _RateLimitExceeded):
    """Returns 429 with Retry-After header so clients know when to retry."""
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={
            "code": "RATE_LIMITED",
            "detail": "Too many requests. Please slow down.",
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = exc.body
    if hasattr(body, "items"):
        try:
            body = dict(body)
        except Exception:
            body = str(body)
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "detail": "Request validation failed.",
            "errors": exc.errors(),
            "request_id": _get_req_id(),
        },
    )

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Global HTTP exception handler — ensures every error response has a
    structured `code` field regardless of where the exception was raised.
    """
    detail = exc.detail

    # Already structured — raised via raise_api_error()
    if isinstance(detail, dict) and "code" in detail:
        body = {**detail, "request_id": _get_req_id()}
        return JSONResponse(status_code=exc.status_code, content=body)

    # Plain string detail — infer a code from the status
    _inferred = {
        400: "BAD_REQUEST",
        401: "AUTH_TOKEN_INVALID",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        503: "DB_UNAVAILABLE",
        504: "TIMEOUT",
    }
    code = _inferred.get(exc.status_code, "INTERNAL_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "detail": str(detail) if detail else "An error occurred.",
            "request_id": _get_req_id(),
        },
    )
