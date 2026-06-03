# -*- coding: utf-8 -*-
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from decimal import Decimal

from backend.deps import get_current_user, write_access, admin_only, get_db
from backend.models import BankDeposit
from backend.services.coa_rcd_generator import generate_coa_rcd_excel
from backend.services.system_service import log_action
from utils.logger import mto_logger

router = APIRouter(prefix="/reports", tags=["Reports & Audit"])

class BankDepositCreateSchema(BaseModel):
    date_deposited: str = Field(..., description="Date of deposit (YYYY-MM-DD)")
    bank_name: str = Field(..., min_length=2, max_length=255, description="Name of the bank")
    reference_number: str = Field(..., min_length=2, max_length=255, description="Deposit slip reference number")
    amount: float = Field(..., gt=0, description="Deposited amount")

class BankDepositResponseSchema(BaseModel):
    id: int
    date_deposited: str
    bank_name: str
    reference_number: str
    amount: float
    deposited_by: str
    created_at: str

    class Config:
        from_attributes = True

@router.post("/deposits", response_model=BankDepositResponseSchema, status_code=status.HTTP_201_CREATED)
async def log_bank_deposit(
    payload: BankDepositCreateSchema,
    current_user: dict = Depends(write_access),
    db: Session = Depends(get_db)
):
    """Logs a new bank deposit slip."""
    try:
        dep_date = datetime.strptime(payload.date_deposited, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Expected YYYY-MM-DD."
        )

    # Prevent deposits in the future
    if dep_date.date() > datetime.now().date():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deposit date cannot be in the future."
        )

    try:
        new_deposit = BankDeposit(
            date_deposited=dep_date,
            bank_name=payload.bank_name.strip(),
            reference_number=payload.reference_number.strip(),
            amount=Decimal(str(payload.amount)),
            deposited_by=current_user.get("username", "unknown")
        )
        db.add(new_deposit)
        db.commit()
        db.refresh(new_deposit)

        log_action(
            user=current_user,
            action=f"Logged Bank Deposit: {new_deposit.bank_name} - Ref: {new_deposit.reference_number} - Amount: {new_deposit.amount}",
            db_session=db
        )

        return BankDepositResponseSchema(
            id=new_deposit.id,
            date_deposited=new_deposit.date_deposited.strftime("%Y-%m-%d"),
            bank_name=new_deposit.bank_name,
            reference_number=new_deposit.reference_number,
            amount=float(new_deposit.amount),
            deposited_by=new_deposit.deposited_by,
            created_at=new_deposit.created_at.isoformat() if new_deposit.created_at else datetime.now().isoformat()
        )
    except Exception as e:
        db.rollback()
        mto_logger.error(f"Failed to log bank deposit: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save bank deposit: {str(e)}"
        )

@router.get("/deposits", response_model=List[BankDepositResponseSchema])
async def list_bank_deposits(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lists bank deposits filtered by a date range."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Expected YYYY-MM-DD."
        )

    # Set start_dt to start of day, end_dt to end of day
    start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    deposits = db.query(BankDeposit).filter(
        BankDeposit.date_deposited >= start_dt,
        BankDeposit.date_deposited <= end_dt
    ).order_by(BankDeposit.date_deposited.desc()).all()

    return [
        BankDepositResponseSchema(
            id=d.id,
            date_deposited=d.date_deposited.strftime("%Y-%m-%d"),
            bank_name=d.bank_name,
            reference_number=d.reference_number,
            amount=float(d.amount),
            deposited_by=d.deposited_by,
            created_at=d.created_at.isoformat() if d.created_at else datetime.now().isoformat()
        )
        for d in deposits
    ]

@router.delete("/deposits/{deposit_id}", status_code=status.HTTP_200_OK)
async def delete_bank_deposit(
    deposit_id: int,
    current_user: dict = Depends(write_access),
    db: Session = Depends(get_db)
):
    """Deletes a bank deposit slip."""
    deposit = db.query(BankDeposit).filter(BankDeposit.id == deposit_id).first()
    if not deposit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bank deposit record not found."
        )

    try:
        db.delete(deposit)
        log_action(
            user=current_user,
            action=f"Deleted Bank Deposit: {deposit.bank_name} - Ref: {deposit.reference_number} - Amount: {deposit.amount}",
            db_session=db
        )
        db.commit()
        return {"success": True, "message": "Bank deposit record deleted."}
    except Exception as e:
        db.rollback()
        mto_logger.error(f"Failed to delete bank deposit: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not delete bank deposit: {str(e)}"
        )

@router.get("/rcd")
async def export_coa_rcd(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    liquidating_officer: str = Query("N/A", description="Liquidating Officer Signatory"),
    treasurer: str = Query("N/A", description="Treasurer Signatory"),
    current_user: dict = Depends(admin_only),
    db: Session = Depends(get_db)
):
    """Generates and streams the COA RCD Excel sheet for a given date range."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Expected YYYY-MM-DD."
        )

    try:
        # Generate Excel buffer
        excel_buffer = generate_coa_rcd_excel(
            db=db,
            start_date=start_dt,
            end_date=end_dt,
            liquidating_officer=liquidating_officer,
            treasurer=treasurer
        )
        
        log_action(
            user=current_user,
            action=f"Exported COA RCD Excel report from {start_date} to {end_date}",
            db_session=db
        )

        filename = f"COA_RCD_{start_date}_to_{end_date}.xlsx"
        
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        
        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        mto_logger.error(f"COA RCD generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate COA RCD report: {str(e)}"
        )
