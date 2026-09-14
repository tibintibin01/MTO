# -*- coding: utf-8 -*-
"""Tamper-evident, append-only audit-chain primitives.

The chain is application-level evidence of alteration. Database administrators
remain able to alter storage, so independent backups and restricted database
access are still required for full evidentiary assurance.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import copy
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session

from backend.models import AuditChainState, AuditLog

AUDIT_CHAIN_VERSION = 1
AUDIT_CHAIN_STATE_ID = 1
AUDIT_CHAIN_ORIGIN_LIVE = "LIVE"
AUDIT_CHAIN_ORIGIN_LEGACY = "LEGACY_BACKFILL"
AUDIT_EVENT_NAMESPACE = uuid.UUID("87b25255-2ff5-42ab-959f-89ebd5bb29db")
AUDIT_GENESIS_HASH = hashlib.sha256(b"MTO-AUDIT-CHAIN-V1-GENESIS").hexdigest()
AUDIT_TIMESTAMP_RECOVERY_MIGRATION_ID = "phase5_audit_timestamp_precision_recovery_v1"
AUDIT_TIMESTAMP_REQUIRED_PRECISION = 6

REQUIRED_AUDIT_COLUMNS = {
    "event_uuid",
    "previous_hash",
    "current_hash",
    "chain_version",
    "chain_origin",
    "compensates_audit_id",
}

_verification_cache = None
_verification_cache_lock = threading.Lock()


class AuditTimestampRecoveryError(RuntimeError):
    """Raised when timestamp evidence cannot be recovered without ambiguity."""


@dataclass(frozen=True)
class AuditTimestampRecoveryCandidate:
    """One cryptographically proven replacement for a truncated timestamp."""

    audit_id: int
    stored_timestamp: datetime
    recovered_timestamp: datetime
    current_hash: str


@dataclass(frozen=True)
class AuditTimestampRecoveryPlan:
    """Fail-closed recovery plan; raw audit content is intentionally excluded."""

    database_dialect: str
    timestamp_column_type: Optional[str]
    timestamp_precision: Optional[int]
    verification_status: str
    failure_count: int
    failures: tuple[tuple[Optional[int], str], ...]
    candidates: tuple[AuditTimestampRecoveryCandidate, ...]
    issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.issues and (
            self.verification_status == "verified"
            or len(self.candidates) == self.failure_count
        )

    def privacy_safe_report(self) -> dict:
        return {
            "database_dialect": self.database_dialect,
            "timestamp_column_type": self.timestamp_column_type,
            "timestamp_precision": self.timestamp_precision,
            "required_timestamp_precision": AUDIT_TIMESTAMP_REQUIRED_PRECISION,
            "verification_status": self.verification_status,
            "failure_count": self.failure_count,
            "failures": [
                {"audit_id": audit_id, "code": code} for audit_id, code in self.failures
            ],
            "affected_event_ids": [item.audit_id for item in self.candidates],
            "recovered_event_count": len(self.candidates),
            "recovered_microseconds": [
                {
                    "audit_id": item.audit_id,
                    "microsecond": item.recovered_timestamp.microsecond,
                }
                for item in self.candidates
            ],
            "issues": list(self.issues),
            "ready": self.ready,
        }


def canonical_timestamp(value: datetime) -> str:
    """Return a timezone-stable timestamp representation used by the hash."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds") + "Z"


