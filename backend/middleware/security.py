# -*- coding: utf-8 -*-
import os
import asyncio
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from utils.logger import mto_logger
from backend.error_codes import error_response, E

# --- SECURITY HEADERS MIDDLEWARE ---
async def security_headers_middleware(request: Request, call_next):
    """
    Injects security response headers into every API response.
    """
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    # HSTS: instruct browsers to only connect via HTTPS for 1 year.
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# --- REQUEST BODY SIZE LIMIT MIDDLEWARE ---
_BODY_LIMIT_DEFAULT = 10 * 1024 * 1024   # 10 MB
_BODY_LIMIT_IMPORT  = 50 * 1024 * 1024   # 50 MB for bulk imports

async def request_body_size_middleware(request: Request, call_next):
    """Rejects oversized request bodies before they reach route handlers."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            size = int(content_length)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"code": "VALIDATION_ERROR", "detail": "Invalid Content-Length header."},
            )

        path = request.url.path
        limit = _BODY_LIMIT_IMPORT if path.startswith("/system/import") else _BODY_LIMIT_DEFAULT

        if size > limit:
            limit_mb = limit // (1024 * 1024)
            return JSONResponse(
                status_code=413,
                content={
                    "code": "PAYLOAD_TOO_LARGE",
                    "detail": f"Request body exceeds the {limit_mb} MB limit for this endpoint.",
                },
            )

    return await call_next(request)


# --- REQUEST TIMEOUT MIDDLEWARE ---
_DEFAULT_TIMEOUT = 30
_PATH_TIMEOUTS = {
    "/system/backup/trigger": 600,
    "/system/restore":        600,
    "/system/import/commit":  300,
    "/system/import/validate":300,
    "/billing/bulk-soa-pdf":  120,
}

async def request_timeout_middleware(request: Request, call_next):
    path = request.url.path
    timeout = _DEFAULT_TIMEOUT
    for prefix, t in _PATH_TIMEOUTS.items():
        if path.startswith(prefix):
            timeout = t
            break

    try:
        return await asyncio.wait_for(call_next(request), timeout=timeout)
    except asyncio.TimeoutError:
        mto_logger.warning(
            f"Request timeout after {timeout}s",
            method=request.method,
            path=path,
            ip=request.client.host if request.client else "unknown",
        )
        return error_response(
            E.TIMEOUT,
            f"Request timed out after {timeout} seconds. "
            "The operation may still be running in the background. "
            "Please refresh and check if the action completed.",
            request=request,
        )
