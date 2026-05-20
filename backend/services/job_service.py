# -*- coding: utf-8 -*-
"""
Lightweight DB-backed background job queue.

No Celery, no Redis, no extra processes. A single worker thread polls the
jobs table every 2 seconds and executes PENDING jobs one at a time.

Usage — submitting a job from a route handler:
    from backend.services.job_service import submit_job

    job_id = submit_job(
        job_type="backup",
        submitted_by=current_user["username"],
        payload={},          # any JSON-serialisable dict
    )
    return {"job_id": job_id, "status": "queued"}

Usage — checking job status:
    GET /jobs/{job_id}

The worker is started once in main.py startup_event and runs for the
lifetime of the server process.
"""

import json
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import Job
from utils.logger import mto_logger


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

def submit_job(
    job_type: str,
    submitted_by: str,
    payload: dict | None = None,
    db_session: Session | None = None,
) -> str:
    """
    Creates a PENDING job record and returns the job ID.
    The caller should return this ID to the client immediately.
    """
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        job_type=job_type,
        status="PENDING",
        submitted_by=submitted_by,
        payload=json.dumps(payload or {}),
        progress=0,
    )

    if db_session:
        db_session.add(job)
        db_session.commit()
    else:
        with SessionLocal() as db:
            db.add(job)
            db.commit()

    mto_logger.info(f"Job submitted: {job_type} [{job_id[:8]}]", user=submitted_by)
    return job_id


