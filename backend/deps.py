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

    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket):
        await websocket.send_text(message)

    async def broadcast(self, message: dict):
        import json
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except:
                pass

manager = ConnectionManager()

async def get_current_user(request: Request, token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
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

class RoleChecker:
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: dict = Depends(get_current_user)):
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
