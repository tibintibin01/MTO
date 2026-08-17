import os
import asyncio
import json
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
import jwt as _pyjwt
from jwt.exceptions import InvalidTokenError as JWTError  # noqa: F401 — re-exported for callers
import functools
import inspect
from slowapi import Limiter
from slowapi.util import get_remote_address

# --- MONKEY-PATCH SLOWAPI TO SUPPORT MULTIPLE STACKED LIMITERS ---
_original_limit_decorator = Limiter._Limiter__limit_decorator

def _patched_limit_decorator(self, *args, **kwargs):
    decorator = _original_limit_decorator(self, *args, **kwargs)
    def new_decorator(func):
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args_inner, **kwargs_inner):
                request = kwargs_inner.get("request")
                if not request:
                    for arg in args_inner:
                        if isinstance(arg, Request):
                            request = arg
                            break
                if request and hasattr(request, "state"):
                    request.state._rate_limiting_complete = False
                return await func(*args_inner, **kwargs_inner)
            return decorator(async_wrapper)
        else:
            @functools.wraps(func)
            def sync_wrapper(*args_inner, **kwargs_inner):
                request = kwargs_inner.get("request")
                if not request:
                    for arg in args_inner:
                        if isinstance(arg, Request):
                            request = arg
                            break
                if request and hasattr(request, "state"):
                    request.state._rate_limiting_complete = False
                return func(*args_inner, **kwargs_inner)
            return decorator(sync_wrapper)
    return new_decorator

Limiter._Limiter__limit_decorator = _patched_limit_decorator
# -----------------------------------------------------------------

from sqlalchemy.orm import Session
from utils.config import config as mto_config
from utils.secrets_manager import secrets
from utils.logger import mto_logger
from backend.database import get_db

# Security Configuration
SECRET_KEY = secrets.jwt_secret
ALGORITHM = mto_config.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = mto_config.TOKEN_EXPIRE_MINUTES

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# ---------------------------------------------------------------------------
# Rate Limiter Configuration
# ---------------------------------------------------------------------------
# Two limiters run independently:
#
#   limiter      — keyed by IP address (existing, unchanged)
#                  Protects against unauthenticated floods and scraping.
#
#   user_limiter — keyed by authenticated username
#                  Protects against a single compromised account hammering
#                  the API from any IP (e.g. scripted abuse, credential stuffing).
#                  Falls back to IP if the request has no valid token, so
#                  unauthenticated endpoints are still covered.
#
# Usage in route handlers:
#   @limiter.limit("20/minute")          ← IP-based (existing)
#   @user_limiter.limit("20/minute")     ← per-user (new)
#
# Both decorators can be stacked on the same endpoint:
#   @limiter.limit("30/minute")
#   @user_limiter.limit("20/minute")
#   async def my_endpoint(request: Request, ...):
# ---------------------------------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL")
MTO_ENV = os.getenv("MTO_ENV", "development").lower()

# Require Redis in production for distributed rate limiting
if MTO_ENV == "production" and not REDIS_URL:
    raise RuntimeError(
        "REDIS_URL is required in production for rate limiting. "
        "In-memory rate limiting does not work across multiple workers. "
        "Set REDIS_URL=redis://redis:6379/0 in your environment."
    )


def _get_user_identifier(request: Request) -> str:
    """
    Key function for the per-user rate limiter.

    Extracts the username from the JWT (Bearer header or access_token cookie).
    Falls back to the IP address for unauthenticated requests so the limiter
    still applies to public endpoints.

    The JWT is decoded WITHOUT signature verification here — we only need the
    `sub` claim for the rate-limit key, not for authentication. Full signature
    verification happens in get_current_user() as normal.
    """
    token: str | None = None

    # 1. Try Bearer header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]

    # 2. Try cookie (web portal)
    if not token:
        token = request.cookies.get("access_token")

    if token:
        try:
            import base64, json as _json
            # Decode payload without verification — key extraction only
            parts = token.split(".")
            if len(parts) == 3:
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = _json.loads(base64.b64decode(padded).decode("utf-8"))
                username = payload.get("sub")
                if username:
                    return f"user:{username}"
        except Exception:
            pass

    # Fallback: use IP address (same as the IP limiter)
    return f"ip:{get_remote_address(request)}"


