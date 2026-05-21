# -*- coding: utf-8 -*-
"""
DB-backed background job queue with concurrent worker pools.

Architecture
------------
Two thread pools run independently:

  FAST pool  (3 threads) — pdf_receipt, pdf_soa, pdf_computation,
                            pdf_notice, pdf_bulk_soa
  SLOW pool  (1 thread)  — backup, import_commit, sync_billing_years

This prevents a 10-minute bulk import from blocking receipt generation.

Claim mechanism (MariaDB 10.4 compatible)
-----------------------------------------
Each worker thread has a unique worker_id (UUID). To claim a job it does:

    UPDATE jobs SET status='RUNNING', worker_id=?, started_at=?
    WHERE id = (
        SELECT id FROM jobs
        WHERE status='PENDING' AND job_type IN (...)
        ORDER BY created_at ASC LIMIT 1
    )

The UPDATE is atomic — only one thread wins the race even without
SKIP LOCKED. The winner gets rowcount=1; losers get rowcount=0 and
move on to the next poll cycle.

Stale job recovery
------------------
Jobs stuck in RUNNING for >10 minutes are reset to PENDING on startup
and every 5 minutes thereafter. This handles crashed worker threads.
"""

import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import Job
from utils.logger import mto_logger


# ---------------------------------------------------------------------------
# Job type routing
# ---------------------------------------------------------------------------

#: Job types handled by the fast pool (short-running, user-facing)
FAST_JOB_TYPES = frozenset({
    "pdf_receipt",
    "pdf_soa",
    "pdf_computation",
    "pdf_notice",
    "pdf_bulk_soa",
})

#: Job types handled by the slow pool (long-running, background)
SLOW_JOB_TYPES = frozenset({
    "backup",
    "import_commit",
    "sync_billing_years",
})

ALL_JOB_TYPES = FAST_JOB_TYPES | SLOW_JOB_TYPES

# Pool sizes
FAST_POOL_SIZE = 3
SLOW_POOL_SIZE = 1

# A job stuck in RUNNING longer than this is considered stale
STALE_THRESHOLD_MINUTES = 10


# ---------------------------------------------------------------------------
# Submit / query
# ---------------------------------------------------------------------------

_job_submitted_event = threading.Event()


def submit_job(
    job_type: str,
    submitted_by: str,
    payload: dict | None = None,
    db_session: Session | None = None,
) -> str:
    """Creates a PENDING job and returns its ID immediately."""
    if job_type not in ALL_JOB_TYPES:
        raise ValueError(f"Unknown job type: {job_type!r}")

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
    _job_submitted_event.set()
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
# Claim mechanism
# ---------------------------------------------------------------------------

def _try_claim_job(worker_id: str, job_types: frozenset) -> Job | None:
    """
    Atomically claims the oldest PENDING job of the given types.

    Uses a two-step approach compatible with MariaDB 10.4:
      1. SELECT the oldest PENDING job id (no lock needed — just a hint)
      2. UPDATE ... WHERE id=? AND status='PENDING'
         (atomic — only one thread wins; losers get rowcount=0)

    Returns the claimed Job object, or None if nothing was available.
    """
    type_list = ", ".join(f"'{t}'" for t in job_types)

    with SessionLocal() as db:
        # Step 1: find a candidate
        row = db.execute(text(
            f"SELECT id FROM jobs "
            f"WHERE status = 'PENDING' AND job_type IN ({type_list}) "
            f"ORDER BY created_at ASC LIMIT 1"
        )).fetchone()

        if not row:
            return None

        candidate_id = row[0]
        now = datetime.now(timezone.utc).isoformat()

        # Step 2: atomic claim — only one thread wins
        result = db.execute(text(
            "UPDATE jobs SET status = 'RUNNING', "
            "started_at = :now, "
            "progress_message = 'Claimed by worker' "
            "WHERE id = :id AND status = 'PENDING'"
        ), {"id": candidate_id, "now": now})
        db.commit()

        if result.rowcount == 0:
            # Another thread claimed it first
            return None

        # Re-fetch the full object in a fresh query
        job = db.query(Job).filter(Job.id == candidate_id).first()
        if job:
            db.expunge(job)  # detach so it can be used outside this session
        return job


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------

def _update_job(job_id: str, **kwargs):
    """Updates job fields by ID using a fresh session."""
    with SessionLocal() as db:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            for k, v in kwargs.items():
                setattr(job, k, v)
            db.commit()


