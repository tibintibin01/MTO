import asyncio
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.routes import reports


def _deposit_payload():
    return reports.BankDepositCreateSchema(
        date_deposited="2026-09-15",
        bank_name="Government Bank",
        reference_number="PILOT-001",
        amount=1250.50,
    )


def _set_generated_deposit_fields(db):
    deposit = db.add.call_args.args[0]
    deposit.id = 71
    deposit.created_at = datetime(2026, 9, 15, 8, 0)


def test_bank_deposit_and_audit_commit_in_one_transaction():
    db = MagicMock()
    order = []
    db.flush.side_effect = lambda: (
        order.append("flush"),
        _set_generated_deposit_fields(db),
    )
    db.commit.side_effect = lambda: order.append("commit")

    with patch.object(
        reports,
        "log_action",
        side_effect=lambda **_kwargs: order.append("audit"),
    ):
        result = asyncio.run(
            reports.log_bank_deposit(
                _deposit_payload(),
                current_user={"id": 1, "username": "kevin"},
                db=db,
            )
        )

    assert result.id == 71
    assert order == ["flush", "audit", "commit"]
    db.refresh.assert_called_once()


def test_bank_deposit_is_not_committed_when_audit_append_fails():
    db = MagicMock()
    db.flush.side_effect = lambda: _set_generated_deposit_fields(db)

    with patch.object(
        reports,
        "log_action",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                reports.log_bank_deposit(
                    _deposit_payload(),
                    current_user={"id": 1, "username": "kevin"},
                    db=db,
                )
            )

    assert exc_info.value.status_code == 500
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_rcd_export_commits_its_audit_event_before_streaming():
    db = MagicMock()
    order = []
    db.commit.side_effect = lambda: order.append("commit")

    with (
        patch.object(
            reports,
            "generate_coa_rcd_excel",
            return_value=BytesIO(b"report"),
        ),
        patch.object(
            reports,
            "log_action",
            side_effect=lambda **_kwargs: order.append("audit"),
        ),
    ):
        response = asyncio.run(
            reports.export_coa_rcd(
                start_date="2026-09-01",
                end_date="2026-09-15",
                current_user={"id": 1, "username": "kevin"},
                db=db,
            )
        )

    assert response.status_code == 200
    assert order == ["audit", "commit"]
