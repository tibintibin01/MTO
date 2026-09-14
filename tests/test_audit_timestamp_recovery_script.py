import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services import audit_integrity_service as integrity
from scripts import phase5_audit_timestamp_recovery as recovery


def _ready_plan():
    return integrity.AuditTimestampRecoveryPlan(
        database_dialect="mysql",
        timestamp_column_type="datetime",
        timestamp_precision=0,
        verification_status="failed",
        failure_count=1,
        failures=((6161, "CURRENT_HASH_MISMATCH"),),
        candidates=(
            integrity.AuditTimestampRecoveryCandidate(
                audit_id=6161,
                stored_timestamp=datetime(2026, 9, 14, 23, 8, 8),
                recovered_timestamp=datetime(2026, 9, 14, 23, 8, 8, 123456),
                current_hash="a" * 64,
            ),
        ),
        issues=(),
    )


def test_preflight_requires_api_stopped_and_backup_ready(monkeypatch):
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    monkeypatch.setattr(recovery, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        recovery,
        "build_audit_timestamp_recovery_plan",
        lambda _session: _ready_plan(),
    )
    monkeypatch.setattr(recovery, "_migration_applied", lambda _session: False)
    monkeypatch.setattr(recovery, "_api_is_listening", lambda: False)
    monkeypatch.setattr(
        recovery,
        "_backup_summary",
        lambda: ({"present": True}, []),
    )

    report = recovery.capture_preflight()

    assert report["ready"] is True
    assert report["api_stopped"] is True
    assert report["backup_ready"] is True
    assert report["recovery"]["affected_event_ids"] == [6161]


def test_fresh_incident_backup_failure_blocks_recovery():
    with patch.object(
        recovery,
        "run_hybrid_backup",
        AsyncMock(return_value=(False, "failed")),
    ):
        with pytest.raises(recovery.RecoveryUtilityError, match="backup failed"):
            recovery._create_fresh_incident_backup()


def test_fresh_incident_backup_must_pass_restore_and_protection_gates():
    with (
        patch.object(
            recovery,
            "run_hybrid_backup",
            AsyncMock(return_value=(True, "created")),
        ),
        patch.object(
            recovery,
            "_require_backup_ready",
            side_effect=RuntimeError("restore stale"),
        ),
    ):
        with pytest.raises(
            recovery.RecoveryUtilityError,
            match="protection and restore gates",
        ):
            recovery._create_fresh_incident_backup()


def test_fresh_incident_backup_returns_redacted_attestation():
    expected = {
        "present": True,
        "filename": "revenue_backup.sql",
        "checksum_short": "abc...123",
    }
    with (
        patch.object(
            recovery,
            "run_hybrid_backup",
            AsyncMock(return_value=(True, "created")),
        ),
        patch.object(recovery, "_require_backup_ready"),
        patch.object(recovery, "_backup_summary", return_value=(expected, [])),
    ):
        assert recovery._create_fresh_incident_backup() == expected


def test_apply_confirmation_must_match_exactly(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["recovery", "--apply"])

    with (
        patch("builtins.input", return_value="no"),
        patch.object(recovery, "apply_recovery") as apply_recovery,
    ):
        assert recovery.main() == 3

    apply_recovery.assert_not_called()
