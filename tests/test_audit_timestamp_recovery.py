from dataclasses import replace
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from backend.database import Base
from backend.models import AuditLog
from backend.services import audit_integrity_service as integrity
from backend.services import migration_service
from backend.services.migration_service import MIGRATIONS


def _truncated_event(original_timestamp: datetime) -> AuditLog:
    previous_hash = "a" * 64
    fields = {
        "event_uuid": "6890193e-ffde-44a8-97a1-5e40bd9fb744",
        "user_id": 7,
        "username": "auditor",
        "action": "EXPORTED_TEST_REPORT",
        "table_name": "system_events",
        "record_id": None,
        "old_values": None,
        "new_values": None,
        "ip_address": None,
        "timestamp": original_timestamp,
        "chain_version": integrity.AUDIT_CHAIN_VERSION,
        "chain_origin": integrity.AUDIT_CHAIN_ORIGIN_LIVE,
        "compensates_audit_id": None,
    }
    payload = integrity.canonical_audit_payload(**fields)
    return AuditLog(
        id=6161,
        **{**fields, "timestamp": original_timestamp.replace(microsecond=0)},
        previous_hash=previous_hash,
        current_hash=integrity.calculate_audit_hash(previous_hash, payload),
    )


def test_recovers_exact_microseconds_without_changing_existing_hash():
    original = datetime(2026, 9, 14, 23, 8, 8, 73)
    event = _truncated_event(original)
    original_hash = event.current_hash

    recovered = integrity.recover_truncated_audit_timestamp(
        event,
        candidate_microseconds=range(100),
    )

    assert recovered == original
    assert event.current_hash == original_hash
    payload = integrity._canonical_payload_for_log(event, recovered)
    assert integrity.calculate_audit_hash(event.previous_hash, payload) == original_hash


def test_recovery_fails_when_timestamp_cannot_explain_the_hash():
    event = _truncated_event(datetime(2026, 9, 14, 23, 8, 8, 73))
    event.current_hash = "f" * 64

    assert (
        integrity.recover_truncated_audit_timestamp(
            event,
            candidate_microseconds=range(100),
        )
        is None
    )


def test_recovery_plan_accepts_only_hash_proven_timestamp_mismatches():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    original = datetime(2026, 9, 14, 23, 8, 8, 73)
    try:
        event = integrity.append_audit_event(
            db_session=session,
            user_id=7,
            username="auditor",
            table_name="system_events",
            record_id=None,
            action="EXPORTED_TEST_REPORT",
            event_time=original,
        )
        session.commit()
        event_id = event.id
        session.query(AuditLog).filter(AuditLog.id == event_id).update(
            {AuditLog.timestamp: original.replace(microsecond=0)}
        )
        session.commit()
        session.expire_all()
        assert integrity.verify_audit_chain(session)["status"] == "failed"

        with patch.object(
            integrity,
            "audit_timestamp_storage_status",
            return_value={
                "database_dialect": "mysql",
                "data_type": "datetime",
                "column_type": "datetime",
                "datetime_precision": 0,
            },
        ):
            plan = integrity.build_audit_timestamp_recovery_plan(
                session,
                candidate_microseconds=range(100),
            )

        assert plan.ready is True
        assert plan.failure_count == 1
        assert plan.candidates[0].audit_id == event_id
        assert plan.candidates[0].recovered_timestamp == original
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_invalid_candidate_microseconds_are_rejected():
    event = _truncated_event(datetime(2026, 9, 14, 23, 8, 8, 73))

    with pytest.raises(ValueError, match="between 0 and 999999"):
        integrity.recover_truncated_audit_timestamp(
            event,
            candidate_microseconds=[-1],
        )


def test_mariadb_model_ddl_preserves_audit_microseconds():
    ddl = str(CreateTable(AuditLog.__table__).compile(dialect=mysql.dialect()))

    assert "timestamp DATETIME(6) NOT NULL" in ddl


