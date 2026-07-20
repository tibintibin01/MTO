from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from backend.deps import get_current_user, admin_only, get_db, Session
from backend.schemas import UserCreateSchema, UserUpdateSchema, PasswordResetSchema
import backend.services.auth_service as auth_svc

router = APIRouter(prefix="/users", tags=["Admin"], dependencies=[Depends(admin_only)])


@router.get("/{user_id}/active-sessions")
async def list_active_sessions(
    user_id: int,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    return {
        "items": auth_svc.get_active_sessions(user_id, current_user, db_session)
    }


@router.post("/active-sessions/{session_id}/revoke")
async def revoke_active_session(
    session_id: int,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    try:
        user_id = auth_svc.revoke_managed_session(
            session_id, current_user, db_session
        )
        return {"status": "revoked", "user_id": user_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{user_id}/active-sessions/revoke-others")
async def revoke_other_sessions(
    user_id: int,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    count = auth_svc.revoke_other_user_sessions(user_id, current_user, db_session)
    return {"status": "revoked", "count": count}

@router.get("")
async def list_users(
    limit: int = 50,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    return auth_svc.get_all_users(limit=limit, cursor=cursor, db_session=db_session)

@router.post("")
async def create_user(
    data: UserCreateSchema, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    user_id = auth_svc.create_user(
        username=data.username,
        full_name=data.full_name,
        password=data.password,
        role=data.role,
        admin_user=current_user,
        db_session=db_session
    )
    return {"status": "created", "user_id": user_id}

@router.patch("/{user_id}")
async def update_user(
    user_id: int, data: UserUpdateSchema, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    if data.role is not None:
        auth_svc.update_user_role(user_id, data.role, current_user, db_session=db_session)
    if data.is_active is not None:
        auth_svc.update_user_status(user_id, data.is_active, current_user, db_session=db_session)
    return {"status": "updated"}

@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    data: PasswordResetSchema,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    try:
        auth_svc.reset_user_password(user_id, data.new_password, current_user, db_session=db_session)
    except Exception as e:
        # ValidationError from validate_password_complexity — return 422 with
        # a clear message so the desktop client can show it to the admin.
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(e))
    return {"status": "password_reset"}

@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    auth_svc.delete_user(user_id, current_user, db_session=db_session)
    return {"status": "deleted"}
