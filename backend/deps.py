import os
import asyncio
import json
from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from slowapi import Limiter
from slowapi.util import get_remote_address

from sqlalchemy.orm import Session
from utils.config import config as mto_config
from utils.secrets_manager import secrets
from utils.logger import mto_logger
from backend.database import get_db

# Security Configuration
SECRET_KEY = secrets.jwt_secret
ALGORITHM = mto_config.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = mto_config.TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Rate Limiter Configuration
REDIS_URL = os.getenv("REDIS_URL")
MTO_ENV = os.getenv("MTO_ENV", "development").lower()

if REDIS_URL:
    try:
        limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL)
    except Exception:
        limiter = Limiter(key_func=get_remote_address)
else:
    limiter = Limiter(key_func=get_remote_address)


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
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("id")
        username: str = payload.get("sub")
        role: str = payload.get("role")

        if username is None or role is None or user_id is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception
    except Exception as e:
        from utils.logger import mto_logger
        mto_logger.error(f"AUTH ERROR: {str(e)}")
        raise credentials_exception

    # Verify the user still exists, is active, and has not been soft-deleted.
    # Fetches only the three columns needed — avoids loading password hash etc.
    from backend.models import User
    from sqlalchemy.orm import load_only

    user = (
        db_session.query(User)
        .options(load_only(User.id, User.is_active, User.deleted_at))
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

    return {"id": user_id, "username": username, "role": role}

async def verify_csrf_token(request: Request):
    """
    Validates the CSRF double-submit cookie pattern.

    The client reads the csrf_token cookie (non-httpOnly) and echoes it back
    in the X-CSRF-Token request header. The server compares the two values.
    A cross-origin attacker cannot read the cookie value, so they cannot
    forge the header — even if SameSite cookies are bypassed.

    Bearer token clients (desktop app) are exempt — CSRF only applies to
    cookie-authenticated sessions.
    """
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return

    # Bearer token clients are not cookie-authenticated — CSRF does not apply
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
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

# Permission presets
admin_only = RoleChecker(["admin"])
write_access = RoleChecker(["admin", "cashier", "encoder"])
read_only = RoleChecker(["admin", "cashier", "encoder", "viewer"])

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
