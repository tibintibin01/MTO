from datetime import datetime, timedelta, timezone

from scripts.manage_duplicate_td_rollout import (
    evaluate_acceptance,
    evaluate_preflight,
    normalize_td,
)


def _preflight(tmp_path, now):
    backup = tmp_path / "verified.sql"
    backup.write_text("-- verified backup", encoding="utf-8")
    return {
        "migration_applied": True,
        "schema": {
            "dialect": "mariadb",
            "required_columns_present": True,
            "missing_columns": [],
            "td_unique_names": [],
            "has_td_lookup_index": True,
        },
        "backup": {
            "filename": "verified.sql",
            "file_path": str(backup),
            "checksum": "a" * 64,
            "status": "CLOUD_ONLY",
            "health": "OK",
            "timestamp": now - timedelta(minutes=5),
        },
        "backup_running": False,
        "cloud_enabled": True,
        "cloud_ready": True,
        "cloud_message": "Phase 3 is current.",
        "unresolved_duplicate_tds": [],
        "verified_duplicate_tds": [],
        "pilot_td": "06-0017-00249",
        "pilot_match_count": 1,
        "pilot_fully_verified": False,
    }


def _acceptance(now):
    return {
        "td_number": "06-0017-00249",
        "properties": [
            {
                "id": 10,
                "reference": "ARP-2026-001",
                "reason": "Confirmed distinct assessment.",
                "approved_by": "admin",
                "approved_at": now - timedelta(hours=2),
                "verified": True,
            },
            {
                "id": 20,
                "reference": "ARP-2026-001",
                "reason": "Confirmed distinct assessment.",
                "approved_by": "admin",
                "approved_at": now - timedelta(hours=2),
                "verified": True,
            },
        ],
        "cross_property_allocation_count": 0,
        "audit_actions": [
            "MARK_VERIFIED_DUPLICATE_TD",
            "CREATE_VERIFIED_DUPLICATE_TD",
        ],
        "latest_approval_at": now - timedelta(hours=2),
        "backup": {"timestamp": now - timedelta(hours=1)},
    }


def test_phase4_preflight_passes_only_for_one_existing_pilot_property(tmp_path):
    now = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
    errors = evaluate_preflight(_preflight(tmp_path, now), now=now)

    assert errors == []


def test_phase4_preflight_requires_cloud_restore_and_no_unresolved_duplicates(tmp_path):
    now = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
    snapshot = _preflight(tmp_path, now)
    snapshot["backup"]["status"] = "LOCAL_ONLY"
    snapshot["backup"]["health"] = "RESTORE_SKIPPED"
    snapshot["cloud_ready"] = False
    snapshot["cloud_message"] = "Phase 3 is missing."
    snapshot["unresolved_duplicate_tds"] = ["06-0001-00001"]

    errors = evaluate_preflight(snapshot, now=now)

    assert any("not protected in cloud" in error for error in errors)
    assert any("full restore verification" in error for error in errors)
    assert any("Phase 3 is missing" in error for error in errors)
    assert any("Unverified active duplicate" in error for error in errors)


def test_phase4_expansion_requires_verified_group_and_newer_backup(tmp_path):
    now = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
    snapshot = _preflight(tmp_path, now)
    snapshot["pilot_match_count"] = 2
    snapshot["pilot_fully_verified"] = True
    snapshot["verified_duplicate_tds"] = ["06-0017-00249"]

    assert evaluate_preflight(
        snapshot, require_existing_pilot_group=True, now=now
    ) == []

    acceptance = _acceptance(now)
    assert evaluate_acceptance(
        acceptance, require_backup_after_approval=True
    ) == []
    acceptance["backup"]["timestamp"] = now - timedelta(hours=3)
    errors = evaluate_acceptance(acceptance, require_backup_after_approval=True)
    assert any("new verified Hybrid Backup" in error for error in errors)


def test_acceptance_rejects_cross_property_payment_allocation():
    now = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
    snapshot = _acceptance(now)
    snapshot["cross_property_allocation_count"] = 1

    errors = evaluate_acceptance(snapshot)

    assert any("another property account's billing" in error for error in errors)


def test_normalize_td_is_case_insensitive_and_rejects_control_characters():
    assert normalize_td(" 06-abcd-00001 ") == "06-ABCD-00001"

    try:
        normalize_td("06-001\n")
    except ValueError as exc:
        assert "printable" in str(exc)
    else:
        raise AssertionError("Control characters must be rejected")
