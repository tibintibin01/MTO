# -*- coding: utf-8 -*-
import re
import hashlib
import json as _json
import base64
from datetime import datetime, timedelta, timezone
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response as StarletteResponse
from utils.logger import mto_logger
from backend.database import SessionLocal
from backend.models import IdempotencyKey

_IDEMPOTENCY_PATHS = (
    "/properties",
    "/payments",
    "/billing",
    "/users",
)

# Maximum response body size to cache in the idempotency store.
_IDEMPOTENCY_MAX_CACHE_BYTES = 64 * 1024  # 64 KB

async def idempotency_middleware(request: Request, call_next):
    # Only apply to state-changing methods on financial paths
    if request.method not in ("POST", "PUT", "PATCH"):
        return await call_next(request)

    path = request.url.path
    if not any(path.startswith(p) for p in _IDEMPOTENCY_PATHS):
        return await call_next(request)

    idempotency_key = request.headers.get("X-Idempotency-Key")
    if not idempotency_key:
        # No key provided — process normally (backwards compatible)
        return await call_next(request)

    # Validate key format — must be a UUID to prevent injection
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", idempotency_key.lower()):
        return JSONResponse(
            status_code=400,
            content={"code": "VALIDATION_ERROR", "detail": "X-Idempotency-Key must be a valid UUID v4."},
        )

    # Bind idempotency key to (user_id, sha256(request_body))
    # Read the body so we can hash it. We must re-inject it for the handler.
    body_bytes = await request.body()
    body_hash = hashlib.sha256(body_bytes).hexdigest()

    # Extract user_id from the JWT for scoping (no full auth — key extraction only)
    user_scope = "anon"
    try:
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
        if not token:
            token = request.cookies.get("access_token")
        if token:
            parts = token.split(".")
            if len(parts) == 3:
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = _json.loads(base64.b64decode(padded).decode("utf-8"))
                uid = payload.get("id") or payload.get("sub")
                if uid:
                    user_scope = str(uid)
    except Exception:
        pass

    # Composite cache key: UUID + user scope + body hash
    composite_key = f"{idempotency_key}:{user_scope}:{body_hash}"

    # Check for an existing non-expired response for this composite key
    try:
        with SessionLocal() as db:
            existing = db.query(IdempotencyKey).filter(
                IdempotencyKey.key == composite_key,
                IdempotencyKey.expires_at > datetime.now(timezone.utc),
            ).first()

            if existing:
                mto_logger.info(
                    f"Idempotency cache hit for key {idempotency_key[:8]}...",
                    method=request.method,
                    path=path,
                )
                cached_body = _json.loads(existing.response_body) if existing.response_body else {}
                return JSONResponse(
                    status_code=existing.status_code,
                    content=cached_body,
                    headers={"X-Idempotency-Replayed": "true"},
                )
    except Exception as e:
        # DB error checking idempotency — log and proceed rather than blocking
        mto_logger.warning(f"Idempotency check failed, proceeding: {e}")
        return await call_next(request)

    # Key is new — process the request and cache the response.
    # Re-inject the consumed body bytes so the route handler can read them.
    async def receive_with_body():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    # Patch the request's receive callable so the handler sees the body
    request._receive = receive_with_body

    response = await call_next(request)

    # Only cache successful JSON responses within the size limit
    content_type = response.headers.get("content-type", "")
    if 200 <= response.status_code < 300 and "application/json" in content_type:
        try:
            resp_body_bytes = b""
            async for chunk in response.body_iterator:
                resp_body_bytes += chunk
                if len(resp_body_bytes) > _IDEMPOTENCY_MAX_CACHE_BYTES:
                    # Response too large to cache — stream it through uncached
                    mto_logger.info(
                        f"Idempotency response too large to cache ({len(resp_body_bytes)} bytes), skipping.",
                        path=path,
                    )
                    return StarletteResponse(
                        content=resp_body_bytes,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        media_type=response.media_type,
                    )

            body_str = resp_body_bytes.decode("utf-8")

            with SessionLocal() as db:
                record = IdempotencyKey(
                    key=composite_key,
                    method=request.method,
                    path=path,
                    status_code=response.status_code,
                    response_body=body_str,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                )
                db.add(record)
                db.commit()

            return StarletteResponse(
                content=resp_body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception as e:
            mto_logger.warning(f"Failed to cache idempotency response: {e}")

    return response
