# -*- coding: utf-8 -*-

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.deps import RoleChecker, get_db, read_only
from backend.schemas_portfolio import (
    PortfolioCreateSchema,
    PortfolioPropertyLinkSchema,
    PortfolioUpdateSchema,
)
from backend.services.auth_service import ROLE_PERMISSIONS
from backend.services import portfolio_service as portfolio_svc


router = APIRouter(prefix="/portfolios", tags=["Property Portfolios"])

portfolio_write = RoleChecker(
    [
        role
        for role, permissions in ROLE_PERMISSIONS.items()
        if "property_edit" in permissions
    ]
)


def _raise_service_error(exc: Exception):
    if isinstance(exc, portfolio_svc.PortfolioNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, portfolio_svc.PortfolioConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, portfolio_svc.PortfolioValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    raise exc


@router.get("")
def list_portfolios(
    search: str = "",
    include_inactive: bool = False,
    current_user: dict = Depends(read_only),
    db_session: Session = Depends(get_db),
):
    return {
        "items": portfolio_svc.list_portfolios(
            search=search,
            include_inactive=include_inactive,
            db_session=db_session,
        )
    }


@router.get("/{portfolio_id}")
def get_portfolio(
    portfolio_id: int,
    current_user: dict = Depends(read_only),
    db_session: Session = Depends(get_db),
):
    try:
        return portfolio_svc.get_portfolio_detail(
            portfolio_id,
            db_session=db_session,
        )
    except Exception as exc:
        _raise_service_error(exc)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_portfolio(
    data: PortfolioCreateSchema,
    current_user: dict = Depends(portfolio_write),
    db_session: Session = Depends(get_db),
):
    try:
        return portfolio_svc.create_portfolio(
            data.name,
            current_user,
            db_session=db_session,
        )
    except Exception as exc:
        _raise_service_error(exc)


@router.patch("/{portfolio_id}")
def update_portfolio(
    portfolio_id: int,
    data: PortfolioUpdateSchema,
    current_user: dict = Depends(portfolio_write),
    db_session: Session = Depends(get_db),
):
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide a new name or active status.",
        )
    try:
        return portfolio_svc.update_portfolio(
            portfolio_id,
            name=changes.get("name"),
            is_active=changes.get("is_active"),
            user=current_user,
            db_session=db_session,
        )
    except Exception as exc:
        _raise_service_error(exc)


@router.post("/{portfolio_id}/properties")
def link_property(
    portfolio_id: int,
    data: PortfolioPropertyLinkSchema,
    current_user: dict = Depends(portfolio_write),
    db_session: Session = Depends(get_db),
):
    try:
        return portfolio_svc.link_property(
            portfolio_id,
            data.property_id,
            current_user,
            db_session=db_session,
        )
    except Exception as exc:
        _raise_service_error(exc)


@router.delete("/{portfolio_id}/properties/{property_id}")
def unlink_property(
    portfolio_id: int,
    property_id: int,
    current_user: dict = Depends(portfolio_write),
    db_session: Session = Depends(get_db),
):
    try:
        return portfolio_svc.unlink_property(
            portfolio_id,
            property_id,
            current_user,
            db_session=db_session,
        )
    except Exception as exc:
        _raise_service_error(exc)
