"""Fail-closed Phase 4 rollout manager for verified duplicate TD accounts.

The command never creates a property or posts a payment. It validates the
database migration, current cloud-protected backup, restore verification,
duplicate state, and administrator identity before changing the protected
machine-vault flag. Activation starts in one-TD pilot mode. Expansion requires
an automated isolation check, a newer verified backup, and explicit operator
confirmation after the manual acceptance checklist has been completed.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal  # noqa: E402
from backend.models import (  # noqa: E402
    AuditLog,
    BackupHistory,
    Payment,
    PaymentBilling,
    Property,
    PropertyBilling,
    User,
)
from backend.services.cloud_backup_service import (  # noqa: E402
    cloud_backup_activation_ready,
    cloud_backup_enabled,
)
from backend.services.history_service import log_data_change  # noqa: E402
from scripts.configure_r2_backup import (  # noqa: E402
    VAULT_PATH,
    _atomic_write_vault,
    _read_vault,
)
from scripts.migrate_r2_vault import _require_administrator  # noqa: E402


FEATURE_KEY = "MTO_ENABLE_VERIFIED_DUPLICATE_TD"
PILOT_KEY = "MTO_VERIFIED_DUPLICATE_TD_PILOT_TD"
EXPANDED_AT_KEY = "MTO_VERIFIED_DUPLICATE_TD_EXPANDED_AT"
MIGRATION_ID = "verified_duplicate_td_accounts_v1"
TRUE_VALUES = {"1", "true", "yes", "on"}
SUCCESS_BACKUP_STATUSES = {"CLOUD_ONLY", "SYNCED"}
SUCCESS_BACKUP_HEALTH = {"OK", "SUCCESS"}
REQUIRED_COLUMNS = {
    "previous_property_id",
    "duplicate_td_verified",
    "duplicate_td_reason",
    "duplicate_td_reference",
    "duplicate_td_approved_by",
    "duplicate_td_approved_at",
}


def normalize_td(value: Any) -> str:
    raw = str(value or "")
    if any(ord(char) < 32 and char not in {" ", "\t"} for char in raw):
        raise ValueError("Pilot TD must contain 3-100 printable characters.")
    normalized = raw.strip().upper()
    if not 3 <= len(normalized) <= 100:
        raise ValueError("Pilot TD must contain 3-100 printable characters.")
    return normalized


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _backup_snapshot(row: BackupHistory | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row.id,
        "filename": row.filename,
        "file_path": row.file_path,
        "checksum": row.checksum,
        "status": row.status,
        "health": row.health,
        "timestamp": row.timestamp,
    }


def _latest_backup(session) -> dict[str, Any] | None:
    row = (
        session.query(BackupHistory)
        .filter(BackupHistory.filename != "__lock__", BackupHistory.status != "RUNNING")
        .order_by(BackupHistory.id.desc())
        .first()
    )
    return _backup_snapshot(row)


def _schema_snapshot(session) -> dict[str, Any]:
    connection = session.connection()
    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("properties")}
    td_unique_names = {
        item["name"]
        for item in inspector.get_unique_constraints("properties")
        if item.get("name") and item.get("column_names") == ["td_number"]
    }
    indexes = inspector.get_indexes("properties")
    td_unique_names.update(
        item["name"]
        for item in indexes
        if item.get("name")
        and item.get("unique")
        and item.get("column_names") == ["td_number"]
    )
    return {
        "dialect": connection.dialect.name,
        "required_columns_present": REQUIRED_COLUMNS.issubset(columns),
        "missing_columns": sorted(REQUIRED_COLUMNS - columns),
        "td_unique_names": sorted(td_unique_names),
        "has_td_lookup_index": any(
            item.get("column_names") == ["td_number"] and not item.get("unique")
            for item in indexes
        ),
    }


def _duplicate_group_snapshots(session) -> list[dict[str, Any]]:
    groups: dict[str, list[Property]] = defaultdict(list)
    rows = (
        session.query(Property)
        .filter(Property.deleted_at == None)  # noqa: E711
        .order_by(Property.id.asc())
        .all()
    )
    for row in rows:
        groups[str(row.td_number or "").strip().upper()].append(row)

    result = []
    for td_number, matches in sorted(groups.items()):
        if not td_number or len(matches) < 2:
            continue
        complete = [
            bool(
                row.duplicate_td_verified
                and str(row.duplicate_td_reason or "").strip()
                and str(row.duplicate_td_reference or "").strip()
                and str(row.duplicate_td_approved_by or "").strip()
                and row.duplicate_td_approved_at
            )
            for row in matches
        ]
        result.append(
            {
                "td_number": td_number,
                "property_ids": [row.id for row in matches],
                "count": len(matches),
                "fully_verified": all(complete),
            }
        )
    return result


def _raw_active_duplicate_tds(session) -> list[str]:
    """Inspect duplicate TD groups without selecting newly migrated ORM columns."""
    rows = session.execute(
        text(
            "SELECT UPPER(TRIM(td_number)) AS td_key "
            "FROM properties WHERE deleted_at IS NULL "
            "GROUP BY UPPER(TRIM(td_number)) HAVING COUNT(*) > 1 "
            "ORDER BY td_key"
        )
    ).all()
    return [str(row[0] or "").strip().upper() for row in rows if row[0]]


def collect_preflight(session, pilot_td: str) -> dict[str, Any]:
    try:
        migration_applied = bool(
            session.execute(
                text("SELECT 1 FROM system_migrations WHERE id = :id LIMIT 1"),
                {"id": MIGRATION_ID},
            ).scalar()
        )
    except Exception:
        session.rollback()
        migration_applied = False

    try:
        cloud_enabled = cloud_backup_enabled()
        cloud_ready, cloud_message = cloud_backup_activation_ready()
    except Exception as exc:
        cloud_enabled = False
        cloud_ready = False
        cloud_message = f"Cloud configuration check failed: {exc}"

    schema = _schema_snapshot(session)
    if schema["required_columns_present"]:
        groups = _duplicate_group_snapshots(session)
        unresolved_duplicate_tds = [
            group["td_number"] for group in groups if not group["fully_verified"]
        ]
        verified_duplicate_tds = [
            group["td_number"] for group in groups if group["fully_verified"]
        ]
        pilot_matches = (
            session.query(Property)
            .filter(
                Property.deleted_at == None,  # noqa: E711
                func.upper(func.trim(Property.td_number)) == pilot_td,
            )
            .order_by(Property.id.asc())
            .all()
        )
        pilot_property_ids = [row.id for row in pilot_matches]
        pilot_fully_verified = bool(pilot_matches) and all(
            row.duplicate_td_verified for row in pilot_matches
        )
    else:
        # A missing migration must produce a concise fail-closed report rather
        # than letting SQLAlchemy select columns that do not exist yet.
        unresolved_duplicate_tds = _raw_active_duplicate_tds(session)
        verified_duplicate_tds = []
        pilot_property_ids = [
            int(row[0])
            for row in session.execute(
                text(
                    "SELECT id FROM properties "
                    "WHERE deleted_at IS NULL AND UPPER(TRIM(td_number)) = :td "
                    "ORDER BY id"
                ),
                {"td": pilot_td},
            ).all()
        ]
        pilot_matches = pilot_property_ids
        pilot_fully_verified = False
    backup_running = bool(
        session.query(BackupHistory)
        .filter(BackupHistory.status == "RUNNING")
        .first()
    )
    return {
        "migration_applied": migration_applied,
        "schema": schema,
        "backup": _latest_backup(session),
        "backup_running": backup_running,
        "cloud_enabled": cloud_enabled,
        "cloud_ready": cloud_ready,
        "cloud_message": cloud_message,
        "unresolved_duplicate_tds": unresolved_duplicate_tds,
        "verified_duplicate_tds": verified_duplicate_tds,
        "pilot_td": pilot_td,
        "pilot_match_count": len(pilot_matches),
        "pilot_property_ids": pilot_property_ids,
        "pilot_fully_verified": pilot_fully_verified,
    }


def evaluate_migration_preflight(
    snapshot: dict[str, Any],
    *,
    max_backup_age_hours: int = 24,
    now: datetime | None = None,
) -> list[str]:
    """Return blockers for the one-time controlled schema migration."""
    errors: list[str] = []
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    schema = snapshot.get("schema") or {}
    if schema.get("dialect") not in {"mysql", "mariadb"}:
        errors.append("Production duplicate-TD migration requires MariaDB/MySQL.")
    if snapshot.get("backup_running"):
        errors.append("A Hybrid Backup is currently running.")
    if not snapshot.get("cloud_enabled"):
        errors.append("Encrypted cloud backup is not enabled.")
    if not snapshot.get("cloud_ready"):
        errors.append(str(snapshot.get("cloud_message") or "Cloud restore attestation is not current."))
    existing_duplicates = snapshot.get("unresolved_duplicate_tds") or []
    if existing_duplicates:
        errors.append(
            "Active duplicate TD groups already exist before migration: "
            + ", ".join(existing_duplicates)
        )

    backup = snapshot.get("backup")
    if not backup:
        errors.append("No completed Hybrid Backup record exists.")
    else:
        status = str(backup.get("status") or "").upper()
        health = str(backup.get("health") or "").upper()
        checksum = str(backup.get("checksum") or "")
        created_at = _timestamp(backup.get("timestamp"))
        if status not in SUCCESS_BACKUP_STATUSES:
            errors.append("Latest backup is not protected in cloud: " + (status or "missing status"))
        if health not in SUCCESS_BACKUP_HEALTH:
            errors.append(
                "Latest backup did not pass full restore verification: "
                + (health or "missing health")
            )
        if len(checksum) != 64:
            errors.append("Latest backup does not have a complete SHA-256 checksum.")
        file_path = str(backup.get("file_path") or "")
        if not file_path or not os.path.isfile(file_path):
            errors.append("Latest verified backup file is missing from the server.")
        if created_at is None:
            errors.append("Latest backup timestamp is missing or invalid.")
        elif current - created_at > timedelta(hours=max_backup_age_hours):
            errors.append(
                f"Latest cloud-protected backup is older than {max_backup_age_hours} hours."
            )
    return errors


def evaluate_preflight(
    snapshot: dict[str, Any],
    *,
    max_backup_age_hours: int = 24,
    require_existing_pilot_group: bool = False,
    now: datetime | None = None,
) -> list[str]:
    errors: list[str] = []
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    schema = snapshot.get("schema") or {}

    if schema.get("dialect") not in {"mysql", "mariadb"}:
        errors.append("Production duplicate-TD rollout requires MariaDB/MySQL.")
    if not snapshot.get("migration_applied"):
        errors.append(f"Required migration {MIGRATION_ID} is not recorded.")
    if not schema.get("required_columns_present"):
        errors.append(
            "Duplicate-TD schema columns are missing: "
            + ", ".join(schema.get("missing_columns") or ["unknown"])
        )
    if schema.get("td_unique_names"):
        errors.append(
            "A single-column TD uniqueness constraint still exists: "
            + ", ".join(schema["td_unique_names"])
        )
    if not schema.get("has_td_lookup_index"):
        errors.append("The non-unique TD lookup index is missing.")
    if snapshot.get("backup_running"):
        errors.append("A Hybrid Backup is currently running.")
    if not snapshot.get("cloud_enabled"):
        errors.append("Encrypted cloud backup is not enabled.")
    if not snapshot.get("cloud_ready"):
        errors.append(str(snapshot.get("cloud_message") or "Cloud restore attestation is not current."))
    unresolved = snapshot.get("unresolved_duplicate_tds") or []
    if unresolved:
        errors.append(
            "Unverified active duplicate TD groups already exist: " + ", ".join(unresolved)
        )
    verified_groups = snapshot.get("verified_duplicate_tds") or []
    out_of_scope_verified = [
        td_number
        for td_number in verified_groups
        if not require_existing_pilot_group or td_number != snapshot.get("pilot_td")
    ]
    if out_of_scope_verified:
        errors.append(
            "Verified duplicate TD groups exist outside this controlled pilot: "
            + ", ".join(out_of_scope_verified)
        )

    backup = snapshot.get("backup")
    if not backup:
        errors.append("No completed Hybrid Backup record exists.")
    else:
        status = str(backup.get("status") or "").upper()
        health = str(backup.get("health") or "").upper()
        checksum = str(backup.get("checksum") or "")
        created_at = _timestamp(backup.get("timestamp"))
        if status not in SUCCESS_BACKUP_STATUSES:
            errors.append(
                "Latest backup is not protected in cloud: " + (status or "missing status")
            )
        if health not in SUCCESS_BACKUP_HEALTH:
            errors.append(
                "Latest backup did not pass full restore verification: "
                + (health or "missing health")
            )
        if len(checksum) != 64:
            errors.append("Latest backup does not have a complete SHA-256 checksum.")
        file_path = str(backup.get("file_path") or "")
        if not file_path or not os.path.isfile(file_path):
            errors.append("Latest verified backup file is missing from the server.")
        if created_at is None:
            errors.append("Latest backup timestamp is missing or invalid.")
        elif current - created_at > timedelta(hours=max_backup_age_hours):
            errors.append(
                f"Latest cloud-protected backup is older than {max_backup_age_hours} hours."
            )

    match_count = int(snapshot.get("pilot_match_count") or 0)
    if require_existing_pilot_group:
        if match_count < 2:
            errors.append("Pilot TD does not yet contain at least two active property accounts.")
        elif not snapshot.get("pilot_fully_verified"):
            errors.append("Pilot TD group is not fully marked as verified.")
    elif match_count != 1:
        errors.append(
            "Pilot activation requires exactly one existing active property for the TD; "
            f"found {match_count}."
        )
    elif snapshot.get("pilot_fully_verified"):
        errors.append("The single pilot property has a stale duplicate-verification marker.")
    return errors


def collect_acceptance(session, td_number: str) -> dict[str, Any]:
    properties = (
        session.query(Property)
        .filter(
            Property.deleted_at == None,  # noqa: E711
            func.upper(func.trim(Property.td_number)) == td_number,
        )
        .order_by(Property.id.asc())
        .all()
    )
    property_ids = [row.id for row in properties]
    payment_counts = dict(
        session.query(Payment.property_id, func.count(Payment.id))
        .filter(Payment.property_id.in_(property_ids or [-1]))
        .group_by(Payment.property_id)
        .all()
    )
    billing_counts = dict(
        session.query(PropertyBilling.property_id, func.count(PropertyBilling.id))
        .filter(PropertyBilling.property_id.in_(property_ids or [-1]))
        .group_by(PropertyBilling.property_id)
        .all()
    )
    cross_allocations = (
        session.query(func.count(PaymentBilling.id))
        .join(Payment, Payment.id == PaymentBilling.payment_id)
        .join(PropertyBilling, PropertyBilling.id == PaymentBilling.billing_id)
        .filter(
            Payment.property_id.in_(property_ids or [-1]),
            Payment.property_id != PropertyBilling.property_id,
        )
        .scalar()
        or 0
    )
    audit_rows = (
        session.query(AuditLog.action, AuditLog.record_id)
        .filter(
            AuditLog.table_name == "properties",
            AuditLog.record_id.in_(property_ids or [-1]),
            AuditLog.action.in_(
                ["MARK_VERIFIED_DUPLICATE_TD", "CREATE_VERIFIED_DUPLICATE_TD"]
            ),
        )
        .all()
    )
    approved_times = [
        _timestamp(row.duplicate_td_approved_at)
        for row in properties
        if _timestamp(row.duplicate_td_approved_at)
    ]
    return {
        "td_number": td_number,
        "properties": [
            {
                "id": row.id,
                "owner_name": row.owner_name,
                "reference": row.duplicate_td_reference,
                "reason": row.duplicate_td_reason,
                "approved_by": row.duplicate_td_approved_by,
                "approved_at": row.duplicate_td_approved_at,
                "verified": bool(row.duplicate_td_verified),
                "payment_count": int(payment_counts.get(row.id, 0)),
                "billing_count": int(billing_counts.get(row.id, 0)),
            }
            for row in properties
        ],
        "cross_property_allocation_count": int(cross_allocations),
        "audit_actions": [row.action for row in audit_rows],
        "latest_approval_at": max(approved_times) if approved_times else None,
        "backup": _latest_backup(session),
    }


def evaluate_acceptance(
    snapshot: dict[str, Any], *, require_backup_after_approval: bool = False
) -> list[str]:
    errors: list[str] = []
    rows = snapshot.get("properties") or []
    if len(rows) < 2:
        errors.append("The pilot TD must contain at least two active properties.")
        return errors
    if not all(row.get("verified") for row in rows):
        errors.append("Every property in the pilot TD group must be verified.")
    for row in rows:
        missing = [
            key
            for key in ("reference", "reason", "approved_by", "approved_at")
            if not row.get(key)
        ]
        if missing:
            errors.append(
                f"Property #{row.get('id')} is missing authorization metadata: "
                + ", ".join(missing)
            )
    references = {str(row.get("reference") or "").strip() for row in rows}
    if len(references) != 1 or not next(iter(references), ""):
        errors.append("Pilot properties do not share one Assessor reference.")
    if int(snapshot.get("cross_property_allocation_count") or 0):
        errors.append("A payment is allocated to another property account's billing.")
    actions = snapshot.get("audit_actions") or []
    if "CREATE_VERIFIED_DUPLICATE_TD" not in actions:
        errors.append("The verified duplicate creation audit event is missing.")
    if "MARK_VERIFIED_DUPLICATE_TD" not in actions:
        errors.append("The existing-property verification audit event is missing.")

    if require_backup_after_approval:
        approved_at = _timestamp(snapshot.get("latest_approval_at"))
        backup_at = _timestamp((snapshot.get("backup") or {}).get("timestamp"))
        if not approved_at or not backup_at or backup_at <= approved_at:
            errors.append(
                "Run a new verified Hybrid Backup after creating the pilot duplicate."
            )
    return errors


def _admin_user(session, username: str) -> User:
    user = (
        session.query(User)
        .filter(
            func.lower(User.username) == str(username or "").strip().lower(),
            User.deleted_at == None,  # noqa: E711
            User.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not user or str(user.role or "").lower() != "admin":
        raise RuntimeError("The supplied MTO account is not an active administrator.")
    return user


def _write_rollout_state(
    session,
    *,
    user: User,
    action: str,
    enabled: bool,
    pilot_td: str | None,
    expanded: bool = False,
) -> None:
    _require_administrator()
    original = _read_vault(VAULT_PATH)
    updated = dict(original)
    before = {
        "enabled": str(original.get(FEATURE_KEY, "false")).lower() in TRUE_VALUES,
        "pilot_td": original.get(PILOT_KEY),
    }
    updated[FEATURE_KEY] = "true" if enabled else "false"
    if pilot_td:
        updated[PILOT_KEY] = pilot_td
    else:
        updated.pop(PILOT_KEY, None)
    if expanded:
        updated[EXPANDED_AT_KEY] = datetime.now(timezone.utc).isoformat()

    _atomic_write_vault(updated, VAULT_PATH)
    try:
        persisted = _read_vault(VAULT_PATH)
        if persisted.get(FEATURE_KEY) != updated.get(FEATURE_KEY):
            raise RuntimeError("Feature flag did not persist to the machine vault.")
        if persisted.get(PILOT_KEY) != updated.get(PILOT_KEY):
            raise RuntimeError("Pilot restriction did not persist to the machine vault.")
        log_data_change(
            user.id,
            "system_configuration",
            0,
            action,
            before=before,
            after={"enabled": enabled, "pilot_td": pilot_td, "expanded": expanded},
            username=user.username,
            db_session=session,
        )
        session.commit()
    except Exception:
        session.rollback()
        _atomic_write_vault(original, VAULT_PATH)
        raise


def _apply_duplicate_td_migration(session, *, user: User) -> None:
    """Apply only the approved duplicate-TD migration and audit the action."""
    _require_administrator()
    from backend.services.migration_service import ensure_verified_duplicate_td_schema

    before = _schema_snapshot(session)
    ensure_verified_duplicate_td_schema(session)
    session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS system_migrations ("
            "id VARCHAR(255) PRIMARY KEY, applied_at DATETIME)"
        )
    )
    session.execute(
        text(
            "INSERT INTO system_migrations (id, applied_at) VALUES (:id, :now) "
            "ON DUPLICATE KEY UPDATE applied_at = VALUES(applied_at)"
        ),
        {"id": MIGRATION_ID, "now": datetime.now(timezone.utc)},
    )
    after = _schema_snapshot(session)
    if not after.get("required_columns_present"):
        raise RuntimeError(
            "Migration did not create every required column: "
            + ", ".join(after.get("missing_columns") or ["unknown"])
        )
    if after.get("td_unique_names"):
        raise RuntimeError(
            "Migration did not remove TD uniqueness: "
            + ", ".join(after["td_unique_names"])
        )
    if not after.get("has_td_lookup_index"):
        raise RuntimeError("Migration did not create the non-unique TD lookup index.")
    log_data_change(
        user.id,
        "system_migrations",
        0,
        "APPLY_VERIFIED_DUPLICATE_TD_SCHEMA",
        before={
            "migration_id": MIGRATION_ID,
            "missing_columns": before.get("missing_columns"),
            "td_unique_names": before.get("td_unique_names"),
        },
        after={
            "migration_id": MIGRATION_ID,
            "missing_columns": after.get("missing_columns"),
            "td_unique_names": after.get("td_unique_names"),
            "has_td_lookup_index": after.get("has_td_lookup_index"),
        },
        username=user.username,
        db_session=session,
    )
    session.commit()


def _print_preflight(snapshot: dict[str, Any], errors: list[str]) -> None:
    backup = snapshot.get("backup") or {}
    print("\nVERIFIED DUPLICATE TD - PHASE 4 PREFLIGHT")
    print(f"Pilot TD: {snapshot.get('pilot_td')}")
    print(f"Existing active pilot records: {snapshot.get('pilot_match_count')}")
    print(f"Migration: {'PASS' if snapshot.get('migration_applied') else 'FAIL'}")
    print(
        "Latest backup: "
        f"{backup.get('filename') or 'NONE'} | {backup.get('status') or 'UNKNOWN'} | "
        f"{backup.get('health') or 'UNKNOWN'}"
    )
    print(f"Cloud restore attestation: {'PASS' if snapshot.get('cloud_ready') else 'FAIL'}")
    print(f"Unverified duplicate groups: {len(snapshot.get('unresolved_duplicate_tds') or [])}")
    if errors:
        print("\nPHASE 4 PREFLIGHT BLOCKED")
        for error in errors:
            print(f"- {error}")
    else:
        print("\nPHASE 4 PREFLIGHT PASSED")


def _print_acceptance(snapshot: dict[str, Any], errors: list[str]) -> None:
    print(f"\nPILOT ACCEPTANCE CHECK: {snapshot.get('td_number')}")
    for row in snapshot.get("properties") or []:
        print(
            f"- Property #{row['id']} | {row.get('owner_name') or 'UNKNOWN OWNER'} | "
            f"payments={row['payment_count']} | billings={row['billing_count']}"
        )
    print(
        "Cross-property payment allocations: "
        f"{snapshot.get('cross_property_allocation_count', 0)}"
    )
    if errors:
        print("AUTOMATED PILOT CHECK BLOCKED")
        for error in errors:
            print(f"- {error}")
    else:
        print("AUTOMATED PILOT CHECK PASSED")
    print("\nManual checks still required before expansion:")
    print("1. Open each matching property from Property Records and confirm owner/PIN/lot.")
    print("2. Open each account in the Payment Ledger and confirm histories stay separate.")
    print("3. Generate the applicable Tax Bill, SOA, and delinquency document per property.")
    print("4. Confirm compliance and delinquency classify each property independently.")
    print("5. Run Data Integrity Audit; the TD must appear only as a verified duplicate group.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--preflight", action="store_true")
    modes.add_argument("--apply-migration", action="store_true")
    modes.add_argument("--activate", action="store_true")
    modes.add_argument("--verify-td", metavar="TD_NUMBER")
    modes.add_argument("--expand", action="store_true")
    modes.add_argument("--deactivate", action="store_true")
    parser.add_argument("--pilot-td")
    parser.add_argument("--admin-username")
    parser.add_argument("--max-backup-age-hours", type=int, default=24)
    args = parser.parse_args()

    if not any(
        (
            args.preflight,
            args.apply_migration,
            args.activate,
            args.verify_td,
            args.expand,
            args.deactivate,
        )
    ):
        args.preflight = True

    session = SessionLocal()
    try:
        if args.verify_td:
            td_number = normalize_td(args.verify_td)
            acceptance = collect_acceptance(session, td_number)
            errors = evaluate_acceptance(acceptance)
            _print_acceptance(acceptance, errors)
            return 2 if errors else 0

        if args.apply_migration:
            if not args.admin_username:
                raise RuntimeError("--admin-username is required for migration.")
            migration_snapshot = collect_preflight(session, "MIGRATION-CHECK")
            schema = migration_snapshot.get("schema") or {}
            if (
                migration_snapshot.get("migration_applied")
                and schema.get("required_columns_present")
                and not schema.get("td_unique_names")
                and schema.get("has_td_lookup_index")
            ):
                print("Verified duplicate TD migration is already fully applied.")
                return 0
            errors = evaluate_migration_preflight(
                migration_snapshot,
                max_backup_age_hours=args.max_backup_age_hours,
            )
            print("\nVERIFIED DUPLICATE TD - CONTROLLED MIGRATION PREFLIGHT")
            backup = migration_snapshot.get("backup") or {}
            print(
                f"Latest backup: {backup.get('filename') or 'NONE'} | "
                f"{backup.get('status') or 'UNKNOWN'} | {backup.get('health') or 'UNKNOWN'}"
            )
            print(
                "Cloud restore attestation: "
                f"{'PASS' if migration_snapshot.get('cloud_ready') else 'FAIL'}"
            )
            print(
                "Existing active duplicate groups: "
                f"{len(migration_snapshot.get('unresolved_duplicate_tds') or [])}"
            )
            if errors:
                print("CONTROLLED MIGRATION BLOCKED")
                for error in errors:
                    print(f"- {error}")
                return 2
            user = _admin_user(session, args.admin_username)
            expected = "APPLY DUPLICATE TD MIGRATION - USERS LOGGED OUT"
            if input(f"Type {expected} to continue: ").strip() != expected:
                raise RuntimeError("Migration cancelled; no migration command was run.")
            _apply_duplicate_td_migration(session, user=user)
            print("Controlled duplicate TD migration PASSED.")
            print("Duplicate creation remains disabled. Restart the MTO API, then rerun preflight.")
            return 0

        vault = _read_vault(VAULT_PATH)
        stored_pilot = str(vault.get(PILOT_KEY) or "").strip().upper()
        if args.deactivate:
            if not args.admin_username:
                raise RuntimeError("--admin-username is required for deactivation.")
            user = _admin_user(session, args.admin_username)
            expected = "DISABLE VERIFIED DUPLICATE TD"
            if input(f"Type {expected} to continue: ").strip() != expected:
                raise RuntimeError("Deactivation cancelled; no settings changed.")
            _write_rollout_state(
                session,
                user=user,
                action="DEACTIVATE_VERIFIED_DUPLICATE_TD",
                enabled=False,
                pilot_td=None,
            )
            print("Verified duplicate TD creation is disabled. Restart the MTO API.")
            return 0

        pilot_td = normalize_td(args.pilot_td or stored_pilot)
        require_group = bool(args.expand)
        snapshot = collect_preflight(session, pilot_td)
        errors = evaluate_preflight(
            snapshot,
            max_backup_age_hours=args.max_backup_age_hours,
            require_existing_pilot_group=require_group,
        )
        _print_preflight(snapshot, errors)
        if errors:
            return 2
        if args.preflight:
            print("No settings were changed.")
            return 0

        if args.activate:
            if not args.admin_username:
                raise RuntimeError("--admin-username is required for activation.")
            user = _admin_user(session, args.admin_username)
            expected = f"ACTIVATE VERIFIED DUPLICATE TD {pilot_td}"
            if input(f"Type {expected} to continue: ").strip() != expected:
                raise RuntimeError("Activation cancelled; no settings changed.")
            _write_rollout_state(
                session,
                user=user,
                action="ACTIVATE_VERIFIED_DUPLICATE_TD_PILOT",
                enabled=True,
                pilot_td=pilot_td,
            )
            print(f"Phase 4 pilot activated only for TD {pilot_td}.")
            print("Restart the MTO API before opening the desktop client.")
            return 0

        if args.expand:
            if str(vault.get(FEATURE_KEY) or "").strip().lower() not in TRUE_VALUES:
                raise RuntimeError("The duplicate-TD pilot is not activated.")
            if not args.admin_username:
                raise RuntimeError("--admin-username is required for expansion.")
            acceptance = collect_acceptance(session, pilot_td)
            acceptance_errors = evaluate_acceptance(
                acceptance, require_backup_after_approval=True
            )
            _print_acceptance(acceptance, acceptance_errors)
            if acceptance_errors:
                return 2
            user = _admin_user(session, args.admin_username)
            expected = f"EXPAND VERIFIED DUPLICATE TD {pilot_td}"
            if input(f"Type {expected} after completing all manual checks: ").strip() != expected:
                raise RuntimeError("Expansion cancelled; pilot restriction remains active.")
            _write_rollout_state(
                session,
                user=user,
                action="EXPAND_VERIFIED_DUPLICATE_TD_ROLLOUT",
                enabled=True,
                pilot_td=None,
                expanded=True,
            )
            print("Phase 4 rollout expanded. Restart the MTO API.")
            return 0
        return 0
    except Exception as exc:
        session.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
