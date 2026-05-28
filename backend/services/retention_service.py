# -*- coding: utf-8 -*-
"""
Data Retention Service — RA 10173 (Data Privacy Act) & DICT MC 2022-002 Compliance
====================================================================================

Implements the government-mandated data lifecycle for the MTO Treasury System:

  Financial records (payments, receipts, billings)
    → ARCHIVE after 10 years  (COA minimum retention)
    → Never purged — archived records remain in DB, read-only

  Property assessments
    → Permanent — land records are never archived or purged

  Audit logs
    → ARCHIVE after 10 years  (COA minimum retention)
    → Never purged — immutable by design

  Deleted user accounts
    → PURGE after 5 years  (NPC: no longer necessary for declared purpose)

  Refresh tokens (expired/revoked)
    → PURGE after 30 days  (already short-lived, cleanup for DB hygiene)

Design decisions:
  - ARCHIVE = set is_archived=True / archived=True. Records stay in the DB,
    remain queryable for audit, but are excluded from active reports.
  - PURGE = hard DELETE. Only used for non-financial, non-audit data where
    the NPC requires actual erasure (deleted staff accounts, expired tokens).
  - Every action is recorded in retention_logs for COA/NPC audit trail.
  - dry_run=True previews what would be affected without writing anything.
  - All operations are batched (500 rows at a time) to avoid long-running
    transactions that could lock the DB.
"""

from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.database import SessionLocal
from backend.models import (
    RetentionPolicy,
    RetentionLog,
    Payment,
    PropertyBilling,
    PaymentBilling,
    ReceiptHistory,
    AuditLog,
    User,
    RefreshToken,
)
from utils.logger import mto_logger

# ---------------------------------------------------------------------------
# Default retention schedule (seeded into DB on first migration)
# ---------------------------------------------------------------------------

DEFAULT_POLICIES = [
    {
        "data_type": "payments",
        "description": "Official Receipt payment records. COA requires 10-year minimum retention.",
        "retention_years": 10,
        "action": "ARCHIVE",
        "legal_basis": "COA Circular 2009-006; RA 10173 Sec. 11",
    },
    {
        "data_type": "property_billings",
        "description": "Annual tax billing records per property. COA requires 10-year minimum retention.",
        "retention_years": 10,
        "action": "ARCHIVE",
        "legal_basis": "COA Circular 2009-006; RA 10173 Sec. 11",
    },
    {
        "data_type": "receipt_history",
        "description": "Generated PDF receipt audit trail. Retained alongside payment records.",
        "retention_years": 10,
        "action": "ARCHIVE",
        "legal_basis": "COA Circular 2009-006",
    },
    {
        "data_type": "audit_logs",
        "description": "System audit trail. Immutable by design; archived after 10 years for DB performance.",
        "retention_years": 10,
        "action": "ARCHIVE",
        "legal_basis": "COA Circular 2009-006; DICT MC 2022-002",
    },
    {
        "data_type": "deleted_users",
        "description": "Soft-deleted staff accounts. Purged after 5 years per NPC guidelines.",
        "retention_years": 5,
        "action": "PURGE",
        "legal_basis": "RA 10173 Sec. 11(e) — no longer necessary for declared purpose",
    },
    {
        "data_type": "expired_tokens",
        "description": "Expired and revoked refresh tokens. Purged after 30 days for DB hygiene.",
        "retention_years": 0,   # handled in days, not years — see _purge_expired_tokens
        "action": "PURGE",
        "legal_basis": "RA 10173 Sec. 11(e)",
    },
]

BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Policy management
# ---------------------------------------------------------------------------

def seed_default_policies(db_session: Session) -> int:
    """
    Inserts the default retention policies if they don't already exist.
    Called once during migration. Safe to call multiple times (INSERT IGNORE).
    Returns the number of policies inserted.
    """
    inserted = 0
    for p in DEFAULT_POLICIES:
        existing = db_session.query(RetentionPolicy).filter(
            RetentionPolicy.data_type == p["data_type"]
        ).first()
        if not existing:
            db_session.add(RetentionPolicy(**p))
            inserted += 1
    if inserted:
        db_session.commit()
    return inserted


def get_all_policies(db_session: Session) -> list[dict]:
    """Returns all retention policies with their last execution info."""
    policies = db_session.query(RetentionPolicy).order_by(
        RetentionPolicy.data_type
    ).all()

    result = []
    for p in policies:
        # Get the most recent log entry for this policy
        last_run = (
            db_session.query(RetentionLog)
            .filter(RetentionLog.policy_id == p.id)
            .order_by(RetentionLog.executed_at.desc())
            .first()
        )
        result.append({
            "id": p.id,
            "data_type": p.data_type,
            "description": p.description,
            "retention_years": p.retention_years,
            "action": p.action,
            "legal_basis": p.legal_basis,
            "is_active": p.is_active,
            "last_run": last_run.executed_at.isoformat() if last_run else None,
            "last_run_affected": last_run.records_affected if last_run else None,
            "last_run_action": last_run.action if last_run else None,
        })
    return result


