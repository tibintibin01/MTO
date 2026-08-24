import os
import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from backend.deps import get_current_user, write_access, get_db, Session
from backend.schemas import ReceiptRecordSchema, RecentPaymentSchema
from backend.models import Payment, Property
import backend.services.payment_service as pay_svc
from backend.generators import receipt_gen
from backend.services.storage_service import storage_service
from utils.logger import mto_logger

router = APIRouter(prefix="/payments", tags=["Financial"])


class PaymentUpdateRequest(BaseModel):
    or_number: str = Field(..., min_length=1)
    date_paid: str = Field(..., min_length=1)
    tax_year: str = Field(..., min_length=4)
    amount: float = Field(..., gt=0)
    penalty: float = Field(default=0.0, ge=0)
    discount: float = Field(default=0.0, ge=0)
    remarks: Optional[str] = None


@router.get("/recent", response_model=list[RecentPaymentSchema])
def get_recent_payments(
    limit: int = Query(default=8, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    return pay_svc.get_recent_payments(limit, db_session=db_session)


@router.get("/records")
def get_payment_records(
    term: str,
    limit: int = 50,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    return pay_svc.get_payment_receipt_records(
        term, limit=limit, cursor=cursor, db_session=db_session
    )


@router.get("/{payment_id}/details")
def get_payment_details(
    payment_id: int,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    res = pay_svc.get_payment_receipt_details(payment_id, db_session=db_session)
    if not res:
        raise HTTPException(status_code=404, detail="Payment details not found")
    return res


@router.post("/receipt-record")
def save_receipt_record(
    data: ReceiptRecordSchema,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    return pay_svc.save_receipt_record(
        data.property_id,
        data.payment_id,
        data.details,
        data.file_path,
        data.user_name,
        current_user=current_user,
        db_session=db_session,
    )


@router.get("/ledger")
def get_payment_ledger(
    term: str,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    return pay_svc.get_unified_payment_history(term, db_session=db_session)


@router.get("/next-or")
def get_next_or_number(
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    return {"next_or": pay_svc.get_next_or_number(db_session=db_session)}


@router.get("/trend")
def get_collection_trend(
    months: int = 6,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    return pay_svc.get_monthly_collection_trend(months, db_session=db_session)


@router.post("/{payment_id}/receipt-pdf")
async def generate_receipt_pdf(
    payment_id: int,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    details = pay_svc.get_payment_receipt_details(payment_id, db_session=db_session)
    if not details:
        raise HTTPException(status_code=404, detail="Payment details not found")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # PDF generation is CPU/IO-bound — offload to a thread to avoid
    # blocking the async event loop under concurrent requests.
    pdf_path = await asyncio.to_thread(
        receipt_gen.generate_or_receipt, details, base_dir
    )
    file_name = os.path.basename(pdf_path)

    # Determine the final stored path (local or S3 key) before persisting
    stored_path = pdf_path

    if storage_service.enabled:
        s3_key = f"receipts/{file_name}"
        uploaded_key = await asyncio.to_thread(
            storage_service.upload_file, pdf_path, s3_key
        )
        if uploaded_key:
            presigned_url = await asyncio.to_thread(
                storage_service.generate_presigned_url, s3_key
            )
            stored_path = s3_key  # Store the S3 key so it can be re-signed later
            try:
                pay_svc.save_receipt_record(
                    details["property_id"],
                    payment_id,
                    details,
                    stored_path,
                    current_user.get("username", "system"),
                    current_user=current_user,
                    db_session=db_session,
                )
            except Exception as save_err:
                mto_logger.error(
                    f"Failed to register cloud payment-record PDF: {save_err}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="The PDF was created but its retained copy could not be registered.",
                ) from save_err
            if presigned_url:
                try:
                    os.remove(pdf_path)
                except Exception as cleanup_err:
                    mto_logger.warning(
                        f"Failed to remove local temp PDF '{pdf_path}': {cleanup_err}"
                    )
                return RedirectResponse(presigned_url, status_code=303)

    # Keep one current server-side PDF reference for this payment. Generating
    # again replaces that copy instead of creating a new historical document.
    try:
        pay_svc.save_receipt_record(
            details["property_id"],
            payment_id,
            details,
            stored_path,
            current_user.get("username", "system"),
            current_user=current_user,
            db_session=db_session,
        )
    except Exception as save_err:
        mto_logger.error(f"Failed to register payment-record PDF: {save_err}")
        raise HTTPException(
            status_code=500,
            detail="The PDF was created but its retained copy could not be registered.",
        ) from save_err

    return FileResponse(pdf_path, media_type="application/pdf", filename=file_name)


@router.get("/{payment_id}/receipt-pdf")
async def view_receipt_pdf(
    payment_id: int,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """Download the current retained PDF copy without regenerating it."""
    details = pay_svc.get_payment_receipt_details(payment_id, db_session=db_session)
    if not details:
        raise HTTPException(status_code=404, detail="Payment details not found")

    stored_path = details.get("file_path")
    local_path = pay_svc._trusted_local_receipt_path(stored_path)
    if local_path is not None and local_path.is_file():
        return FileResponse(
            str(local_path),
            media_type="application/pdf",
            filename=local_path.name,
        )

    if (
        stored_path
        and local_path is None
        and pay_svc._trusted_receipt_reference(stored_path)
        and storage_service.enabled
    ):
        presigned_url = await asyncio.to_thread(
            storage_service.generate_presigned_url,
            str(stored_path).replace("\\", "/"),
        )
        if presigned_url:
            return RedirectResponse(presigned_url, status_code=307)

    raise HTTPException(
        status_code=404,
        detail=(
            "The payment is recorded, but its generated PDF copy is unavailable. "
            "Use Regenerate PDF to create the current copy."
        ),
    )


@router.put("/{payment_id}")
def update_payment(
    payment_id: int,
    data: PaymentUpdateRequest,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    try:
        return pay_svc.update_payment_record(
            payment_id, data.model_dump(), current_user, db_session=db_session
        )
    except Exception as e:
        mto_logger.error(f"Payment update failed for id={payment_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{payment_id}")
def delete_payment(
    payment_id: int,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    try:
        return pay_svc.delete_payment_record(
            payment_id, current_user, db_session=db_session
        )
    except Exception as e:
        mto_logger.error(f"Payment deletion failed for id={payment_id}: {e}")
        raise HTTPException(
            status_code=400,
            detail="Payment could not be deleted. It may be linked to other records.",
        )


# ---------------------------------------------------------------------------
# Batch delete — for correcting bulk import mistakes
# ---------------------------------------------------------------------------


class BatchDeletePreviewRequest(BaseModel):
    or_numbers: list


class BatchDeleteCommitRequest(BaseModel):
    payment_ids: list


@router.get("/cleanup-candidates")
def payment_cleanup_candidates(
    year: int = 2026,
    limit: int = 500,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    """
    Preview payment rows that may explain reconciliation drift.
    This does not delete or modify anything.
    """
    return pay_svc.get_payment_cleanup_candidates(
        year=year, limit=limit, db_session=db_session
    )


@router.post("/batch-delete/preview")
def batch_delete_preview(
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
                "or_number": r[1],
                "tax_year": r[2],
                "amount": float(r[3] or 0),
                "discount": float(r[4] or 0),
                "penalty": float(r[5] or 0),
                "date_paid": r[6].strftime("%Y-%m-%d") if r[6] else None,
                "td_number": r[7],
                "owner_name": r[8],
            }
            for r in rows
        ],
    }


@router.post("/batch-delete/preview-by-ids")
def batch_delete_preview_by_ids(
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

    found_ids = {r[0] for r in rows}
    not_found = [i for i in id_list if i not in found_ids]

    return {
        "found": len(rows),
        "not_found_count": len(not_found),
        "not_found": not_found[:50],
        "preview": [
            {
                "payment_id": r[0],
                "or_number": r[1],
                "tax_year": r[2],
                "amount": float(r[3] or 0),
                "discount": float(r[4] or 0),
                "penalty": float(r[5] or 0),
                "date_paid": r[6].strftime("%Y-%m-%d") if r[6] else None,
                "td_number": r[7],
                "owner_name": r[8],
            }
            for r in rows
        ],
    }


@router.post("/batch-delete/commit")
def batch_delete_commit(
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
            pay_svc.delete_payment_record(
                pid, current_user, db_session=db_session, current_user=current_user
            )
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
