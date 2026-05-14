import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from backend.deps import get_current_user, write_access, get_db, Session
from backend.schemas import ReceiptRecordSchema
import backend.services.payment_service as pay_svc
from backend.generators import receipt_gen

router = APIRouter(prefix="/payments", tags=["Financial"])

@router.get("/recent")
async def get_recent_payments(
    limit: int = 8, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    return pay_svc.get_recent_payments(limit, db_session=db_session)

@router.get("/records")
async def get_payment_records(
    term: str, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    return pay_svc.get_payment_receipt_records(term, db_session=db_session)

@router.get("/{payment_id}/details")
async def get_payment_details(
    payment_id: int, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    res = pay_svc.get_payment_receipt_details(payment_id, db_session=db_session)
    if not res:
        raise HTTPException(status_code=404, detail="Payment details not found")
    return res

@router.post("/receipt-record")
async def save_receipt_record(
    data: ReceiptRecordSchema, current_user: dict = Depends(write_access), db_session: Session = Depends(get_db)
):
    return pay_svc.save_receipt_record(
        data.property_id,
        data.payment_id,
        data.details,
        data.file_path,
        data.user_name,
        current_user=current_user,
        db_session=db_session
    )

@router.get("/ledger")
async def get_payment_ledger(term: str, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return pay_svc.get_unified_payment_history(term, db_session=db_session)

@router.get("/next-or")
async def get_next_or_number(current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)):
    return {"next_or": pay_svc.get_next_or_number(db_session=db_session)}

@router.get("/trend")
async def get_collection_trend(
    months: int = 6, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    return pay_svc.get_monthly_collection_trend(months, db_session=db_session)

@router.post("/{payment_id}/receipt-pdf")
async def generate_receipt_pdf(
    payment_id: int, current_user: dict = Depends(write_access), db_session: Session = Depends(get_db)
):
    details = pay_svc.get_payment_receipt_details(payment_id, db_session=db_session)
    if not details:
        raise HTTPException(status_code=404, detail="Payment details not found")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_path = receipt_gen.generate_or_receipt(details, base_dir)
    return FileResponse(
        pdf_path, media_type="application/pdf", filename=os.path.basename(pdf_path)
    )
