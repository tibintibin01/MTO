# -*- coding: utf-8 -*-
"""
Job queue API endpoints.

Clients submit long-running operations here and get a job_id back immediately.
They then poll GET /jobs/{id} until status is COMPLETED or FAILED.

The desktop app's progress bars and the WebSocket notification system both
use these endpoints to show real-time feedback without blocking the UI.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.deps import get_current_user, write_access, admin_only, get_db, Session
from backend.services.job_service import submit_job, get_job
from utils.logger import mto_logger

router = APIRouter(prefix="/jobs", tags=["Jobs"])


# ---------------------------------------------------------------------------
# Status endpoint — poll this after submitting a job
# ---------------------------------------------------------------------------

@router.get("/{job_id}")
async def get_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """
    Returns the current status of a background job.

    Poll this endpoint after submitting any async operation.
    Status values: PENDING | RUNNING | COMPLETED | FAILED

    When COMPLETED, the `result` field contains the output (e.g. file path).
    When FAILED, the `error` field contains the failure reason.
    """
    job = get_job(job_id, db_session=db_session)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return job


# ---------------------------------------------------------------------------
# Submit endpoints — one per job type
# ---------------------------------------------------------------------------

@router.post("/backup")
async def submit_backup_job(
    current_user: dict = Depends(admin_only),
    db_session: Session = Depends(get_db),
):
    """Submits a hybrid backup job. Returns job_id immediately."""
    job_id = submit_job(
        job_type="backup",
        submitted_by=current_user["username"],
        payload={},
        db_session=db_session,
    )
    mto_logger.info("Backup job submitted", user=current_user["username"], job_id=job_id)
    return {"job_id": job_id, "status": "queued", "message": "Backup queued. Poll /jobs/{job_id} for progress."}


class ImportJobRequest(BaseModel):
    mode: str = Field("property", pattern="^(property|assessment|payments)$")
    data: List[dict]


@router.post("/import")
async def submit_import_job(
    body: ImportJobRequest,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    """Submits a bulk import job. Returns job_id immediately."""
    job_id = submit_job(
        job_type="import_commit",
        submitted_by=current_user["username"],
        payload={"mode": body.mode, "data": body.data},
        db_session=db_session,
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "message": f"Import of {len(body.data)} records queued.",
    }


@router.post("/pdf/receipt/{payment_id}")
async def submit_receipt_pdf_job(
    payment_id: int,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    """Submits a receipt PDF generation job. Returns job_id immediately."""
    job_id = submit_job(
        job_type="pdf_receipt",
        submitted_by=current_user["username"],
        payload={"payment_id": payment_id},
        db_session=db_session,
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/pdf/soa/{property_id}")
async def submit_soa_pdf_job(
    property_id: int,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """Submits a Statement of Account PDF generation job."""
    job_id = submit_job(
        job_type="pdf_soa",
        submitted_by=current_user["username"],
        payload={"property_id": property_id},
        db_session=db_session,
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/pdf/computation/{property_id}")
async def submit_computation_pdf_job(
    property_id: int,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """Submits a delinquency computation PDF generation job."""
    job_id = submit_job(
        job_type="pdf_computation",
        submitted_by=current_user["username"],
        payload={"property_id": property_id},
        db_session=db_session,
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/pdf/notice/{property_id}")
async def submit_notice_pdf_job(
    property_id: int,
    current_user: dict = Depends(get_current_user),
    db_session: Session = Depends(get_db),
):
    """Submits a delinquency notice PDF generation job."""
    job_id = submit_job(
        job_type="pdf_notice",
        submitted_by=current_user["username"],
        payload={"property_id": property_id},
        db_session=db_session,
    )
    return {"job_id": job_id, "status": "queued"}


class BulkSOAJobRequest(BaseModel):
    property_ids: List[int] = Field(..., min_length=1, max_length=200)


@router.post("/pdf/bulk-soa")
async def submit_bulk_soa_job(
    body: BulkSOAJobRequest,
    current_user: dict = Depends(write_access),
    db_session: Session = Depends(get_db),
):
    """Submits a bulk SOA PDF generation job for multiple properties."""
    job_id = submit_job(
        job_type="pdf_bulk_soa",
        submitted_by=current_user["username"],
        payload={"property_ids": body.property_ids},
        db_session=db_session,
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "message": f"Bulk SOA for {len(body.property_ids)} properties queued.",
    }
