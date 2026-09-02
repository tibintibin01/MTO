from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from scripts.capture_remediation_baseline import (
    assess_database_readiness,
    collect_database_snapshot,
    compare_financial_invariants,
)


def _baseline_database_session(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        )
        connection.execute(
            text(
                "CREATE TABLE properties ("
                "id INTEGER PRIMARY KEY, td_number TEXT NOT NULL, deleted_at DATETIME, "
                "archived BOOLEAN NOT NULL DEFAULT 0, duplicate_td_verified BOOLEAN, "
                "duplicate_td_reason TEXT, duplicate_td_reference TEXT, "
                "duplicate_td_approved_by TEXT, duplicate_td_approved_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE payments (id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL, "
                "amount NUMERIC, penalty NUMERIC, discount NUMERIC)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE property_billings (id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL, "
                "assessed_value NUMERIC, penalty NUMERIC, discount NUMERIC, amount_paid NUMERIC, "
                "is_archived BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE payment_billings (id INTEGER PRIMARY KEY, payment_id INTEGER NOT NULL, "
                "billing_id INTEGER NOT NULL, amount_paid NUMERIC)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE backup_history (id INTEGER PRIMARY KEY, filename TEXT NOT NULL, "
                "file_path TEXT NOT NULL, checksum TEXT, status TEXT, health TEXT, timestamp DATETIME)"
            )
        )
        connection.execute(text("INSERT INTO alembic_version VALUES ('phase0-test')"))
        connection.execute(
            text(
                "INSERT INTO properties VALUES "
                "(1, '06-0001-00001', NULL, 0, 1, 'Distinct account', 'REF-1', 'admin', '2026-09-01'), "
                "(2, '06-0001-00001', NULL, 0, 1, 'Distinct account', 'REF-2', 'admin', '2026-09-01')"
            )
        )
        connection.execute(
            text("INSERT INTO payments VALUES (1, 1, 100.50, 5.00, 1.00)")
        )
        connection.execute(
            text("INSERT INTO property_billings VALUES (1, 1, 5000, 5, 1, 100.50, 0)")
        )
        connection.execute(
            text("INSERT INTO payment_billings VALUES (1, 1, 1, 100.50)")
        )
        backup_file = tmp_path / "verified.sql"
        backup_file.write_text("-- test backup", encoding="utf-8")
        connection.execute(
            text(
                "INSERT INTO backup_history VALUES "
                "(1, 'verified.sql', :path, :checksum, 'CLOUD_ONLY', 'OK', :timestamp)"
            ),
            {
                "path": str(backup_file),
                "checksum": "a" * 64,
                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None),
            },
        )
    return Session(engine)


def test_database_snapshot_contains_aggregates_without_sensitive_rows(tmp_path):
    session = _baseline_database_session(tmp_path)
    try:
        snapshot = collect_database_snapshot(session)
    finally:
        session.rollback()
        session.close()

    assert snapshot["schema"]["alembic_revision"] == "phase0-test"
    assert snapshot["properties"] == {"total_count": 2, "active_count": 2}
    assert snapshot["payments"]["amount_total"] == "100.50"
    assert snapshot["allocations"]["cross_property_count"] == 0
    assert snapshot["duplicate_td"] == {
        "group_count": 1,
        "verified_group_count": 1,
        "unverified_group_count": 0,
    }
    assert snapshot["backup"]["filename"] == "verified.sql"
    assert "file_path" not in snapshot["backup"]
    assert "td_number" not in str(snapshot).lower()


def test_readiness_gate_requires_current_restore_attestation(tmp_path):
    session = _baseline_database_session(tmp_path)
    try:
        snapshot = collect_database_snapshot(session)
    finally:
        session.rollback()
        session.close()
    snapshot["backup"]["restore_verification_current"] = False

    issues = assess_database_readiness(snapshot)

    assert any("restore verification is not current" in issue for issue in issues)


def test_comparison_reports_financial_drift_and_ignores_metadata():
    before = {
        "captured_at_utc": "2026-09-01T00:00:00+00:00",
        "database": {
            "properties": {"total_count": 2, "active_count": 2},
            "payments": {
                "count": 1,
                "amount_total": "100.50",
                "penalty_total": "5.00",
                "discount_total": "1.00",
            },
            "billings": {
                "count": 1,
                "active_count": 1,
                "assessed_value_total": "5000.00",
                "penalty_total": "5.00",
                "discount_total": "1.00",
                "amount_paid_total": "100.50",
            },
            "allocations": {
                "count": 1,
                "amount_paid_total": "100.50",
                "cross_property_count": 0,
            },
            "duplicate_td": {
                "group_count": 1,
                "verified_group_count": 1,
                "unverified_group_count": 0,
            },
        },
    }
    after = {**before, "captured_at_utc": "2026-09-02T00:00:00+00:00"}
    assert compare_financial_invariants(before, after) == []

    changed = {**after, "database": {**after["database"]}}
    changed["database"]["payments"] = {
        **after["database"]["payments"],
        "amount_total": "101.00",
    }
    assert compare_financial_invariants(before, changed) == [
        {
            "field": "database.payments.amount_total",
            "before": "100.50",
            "after": "101.00",
        }
    ]