def test_recovery_handler_refuses_non_mariadb_before_writing():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        with pytest.raises(integrity.AuditTimestampRecoveryError, match="MariaDB"):
            integrity.ensure_audit_timestamp_precision_recovery(session)
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_automatic_migration_cannot_recover_incident_evidence():
    event = _truncated_event(datetime(2026, 9, 14, 23, 8, 8, 73))
    plan = integrity.AuditTimestampRecoveryPlan(
        database_dialect="mysql",
        timestamp_column_type="datetime",
        timestamp_precision=0,
        verification_status="failed",
        failure_count=1,
        failures=((event.id, "CURRENT_HASH_MISMATCH"),),
        candidates=(
            integrity.AuditTimestampRecoveryCandidate(
                audit_id=event.id,
                stored_timestamp=event.timestamp,
                recovered_timestamp=datetime(2026, 9, 14, 23, 8, 8, 73),
                current_hash=event.current_hash,
            ),
        ),
        issues=(),
    )
    session = MagicMock()
    session.connection.return_value.dialect.name = "mysql"

    with patch.object(
        integrity,
        "build_audit_timestamp_recovery_plan",
        return_value=plan,
    ):
        with pytest.raises(
            integrity.AuditTimestampRecoveryError,
            match="dedicated Phase 5 recovery utility",
        ):
            integrity.ensure_audit_timestamp_precision_recovery(session)

    session.execute.assert_not_called()


def test_confirmed_recovery_updates_only_timestamp_and_preserves_hashes():
    event = _truncated_event(datetime(2026, 9, 14, 23, 8, 8, 73))
    recovered = datetime(2026, 9, 14, 23, 8, 8, 73)
    plan = integrity.AuditTimestampRecoveryPlan(
        database_dialect="mysql",
        timestamp_column_type="datetime",
        timestamp_precision=0,
        verification_status="failed",
        failure_count=1,
        failures=((event.id, "CURRENT_HASH_MISMATCH"),),
        candidates=(
            integrity.AuditTimestampRecoveryCandidate(
                audit_id=event.id,
                stored_timestamp=event.timestamp,
                recovered_timestamp=recovered,
                current_hash=event.current_hash,
            ),
        ),
        issues=(),
    )
    session = MagicMock()
    session.connection.return_value.dialect.name = "mysql"
    update_result = MagicMock(rowcount=1)

    def execute(statement, _parameters=None):
        if str(statement).startswith("UPDATE audit_logs"):
            return update_result
        return MagicMock()

    session.execute.side_effect = execute
    locked_plan = replace(plan, timestamp_precision=6)
    with (
        patch.object(
            integrity,
            "build_audit_timestamp_recovery_plan",
            side_effect=[plan, locked_plan],
        ),
        patch.object(
            integrity,
            "verify_audit_chain",
            return_value={"status": "verified"},
        ),
    ):
        result = integrity.ensure_audit_timestamp_precision_recovery(
            session,
            allow_evidence_recovery=True,
        )

    statements = [str(call.args[0]) for call in session.execute.call_args_list]
    assert any("DATETIME(6)" in statement for statement in statements)
    timestamp_update = next(
        statement
        for statement in statements
        if statement.startswith("UPDATE audit_logs")
    )
    assert "SET timestamp=" in timestamp_update
    assert "SET current_hash=" not in timestamp_update
    update_parameters = next(
        call.args[1]
        for call in session.execute.call_args_list
        if str(call.args[0]).startswith("UPDATE audit_logs")
    )
    assert update_parameters["recovered_timestamp"] == recovered
    assert update_parameters["current_hash"] == event.current_hash
    assert result["hashes_modified"] is False
    assert result["timestamp_values_restored"] is True
    assert result["non_timestamp_fields_modified"] is False
    assert result["timestamp_precision"] == 0
    assert result["timestamp_precision_after"] == 6


def test_recovery_migration_is_registered_as_the_latest_server_migration():
    assert MIGRATIONS[-1] == {
        "id": integrity.AUDIT_TIMESTAMP_RECOVERY_MIGRATION_ID,
        "handler": "ensure_audit_timestamp_precision_recovery",
        "sql": "",
    }


def test_server_startup_rejects_second_precision_audit_storage():
    session = MagicMock()
    with (
        patch.object(
            integrity,
            "audit_chain_schema_status",
            return_value={"active": True, "missing_columns": []},
        ),
        patch.object(
            integrity,
            "audit_timestamp_storage_status",
            return_value={
                "database_dialect": "mysql",
                "datetime_precision": 0,
            },
        ),
        patch.object(integrity, "verify_audit_chain") as verify,
    ):
        with pytest.raises(RuntimeError, match=r"DATETIME\(6\)"):
            migration_service.require_audit_integrity_schema(session)

    verify.assert_not_called()
