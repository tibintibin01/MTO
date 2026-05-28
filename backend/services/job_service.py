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
from typing import Any  # noqa: F401 — reserved for future typed job payloads

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, DisconnectionError
from sqlalchemy.orm import Session

from backend.database import SessionLocal, dispose_and_reconnect
from backend.models import Job
from utils.logger import mto_logger

# ---------------------------------------------------------------------------
# DB outage backoff constants
# ---------------------------------------------------------------------------
# When the worker detects a DB OperationalError it enters a backoff loop
# rather than hammering the DB every 5 seconds.
#
# Schedule: 2s → 4s → 8s → 16s → 30s (capped), then stays at 30s until
# the DB comes back. Once reconnected, backoff resets to the base value.
_DB_BACKOFF_BASE    = 2.0
_DB_BACKOFF_MAX     = 30.0
_DB_BACKOFF_FACTOR  = 2.0

# Sentinel exception classes so we can distinguish DB errors from job bugs
_DB_ERROR_TYPES = (OperationalError, DisconnectionError)


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
    "retention_run",
    "accrue_penalties",   # Monthly penalty accrual for delinquent accounts
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
    """
    Updates job fields by ID using a fresh session.

    Retries once on OperationalError — a brief DB blip during a long-running
    job (backup, bulk import) should not prevent the final status update from
    being written. If the second attempt also fails, the error is logged and
    the stale-job recovery mechanism will reset the job to PENDING on the
    next maintenance cycle.
    """
    for attempt in (1, 2):
        try:
            with SessionLocal() as db:
                job = db.query(Job).filter(Job.id == job_id).first()
                if job:
                    for k, v in kwargs.items():
                        setattr(job, k, v)
                    db.commit()
            return
        except _DB_ERROR_TYPES as e:
            if attempt == 1:
                mto_logger.warning(
                    "_update_job: DB error on attempt 1, retrying after pool reset: %s", e
                )
                dispose_and_reconnect()
                time.sleep(1)
            else:
                mto_logger.error(
                    "_update_job: DB error on attempt 2, giving up for job %s: %s",
                    job_id[:8], e,
                )


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
        elif job.job_type == "retention_run":
            _handle_retention_run(job, payload)
        elif job.job_type == "accrue_penalties":
            _handle_accrue_penalties(job, payload)
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


def _handle_retention_run(job: Job, payload: dict):
    """Runs the data retention policy for all active policies."""
    from backend.services.retention_service import run_retention

    dry_run = payload.get("dry_run", False)
    data_type = payload.get("data_type")  # None = run all

    _update_job(job.id, progress=10,
                progress_message="Starting retention policy run...")

    with SessionLocal() as db:
        result = run_retention(
            executed_by=job.submitted_by,
            dry_run=dry_run,
            data_type=data_type,
            db_session=db,
        )

    summary = (
        f"{'DRY RUN — ' if dry_run else ''}"
        f"{result['policies_run']} policy(ies) run, "
        f"{result['total_records_affected']} record(s) affected."
    )
    _update_job(job.id,
                status="COMPLETED",
                result=json.dumps(result),
                completed_at=datetime.now(timezone.utc),
                progress=100,
                progress_message=summary)


