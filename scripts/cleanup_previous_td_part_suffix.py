"""Safely normalize canonical Previous TD values ending in ``-PART``.

The command is a dry run unless ``--apply`` is supplied. Only values that can
be reduced unambiguously to ``NN-NNNN-NNNNN`` are changed. Legacy and malformed
values are preserved for manual review and included in the audit CSV.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import bindparam, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CANONICAL_TD = re.compile(r"^\d{2}-\d{4}-\d{5}$")
CANONICAL_WITH_MARKER = re.compile(
    r"^(?P<td>\d{2}-\d{4}-\d{5})-[A-Z]+$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CleanupDecision:
    action: str
    normalized_value: str | None


def classify_previous_td(value: str | None) -> CleanupDecision:
    """Return a conservative cleanup decision for one Previous TD value."""
    cleaned = (value or "").strip()
    if not cleaned.upper().endswith("-PART"):
        return CleanupDecision("not_part_suffix", None)

    without_part = cleaned[:-5].strip()
    if CANONICAL_TD.fullmatch(without_part):
        return CleanupDecision("normalize", without_part)

    marker_match = CANONICAL_WITH_MARKER.fullmatch(without_part)
    if marker_match:
        return CleanupDecision("normalize_marker", marker_match.group("td"))

    return CleanupDecision("skip_legacy_or_malformed", None)


def _write_audit_csv(rows: Iterable[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "property_id",
        "current_td_number",
        "owner_name",
        "barangay",
        "old_previous_td",
        "new_previous_td",
        "action",
    )
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_cleanup(*, apply_changes: bool, backup_dir: Path) -> int:
    from backend.database import engine

    select_query = text(
        """
        SELECT id, td_number, owner_name, barangay, prev_td_number
        FROM properties
        WHERE UPPER(TRIM(COALESCE(prev_td_number, ''))) LIKE '%-PART'
        ORDER BY id
        """
    )

    with engine.connect() as connection:
        database_rows = connection.execute(select_query).mappings().all()

    audit_rows: list[dict] = []
    updates: list[dict] = []
    action_counts: dict[str, int] = {}
    for row in database_rows:
        decision = classify_previous_td(row["prev_td_number"])
        action_counts[decision.action] = action_counts.get(decision.action, 0) + 1
        audit_rows.append(
            {
                "property_id": row["id"],
                "current_td_number": row["td_number"],
                "owner_name": row["owner_name"],
                "barangay": row["barangay"],
                "old_previous_td": row["prev_td_number"],
                "new_previous_td": decision.normalized_value or "",
                "action": decision.action,
            }
        )
        if decision.normalized_value:
            updates.append(
                {
                    "property_id": row["id"],
                    "old_value": row["prev_td_number"],
                    "new_value": decision.normalized_value,
                }
            )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "applied" if apply_changes else "dry_run"
    audit_path = backup_dir / f"previous_td_part_cleanup_{mode}_{timestamp}.csv"
    _write_audit_csv(audit_rows, audit_path)

    print(f"Previous TD values ending in -PART: {len(database_rows):,}")
    print(f"Safe canonical updates: {len(updates):,}")
    print(
        "Skipped legacy/malformed values: "
        f"{action_counts.get('skip_legacy_or_malformed', 0):,}"
    )
    print(f"Audit CSV: {audit_path}")

    if not apply_changes:
        print("Dry run only. No database values were changed.")
        return 0

    update_query = text(
        """
        UPDATE properties
        SET prev_td_number = :new_value
        WHERE id = :property_id
          AND prev_td_number = :old_value
        """
    )

    with engine.begin() as connection:
        result = connection.execute(update_query, updates)
        if result.rowcount != len(updates):
            raise RuntimeError(
                "Cleanup aborted: expected to update "
                f"{len(updates)} rows but matched {result.rowcount}."
            )

        invalid_updated = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM properties
                WHERE id IN :property_ids
                  AND prev_td_number NOT REGEXP '^[0-9]{2}-[0-9]{4}-[0-9]{5}$'
                """
            ).bindparams(bindparam("property_ids", expanding=True)),
            {"property_ids": [item["property_id"] for item in updates]},
        ).scalar_one()
        if invalid_updated:
            raise RuntimeError(
                f"Cleanup aborted: {invalid_updated} updated values failed validation."
            )

    with engine.connect() as connection:
        remaining_safe = connection.execute(select_query).mappings().all()
    remaining_normalizable = sum(
        classify_previous_td(row["prev_td_number"]).normalized_value is not None
        for row in remaining_safe
    )
    if remaining_normalizable:
        raise RuntimeError(
            f"Post-cleanup verification failed: {remaining_normalizable} safe rows remain."
        )

    print(f"Applied and verified {len(updates):,} Previous TD updates.")
    print(f"Preserved {len(remaining_safe):,} legacy/malformed values for review.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply safe changes. Without this flag, the command is read-only.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path.home() / "mto_backups" / "data_cleanup",
        help="Directory for the before/after audit CSV.",
    )
    args = parser.parse_args()
    return run_cleanup(apply_changes=args.apply, backup_dir=args.backup_dir)


if __name__ == "__main__":
    raise SystemExit(main())