def _run_job(job: Job):
    """Dispatches a claimed job to the correct handler."""
    payload = json.loads(job.payload or "{}")
    _update_job(job.id, progress=5, progress_message="Starting...")

    try:
        if job.job_type == "backup":
            _handle_backup(job, payload)
        elif job.job_type == "import_commit":
            _handle_import_commit(job, payload)
        elif job.job_type in FAST_JOB_TYPES:
            _handle_pdf(job, payload)
        elif job.job_type == "sync_billing_years":
            _handle_sync_billing_years(job, payload)
        else:
            raise ValueError(f"Unknown job type: {job.job_type}")

    except Exception as e:
        import traceback
        mto_logger.error(
            f"Job {job.job_type} [{job.id[:8]}] failed: {e}\n{traceback.format_exc()}"
        )
        _update_job(job.id,
                    status="FAILED",
                    error=str(e),
                    completed_at=datetime.now(timezone.utc),
                    progress=0,
                    progress_message=f"Failed: {str(e)[:200]}")


# ---------------------------------------------------------------------------
# Job handlers — each uses its own DB session
# ---------------------------------------------------------------------------

def _handle_sync_billing_years(job: Job, payload: dict):
    from backend.services.billing_sync_service import sync_billing_years

    def progress(current, total, msg):
        pct = int((current / total) * 100) if total > 0 else 0
        _update_job(job.id, progress=pct, progress_message=msg)

    with SessionLocal() as db:
        result = sync_billing_years(db_session=db, dry_run=False, progress_callback=progress)

    _update_job(job.id,
                status="COMPLETED",
                result=json.dumps(result),
                completed_at=datetime.now(timezone.utc),
                progress=100,
                progress_message=(
                    f"Done: {result['records_created']} records created, "
                    f"{result['records_skipped']} already existed."
                ))


def _handle_backup(job: Job, payload: dict):
    import asyncio
    from backend.services.backup_service import run_hybrid_backup

    _update_job(job.id, progress=10, progress_message="Initiating backup...")

    loop = asyncio.new_event_loop()
    try:
        user = {"username": job.submitted_by, "role": "admin"}
        with SessionLocal() as db:
            success, message = loop.run_until_complete(
                run_hybrid_backup(user=user, db_session=db)
            )
    finally:
        loop.close()

    if success:
        _update_job(job.id,
                    status="COMPLETED",
                    result=json.dumps({"message": message}),
                    completed_at=datetime.now(timezone.utc),
                    progress=100,
                    progress_message="Backup completed successfully.")
    else:
        raise Exception(message)


def _handle_import_commit(job: Job, payload: dict):
    mode = payload.get("mode", "property")
    data = payload.get("data", [])
    user = {"username": job.submitted_by, "role": "admin"}

    _update_job(job.id, progress=20, progress_message=f"Importing {len(data)} records...")

    with SessionLocal() as db:
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

    _update_job(job.id,
                status="COMPLETED",
                result=json.dumps(result),
                completed_at=datetime.now(timezone.utc),
                progress=100,
                progress_message="Import completed.")


def _handle_pdf(job: Job, payload: dict):
    import os
    from backend.generators import receipt_gen, soa_gen, computation_gen, notice_gen

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _update_job(job.id, progress=20, progress_message="Generating PDF...")

    with SessionLocal() as db:
        from backend.services.billing_service import get_property_statement_data
        from backend.services.payment_service import get_payment_receipt_details

        if job.job_type == "pdf_receipt":
            details = get_payment_receipt_details(payload["payment_id"], db_session=db)
            if not details:
                raise Exception(f"Payment {payload['payment_id']} not found.")
            pdf_path = receipt_gen.generate_or_receipt(details, base_dir)

        elif job.job_type == "pdf_soa":
            details = get_property_statement_data(payload["property_id"], db_session=db)
            if not details:
                raise Exception(f"Property {payload['property_id']} not found.")
            pdf_path = soa_gen.generate_statement_of_account(details, base_dir)

        elif job.job_type == "pdf_computation":
            details = get_property_statement_data(payload["property_id"], db_session=db)
            if not details:
                raise Exception(f"Property {payload['property_id']} not found.")
            pdf_path = computation_gen.generate_delinquency_computation(details, base_dir)

        elif job.job_type == "pdf_notice":
            details = get_property_statement_data(payload["property_id"], db_session=db)
            if not details:
                raise Exception(f"Property {payload['property_id']} not found.")
            pdf_path = notice_gen.generate_delinquency_notice(details, base_dir)

        elif job.job_type == "pdf_bulk_soa":
            statements = [
                d for pid in payload["property_ids"]
                if (d := get_property_statement_data(pid, db_session=db))
            ]
            if not statements:
                raise Exception("No valid properties found for bulk SOA.")
            pdf_path = soa_gen.bulk_generate_soa(statements, base_dir)

        else:
            raise ValueError(f"Unknown PDF job type: {job.job_type}")

    _update_job(job.id,
                status="COMPLETED",
                result=json.dumps({"file_path": pdf_path}),
                completed_at=datetime.now(timezone.utc),
                progress=100,
                progress_message="PDF ready.")


