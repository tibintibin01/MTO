from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
import os
import secrets
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Dict

import backend.services.auth_service as auth_svc
from backend.deps import (
    get_current_user,
    limiter,
    get_db,
    Session
)
from utils.logger import mto_logger

router = APIRouter(tags=["Auth"])

# Cookies must be Secure (HTTPS-only) in production.
# On a local office network running plain HTTP, Secure=True causes the browser
# to silently drop the cookie, making login appear to fail.
# Setting Secure=False for non-production allows HTTP deployments to work.
_IS_PRODUCTION = os.getenv("MTO_ENVIRONMENT", "development").lower() == "production"
_COOKIE_SECURE = _IS_PRODUCTION

class Token(BaseModel):
    access_token: str
    token_type: str

@router.post("/token", response_model=Token)
@limiter.limit("10/minute")
async def login_for_access_token(
    request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db_session: Session = Depends(get_db)
):
    """
    OAuth2-compatible token endpoint for the desktop client and Swagger UI.
    Delegates entirely to verify_user_login() so lockout, refresh token
    generation, and hash-upgrade logic are identical to /api/auth/login.
    """
    try:
        user_data = auth_svc.verify_user_login(
            form_data.username, form_data.password, db_session=db_session
        )
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        mto_logger.info("Login successful via /token", user=form_data.username, ip=request.client.host)
        return {"access_token": user_data["access_token"], "token_type": "bearer"}
    except HTTPException:
        raise
    except ValueError as ve:
        mto_logger.security(f"Login failed via /token: {str(ve)}", user=form_data.username, ip=request.client.host)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(ve),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        mto_logger.error(f"Unexpected error during /token login: {str(e)}", user=form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )

@router.post("/api/auth/login")
async def login(credentials: Dict[str, str], request: Request, response: Response, db_session: Session = Depends(get_db)):
    """
    Secure login with brute-force protection and structured logging.
    """
    username = credentials.get("username")
    password = credentials.get("password")
    
    mto_logger.info(f"Login attempt received for user: {username}", ip=request.client.host)
    
    try:
        user_data = auth_svc.verify_user_login(username, password, db_session=db_session)
    except ValueError as ve:
        msg = str(ve)
        mto_logger.security(f"Login failed: {msg}", user=username, ip=request.client.host)

        from backend.error_codes import raise_api_error, E
        if msg.startswith("DISABLED:"):
            raise_api_error(E.AUTH_ACCOUNT_DISABLED, "Account is disabled. Please contact the administrator.")
        elif msg.startswith("LOCKED:"):
            minutes = msg.split(":", 1)[1]
            raise_api_error(E.AUTH_ACCOUNT_LOCKED, f"Account temporarily locked. Please try again in {minutes} minute(s).")
        elif msg.startswith("INVALID:"):
            remaining = msg.split(":", 1)[1]
            raise_api_error(E.AUTH_INVALID_CREDENTIALS, f"Invalid password. {remaining} attempt(s) remaining before lockout.")
        else:
            raise_api_error(E.AUTH_INVALID_CREDENTIALS, msg)
    
    if user_data:
        mto_logger.info("Login successful", user=username, ip=request.client.host)
        response.set_cookie(
            key="access_token",
            value=user_data["access_token"],
            httponly=True,
            secure=_COOKIE_SECURE,
            samesite="strict",
            max_age=60 * 60  # 1 hour — matches token expiry
        )
        return user_data

    else:
        mto_logger.security("Login failed: Invalid credentials or account locked", user=username, ip=request.client.host)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

@router.get("/me")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.post("/api/auth/refresh")
async def refresh_access_token(
    credentials: Dict[str, str],
    db_session: Session = Depends(get_db)
):
    """
    Issues a new access token using a valid refresh token.
    Called automatically by the desktop client when the access token expires,
    so the user stays logged in without seeing a session expired error.
    """
    refresh_token = credentials.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="refresh_token is required")

    try:
        result = auth_svc.refresh_access_token(refresh_token, db_session=db_session)
        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"message": "Successfully logged out"}

@router.get("/api/auth/csrf")
async def get_csrf_token(response: Response):
    """
    Issues a CSRF token using the double-submit cookie pattern.

    The token is set as a non-httpOnly cookie so JavaScript can read it
    and copy it into the X-CSRF-Token request header on state-changing calls.
    The server then compares the header value against the cookie value.

    The CSRF cookie must NOT be httpOnly — that would prevent JS from reading
    it, breaking the pattern. The auth session cookie (access_token) remains
    httpOnly because it never needs to be read by JS.
    """
    token = secrets.token_hex(32)
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=False,   # Must be readable by JS to implement double-submit
        secure=_COOKIE_SECURE,
        samesite="strict",
        max_age=3600,     # 1 hour
    )
    # Return 204 — the token is in the cookie, clients read it from there.
    # Returning it in the body too would create a confusing dual-channel.
    return Response(status_code=204)