def get_job(job_id: str, db_session: Session | None = None) -> dict | None:
    """Returns the current state of a job as a dict."""
    def _fetch(db):
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        return {
            "id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "submitted_by": job.submitted_by,
            "progress": job.progress,
            "progress_message": job.progress_message,
            "result": json.loads(job.result) if job.result else None,
            "error": job.error,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

    if db_session:
        return _fetch(db_session)
    with SessionLocal() as db:
        return _fetch(db)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _update_job(db: Session, job: Job, **kwargs):
    for k, v in kwargs.items():
        setattr(job, k, v)
    db.commit()


def _run_job(job: Job, db: Session):
    """Dispatches a job to the correct handler based on job_type."""
    payload = json.loads(job.payload or "{}")

    _update_job(db, job, status="RUNNING", started_at=datetime.now(), progress=5,
                progress_message="Starting...")

    try:
        if job.job_type == "backup":
            _handle_backup(job, db, payload)

        elif job.job_type == "import_commit":
            _handle_import_commit(job, db, payload)

        elif job.job_type in ("pdf_receipt", "pdf_soa", "pdf_computation",
                               "pdf_notice", "pdf_bulk_soa"):
            _handle_pdf(job, db, payload)

        else:
            raise ValueError(f"Unknown job type: {job.job_type}")

    except Exception as e:
        import traceback
        mto_logger.error(
            f"Job {job.job_type} [{job.id[:8]}] failed: {e}\n{traceback.format_exc()}"
        )
        _update_job(db, job,
                    status="FAILED",
                    error=str(e),
                    completed_at=datetime.now(),
                    progress=0)


def _handle_backup(job: Job, db: Session, payload: dict):
    import asyncio
    from backend.services.backup_service import run_hybrid_backup

    _update_job(db, job, progress=10, progress_message="Initiating backup...")

    # run_hybrid_backup is async — run it in a new event loop on this thread
    loop = asyncio.new_event_loop()
    try:
        user = {"username": job.submitted_by, "role": "admin"}
        success, message = loop.run_until_complete(
            run_hybrid_backup(user=user, db_session=db)
        )
    finally:
        loop.close()

    if success:
        _update_job(db, job,
                    status="COMPLETED",
                    result=json.dumps({"message": message}),
                    completed_at=datetime.now(),
                    progress=100,
                    progress_message="Backup completed successfully.")
    else:
        raise Exception(message)


def _handle_import_commit(job: Job, db: Session, payload: dict):
    mode = payload.get("mode", "property")
    data = payload.get("data", [])
    user = {"username": job.submitted_by, "role": "admin"}

    _update_job(db, job, progress=20, progress_message=f"Importing {len(data)} records...")

    if mode == "assessment":
        from backend.services.import_service import commit_assessment_import
        res = commit_assessment_import(data, user, db_session=db)
        result = {"inserted": res["inserted"], "updated": res["updated"]}
    elif mode == "payments":
        from backend.services.import_service import commit_payment_import
        res = commit_payment_import(data, user, db_session=db)
        result = {"inserted": res["inserted"]}
    else:
        from backend.services.import_service import commit_property_import
        count = commit_property_import(data, user, db_session=db)
        result = {"imported": count}

    _update_job(db, job,
                status="COMPLETED",
                result=json.dumps(result),
                completed_at=datetime.now(),
                progress=100,
                progress_message="Import completed.")


def _handle_pdf(job: Job, db: Session, payload: dict):
    import os
    from backend.generators import receipt_gen, soa_gen, computation_gen, notice_gen
    from backend.services.billing_service import get_property_statement_data
    from backend.services.payment_service import get_payment_receipt_details

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _update_job(db, job, progress=20, progress_message="Generating PDF...")

    if job.job_type == "pdf_receipt":
        payment_id = payload["payment_id"]
        details = get_payment_receipt_details(payment_id, db_session=db)
        if not details:
            raise Exception(f"Payment {payment_id} not found.")
        pdf_path = receipt_gen.generate_or_receipt(details, base_dir)

    elif job.job_type == "pdf_soa":
        property_id = payload["property_id"]
        details = get_property_statement_data(property_id, db_session=db)
        if not details:
            raise Exception(f"Property {property_id} not found.")
        pdf_path = soa_gen.generate_statement_of_account(details, base_dir)

    elif job.job_type == "pdf_computation":
        property_id = payload["property_id"]
        details = get_property_statement_data(property_id, db_session=db)
        if not details:
            raise Exception(f"Property {property_id} not found.")
        pdf_path = computation_gen.generate_delinquency_computation(details, base_dir)

    elif job.job_type == "pdf_notice":
        property_id = payload["property_id"]
        details = get_property_statement_data(property_id, db_session=db)
        if not details:
            raise Exception(f"Property {property_id} not found.")
        pdf_path = notice_gen.generate_delinquency_notice(details, base_dir)

    elif job.job_type == "pdf_bulk_soa":
        property_ids = payload["property_ids"]
        statements = []
        for pid in property_ids:
            d = get_property_statement_data(pid, db_session=db)
            if d:
                statements.append(d)
        if not statements:
            raise Exception("No valid properties found for bulk SOA.")
        pdf_path = soa_gen.bulk_generate_soa(statements, base_dir)

    else:
        raise ValueError(f"Unknown PDF job type: {job.job_type}")

    _update_job(db, job,
                status="COMPLETED",
                result=json.dumps({"file_path": pdf_path}),
                completed_at=datetime.now(),
                progress=100,
                progress_message="PDF ready.")


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

_worker_running = False


def start_worker():
    """
    Starts the background job worker thread.
    Called once from main.py startup_event.
    Safe to call multiple times — only one worker runs at a time.
    """
    global _worker_running
    if _worker_running:
        return

    _worker_running = True

    def worker_loop():
        mto_logger.info("Job worker started.")
        while _worker_running:
            try:
                with SessionLocal() as db:
                    # Pick the oldest PENDING job
                    job = (
                        db.query(Job)
                        .filter(Job.status == "PENDING")
                        .order_by(Job.created_at.asc())
                        .with_for_update(skip_locked=True)
                        .first()
                    )
                    if job:
                        mto_logger.info(
                            f"Job worker picked up: {job.job_type} [{job.id[:8]}]"
                        )
                        _run_job(job, db)
            except Exception as e:
                mto_logger.error(f"Job worker error: {e}")

            time.sleep(2)  # Poll every 2 seconds

    t = threading.Thread(target=worker_loop, daemon=True, name="JobWorker")
    t.start()


def stop_worker():
    global _worker_running
    _worker_running = False