def _handle_accrue_penalties(job: Job, payload: dict):
    """
    Monthly penalty accrual for all delinquent PropertyBilling records.

    For each active property billing row where:
      - tax_year < current year (prior year, not yet settled)
      - amount_paid < (assessed_value * total_rate)  (still has a balance)

    Adds 2% of the outstanding balance to the penalty column.
    This ensures the delinquency dashboard always shows current penalty
    amounts without requiring a manual computation trigger.

    dry_run=True → computes totals but writes nothing to the DB.
    """
    from decimal import Decimal, ROUND_HALF_UP
    from backend.models import PropertyBilling, TaxPolicy

    dry_run = payload.get("dry_run", False)
    _update_job(job.id, progress=5, progress_message="Starting penalty accrual...")

    updated = 0
    skipped = 0
    total_penalty_added = Decimal("0.00")

    with SessionLocal() as db:
        current_year = datetime.now(timezone.utc).year

        # Fetch all prior-year billing rows that still have a balance
        rows = (
            db.query(PropertyBilling)
            .filter(
                PropertyBilling.tax_year < current_year,
                PropertyBilling.is_archived == False,
            )
            .all()
        )

        _update_job(job.id, progress=20,
                    progress_message=f"Scanning {len(rows)} billing rows...")

        # Cache tax policies to avoid N+1 queries
        policies = {
            p.tax_year: p
            for p in db.query(TaxPolicy).all()
        }

        for billing in rows:
            policy = policies.get(billing.tax_year)
            basic_rate   = Decimal(str(policy.basic_rate))   if policy else Decimal("0.01")
            sef_rate     = Decimal(str(policy.sef_rate))     if policy else Decimal("0.01")
            penalty_rate = Decimal(str(policy.penalty_rate)) if policy else Decimal("0.02")

            av = Decimal(str(billing.assessed_value or 0))
            total_tax = (av * (basic_rate + sef_rate)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            amount_paid = Decimal(str(billing.amount_paid or 0))
            current_penalty = Decimal(str(billing.penalty or 0))

            # Outstanding balance before this accrual
            balance = total_tax - amount_paid
            if balance <= 0:
                skipped += 1
                continue

            # Accrue one month's penalty on the outstanding balance
            new_penalty_increment = (balance * penalty_rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            if not dry_run:
                billing.penalty = current_penalty + new_penalty_increment

            total_penalty_added += new_penalty_increment
            updated += 1

        if not dry_run and updated > 0:
            db.commit()

    summary = (
        f"{'DRY RUN — ' if dry_run else ''}"
        f"Penalty accrual: {updated} rows updated, {skipped} skipped (no balance). "
        f"Total penalty added: ₱{total_penalty_added:,.2f}"
    )
    mto_logger.info(summary, job_id=job.id[:8])
    _update_job(
        job.id,
        status="COMPLETED",
        result=json.dumps({
            "dry_run": dry_run,
            "rows_updated": updated,
            "rows_skipped": skipped,
            "total_penalty_added": float(total_penalty_added),
        }),
        completed_at=datetime.now(timezone.utc),
        progress=100,
        progress_message=summary,
    )


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


def _cleanup_expired_refresh_tokens():
    """
    Deletes expired and revoked refresh tokens from the database.

    Refresh tokens expire after 7 days and are marked is_revoked=True on
    logout or password reset. Without cleanup the table grows unbounded —
    one row per login session per user, forever.

    Runs every 5 minutes alongside stale job recovery. Deletes tokens that
    are BOTH expired AND revoked (safe) or expired regardless of revocation
    status (expired tokens are useless whether revoked or not).
    """
    try:
        from backend.models import RefreshToken
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            deleted = db.query(RefreshToken).filter(
                RefreshToken.expires_at < now
            ).delete(synchronize_session=False)
            db.commit()
            if deleted > 0:
                mto_logger.info(f"Pruned {deleted} expired refresh token(s).")
    except Exception as e:
        mto_logger.error(f"Refresh token cleanup error: {e}")


def _check_scheduled_backup():
    """
    Submits a backup job if the configured schedule is due and no backup
    has already run in the current window.

    Schedule logic:
      disabled — never runs automatically
      daily    — runs once per day at BACKUP_SCHEDULE_HOUR:BACKUP_SCHEDULE_MINUTE
      weekly   — runs once per week on BACKUP_SCHEDULE_DAY_OF_WEEK at the
                 configured hour:minute

    Idempotency: checks BackupHistory for a completed backup within the
    current window before submitting. Safe to call every 5 minutes.
    """
    from utils.config import config as _cfg

    schedule = _cfg.BACKUP_SCHEDULE.strip().lower()
    if schedule == "disabled":
        return

    now = datetime.now()
    scheduled_hour   = _cfg.BACKUP_SCHEDULE_HOUR
    scheduled_minute = _cfg.BACKUP_SCHEDULE_MINUTE

    # Is it within the 5-minute window starting at the scheduled time?
    # The maintenance thread runs every 5 minutes, so we check whether
    # now falls in [scheduled_time, scheduled_time + 5 min).
    from datetime import timedelta
    window_start = now.replace(
        hour=scheduled_hour, minute=scheduled_minute,
        second=0, microsecond=0,
    )
    window_end = window_start + timedelta(minutes=5)

    if not (window_start <= now < window_end):
        return

    # For weekly: is it the right day?
    if schedule == "weekly":
        if now.weekday() != _cfg.BACKUP_SCHEDULE_DAY_OF_WEEK:
            return

    # Has a backup already completed in this window?
    try:
        from backend.models import BackupHistory, Job
        with SessionLocal() as db:
            recent = db.query(BackupHistory).filter(
                BackupHistory.status.in_(["LOCAL_ONLY", "SYNCED", "COMPLETED"]),
                BackupHistory.timestamp >= window_start,
                BackupHistory.filename != "__lock__",
            ).first()

            if recent:
                return  # Already ran this window

            # Is a backup job already queued or running?
            pending = db.query(Job).filter(
                Job.job_type == "backup",
                Job.status.in_(["PENDING", "RUNNING"]),
            ).first()

            if pending:
                return  # Already in the queue

        job_id = submit_job(job_type="backup", submitted_by="system:scheduler")
        mto_logger.info(
            "Scheduled backup submitted (schedule=%s, time=%02d:%02d): job %s",
            schedule, scheduled_hour, scheduled_minute, job_id[:8],
        )

    except Exception as e:
        mto_logger.error("Scheduled backup check failed: %s", e)


def _check_monthly_penalty_accrual():
    """
    Submits a penalty accrual job on the 1st of each month at 00:05 local time.

    Penalties accrue monthly per RA 7160 (Local Government Code) — 2% per month
    on the outstanding balance. Without this job, penalty amounts only update
    when a cashier manually triggers a computation. This job ensures the
    delinquency dashboard always shows current, accurate penalty totals.

    Idempotency: checks the jobs table for a completed accrual job this month
    before submitting. Safe to call every 5 minutes.
    """
    now = datetime.now()

    # Only run on the 1st of the month, between 00:05 and 00:10
    if now.day != 1:
        return
    if not (0 == now.hour and 5 <= now.minute < 10):
        return

    try:
        from backend.models import Job
        # Month window: from midnight on the 1st to now
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        with SessionLocal() as db:
            already_ran = db.query(Job).filter(
                Job.job_type == "accrue_penalties",
                Job.status.in_(["PENDING", "RUNNING", "COMPLETED"]),
                Job.created_at >= month_start,
            ).first()

            if already_ran:
                return

        job_id = submit_job(job_type="accrue_penalties", submitted_by="system:scheduler",
                            payload={"dry_run": False})
        mto_logger.info(
            "Monthly penalty accrual job submitted for %s-%02d: job %s",
            now.year, now.month, job_id[:8],
        )

    except Exception as e:
        mto_logger.error("Monthly penalty accrual check failed: %s", e)


def _recover_stale_jobs():
    """
    Resets jobs stuck in RUNNING back to PENDING.
    Called on startup and every 5 minutes by the maintenance thread.
    Also prunes expired idempotency keys, refresh tokens, and import caches.
    """
    _cleanup_expired_idempotency_keys()
    _cleanup_expired_refresh_tokens()

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
# Worker heartbeat registry
# ---------------------------------------------------------------------------
# Each worker thread writes its worker_id → timestamp here on every loop
# iteration (idle or busy). The health check reads this dict to detect
# threads that have stopped updating — indicating a dead or hung thread.
#
# Structure:
#   _worker_heartbeats = {
#       "fast-0-abc123": {
#           "last_beat":  datetime,   # last time the thread updated
#           "pool":       "fast",     # "fast" | "slow"
#           "status":     "idle",     # "idle" | "running" | "db_backoff"
#           "current_job": None,      # job_id[:8] or None
#           "thread_alive": True,     # threading.Thread.is_alive()
#       },
#       ...
#   }
#
# A thread is considered DEAD when:
#   - thread_alive is False (Python confirmed the thread exited), OR
#   - last_beat is older than HEARTBEAT_DEAD_THRESHOLD_SECONDS
#     (thread is alive but stuck — e.g. deadlock inside a job handler)
#
# A thread is considered STALE (warning, not dead) when:
#   - last_beat is older than HEARTBEAT_STALE_THRESHOLD_SECONDS
#     (thread is processing a long job — backup, bulk import)

HEARTBEAT_STALE_THRESHOLD_SECONDS = 60   # warn after 60s without a beat
HEARTBEAT_DEAD_THRESHOLD_SECONDS  = 300  # dead after 5 min without a beat

_worker_heartbeats: dict[str, dict] = {}
_heartbeat_lock = threading.Lock()
# Keep a reference to each Thread object so we can call .is_alive()
_worker_threads: dict[str, threading.Thread] = {}


def _beat(worker_id: str, pool: str, status: str, current_job: str | None = None):
    """
    Records a heartbeat for the given worker.
    Called from inside the worker loop — must be fast and never raise.
    """
    with _heartbeat_lock:
        _worker_heartbeats[worker_id] = {
            "last_beat": datetime.now(),
            "pool": pool,
            "status": status,
            "current_job": current_job,
        }


def get_worker_health() -> dict:
    """
    Returns the health status of all worker threads.

    Called by the /healthz endpoint and the /system/workers endpoint.
    Returns a dict with:
        overall:  "healthy" | "degraded" | "dead"
        workers:  list of per-thread status dicts
        summary:  human-readable summary string
    """
    now = datetime.now()
    workers = []
    dead_count = 0
    stale_count = 0

    with _heartbeat_lock:
        heartbeats = dict(_worker_heartbeats)
        threads = dict(_worker_threads)

    for worker_id, info in heartbeats.items():
        thread = threads.get(worker_id)
        thread_alive = thread.is_alive() if thread else False
        last_beat = info["last_beat"]
        age_seconds = (now - last_beat).total_seconds()

        if not thread_alive or age_seconds > HEARTBEAT_DEAD_THRESHOLD_SECONDS:
            state = "dead"
            dead_count += 1
        elif age_seconds > HEARTBEAT_STALE_THRESHOLD_SECONDS:
            state = "stale"
            stale_count += 1
        else:
            state = "healthy"

        workers.append({
            "worker_id": worker_id,
            "pool": info["pool"],
            "status": info["status"],
            "state": state,
            "current_job": info["current_job"],
            "last_beat_seconds_ago": round(age_seconds, 1),
            "thread_alive": thread_alive,
        })

    # Sort for consistent output: fast pool first, then slow
    workers.sort(key=lambda w: (w["pool"] != "fast", w["worker_id"]))

    if dead_count > 0:
        overall = "dead"
    elif stale_count > 0:
        overall = "stale"
    else:
        overall = "healthy"

    total = len(workers)
    summary = (
        f"{total} worker(s) registered — "
        f"{sum(1 for w in workers if w['state'] == 'healthy')} healthy, "
        f"{stale_count} stale, "
        f"{dead_count} dead"
    )

    return {
        "overall": overall,
        "workers": workers,
        "summary": summary,
        "fast_pool_size": FAST_POOL_SIZE,
        "slow_pool_size": SLOW_POOL_SIZE,
    }


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
            # Register initial heartbeat so the thread appears immediately
            _beat(worker_id, pool_name, "idle")
            # Current DB backoff delay. Resets to base after a successful DB op.
            db_backoff = _DB_BACKOFF_BASE

            while True:
                try:
                    job = _try_claim_job(worker_id, job_types)
                    if job:
                        mto_logger.info(
                            f"[{worker_id}] Claimed: {job.job_type} [{job.id[:8]}]"
                        )
                        _beat(worker_id, pool_name, "running", job.id[:8])
                        _run_job(job)
                        _beat(worker_id, pool_name, "idle")
                    else:
                        # Clear event, double-check, then block until woken
                        _job_submitted_event.clear()
                        job = _try_claim_job(worker_id, job_types)
                        if job:
                            mto_logger.info(
                                f"[{worker_id}] Claimed: {job.job_type} [{job.id[:8]}]"
                            )
                            _beat(worker_id, pool_name, "running", job.id[:8])
                            _run_job(job)
                            _beat(worker_id, pool_name, "idle")
                        else:
                            _beat(worker_id, pool_name, "idle")
                            _job_submitted_event.wait(timeout=10.0)

                    # Successful DB interaction — reset backoff
                    db_backoff = _DB_BACKOFF_BASE

                except _DB_ERROR_TYPES as e:
                    _beat(worker_id, pool_name, "db_backoff")
                    mto_logger.warning(
                        f"[{worker_id}] DB unavailable (backoff {db_backoff:.0f}s): {e}"
                    )
                    dispose_and_reconnect()
                    time.sleep(db_backoff)
                    db_backoff = min(db_backoff * _DB_BACKOFF_FACTOR, _DB_BACKOFF_MAX)

                except Exception as e:
                    _beat(worker_id, pool_name, "idle")
                    mto_logger.error(f"[{worker_id}] Unhandled error: {e}")
                    time.sleep(5)
                    db_backoff = _DB_BACKOFF_BASE

        t = threading.Thread(target=loop, daemon=True, name=worker_id)
        # Register thread reference before starting so health check can call .is_alive()
        with _heartbeat_lock:
            _worker_threads[worker_id] = t
        t.start()

    # Start fast pool
    for i in range(FAST_POOL_SIZE):
        make_worker("fast", FAST_JOB_TYPES, i)

    # Start slow pool
    for i in range(SLOW_POOL_SIZE):
        make_worker("slow", SLOW_JOB_TYPES, i)

    # Maintenance thread — recovers stale jobs every 5 minutes
    # and checks whether a scheduled backup is due.
    def maintenance_loop():
        while True:
            time.sleep(300)
            _recover_stale_jobs()
            _check_scheduled_backup()
            _cleanup_expired_idempotency_keys()
            _check_monthly_penalty_accrual()

    threading.Thread(target=maintenance_loop, daemon=True, name="JobMaintenance").start()

    mto_logger.info(
        f"Job worker pools started: {FAST_POOL_SIZE} fast + {SLOW_POOL_SIZE} slow threads."
    )


def _cleanup_expired_idempotency_keys() -> None:
    """
    Deletes idempotency_keys rows whose expires_at has passed.

    Called every 5 minutes by the maintenance thread. Without this, the
    table grows unbounded — every POST/PUT with an X-Idempotency-Key header
    adds a row that is never removed.

    Deletes in batches of 500 to avoid long-running DELETE statements that
    could lock the table and block concurrent payment operations.
    """
    try:
        with SessionLocal() as db:
            now = datetime.now(timezone.utc)
            total_deleted = 0
            while True:
                # Batch delete — find expired key IDs first, then delete by PK
                # to avoid a full table scan on the DELETE itself.
                rows = db.execute(text(
                    "SELECT id FROM idempotency_keys "
                    "WHERE expires_at < :now LIMIT 500"
                ), {"now": now}).fetchall()

                if not rows:
                    break

                ids = [r[0] for r in rows]
                db.execute(text(
                    "DELETE FROM idempotency_keys WHERE id IN :ids"
                ), {"ids": tuple(ids)})
                db.commit()
                total_deleted += len(ids)

                if len(ids) < 500:
                    break  # No more expired rows

            if total_deleted > 0:
                mto_logger.info(
                    f"Idempotency key cleanup: {total_deleted} expired keys deleted."
                )
    except Exception as e:
        mto_logger.warning(f"Idempotency key cleanup failed (non-fatal): {e}")


def stop_worker():
    """No-op — daemon threads stop automatically when the process exits."""
    pass