# Build both limiters with the same storage backend (Redis if available)
_limiter_kwargs: dict = {}
if REDIS_URL:
    try:
        _limiter_kwargs["storage_uri"] = REDIS_URL
    except Exception:
        pass

limiter = Limiter(key_func=get_remote_address, **_limiter_kwargs)
user_limiter = Limiter(key_func=_get_user_identifier, **_limiter_kwargs)


# WebSocket Connection Manager
class ConnectionManager:
    """
    Manages WebSocket connections with optional Redis pub/sub for
    multi-worker broadcast.

    Redis init is deferred to the first async operation so the manager
    can be safely instantiated at module level without a running event loop.
    Connection pooling is configured explicitly and the pub/sub listener
    reconnects automatically with exponential backoff on disconnect.
    """

    # Reconnection backoff: starts at 1s, doubles each attempt, caps at 60s
    _RECONNECT_BASE = 1
    _RECONNECT_MAX = 60

    def __init__(self):
        from fastapi import WebSocket
        self.active_connections: List[WebSocket] = []
        self._redis = None          # Lazy-initialised on first use
        self._pubsub = None
        self._listener_task: Optional[asyncio.Task] = None
        self._redis_initialised = False

    async def _get_redis(self):
        """
        Returns the Redis client, creating it on first call.
        Uses a connection pool with explicit sizing and health-check pings.
        Deferred init avoids calling asyncio APIs at module import time.
        """
        if self._redis_initialised:
            return self._redis
        self._redis_initialised = True  # Set before await to prevent races

        if not REDIS_URL:
            return None

        try:
            import redis.asyncio as aioredis

            # Explicit pool: max 20 connections, 5s socket timeout,
            # health_check_interval pings idle connections every 30s
            # so stale connections are detected before use.
            pool = aioredis.ConnectionPool.from_url(
                REDIS_URL,
                decode_responses=True,
                max_connections=20,
                socket_connect_timeout=5,
                socket_timeout=5,
                health_check_interval=30,
            )
            self._redis = aioredis.Redis(connection_pool=pool)
            # Verify connectivity immediately so a misconfigured URL fails fast
            await self._redis.ping()
            mto_logger.info("Redis connection pool initialised", url=REDIS_URL[:20] + "...")
        except Exception as e:
            mto_logger.warning(f"Redis unavailable — falling back to in-process broadcast: {e}")
            self._redis = None

        return self._redis

    async def _start_listener(self):
        """Starts the pub/sub listener task if not already running."""
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._listen_redis())

    async def _listen_redis(self):
        """
        Subscribes to the mto_notifications channel and forwards messages
        to all connected WebSocket clients.

        Reconnects automatically with exponential backoff on any error.
        Exits cleanly when the event loop is shutting down.
        """
        backoff = self._RECONNECT_BASE

        while True:
            redis = await self._get_redis()
            if not redis:
                return  # No Redis configured — nothing to listen to

            try:
                self._pubsub = redis.pubsub()
                await self._pubsub.subscribe("mto_notifications")
                mto_logger.info("Redis pub/sub listener subscribed to mto_notifications")
                backoff = self._RECONNECT_BASE  # Reset on successful connect

                async for message in self._pubsub.listen():
                    if message["type"] == "message":
                        data = message["data"]
                        dead = []
                        for ws in list(self.active_connections):
                            try:
                                await ws.send_text(data)
                            except Exception as ws_err:
                                mto_logger.warning(f"WebSocket send failed, removing connection: {ws_err}")
                                dead.append(ws)
                        for ws in dead:
                            self.disconnect(ws)

            except asyncio.CancelledError:
                # Event loop shutting down — exit cleanly
                mto_logger.info("Redis pub/sub listener cancelled")
                return
            except Exception as e:
                mto_logger.warning(
                    f"Redis pub/sub listener disconnected: {e}. "
                    f"Reconnecting in {backoff}s..."
                )
                # Force re-init on next _get_redis() call
                self._redis = None
                self._redis_initialised = False
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    return
                backoff = min(backoff * 2, self._RECONNECT_MAX)

    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Start the listener lazily on first connection
        await self._start_listener()

    def disconnect(self, websocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass

    async def send_personal_message(self, message: str, websocket):
        await websocket.send_text(message)

    async def broadcast(self, message: dict):
        msg_str = json.dumps(message)
        redis = await self._get_redis()

        if redis:
            try:
                await redis.publish("mto_notifications", msg_str)
                return
            except Exception as e:
                mto_logger.warning(f"Redis publish failed, falling back to direct broadcast: {e}")
                # Force re-init so the next call attempts reconnection
                self._redis = None
                self._redis_initialised = False

        # Direct broadcast fallback (single-worker or Redis unavailable)
        dead = []
        for ws in list(self.active_connections):
            try:
                await ws.send_text(msg_str)
            except Exception as ws_err:
                mto_logger.warning(f"Direct WebSocket send failed: {ws_err}")
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

async def get_current_user(request: Request, token: Optional[str] = None, db_session: Session = Depends(get_db)):
    """
    Validates the JWT and verifies the user still exists and is active in the DB.

    Token validation alone is insufficient — a deleted or deactivated user's
    token remains cryptographically valid until expiry (up to 15 minutes).
    This DB check closes that window: any request from a deleted/disabled
    account is rejected immediately regardless of token validity.

    The DB lookup uses only the primary key (user_id) with a load_only() hint
    to fetch the minimum columns needed — no full ORM hydration.
    """
    # Support cookie auth (Web portal BFF) and Bearer auth (Desktop & Tests)
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    try:
        payload = _pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("id")
        username: str = payload.get("sub")
        role: str = payload.get("role")
        iat: int | None = payload.get("iat")   # issued-at timestamp (Unix epoch)
        session_id: int | None = payload.get("sid")

        if username is None or role is None or user_id is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception
    except Exception as e:
        from utils.logger import mto_logger
        mto_logger.error(f"AUTH ERROR: {str(e)}")
        raise credentials_exception

    # Verify the user still exists, is active, and has not been soft-deleted.
    # Also check password_changed_at: if the token was issued before the last
    # password change, reject it immediately — even within the 1-hour window.
    from backend.models import User, RefreshToken
    from sqlalchemy.orm import load_only

    user = (
        db_session.query(User)
        .options(load_only(User.id, User.full_name, User.is_active,
                           User.deleted_at, User.password_changed_at))
        .filter(User.id == user_id)
        .first()
    )

    if user is None or user.deleted_at is not None or not user.is_active:
        from utils.logger import mto_logger
        mto_logger.security(
            "Token presented for inactive or deleted user",
            user_id=user_id,
            username=username,
            exists=user is not None,
            deleted=user.deleted_at is not None if user else None,
            active=user.is_active if user else None,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive or has been removed",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # New access tokens are bound to a revocable refresh-session row. Tokens
    # issued before this feature have no sid and remain valid until their normal
    # one-hour expiry, which keeps deployments backward compatible.
    if session_id is not None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        active_session = (
            db_session.query(RefreshToken.id)
            .filter(
                RefreshToken.id == session_id,
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked == False,
                RefreshToken.expires_at > now,
            )
            .first()
        )
        if active_session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This session has been signed out. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Reject tokens issued before the last password change.
    # password_changed_at is a naive MariaDB datetime — compare with naive iat.
    if iat is not None and user.password_changed_at is not None:
        token_issued_at = datetime.fromtimestamp(iat, tz=timezone.utc).replace(tzinfo=None)
        if token_issued_at < user.password_changed_at:
            from utils.logger import mto_logger
            mto_logger.security(
                "Token rejected: issued before password change",
                user_id=user_id,
                username=username,
                token_iat=token_issued_at.isoformat(),
                password_changed_at=user.password_changed_at.isoformat(),
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired due to password change. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return {
        "id": user_id,
        "username": username,
        "full_name": user.full_name,
        "role": role,
        "session_id": session_id,
    }

async def verify_csrf_token(request: Request):
    """
    Validates the CSRF double-submit cookie pattern.

    The client reads the csrf_token cookie (non-httpOnly) and echoes it back
    in the X-CSRF-Token request header. The server compares the two values.
    A cross-origin attacker cannot read the cookie value, so they cannot
    forge the header — even if SameSite cookies are bypassed.

    Bearer token clients (desktop app) are exempt — CSRF only applies to
    cookie-authenticated sessions. The Bearer token must be a non-empty,
    structurally valid JWT (3 dot-separated parts) to qualify for exemption.
    A bare "Bearer null" or "Bearer " does NOT bypass CSRF.
    """
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return

    # Bearer token clients are not cookie-authenticated — CSRF does not apply.
    # But only if the token is actually present and structurally valid (3 parts).
    # Bearer token clients are not cookie-authenticated — CSRF does not apply.
    # But only if the token is actually present and structurally valid (3 parts)
    # AND there is no session cookie present. If a session cookie is present,
    # we must enforce CSRF protection since cookie authentication will be used.
    has_session_cookie = bool(request.cookies.get("access_token"))

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and not has_session_cookie:
        token_value = auth_header[7:].strip()
        # A valid JWT has exactly 3 dot-separated base64 segments
        if token_value and token_value.count(".") == 2 and len(token_value) > 20:
            return

    csrf_header = request.headers.get("X-CSRF-Token", "")
    csrf_cookie = request.cookies.get("csrf_token", "")

    # Use compare_digest to prevent timing attacks on the token comparison
    import hmac
    valid = (
        bool(csrf_header)
        and bool(csrf_cookie)
        and hmac.compare_digest(csrf_header, csrf_cookie)
    )

    if not valid:
        from utils.logger import mto_logger
        mto_logger.security(
            "CSRF validation failed",
            method=request.method,
            path=str(request.url.path),
            ip=request.client.host if request.client else "unknown",
            has_header=bool(csrf_header),
            has_cookie=bool(csrf_cookie),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token validation failed",
        )

class RoleChecker:
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    async def __call__(self, request: Request, current_user: dict = Depends(get_current_user)):
        await verify_csrf_token(request)
        role = str(current_user.get("role", "")).strip().lower()
        if role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Required permissions missing. You have '{role}', need one of {self.allowed_roles}",
            )
        return current_user

# ---------------------------------------------------------------------------
# Permission presets — derived from auth_service.ROLE_PERMISSIONS
# ---------------------------------------------------------------------------
# These are the route-level guards. They answer: "which roles can ACCESS
# this endpoint at all?" The granular per-operation checks inside services
# (auth_service.has_permission) answer: "can this specific user DO this
# specific action?"
#
# Both systems reference the same ROLE_PERMISSIONS map in auth_service.py
# so they cannot drift independently.
# ---------------------------------------------------------------------------
from backend.services.auth_service import ROLE_PERMISSIONS

def _roles_with_any_permission(*permissions: str) -> list[str]:
    """Returns all roles that have at least one of the given permissions."""
    return [
        role for role, perms in ROLE_PERMISSIONS.items()
        if any(p in perms for p in permissions)
    ]

admin_only = RoleChecker(["admin"])
write_access = RoleChecker(_roles_with_any_permission("property_edit", "payment_post"))
read_only = RoleChecker(_roles_with_any_permission("property_view"))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=60)
    # Embed issued-at (iat) so get_current_user can reject tokens issued
    # before a password change even within the 1-hour expiry window.
    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = _pyjwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