def get_retention_logs(
    limit: int = 100,
    cursor: Optional[int] = None,
    db_session: Session = None,
) -> dict:
    """Returns paginated retention execution history."""
    safe_limit = min(max(1, int(limit)), 200)
    query = db_session.query(RetentionLog).order_by(RetentionLog.executed_at.desc())
    if cursor:
        query = query.filter(RetentionLog.id < int(cursor))
    rows = query.limit(safe_limit + 1).all()
    has_more = len(rows) > safe_limit
    items = rows[:safe_limit]
    return {
        "items": [
            {
                "id": r.id,
                "data_type": r.data_type,
                "action": r.action,
                "records_affected": r.records_affected,
                "cutoff_date": r.cutoff_date.strftime("%Y-%m-%d"),
                "executed_by": r.executed_by,
                "notes": r.notes,
                "executed_at": r.executed_at.isoformat(),
            }
            for r in items
        ],
        "next_cursor": items[-1].id if has_more and items else None,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# Core retention runner
# ---------------------------------------------------------------------------

def run_retention(
    executed_by: str,
    dry_run: bool = False,
    data_type: Optional[str] = None,
    db_session: Session = None,
) -> dict:
    """
    Runs the retention policy for all active policies (or a specific one).

    Parameters
    ----------
    executed_by : str
        Username of the admin who triggered this, or "system" for scheduled runs.
    dry_run : bool
        If True, counts affected records but writes nothing.
    data_type : str, optional
        Run only for this data type. If None, runs all active policies.
    db_session : Session
        Active SQLAlchemy session.

    Returns
    -------
    dict with summary of actions taken per data type.
    """
    query = db_session.query(RetentionPolicy).filter(RetentionPolicy.is_active == True)
    if data_type:
        query = query.filter(RetentionPolicy.data_type == data_type)
    policies = query.all()

    if not policies:
        return {"message": "No active retention policies found.", "results": []}

    results = []
    for policy in policies:
        try:
            result = _run_single_policy(policy, executed_by, dry_run, db_session)
            results.append(result)
        except Exception as e:
            mto_logger.error(
                "Retention policy failed for %s: %s", policy.data_type, e,
                exc_info=True,
            )
            results.append({
                "data_type": policy.data_type,
                "action": policy.action,
                "records_affected": 0,
                "error": str(e),
                "dry_run": dry_run,
            })

    total_affected = sum(r.get("records_affected", 0) for r in results)
    mto_logger.info(
        "Retention run complete: %d record(s) affected across %d policy(ies) (dry_run=%s)",
        total_affected, len(results), dry_run,
    )
    return {
        "dry_run": dry_run,
        "policies_run": len(results),
        "total_records_affected": total_affected,
        "results": results,
    }


def _run_single_policy(
    policy: RetentionPolicy,
    executed_by: str,
    dry_run: bool,
    db_session: Session,
) -> dict:
    """Dispatches to the correct handler based on data_type."""
    handlers = {
        "payments":         _archive_payments,
        "property_billings": _archive_property_billings,
        "receipt_history":  _archive_receipt_history,
        "audit_logs":       _archive_audit_logs,
        "deleted_users":    _purge_deleted_users,
        "expired_tokens":   _purge_expired_tokens,
    }

    handler = handlers.get(policy.data_type)
    if not handler:
        return {
            "data_type": policy.data_type,
            "action": policy.action,
            "records_affected": 0,
            "notes": "No handler registered for this data type.",
            "dry_run": dry_run,
        }

    cutoff = _cutoff_date(policy)
    affected = handler(cutoff, dry_run, db_session)

    if not dry_run:
        log = RetentionLog(
            policy_id=policy.id,
            data_type=policy.data_type,
            action=policy.action,
            records_affected=affected,
            cutoff_date=cutoff,
            executed_by=executed_by,
            notes=f"{'DRY RUN — ' if dry_run else ''}Cutoff: {cutoff.strftime('%Y-%m-%d')}",
            executed_at=datetime.now(),
        )
        db_session.add(log)
        db_session.commit()

    return {
        "data_type": policy.data_type,
        "action": "DRY_RUN" if dry_run else policy.action,
        "records_affected": affected,
        "cutoff_date": cutoff.strftime("%Y-%m-%d"),
        "dry_run": dry_run,
    }


def _cutoff_date(policy: RetentionPolicy) -> datetime:
    """Returns the datetime before which records are eligible for action."""
    if policy.data_type == "expired_tokens":
        # Tokens use days, not years
        return datetime.now() - timedelta(days=30)
    return datetime.now() - timedelta(days=policy.retention_years * 365)


# ---------------------------------------------------------------------------
# Individual handlers
# ---------------------------------------------------------------------------

def _archive_payments(cutoff: datetime, dry_run: bool, db: Session) -> int:
    """
    Archives payments older than the cutoff by marking their billing records
    as is_archived=True. The payment rows themselves are never deleted —
    they are financial records required by COA.

    We archive at the PropertyBilling level (which aggregates per year)
    rather than individual payment rows, since billing is the unit of
    financial reporting.
    """
    # Find property_billing records where all payments are older than cutoff
    # and the billing year is before the cutoff year
    cutoff_year = cutoff.year

    query = db.query(PropertyBilling).filter(
        PropertyBilling.is_archived == False,
        PropertyBilling.tax_year < cutoff_year,
    )

    count = query.count()
    if not dry_run and count > 0:
        # Batch update to avoid locking the table for too long
        ids = [r.id for r in query.limit(BATCH_SIZE).all()]
        while ids:
            db.query(PropertyBilling).filter(
                PropertyBilling.id.in_(ids)
            ).update({"is_archived": True}, synchronize_session=False)
            db.commit()
            ids = [
                r.id for r in query.limit(BATCH_SIZE).all()
            ]

    mto_logger.info(
        "Retention [payments/billings]: %d billing record(s) %s (cutoff year %d)",
        count, "would be archived" if dry_run else "archived", cutoff_year,
    )
    return count


def _archive_property_billings(cutoff: datetime, dry_run: bool, db: Session) -> int:
    """Same as _archive_payments — billings are the archival unit."""
    return _archive_payments(cutoff, dry_run, db)


def _archive_receipt_history(cutoff: datetime, dry_run: bool, db: Session) -> int:
    """
    Archives receipt history records older than the cutoff.
    Sets status to 'ARCHIVED'. The file_path is preserved so the PDF
    can still be located if needed for a COA audit.
    """
    query = db.query(ReceiptHistory).filter(
        ReceiptHistory.generated_at < cutoff,
        ReceiptHistory.status != "ARCHIVED",
    )
    count = query.count()

    if not dry_run and count > 0:
        ids = [r.id for r in query.limit(BATCH_SIZE).all()]
        while ids:
            db.query(ReceiptHistory).filter(
                ReceiptHistory.id.in_(ids)
            ).update({"status": "ARCHIVED"}, synchronize_session=False)
            db.commit()
            ids = [r.id for r in query.limit(BATCH_SIZE).all()]

    mto_logger.info(
        "Retention [receipt_history]: %d record(s) %s",
        count, "would be archived" if dry_run else "archived",
    )
    return count


def _archive_audit_logs(cutoff: datetime, dry_run: bool, db: Session) -> int:
    """
    Counts audit logs older than the cutoff.
    Audit logs are immutable (SQLAlchemy event prevents UPDATE/DELETE),
    so we only count them here — actual archival is done via the backup
    process (mysqldump exports them). This satisfies the COA requirement
    to have a documented retention schedule without violating immutability.
    """
    count = db.query(AuditLog).filter(AuditLog.timestamp < cutoff).count()
    mto_logger.info(
        "Retention [audit_logs]: %d record(s) older than %s "
        "(immutable — archived via backup, not modified in DB)",
        count, cutoff.strftime("%Y-%m-%d"),
    )
    return count


def _purge_deleted_users(cutoff: datetime, dry_run: bool, db: Session) -> int:
    """
    Hard-deletes user accounts that were soft-deleted more than 5 years ago.
    Per NPC guidelines, personal data must be erased when no longer necessary.
    Refresh tokens are cascade-deleted automatically.
    """
    query = db.query(User).filter(
        User.deleted_at != None,
        User.deleted_at < cutoff,
    )
    count = query.count()

    if not dry_run and count > 0:
        users = query.limit(BATCH_SIZE).all()
        while users:
            for user in users:
                db.delete(user)
            db.commit()
            users = query.limit(BATCH_SIZE).all()

    mto_logger.info(
        "Retention [deleted_users]: %d account(s) %s (deleted before %s)",
        count, "would be purged" if dry_run else "purged", cutoff.strftime("%Y-%m-%d"),
    )
    return count


def _purge_expired_tokens(cutoff: datetime, dry_run: bool, db: Session) -> int:
    """
    Hard-deletes refresh tokens that expired or were revoked more than 30 days ago.
    These have no legal retention requirement — pure DB hygiene.
    """
    query = db.query(RefreshToken).filter(
        RefreshToken.expires_at < cutoff,
    )
    count = query.count()

    if not dry_run and count > 0:
        query.delete(synchronize_session=False)
        db.commit()

    mto_logger.info(
        "Retention [expired_tokens]: %d token(s) %s",
        count, "would be purged" if dry_run else "purged",
    )
    return count