# ---------------------------------------------------------------------------
# Stale job recovery
# ---------------------------------------------------------------------------

def _cleanup_expired_idempotency_keys():
    """
    Deletes expired rows in the idempotency_keys table.
    """
    try:
        from backend.models import IdempotencyKey
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            deleted = db.query(IdempotencyKey).filter(IdempotencyKey.expires_at < now).delete(synchronize_session=False)
            db.commit()
            if deleted > 0:
                mto_logger.info(f"Pruned {deleted} expired idempotency keys.")
    except Exception as e:
        mto_logger.error(f"Idempotency keys cleanup error: {e}")


def _recover_stale_jobs():
    """
    Resets jobs stuck in RUNNING back to PENDING.
    Called on startup and every 5 minutes by the maintenance thread.
    Also prunes expired idempotency keys and validation caches.
    """
    _cleanup_expired_idempotency_keys()
    
    try:
        from backend.services.import_service import prune_old_import_cache
        prune_old_import_cache()
    except Exception as e:
        mto_logger.error(f"Import cache pruning error: {e}")
        
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_THRESHOLD_MINUTES)
    try:
        with SessionLocal() as db:
            result = db.execute(text(
                "UPDATE jobs SET status = 'PENDING', started_at = NULL, "
                "progress = 0, progress_message = 'Reset after stale timeout' "
                "WHERE status = 'RUNNING' AND started_at < :cutoff"
            ), {"cutoff": cutoff.isoformat()})
            db.commit()
            if result.rowcount > 0:
                mto_logger.warning(
                    f"Recovered {result.rowcount} stale job(s) back to PENDING."
                )
    except Exception as e:
        mto_logger.error(f"Stale job recovery error: {e}")


# ---------------------------------------------------------------------------
# Worker pool
# ---------------------------------------------------------------------------

_workers_started = False
_worker_lock = threading.Lock()


def start_worker():
    """
    Starts two thread pools: FAST (3 threads) and SLOW (1 thread).
    Safe to call multiple times — idempotent.
    """
    global _workers_started
    with _worker_lock:
        if _workers_started:
            return
        _workers_started = True

    # Recover any stale jobs from a previous server crash
    _recover_stale_jobs()

    def make_worker(pool_name: str, job_types: frozenset, worker_index: int):
        worker_id = f"{pool_name}-{worker_index}-{uuid.uuid4().hex[:6]}"

        def loop():
            mto_logger.info(f"Job worker started: {worker_id} ({pool_name} pool)")
            while True:
                try:
                    job = _try_claim_job(worker_id, job_types)
                    if job:
                        mto_logger.info(
                            f"[{worker_id}] Claimed: {job.job_type} [{job.id[:8]}]"
                        )
                        _run_job(job)
                    else:
                        # Clear event, double check, and block on event wake signal
                        _job_submitted_event.clear()
                        job = _try_claim_job(worker_id, job_types)
                        if job:
                            mto_logger.info(
                                f"[{worker_id}] Claimed: {job.job_type} [{job.id[:8]}]"
                            )
                            _run_job(job)
                        else:
                            _job_submitted_event.wait(timeout=10.0)
                except Exception as e:
                    mto_logger.error(f"[{worker_id}] Unhandled error: {e}")
                    time.sleep(5)

        t = threading.Thread(target=loop, daemon=True, name=worker_id)
        t.start()

    # Start fast pool
    for i in range(FAST_POOL_SIZE):
        make_worker("fast", FAST_JOB_TYPES, i)

    # Start slow pool
    for i in range(SLOW_POOL_SIZE):
        make_worker("slow", SLOW_JOB_TYPES, i)

    # Maintenance thread — recovers stale jobs every 5 minutes
    def maintenance_loop():
        while True:
            time.sleep(300)
            _recover_stale_jobs()

    threading.Thread(target=maintenance_loop, daemon=True, name="JobMaintenance").start()

    mto_logger.info(
        f"Job worker pools started: {FAST_POOL_SIZE} fast + {SLOW_POOL_SIZE} slow threads."
    )


def stop_worker():
    """No-op — daemon threads stop automatically when the process exits."""
    pass
