from datetime import datetime, timedelta, timezone

from scripts.validate_compliance_v2_activation import evaluate_activation


def _report(*, newly=None, removed=None):
    affected = [
        {"td_number": td, "change": "newly_compliant"} for td in (newly or [])
    ] + [
        {"td_number": td, "change": "removed_from_compliant"} for td in (removed or [])
    ]
    return {
        "counts": {
            "newly_compliant": len(newly or []),
            "removed_from_compliant": len(removed or []),
        },
        "details_truncated": False,
        "as_of_year": 2026,
        "billing_data_start_year": None,
        "exclude_archived_billings": False,
        "affected_accounts": affected,
    }


def _backup(tmp_path, now):
    path = tmp_path / "verified.sql"
    path.write_text("-- verified backup", encoding="utf-8")
    return {
        "status": "LOCAL_ONLY",
        "health": "SUCCESS",
        "checksum": "a" * 64,
        "file_path": str(path),
        "timestamp": now - timedelta(minutes=5),
    }


def _approval(removed):
    return {
        "as_of_year": 2026,
        "billing_data_start_year": None,
        "exclude_archived_billings": False,
        "approved_removed_td_numbers": list(removed),
        "approved_by": "Municipal Treasurer",
        "approved_at": "2026-07-22T08:00:00+00:00",
    }


def test_preflight_passes_with_verified_backup_and_exact_approval(tmp_path):
    now = datetime(2026, 7, 22, 8, 5, tzinfo=timezone.utc)
    errors = evaluate_activation(
        report=_report(removed=["TD-2", "TD-1"]),
        backup=_backup(tmp_path, now),
        approval=_approval(["TD-1", "TD-2"]),
        now=now,
    )

    assert errors == []


def test_preflight_blocks_newly_compliant_accounts(tmp_path):
    now = datetime(2026, 7, 22, 8, 5, tzinfo=timezone.utc)
    errors = evaluate_activation(
        report=_report(newly=["TD-NEW"]),
        backup=_backup(tmp_path, now),
        approval=_approval([]),
        now=now,
    )

    assert any("newly compliant" in error for error in errors)


def test_preflight_blocks_unapproved_or_changed_removal_list(tmp_path):
    now = datetime(2026, 7, 22, 8, 5, tzinfo=timezone.utc)
    errors = evaluate_activation(
        report=_report(removed=["TD-CURRENT"]),
        backup=_backup(tmp_path, now),
        approval=_approval(["TD-OLD-PREVIEW"]),
        now=now,
    )

    assert any("does not exactly match" in error for error in errors)


def test_preflight_blocks_stale_backup(tmp_path):
    now = datetime(2026, 7, 22, 8, 5, tzinfo=timezone.utc)
    backup = _backup(tmp_path, now)
    backup["timestamp"] = now - timedelta(hours=25)

    errors = evaluate_activation(
        report=_report(),
        backup=backup,
        approval=_approval([]),
        now=now,
    )

    assert any("older than 24 hours" in error for error in errors)


def test_preflight_blocks_truncated_or_incomplete_impact_details(tmp_path):
    now = datetime(2026, 7, 22, 8, 5, tzinfo=timezone.utc)
    report = _report(removed=["TD-LISTED"])
    report["details_truncated"] = True
    report["counts"]["removed_from_compliant"] = 2

    errors = evaluate_activation(
        report=report,
        backup=_backup(tmp_path, now),
        approval=_approval(["TD-LISTED"]),
        now=now,
    )

    assert any("truncated" in error for error in errors)
    assert any("counts do not match" in error for error in errors)
