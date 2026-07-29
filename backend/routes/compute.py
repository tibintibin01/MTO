# -*- coding: utf-8 -*-
"""
Computation routes: smart payment calculation, global search, undo, WebSocket.

Split from the monolithic system.py to keep each router focused.
"""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import jwt as _pyjwt
from jwt.exceptions import InvalidTokenError as JWTError

from backend.deps import (
    get_current_user,
    read_only,
    admin_only,
    manager,
    get_db,
    Session,
    SECRET_KEY,
    ALGORITHM,
)
from utils.logger import mto_logger

router = APIRouter(tags=["Compute"])


# ---------------------------------------------------------------------------
# Smart Payment Computation
# ---------------------------------------------------------------------------


class ComputePaymentRequest(BaseModel):
    assessed_value: float
    tax_year: int
    date_paid: str  # YYYY-MM-DD
    payment_type: str = "annual"
    quarter: int = 0
    property_id: Optional[int] = None


def _count_annual_penalty_months(tax_year: int, paid_date) -> int:
    """
    Count penalty months for annual RPT payments.

    The office calculation counts January through the payment month,
    inclusive, at 2% per month and caps the charge at 36 months. A payment
    for 2024 made in June 2026 is therefore 30 months late (60%).
    """
    from backend.services.billing_service import annual_penalty_months

    return annual_penalty_months(tax_year, paid_date)


@router.post("/system/compute-payment")
async def compute_payment(
    data: ComputePaymentRequest,
    current_user: dict = Depends(read_only),
    db_session: Session = Depends(get_db),
):
    """
    Smart payment computation.
    Returns basic_tax, sef_tax, discount, penalty, and net_amount_due.
    """
    from decimal import Decimal, ROUND_HALF_UP
    from backend.models import Property, TaxPolicy
    from backend.services.assessment_value_service import assessed_value_for_year
    from backend.services.billing_service import payment_discount_terms

    try:
        paid_date = datetime.strptime(data.date_paid, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date_paid format. Use YYYY-MM-DD."
        )

    tax_year = data.tax_year
    av = Decimal(str(data.assessed_value))
    av_source = "input"

    if data.property_id:
        prop = (
            db_session.query(Property)
            .filter(
                Property.id == data.property_id,
                Property.deleted_at == None,
            )
            .first()
        )
        if prop:
            resolved_av = assessed_value_for_year(prop, tax_year, db_session)
            if resolved_av is not None and resolved_av > Decimal("0.00"):
                av = resolved_av
                av_source = "effective_year"

    policy = db_session.query(TaxPolicy).filter(TaxPolicy.tax_year == tax_year).first()
    basic_rate = Decimal(str(policy.basic_rate)) if policy else Decimal("0.01")
    sef_rate = Decimal(str(policy.sef_rate)) if policy else Decimal("0.01")
    penalty_rate = Decimal(str(policy.penalty_rate)) if policy else Decimal("0.02")

    basic_tax = (av * basic_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sef_tax = (av * sef_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_tax = basic_tax + sef_tax

    discount_rate, discount_label, _discount_deadline = payment_discount_terms(
        tax_year, paid_date
    )

    discount_amount = (total_tax * discount_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    penalty_amount = Decimal("0")
    penalty_months = 0
    penalty_label = "No penalty"

    if discount_rate > 0:
        penalty_label = "No penalty (paid within discount period)"
    else:
        months_late = _count_annual_penalty_months(tax_year, paid_date)
        if months_late > 0:
            penalty_months = months_late
            penalty_amount = (
                total_tax * penalty_rate * Decimal(str(months_late))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            penalty_label = (
                f"{months_late} month(s) late × {float(penalty_rate)*100:.0f}%/mo "
                f"= ₱{penalty_amount:,.2f}"
            )

    net_amount_due = total_tax - discount_amount + penalty_amount

    return {
        "assessed_value": float(av),
        "basic_rate": float(basic_rate),
        "assessed_value_source": av_source,
        "sef_rate": float(sef_rate),
        "penalty_rate": float(penalty_rate),
        "basic_tax": float(basic_tax),
        "sef_tax": float(sef_tax),
        "total_tax": float(total_tax),
        "discount_rate": float(discount_rate),
        "discount_amount": float(discount_amount),
        "discount_label": discount_label,
        "penalty_months": penalty_months,
        "penalty_amount": float(penalty_amount),
        "penalty_label": penalty_label,
        "net_amount_due": float(net_amount_due),
        "breakdown": (
            f"Basic: ₱{basic_tax:,.2f} + SEF: ₱{sef_tax:,.2f} = ₱{total_tax:,.2f}  |  "
            f"Discount: -₱{discount_amount:,.2f} ({discount_label})  |  "
            f"Penalty: +₱{penalty_amount:,.2f} ({penalty_label})  |  "
            f"Net Due: ₱{net_amount_due:,.2f}"
        ),
    }


# ---------------------------------------------------------------------------
# Global Search
# ---------------------------------------------------------------------------


@router.get("/search/global")
async def global_search(
    q: str = "",
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """Unified search for the Command Palette."""
    import backend.services.search_service as search_svc

    if not q:
        return {"results": search_svc.get_quick_actions()}
    return {"results": search_svc.global_search(q, db_session=db_session)}


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


@router.post("/api/v1/system/undo")
async def undo_last_system_action(current_user: dict = Depends(get_current_user)):
    """Reverses the last critical action (UPDATE/DELETE) performed by the current user."""
    from backend.services.history_service import undo_last_action

    success, message = undo_last_action(current_user["id"])
    if not success:
        raise HTTPException(status_code=400, detail=message)
    await manager.broadcast(
        {
            "type": "NOTIFICATION",
            "title": "Action Reversed",
            "message": message,
            "level": "success",
        }
    )
    return {"status": "success", "message": message}


# ---------------------------------------------------------------------------
# WebSocket Notifications
# ---------------------------------------------------------------------------


@router.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    """
    Authenticated WebSocket endpoint for real-time notifications.
    Clients must supply a valid JWT via query parameter on connect:
        wss://host/ws/notifications?token=<access_token>
    """
    if not token:
        token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=1008, reason="Missing authentication token")
        mto_logger.security(
            "WebSocket rejected: no token",
            ip=websocket.client.host if websocket.client else "unknown",
        )
        return

    try:
        payload = _pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        user_id: int = payload.get("id")
        if not username or not role or not user_id:
            raise JWTError("Incomplete token payload")
    except JWTError as e:
        await websocket.close(code=1008, reason="Invalid or expired token")
        mto_logger.security(
            f"WebSocket rejected: invalid token — {e}",
            ip=websocket.client.host if websocket.client else "unknown",
        )
        return

    await manager.connect(websocket)
    mto_logger.info(
        "WebSocket connected",
        user=username,
        role=role,
        ip=websocket.client.host if websocket.client else "unknown",
    )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        mto_logger.info("WebSocket disconnected", user=username)
