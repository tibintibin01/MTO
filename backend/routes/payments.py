import os
import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from backend.deps import get_current_user, write_access, get_db, Session
from backend.schemas import ReceiptRecordSchema
from backend.models import Payment, Property
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


# ---------------------------------------------------------------------------
# Batch delete — for correcting bulk import mistakes
# ---------------------------------------------------------------------------

class BatchDeletePreviewRequest(BaseModel):
    or_numbers: list

class BatchDeleteCommitRequest(BaseModel):
    payment_ids: list


@router.post("/batch-delete/preview")
async def batch_delete_preview(
    data: BatchDeletePreviewRequest,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    """
    Preview which payments will be deleted given a list of OR numbers.
    Returns matching payment records so the user can verify before committing.
    """
    if not data.or_numbers:
        raise HTTPException(status_code=400, detail="or_numbers list is required.")

    # Normalise — strip whitespace, remove empty strings, cap at 500
    or_list = [str(o).strip() for o in data.or_numbers if str(o).strip()][:500]

    rows = (
        db_session.query(
            Payment.id,
            Payment.or_number,
            Payment.tax_year,
            Payment.amount,
            Payment.discount,
            Payment.penalty,
            Payment.date_paid,
            Property.td_number,
            Property.owner_name,
        )
        .join(Property, Property.id == Payment.property_id)
        .filter(Payment.or_number.in_(or_list))
        .order_by(Property.td_number.asc(), Payment.tax_year.asc())
        .all()
    )

    found_or = {r[1] for r in rows}
    not_found = [o for o in or_list if o not in found_or]

    return {
        "found": len(rows),
        "not_found_count": len(not_found),
        "not_found": not_found[:50],
        "preview": [
            {
                "payment_id": r[0],
                "or_number":  r[1],
                "tax_year":   r[2],
                "amount":     float(r[3] or 0),
                "discount":   float(r[4] or 0),
                "penalty":    float(r[5] or 0),
                "date_paid":  r[6].strftime("%Y-%m-%d") if r[6] else None,
                "td_number":  r[7],
                "owner_name": r[8],
            }
            for r in rows
        ],
    }


@router.post("/batch-delete/preview-by-ids")
async def batch_delete_preview_by_ids(
    data: BatchDeleteCommitRequest,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    """
    Preview payments by their exact Payment IDs.
    Safer than OR-number lookup — targets only the specific rows you want.
    """
    if not data.payment_ids:
        raise HTTPException(status_code=400, detail="payment_ids list is required.")

    id_list = [int(i) for i in data.payment_ids][:500]

    rows = (
        db_session.query(
            Payment.id,
            Payment.or_number,
            Payment.tax_year,
            Payment.amount,
            Payment.discount,
            Payment.penalty,
            Payment.date_paid,
            Property.td_number,
            Property.owner_name,
        )
        .join(Property, Property.id == Payment.property_id)
        .filter(Payment.id.in_(id_list))
        .order_by(Property.td_number.asc(), Payment.tax_year.asc())
        .all()
    )

    found_ids  = {r[0] for r in rows}
    not_found  = [i for i in id_list if i not in found_ids]

    return {
        "found": len(rows),
        "not_found_count": len(not_found),
        "not_found": not_found[:50],
        "preview": [
            {
                "payment_id": r[0],
                "or_number":  r[1],
                "tax_year":   r[2],
                "amount":     float(r[3] or 0),
                "discount":   float(r[4] or 0),
                "penalty":    float(r[5] or 0),
                "date_paid":  r[6].strftime("%Y-%m-%d") if r[6] else None,
                "td_number":  r[7],
                "owner_name": r[8],
            }
            for r in rows
        ],
    }


async def batch_delete_commit(
    data: BatchDeleteCommitRequest,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    """
    Deletes a list of payment IDs and reverses their billing balances.
    Each deletion is wrapped in the same logic as the single-payment delete
    so billing records are correctly updated.
    """
    if not data.payment_ids:
        raise HTTPException(status_code=400, detail="payment_ids list is required.")

    payment_ids = [int(i) for i in data.payment_ids][:500]

    deleted = 0
    failed = []

    for pid in payment_ids:
        try:
            pay_svc.delete_payment_record(pid, current_user, db_session=db_session)
            deleted += 1
        except Exception as e:
            failed.append({"payment_id": pid, "reason": str(e)[:120]})

    mto_logger.info(
        f"Batch delete: {deleted} deleted, {len(failed)} failed",
        user=current_user.get("username"),
    )

    return {
        "deleted": deleted,
        "failed_count": len(failed),
        "failed": failed[:20],
    }
