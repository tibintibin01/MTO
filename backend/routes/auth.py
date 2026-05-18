from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Dict

import backend.services.auth_service as auth_svc
from backend.deps import (
    get_current_user,
    create_access_token,
    limiter,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    get_db,
    Session
)
from utils.logger import mto_logger

router = APIRouter(tags=["Auth"])

class Token(BaseModel):
    access_token: str
    token_type: str

@router.post("/token", response_model=Token)
@limiter.limit("10/minute")
async def login_for_access_token(
    request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db_session: Session = Depends(get_db)
):
    try:
        user = auth_svc.verify_user_login(form_data.username, form_data.password, db_session=db_session)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user["username"], "role": user["role"], "id": user["id"]},
            expires_delta=access_token_expires,
        )
        return {"access_token": access_token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

from fastapi import Response

@router.post("/api/auth/login")
async def login(credentials: Dict[str, str], request: Request, response: Response, db_session: Session = Depends(get_db)):
    """
    Secure login with brute-force protection and structured logging.
    """
    username = credentials.get("username")
    password = credentials.get("password")
    
    mto_logger.info(f"Login attempt received for user: {username}", ip=request.client.host)
    
    user_data = auth_svc.verify_user_login(username, password, db_session=db_session)
    if user_data:
        mto_logger.info("Login successful", user=username, ip=request.client.host)
        # Set access token in secure HTTP-Only cookie for BFF pattern
        response.set_cookie(
            key="access_token",
            value=user_data["access_token"],
            httponly=True,
            secure=False,  # Set to True in production
            samesite="lax",
            max_age=15 * 60  # 15 minutes
        )
        # TELEMETRY: Verify what we are returning
        mto_logger.info(f"DEBUG: Returning login data for {username}. Token present: {'access_token' in user_data}")
        return user_data

    else:
        mto_logger.security("Login failed: Invalid credentials or account locked", user=username, ip=request.client.host)
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.get("/me")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user

@router.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"message": "Successfully logged out"}