def normalize_event_time(value: Optional[datetime] = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _json_compatible(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_compatible(item) for item in value)
    return value


def _truncate_snapshot(value: Any, maximum: int = 2000) -> Any:
    if isinstance(value, str) and len(value) > maximum:
        return value[:maximum] + "... [TRUNC]"
    if isinstance(value, dict):
        return {
            str(key): _truncate_snapshot(item, maximum) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_truncate_snapshot(item, maximum) for item in value]
    return value


def canonical_snapshot(value: Any) -> Optional[str]:
    """Serialize a before/after snapshot without binary floats or key drift."""
    if value is None:
        return None
    normalized = _truncate_snapshot(_json_compatible(value))
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def deterministic_legacy_event_uuid(audit_id: int) -> str:
    return str(uuid.uuid5(AUDIT_EVENT_NAMESPACE, f"legacy-audit:{audit_id}"))


def canonical_audit_payload(
    *,
    event_uuid: str,
    user_id: Optional[int],
    username: str,
    action: str,
    table_name: Optional[str],
    record_id: Optional[int],
    old_values: Optional[str],
    new_values: Optional[str],
    ip_address: Optional[str],
    timestamp: datetime,
    chain_version: int,
    chain_origin: str,
    compensates_audit_id: Optional[int],
) -> str:
    payload = {
        "action": action,
        "chain_origin": chain_origin,
        "chain_version": int(chain_version),
        "compensates_audit_id": compensates_audit_id,
        "event_uuid": event_uuid,
        "ip_address": ip_address,
        "new_values": new_values,
        "old_values": old_values,
        "record_id": record_id,
        "table_name": table_name,
        "timestamp": canonical_timestamp(timestamp),
        "user_id": user_id,
        "username": username,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def calculate_audit_hash(previous_hash: str, payload: str) -> str:
    framed = f"{previous_hash}\n{payload}".encode("utf-8")
    return hashlib.sha256(framed).hexdigest()


def _canonical_payload_for_log(log: AuditLog, timestamp: datetime) -> str:
    return canonical_audit_payload(
        event_uuid=log.event_uuid,
        user_id=log.user_id,
        username=log.username,
        action=log.action,
        table_name=log.table_name,
        record_id=log.record_id,
        old_values=log.old_values,
        new_values=log.new_values,
        ip_address=log.ip_address,
        timestamp=timestamp,
        chain_version=log.chain_version,
        chain_origin=log.chain_origin,
        compensates_audit_id=log.compensates_audit_id,
    )


def recover_truncated_audit_timestamp(
    log: AuditLog,
    *,
    candidate_microseconds: Optional[Iterable[int]] = None,
) -> Optional[datetime]:
    """Recover a lost fractional second without changing the stored hash.

    MariaDB ``DATETIME(0)`` truncated the fractional component after the event
    was hashed. All other payload fields and the previous hash remain stored,
    leaving at most one million possible timestamp payloads for that second.
    A candidate is accepted only when its digest equals the original hash.

    ``candidate_microseconds`` exists for bounded unit tests. Production calls
    deliberately evaluate the complete 000000-999999 domain.
    """
    if not log.timestamp or not log.previous_hash or not log.current_hash:
        return None

    stored_second = normalize_event_time(log.timestamp).replace(microsecond=0)
    stored_payload = _canonical_payload_for_log(log, stored_second)
    stored_timestamp = canonical_timestamp(stored_second)
    timestamp_field = f'"timestamp":"{stored_timestamp}"'
    if stored_payload.count(timestamp_field) != 1:
        raise AuditTimestampRecoveryError(
            f"Audit event {log.id} has an ambiguous canonical timestamp field."
        )

    marker_start = stored_payload.index(timestamp_field) + len('"timestamp":"')
    marker_end = marker_start + len(stored_timestamp)
    payload_prefix = f"{log.previous_hash}\n{stored_payload[:marker_start]}"
    payload_suffix = stored_payload[marker_end:]
    timestamp_prefix = stored_second.strftime("%Y-%m-%dT%H:%M:%S")
    microseconds = (
        range(1_000_000) if candidate_microseconds is None else candidate_microseconds
    )

    match = None
    for raw_microsecond in microseconds:
        microsecond = int(raw_microsecond)
        if not 0 <= microsecond <= 999_999:
            raise ValueError("Candidate microseconds must be between 0 and 999999.")
        timestamp_text = f"{timestamp_prefix}.{microsecond:06d}Z"
        digest = hashlib.sha256(
            f"{payload_prefix}{timestamp_text}{payload_suffix}".encode("utf-8")
        ).hexdigest()
        if hmac.compare_digest(digest, log.current_hash):
            if match is not None:
                raise AuditTimestampRecoveryError(
                    f"Audit event {log.id} has more than one timestamp candidate."
                )
            match = stored_second.replace(microsecond=microsecond)
    return match


def audit_timestamp_storage_status(db_session: Session) -> dict:
    """Return timestamp precision metadata without exposing audit content."""
    connection = db_session.connection()
    dialect = connection.dialect.name
    if dialect not in {"mysql", "mariadb"}:
        return {
            "database_dialect": dialect,
            "data_type": None,
            "column_type": None,
            "datetime_precision": None,
        }

    row = (
        db_session.execute(
            text(
                "SELECT DATA_TYPE AS data_type, COLUMN_TYPE AS column_type,"
                " DATETIME_PRECISION AS datetime_precision"
                " FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table_name"
                " AND COLUMN_NAME=:column_name"
            ),
            {"table_name": "audit_logs", "column_name": "timestamp"},
        )
        .mappings()
        .one_or_none()
    )
    return {
        "database_dialect": dialect,
        "data_type": str(row["data_type"]).lower() if row else None,
        "column_type": str(row["column_type"]).lower() if row else None,
        "datetime_precision": (
            int(row["datetime_precision"])
            if row and row["datetime_precision"] is not None
            else None
        ),
    }


def audit_chain_schema_status(db_session: Session) -> dict:
    inspector = inspect(db_session.connection())
    has_audit_table = inspector.has_table("audit_logs")
    columns = (
        {column["name"] for column in inspector.get_columns("audit_logs")}
        if has_audit_table
        else set()
    )
    has_state_table = inspector.has_table("audit_chain_state")
    missing_columns = sorted(REQUIRED_AUDIT_COLUMNS - columns)
    return {
        "audit_table": has_audit_table,
        "chain_state_table": has_state_table,
        "missing_columns": missing_columns,
        "active": has_audit_table and has_state_table and not missing_columns,
    }


def _locked_chain_state(db_session: Session) -> AuditChainState:
    state = (
        db_session.query(AuditChainState)
        .filter(AuditChainState.id == AUDIT_CHAIN_STATE_ID)
        .with_for_update()
        .one_or_none()
    )
    if state is None:
        # Unit tests build a clean SQLite schema directly rather than running
        # production migrations. An empty chain can safely initialize there.
        dialect = db_session.connection().dialect.name
        existing = int(db_session.query(func.count(AuditLog.id)).scalar() or 0)
        if dialect != "sqlite" or existing:
            raise RuntimeError("Audit chain state is not initialized.")
        now = normalize_event_time()
        state = AuditChainState(
            id=AUDIT_CHAIN_STATE_ID,
            head_audit_id=None,
            head_hash=AUDIT_GENESIS_HASH,
            chain_version=AUDIT_CHAIN_VERSION,
            legacy_event_count=0,
            initialized_at=now,
            updated_at=now,
        )
        db_session.add(state)
        db_session.flush()

    latest_id = db_session.query(func.max(AuditLog.id)).scalar()
    if latest_id != state.head_audit_id:
        raise RuntimeError(
            "Audit chain head does not match the latest audit record; "
            "run the integrity verifier before accepting new audit events."
        )
    return state


def append_audit_event(
    *,
    db_session: Session,
    user_id: Optional[int],
    username: str,
    table_name: Optional[str],
    record_id: Optional[int],
    action: str,
    old_values: Optional[str] = None,
    new_values: Optional[str] = None,
    ip_address: Optional[str] = None,
    compensates_audit_id: Optional[int] = None,
    event_time: Optional[datetime] = None,
) -> AuditLog:
    """Append one event and advance the chain head in the caller transaction."""
    state = _locked_chain_state(db_session)
    timestamp = normalize_event_time(event_time)
    event_uuid = str(uuid.uuid4())
    previous_hash = state.head_hash
    payload = canonical_audit_payload(
        event_uuid=event_uuid,
        user_id=user_id,
        username=username or "unknown",
        action=action,
        table_name=table_name,
        record_id=record_id,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address,
        timestamp=timestamp,
        chain_version=AUDIT_CHAIN_VERSION,
        chain_origin=AUDIT_CHAIN_ORIGIN_LIVE,
        compensates_audit_id=compensates_audit_id,
    )
    current_hash = calculate_audit_hash(previous_hash, payload)
    log = AuditLog(
        user_id=user_id,
        username=username or "unknown",
        action=action,
        table_name=table_name,
        record_id=record_id,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address,
        timestamp=timestamp,
        event_uuid=event_uuid,
        previous_hash=previous_hash,
        current_hash=current_hash,
        chain_version=AUDIT_CHAIN_VERSION,
        chain_origin=AUDIT_CHAIN_ORIGIN_LIVE,
        compensates_audit_id=compensates_audit_id,
    )
    db_session.add(log)
    db_session.flush()
    state.head_audit_id = log.id
    state.head_hash = current_hash
    state.updated_at = timestamp
    db_session.flush()
    return log


def verify_audit_chain(db_session: Session, max_failures: int = 20) -> dict:
    """Verify every stored link and return a privacy-safe summary."""
    checked_at = datetime.now(timezone.utc).isoformat()
    schema = audit_chain_schema_status(db_session)
    if not schema["active"]:
        return {
            "status": "inactive",
            "schema_active": False,
            "checked_at_utc": checked_at,
            "event_count": 0,
            "verified_event_count": 0,
            "legacy_event_count": 0,
            "live_event_count": 0,
            "failure_count": 0,
            "failures": [],
            "schema": schema,
        }

    state = (
        db_session.query(AuditChainState)
        .filter(AuditChainState.id == AUDIT_CHAIN_STATE_ID)
        .one_or_none()
    )
    failures = []
    failure_total = 0

    def fail(audit_id: Optional[int], code: str) -> None:
        nonlocal failure_total
        failure_total += 1
        if len(failures) < max(1, int(max_failures)):
            failures.append({"audit_id": audit_id, "code": code})

    expected_previous = AUDIT_GENESIS_HASH
    event_count = 0
    verified_count = 0
    legacy_count = 0
    live_count = 0
    last_id = None
    seen_event_uuids = set()
    seen_live_event = False
    verified_legacy_head_id = None
    verified_legacy_head_hash = None

    for log in db_session.query(AuditLog).order_by(AuditLog.id.asc()).yield_per(1000):
        event_count += 1
        last_id = log.id
        if log.chain_origin == AUDIT_CHAIN_ORIGIN_LEGACY:
            legacy_count += 1
            if seen_live_event:
                fail(log.id, "LEGACY_EVENT_AFTER_LIVE_BOUNDARY")
        elif log.chain_origin == AUDIT_CHAIN_ORIGIN_LIVE:
            live_count += 1
            seen_live_event = True

        required = (
            log.event_uuid,
            log.previous_hash,
            log.current_hash,
            log.chain_version,
            log.chain_origin,
        )
        if any(value is None or value == "" for value in required):
            fail(log.id, "UNSEALED_EVENT")
            if log.current_hash:
                expected_previous = log.current_hash
            continue
        if log.event_uuid in seen_event_uuids:
            fail(log.id, "DUPLICATE_EVENT_UUID")
        seen_event_uuids.add(log.event_uuid)
        if log.previous_hash != expected_previous:
            fail(log.id, "PREVIOUS_HASH_MISMATCH")
        payload = canonical_audit_payload(
            event_uuid=log.event_uuid,
            user_id=log.user_id,
            username=log.username,
            action=log.action,
            table_name=log.table_name,
            record_id=log.record_id,
            old_values=log.old_values,
            new_values=log.new_values,
            ip_address=log.ip_address,
            timestamp=log.timestamp,
            chain_version=log.chain_version,
            chain_origin=log.chain_origin,
            compensates_audit_id=log.compensates_audit_id,
        )
        calculated = calculate_audit_hash(log.previous_hash, payload)
        if calculated != log.current_hash:
            fail(log.id, "CURRENT_HASH_MISMATCH")
        else:
            verified_count += 1
        expected_previous = log.current_hash
        if log.chain_origin == AUDIT_CHAIN_ORIGIN_LEGACY:
            verified_legacy_head_id = log.id
            verified_legacy_head_hash = log.current_hash

    if state is None:
        fail(None, "CHAIN_STATE_MISSING")
    else:
        if state.head_audit_id != last_id:
            fail(state.head_audit_id, "CHAIN_HEAD_ID_MISMATCH")
        expected_head_hash = expected_previous if event_count else AUDIT_GENESIS_HASH
        if state.head_hash != expected_head_hash:
            fail(state.head_audit_id, "CHAIN_HEAD_HASH_MISMATCH")
        if state.legacy_event_count != legacy_count:
            fail(state.legacy_head_audit_id, "LEGACY_BOUNDARY_COUNT_MISMATCH")
        if state.legacy_head_audit_id != verified_legacy_head_id:
            fail(state.legacy_head_audit_id, "LEGACY_BOUNDARY_ID_MISMATCH")
        if state.legacy_head_hash != verified_legacy_head_hash:
            fail(state.legacy_head_audit_id, "LEGACY_BOUNDARY_HASH_MISMATCH")
        if state.chain_version != AUDIT_CHAIN_VERSION:
            fail(state.head_audit_id, "CHAIN_VERSION_MISMATCH")

    return {
        "status": "verified" if failure_total == 0 else "failed",
        "schema_active": True,
        "checked_at_utc": checked_at,
        "event_count": event_count,
        "verified_event_count": verified_count,
        "legacy_event_count": legacy_count,
        "live_event_count": live_count,
        "failure_count": failure_total,
        "failures": failures,
        "head_audit_id": state.head_audit_id if state else None,
        "chain_version": AUDIT_CHAIN_VERSION,
        "schema": schema,
    }


def build_audit_timestamp_recovery_plan(
    db_session: Session,
    *,
    candidate_microseconds: Optional[Iterable[int]] = None,
) -> AuditTimestampRecoveryPlan:
    """Prove whether timestamp-only recovery is safe before any write occurs."""
    storage = audit_timestamp_storage_status(db_session)
    verification = verify_audit_chain(db_session, max_failures=1_000_000)
    failures = tuple(
        (item.get("audit_id"), str(item.get("code") or "UNKNOWN"))
        for item in verification.get("failures", [])
    )
    issues = []
    candidates = []

    if storage["database_dialect"] not in {"mysql", "mariadb"}:
        issues.append("Timestamp recovery requires MariaDB/MySQL.")
    if storage["data_type"] != "datetime":
        issues.append("audit_logs.timestamp is not a MariaDB DATETIME column.")
    if verification["status"] not in {"verified", "failed"}:
        issues.append("The audit chain is not active.")

    if verification["status"] == "failed":
        if verification["failure_count"] != len(failures):
            issues.append("The verifier did not return every failing audit event.")
        unsupported = [
            (audit_id, code)
            for audit_id, code in failures
            if code != "CURRENT_HASH_MISMATCH" or audit_id is None
        ]
        if unsupported:
            issues.append(
                "The chain contains failures other than recoverable timestamp hashes."
            )

        event_ids = sorted(
            {
                int(audit_id)
                for audit_id, code in failures
                if audit_id is not None and code == "CURRENT_HASH_MISMATCH"
            }
        )
        rows = (
            db_session.query(AuditLog)
            .filter(AuditLog.id.in_(event_ids))
            .order_by(AuditLog.id.asc())
            .all()
            if event_ids
            else []
        )
        if len(rows) != len(event_ids):
            issues.append("One or more failing audit events could not be loaded.")

        for log in rows:
            if log.chain_origin != AUDIT_CHAIN_ORIGIN_LIVE:
                issues.append(f"Audit event {log.id} is not a live Phase 5 event.")
                continue
            try:
                recovered = recover_truncated_audit_timestamp(
                    log,
                    candidate_microseconds=candidate_microseconds,
                )
            except (AuditTimestampRecoveryError, TypeError, ValueError) as exc:
                issues.append(str(exc))
                continue
            if recovered is None:
                issues.append(
                    f"Audit event {log.id} has no cryptographically valid timestamp."
                )
                continue
            candidates.append(
                AuditTimestampRecoveryCandidate(
                    audit_id=int(log.id),
                    stored_timestamp=normalize_event_time(log.timestamp),
                    recovered_timestamp=recovered,
                    current_hash=str(log.current_hash),
                )
            )

    return AuditTimestampRecoveryPlan(
        database_dialect=storage["database_dialect"],
        timestamp_column_type=storage["column_type"],
        timestamp_precision=storage["datetime_precision"],
        verification_status=str(verification["status"]),
        failure_count=int(verification["failure_count"]),
        failures=failures,
        candidates=tuple(candidates),
        issues=tuple(issues),
    )


def ensure_audit_timestamp_precision_recovery(
    db_session: Session,
    *,
    allow_evidence_recovery: bool = False,
) -> dict:
    """Upgrade to DATETIME(6) and restore only hash-proven timestamps.

    Hashes and all non-timestamp audit fields remain untouched. MariaDB DDL is
    auto-committing, so the operation is intentionally idempotent: a retry can
    still reconstruct a truncated value even when the precision upgrade itself
    completed before a later failure.
    """
    if db_session.connection().dialect.name not in {"mysql", "mariadb"}:
        raise AuditTimestampRecoveryError(
            "Phase 5 audit timestamp recovery requires MariaDB/MySQL."
        )

    plan = build_audit_timestamp_recovery_plan(db_session)
    if not plan.ready:
        detail = "; ".join(plan.issues) or "Recovery evidence is incomplete."
        raise AuditTimestampRecoveryError(detail)
    if plan.candidates and not allow_evidence_recovery:
        raise AuditTimestampRecoveryError(
            "Timestamp evidence recovery requires the dedicated Phase 5 "
            "recovery utility and explicit operator confirmation."
        )

    if plan.timestamp_precision != AUDIT_TIMESTAMP_REQUIRED_PRECISION:
        db_session.execute(
            text(
                "ALTER TABLE audit_logs " "MODIFY COLUMN timestamp DATETIME(6) NOT NULL"
            )
        )
    db_session.execute(
        text(
            "ALTER TABLE audit_chain_state "
            "MODIFY COLUMN initialized_at DATETIME(6) NOT NULL, "
            "MODIFY COLUMN updated_at DATETIME(6) NOT NULL"
        )
    )

    if plan.candidates:
        state = (
            db_session.query(AuditChainState)
            .filter(AuditChainState.id == AUDIT_CHAIN_STATE_ID)
            .with_for_update()
            .one_or_none()
        )
        if state is None:
            raise AuditTimestampRecoveryError(
                "Audit chain state disappeared during recovery."
            )
        locked_plan = build_audit_timestamp_recovery_plan(db_session)
        before_signature = [
            (item.audit_id, item.recovered_timestamp, item.current_hash)
            for item in plan.candidates
        ]
        locked_signature = [
            (item.audit_id, item.recovered_timestamp, item.current_hash)
            for item in locked_plan.candidates
        ]
        if not locked_plan.ready or locked_signature != before_signature:
            raise AuditTimestampRecoveryError(
                "Audit evidence changed while acquiring the recovery lock."
            )
        plan = locked_plan

    for candidate in plan.candidates:
        result = db_session.execute(
            text(
                "UPDATE audit_logs SET timestamp=:recovered_timestamp "
                "WHERE id=:audit_id AND timestamp=:stored_timestamp "
                "AND current_hash=:current_hash"
            ),
            {
                "audit_id": candidate.audit_id,
                "stored_timestamp": candidate.stored_timestamp,
                "recovered_timestamp": candidate.recovered_timestamp,
                "current_hash": candidate.current_hash,
            },
        )
        if result.rowcount != 1:
            raise AuditTimestampRecoveryError(
                f"Audit event {candidate.audit_id} changed after preflight."
            )

    db_session.flush()
    db_session.expire_all()
    verification = verify_audit_chain(db_session, max_failures=1_000_000)
    if verification["status"] != "verified":
        raise AuditTimestampRecoveryError(
            "The original audit hashes did not verify after timestamp recovery."
        )

    report = plan.privacy_safe_report()
    report.update(
        {
            "timestamp_precision_after": AUDIT_TIMESTAMP_REQUIRED_PRECISION,
            "verification_status_after": "verified",
            "hashes_modified": False,
            "timestamp_values_restored": bool(plan.candidates),
            "non_timestamp_fields_modified": False,
        }
    )
    return report


def verify_audit_chain_cached(
    db_session: Session, max_age_seconds: float = 60.0
) -> dict:
    """Reuse a verified result only while the chain head remains unchanged."""
    global _verification_cache
    schema = audit_chain_schema_status(db_session)
    if not schema["active"]:
        return verify_audit_chain(db_session)
    state = (
        db_session.query(AuditChainState)
        .filter(AuditChainState.id == AUDIT_CHAIN_STATE_ID)
        .one_or_none()
    )
    head = (state.head_audit_id, state.head_hash) if state else (None, None)
    now = time.monotonic()
    with _verification_cache_lock:
        if (
            _verification_cache
            and _verification_cache["head"] == head
            and now - _verification_cache["captured"] <= max_age_seconds
        ):
            return copy.deepcopy(_verification_cache["result"])
        result = verify_audit_chain(db_session)
        _verification_cache = {
            "head": head,
            "captured": now,
            "result": copy.deepcopy(result),
        }
        return result
