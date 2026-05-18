import os
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
    def __init__(self):
        from fastapi import WebSocket
        self.active_connections: List[WebSocket] = []
        self.redis = None
        self.pubsub = None
        
        if REDIS_URL:
            try:
                import redis.asyncio as aioredis
                import asyncio
                self.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
                self.pubsub = self.redis.pubsub()
                asyncio.create_task(self._listen_redis())
            except Exception as e:
                print(f"Redis Pub/Sub init failed: {e}")

    async def _listen_redis(self):
        if not self.pubsub: return
        try:
            await self.pubsub.subscribe("mto_notifications")
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    for connection in self.active_connections:
                        try:
                            await connection.send_text(data)
                        except:
                            pass
        except Exception:
            pass

    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass

    async def send_personal_message(self, message: str, websocket):
        await websocket.send_text(message)

    async def broadcast(self, message: dict):
        import json
        msg_str = json.dumps(message)
        if self.redis:
            try:
                await self.redis.publish("mto_notifications", msg_str)
            except Exception:
                # Fallback if publish fails
                for connection in self.active_connections:
                    try:
                        await connection.send_text(msg_str)
                    except:
                        pass
        else:
            for connection in self.active_connections:
                try:
                    await connection.send_text(msg_str)
                except:
                    pass

manager = ConnectionManager()

async def get_current_user(request: Request, token: Optional[str] = None):
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

        return {"id": user_id, "username": username, "role": role}
    except JWTError:
        raise credentials_exception
    except Exception as e:
        print(f"AUTH ERROR: {str(e)}")
        raise credentials_exception

async def verify_csrf_token(request: Request):
    if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
        csrf_token = request.headers.get("X-CSRF-Token")
        csrf_cookie = request.cookies.get("csrf_token")
        
        # Desktop app might use Bearer token without cookies
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return # Skip CSRF for pure Bearer token clients (Desktop app)
            
        if not csrf_token or not csrf_cookie or csrf_token != csrf_cookie:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token validation failed"
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
