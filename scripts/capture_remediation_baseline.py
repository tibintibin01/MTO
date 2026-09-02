"""Capture and compare a privacy-safe MTO remediation baseline.

The default mode inspects source-control and dependency manifests only. Pass
``--database`` explicitly on the API server to add aggregate financial counts,
backup readiness, and schema metadata. Database mode issues SELECT statements
only and always rolls the session back before closing it.

The report deliberately excludes taxpayer names, TD/PIN values, OR numbers,
database URLs, credentials, signing keys, and absolute backup paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import inspect, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = PROJECT_ROOT / "logs"
PROTECTED_BACKUP_STATUSES = {"CLOUD_ONLY", "SYNCED"}
SUCCESSFUL_BACKUP_HEALTH = {"OK", "SUCCESS"}

FINANCIAL_INVARIANTS = (
    "database.properties.total_count",
    "database.properties.active_count",
    "database.payments.count",
    "database.payments.amount_total",
    "database.payments.penalty_total",
    "database.payments.discount_total",
    "database.billings.count",
    "database.billings.active_count",
    "database.billings.assessed_value_total",
    "database.billings.penalty_total",
    "database.billings.discount_total",
    "database.billings.amount_paid_total",
    "database.allocations.count",
    "database.allocations.amount_paid_total",
    "database.allocations.cross_property_count",
    "database.duplicate_td.group_count",
    "database.duplicate_td.verified_group_count",
    "database.duplicate_td.unverified_group_count",
)

REQUIRED_TABLES = {
    "alembic_version",
    "backup_history",
    "payment_billings",
    "payments",
    "properties",
    "property_billings",
}

REQUIRED_PROPERTY_COLUMNS = {
    "duplicate_td_approved_at",
    "duplicate_td_approved_by",
    "duplicate_td_reason",
    "duplicate_td_reference",
    "duplicate_td_verified",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _run_git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_hashes() -> dict[str, str]:
    candidates = (
        "pyproject.toml",
        "requirements.txt",
        "frontend/package.json",
        "frontend/package-lock.json",
    )
    return {
        relative: _sha256(PROJECT_ROOT / relative)
        for relative in candidates
        if (PROJECT_ROOT / relative).is_file()
    }


def collect_source_snapshot() -> dict[str, Any]:
    dirty_lines = [
        line
        for line in _run_git(
            "status", "--porcelain=v1", "--untracked-files=all"
        ).splitlines()
        if line.strip()
    ]
    return {
        "commit": _run_git("rev-parse", "HEAD"),
        "branch": _run_git("branch", "--show-current"),
        "dirty": bool(dirty_lines),
        "changed_file_count": len(dirty_lines),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependency_manifest_sha256": _manifest_hashes(),
    }


def _decimal_text(value: Any) -> str:
    decimal_value = Decimal(str(value or 0))
    return format(decimal_value.quantize(Decimal("0.01")), "f")


def _scalar(session: Any, statement: str) -> int:
    value = session.execute(text(statement)).scalar()
    return int(value or 0)


def _aggregate(session: Any, statement: str, names: Iterable[str]) -> dict[str, Any]:
    row = session.execute(text(statement)).one()
    values = list(row)
    result: dict[str, Any] = {}
    for index, name in enumerate(names):
        value = values[index]
        result[name] = (
            int(value or 0) if name.endswith("count") else _decimal_text(value)
        )
    return result


def _serialize_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat()
    return str(value)


def _backup_age_hours(value: Any, *, now: datetime | None = None) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value
    else:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    current = now or _utc_now()
    return round(
        max(0.0, (current - timestamp.astimezone(timezone.utc)).total_seconds() / 3600),
        2,
    )


def _redacted_backup_snapshot(session: Any) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                "SELECT filename, file_path, checksum, status, health, timestamp "
                "FROM backup_history "
                "WHERE filename <> '__lock__' AND status <> 'RUNNING' "
                "ORDER BY id DESC LIMIT 1"
            )
        )
        .mappings()
        .first()
    )
    if not row:
        return {"present": False}

    checksum = str(row.get("checksum") or "")
    file_path = str(row.get("file_path") or "")
    return {
        "present": True,
        "filename": ntpath.basename(str(row.get("filename") or "")),
        "file_present_on_server": bool(file_path and os.path.isfile(file_path)),
        "checksum_present": len(checksum) == 64,
        "checksum_short": (
            f"{checksum[:12]}...{checksum[-8:]}"
            if len(checksum) == 64
            else "INVALID_OR_MISSING"
        ),
        "status": str(row.get("status") or "UNKNOWN").upper(),
        "health": str(row.get("health") or "UNKNOWN").upper(),
        "timestamp_utc": _serialize_timestamp(row.get("timestamp")),
        "age_hours": _backup_age_hours(row.get("timestamp")),
    }


def _duplicate_td_snapshot(session: Any) -> dict[str, int]:
    rows = session.execute(
        text(
            "SELECT COUNT(*) AS member_count, "
            "SUM(CASE WHEN duplicate_td_verified = 1 "
            "AND NULLIF(TRIM(duplicate_td_reason), '') IS NOT NULL "
            "AND NULLIF(TRIM(duplicate_td_reference), '') IS NOT NULL "
            "AND NULLIF(TRIM(duplicate_td_approved_by), '') IS NOT NULL "
            "AND duplicate_td_approved_at IS NOT NULL THEN 1 ELSE 0 END) AS verified_count "
            "FROM properties WHERE deleted_at IS NULL "
            "GROUP BY UPPER(TRIM(td_number)) HAVING COUNT(*) > 1"
        )
    ).all()
    group_count = len(rows)
    verified_count = sum(int(row[0] or 0) == int(row[1] or 0) for row in rows)
    return {
        "group_count": group_count,
        "verified_group_count": verified_count,
        "unverified_group_count": group_count - verified_count,
    }


def _schema_snapshot(session: Any) -> dict[str, Any]:
    inspector = inspect(session.get_bind())
    table_names = set(inspector.get_table_names())
    missing_tables = sorted(REQUIRED_TABLES - table_names)
    property_columns: set[str] = set()
    if "properties" in table_names:
        property_columns = {
            column["name"] for column in inspector.get_columns("properties")
        }
    missing_property_columns = sorted(REQUIRED_PROPERTY_COLUMNS - property_columns)
    if missing_tables or missing_property_columns:
        details = []
        if missing_tables:
            details.append("missing tables: " + ", ".join(missing_tables))
        if missing_property_columns:
            details.append(
                "missing properties columns: " + ", ".join(missing_property_columns)
            )
        raise RuntimeError(
            "Database schema is not ready for baseline capture ("
            + "; ".join(details)
            + ")"
        )

    revision_row = session.execute(
        text("SELECT version_num FROM alembic_version LIMIT 1")
    ).first()
    return {
        "dialect": session.get_bind().dialect.name,
        "alembic_revision": str(revision_row[0]) if revision_row else None,
        "required_tables_present": True,
        "duplicate_td_columns_present": True,
    }


def collect_database_snapshot(session: Any) -> dict[str, Any]:
    """Collect aggregate database information using SELECT statements only."""
    schema = _schema_snapshot(session)
    properties = {
        "total_count": _scalar(session, "SELECT COUNT(*) FROM properties"),
        "active_count": _scalar(
            session,
            "SELECT COUNT(*) FROM properties "
            "WHERE deleted_at IS NULL AND COALESCE(archived, 0) = 0",
        ),
    }
    payments = _aggregate(
        session,
        "SELECT COUNT(*), COALESCE(SUM(amount), 0), COALESCE(SUM(penalty), 0), "
        "COALESCE(SUM(discount), 0) FROM payments",
        ("count", "amount_total", "penalty_total", "discount_total"),
    )
    billings = _aggregate(
        session,
        "SELECT COUNT(*), COALESCE(SUM(assessed_value), 0), COALESCE(SUM(penalty), 0), "
        "COALESCE(SUM(discount), 0), COALESCE(SUM(amount_paid), 0) FROM property_billings",
        (
            "count",
            "assessed_value_total",
            "penalty_total",
            "discount_total",
            "amount_paid_total",
        ),
    )
    billings["active_count"] = _scalar(
        session,
        "SELECT COUNT(*) FROM property_billings WHERE COALESCE(is_archived, 0) = 0",
    )
    allocations = _aggregate(
        session,
        "SELECT COUNT(*), COALESCE(SUM(amount_paid), 0) FROM payment_billings",
        ("count", "amount_paid_total"),
    )
    allocations["cross_property_count"] = _scalar(
        session,
        "SELECT COUNT(*) FROM payment_billings pb "
        "JOIN payments p ON p.id = pb.payment_id "
        "JOIN property_billings b ON b.id = pb.billing_id "
        "WHERE p.property_id <> b.property_id",
    )
    return {
        "schema": schema,
        "properties": properties,
        "payments": payments,
        "billings": billings,
        "allocations": allocations,
        "duplicate_td": _duplicate_td_snapshot(session),
        "backup": _redacted_backup_snapshot(session),
    }


def _begin_read_only_transaction(session: Any) -> None:
    dialect = session.get_bind().dialect.name.lower()
    if dialect in {"mysql", "mariadb", "postgresql"}:
        session.execute(text("SET TRANSACTION READ ONLY"))


def capture_configured_database() -> dict[str, Any]:
    from backend.database import SessionLocal
    from backend.services.cloud_backup_service import cloud_backup_activation_ready

    session = SessionLocal()
    try:
        _begin_read_only_transaction(session)
        snapshot = collect_database_snapshot(session)
        try:
            restore_ready, restore_message = cloud_backup_activation_ready()
        except (
            Exception
        ) as exc:  # configuration failure must be visible, not fatal to capture
            restore_ready = False
            restore_message = f"Restore verification check failed: {type(exc).__name__}"
        snapshot["backup"]["restore_verification_current"] = bool(restore_ready)
        snapshot["backup"]["restore_verification_status"] = str(restore_message)
        return snapshot
    finally:
        session.rollback()
        session.close()


def assess_database_readiness(database: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    backup = database.get("backup", {})
    if not backup.get("present"):
        issues.append("No completed Hybrid Backup record exists.")
        return issues
    if backup.get("status") not in PROTECTED_BACKUP_STATUSES:
        issues.append("Latest backup is not protected in cloud.")
    if backup.get("health") not in SUCCESSFUL_BACKUP_HEALTH:
        issues.append("Latest backup restore health is not successful.")
    if not backup.get("restore_verification_current"):
        issues.append(
            "Cloud restore verification is not current for this configuration."
        )
    if not backup.get("file_present_on_server"):
        issues.append("Latest backup file is not present on the server.")
    if not backup.get("checksum_present"):
        issues.append("Latest backup checksum is missing or malformed.")
    age_hours = backup.get("age_hours")
    if age_hours is None or float(age_hours) > 24:
        issues.append(
            "Latest protected backup is older than 24 hours or its timestamp is invalid."
        )
    if int(database.get("allocations", {}).get("cross_property_count", 0)):
        issues.append("Cross-property payment allocations exist.")
    if int(database.get("duplicate_td", {}).get("unverified_group_count", 0)):
        issues.append("Unverified active duplicate-TD groups exist.")
    return issues


def _lookup(payload: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return "<MISSING>"
        current = current[part]
    return current


def compare_financial_invariants(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[dict[str, Any]]:
    differences = []
    for path in FINANCIAL_INVARIANTS:
        old_value = _lookup(before, path)
        new_value = _lookup(after, path)
        if old_value != new_value:
            differences.append({"field": path, "before": old_value, "after": new_value})
    return differences


def _default_output_path() -> Path:
    timestamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_REPORT_DIR / f"remediation-baseline-{timestamp}.json"


def write_report(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        action="store_true",
        help="Explicitly add aggregate database and backup information.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Report path (default: ignored logs/remediation-baseline-<UTC>.json).",
    )
    parser.add_argument(
        "--compare-to",
        type=Path,
        default=None,
        help="Compare financial invariants with a previous report.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit non-zero unless database and backup readiness gates pass.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.require_ready and not args.database:
        print("ERROR: --require-ready requires --database.", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "format_version": 1,
        "captured_at_utc": _utc_now().isoformat(),
        "privacy": "Aggregate operational metadata only; no taxpayer or credential data.",
        "source": collect_source_snapshot(),
    }
    if args.database:
        report["database"] = capture_configured_database()
        report["readiness_issues"] = assess_database_readiness(report["database"])

    differences: list[dict[str, Any]] = []
    if args.compare_to:
        previous = json.loads(args.compare_to.read_text(encoding="utf-8"))
        differences = compare_financial_invariants(previous, report)
        report["comparison"] = {
            "baseline_file": args.compare_to.name,
            "financial_invariants_match": not differences,
            "differences": differences,
        }

    output = (args.output or _default_output_path()).resolve()
    write_report(output, report)
    print(f"Baseline report: {output}")
    print(f"Source: {report['source']['commit'][:12]} on {report['source']['branch']}")
    if args.database:
        issues = report["readiness_issues"]
        print(f"Database readiness: {'PASS' if not issues else 'REVIEW'}")
        for issue in issues:
            print(f"- {issue}")
    if args.compare_to:
        print(
            f"Financial invariant comparison: {'PASS' if not differences else 'FAILED'}"
        )
        for difference in differences:
            print(
                f"- {difference['field']}: {difference['before']} -> {difference['after']}"
            )

    if args.require_ready and report.get("readiness_issues"):
        return 3
    if differences:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
