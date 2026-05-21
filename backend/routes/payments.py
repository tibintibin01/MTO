import os
import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from backend.deps import get_current_user, write_access, get_db, Session
from backend.schemas import ReceiptRecordSchema
import backend.services.payment_service as pay_svc
from backend.generators import receipt_gen
from backend.services.storage_service import storage_service
from utils.logger import mto_logger

router = APIRouter(prefix="/payments", tags=["Financial"])

@router.get("/recent")
async def get_recent_payments(
    limit: int = 8, current_user: dict = Depends(get_current_user), db_session: Session = Depends(get_db)
):
    return pay_svc.get_recent_payments(limit, db_session=db_session)

@router.get("/records")
async def get_payment_records(
    term: str,
    limit: int = 50,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db)
):
    return pay_svc.get_payment_receipt_records(term, limit=limit, cursor=cursor, db_session=db_session)

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

    # PDF generation is CPU/IO-bound — offload to a thread to avoid
    # blocking the async event loop under concurrent requests.
    pdf_path = await asyncio.to_thread(receipt_gen.generate_or_receipt, details, base_dir)
    file_name = os.path.basename(pdf_path)

    # Determine the final stored path (local or S3 key) before persisting
    stored_path = pdf_path

    if storage_service.enabled:
        s3_key = f"receipts/{file_name}"
        uploaded_key = await asyncio.to_thread(storage_service.upload_file, pdf_path, s3_key)
        if uploaded_key:
            presigned_url = await asyncio.to_thread(storage_service.generate_presigned_url, s3_key)
            stored_path = s3_key  # Store the S3 key so it can be re-signed later
            if presigned_url:
                try:
                    os.remove(pdf_path)
                except Exception as cleanup_err:
                    mto_logger.warning(f"Failed to remove local temp PDF '{pdf_path}': {cleanup_err}")
                # Update receipt_history with the new S3 path before redirecting
                try:
                    pay_svc.save_receipt_record(
                        details["property_id"], payment_id, details,
                        stored_path, current_user.get("username", "system"),
                        current_user=current_user, db_session=db_session,
                    )
                except Exception as save_err:
                    mto_logger.warning(f"Failed to update receipt_history after S3 upload: {save_err}")
                return RedirectResponse(presigned_url, status_code=307)

    # Update receipt_history so the ledger "View Receipt" always opens the latest file
    try:
        pay_svc.save_receipt_record(
            details["property_id"], payment_id, details,
            stored_path, current_user.get("username", "system"),
            current_user=current_user, db_session=db_session,
        )
    except Exception as save_err:
        mto_logger.warning(f"Failed to update receipt_history: {save_err}")

    return FileResponse(pdf_path, media_type="application/pdf", filename=file_name)

@router.delete("/{payment_id}")
async def delete_payment(
    payment_id: int, current_user: dict = Depends(write_access), db_session: Session = Depends(get_db)
):
    try:
        return pay_svc.delete_payment_record(payment_id, current_user, db_session=db_session)
    except Exception as e:
        mto_logger.error(f"Payment deletion failed for id={payment_id}: {e}")
        raise HTTPException(status_code=400, detail="Payment could not be deleted. It may be linked to other records.")
